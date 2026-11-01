"""One-command 'Polished' film grade - reproduces Testing2_FilmEmulation_4K_Polished.mp4 on any log footage.

No third-party assets needed (uses this repo's own engine, grading/filmemu.py).

  1  read-only shot detection -> one timeline item per shot
  2  one film-emulation LUT per shot (per-shot exposure/WB baked in), installed into Resolve's LUT/MCP folder
  3  each shot gets a NEW grade version with its LUT on node 1 (your other versions stay)
  4  Fusion texture per shot: Halation (SoftGlow, threshold = that shot's top ~1% highlights, red-orange)
     -> FilmGrain (blend 0.25)
  5  verify every shot from rendered frames; optional 4K export + file-level check

usage:
  python -m grading.film_emulation --preset slog3_polished --export
  python -m grading.film_emulation --preset slog3_polished --preview-only   # no Resolve needed: previews only
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image

from . import analysis as A
from . import filmemu as F
from . import resolve_steps as S
from .mcp_client import connect


def make_luts(shots_info: dict, src_dir: Path, out_dir: Path, preset: str, tag: str) -> list[Path]:
    L = F.PRESETS[preset]
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for sh in shots_info["shots"]:
        thumb = A.load_rgb(src_dir / f"shot_{sh['idx']:02d}.jpg")
        trim = F.shot_trim(sh, thumb, L)
        p = out_dir / f"{tag}_shot{sh['idx']:02d}.cube"
        F.write_cube(p, trim, L)
        Image.fromarray((F.grade(thumb, trim, L) * 255 + 0.5).astype(np.uint8)).save(out_dir / f"preview_{sh['idx']:02d}.jpg", quality=88)
        paths.append(p)
    A.contact_sheet(sorted(out_dir.glob("preview_*.jpg")), out_dir / "preview_contact.jpg")
    return paths


async def run(a):
    work = Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    tag = f"FE_{a.preset}_{time.strftime('%Y%m%d%H%M%S')}"  # unique LUT names: Resolve caches LUTs by name

    if a.preview_only:
        shots_info = A.detect_shots(a.source, thumbs_dir=work / "source")
        make_luts(shots_info, work / "source", work / "luts", a.preset, tag)
        S.log(f"previews: {work / 'luts' / 'preview_contact.jpg'}")
        return

    async with connect(a.mcp_config) as r:
        info = await S.ensure_connected(r)
        S.log("1/5 shot detection (read-only) + timeline")
        clip = await S.find_clip(r, a.clip, a.import_path)
        shots_info = A.detect_shots(clip["file_path"], thumbs_dir=work / "source")
        shots = shots_info["shots"]
        A.write_json(shots_info, work / "shots.json")
        S.log(f"  {clip['name']}: {shots_info['width']}x{shots_info['height']}, {len(shots)} shots")
        await S.build_shot_timeline(r, clip, shots, a.timeline_name, clip_fps=shots_info["fps"])

        S.log(f"2/5 per-shot LUTs (preset {a.preset})")
        luts = make_luts(shots_info, work / "source", work / "luts", a.preset, tag)
        for p in luts:
            res = await r.call("lut", "install", {"name": p.name, "source_path": str(p.resolve()), "overwrite": True})
            if not res.get("success"):
                raise SystemExit(f"LUT install failed: {res}")
        await r.call("project_settings", "refresh_luts")

        S.log("3/5 grade versions + LUTs")
        version = f"Film Emulation {a.preset}"
        run_id = (await r.call("timeline_versioning", "begin_run", {"label": version})).get("analysis_run_id")
        for sh, p in zip(shots, luts):
            item = dict(track_type="video", track_index=1, item_index=sh["idx"])
            await r.call("timeline_item_color", "add_version", {**item, "name": version, "type": 0})
            await r.call("graph", "set_lut", {**item, "source": "item", "node_index": 1, "lut_path": f"MCP/{p.name}"})
            got = (await r.call("graph", "get_lut", {**item, "source": "item", "node_index": 1})).get("lut", "")
            S.log(f"  shot {sh['idx']:2d}: {got} {'OK' if p.name in str(got) else 'CHECK'}")
        await r.call("timeline_versioning", "end_run", {"analysis_run_id": run_id})

        S.log("4/5 Fusion halation + grain")
        thresholds = [round(max(0.42, sh["luma_p99"] - 0.01), 3) for sh in shots]
        await S.fusion_texture(r, len(shots), grain_blend=a.grain, halation=thresholds)

        S.log("5/5 verify (rendered frames)")
        caps = await S.capture_shots(r, shots, work / "captures", "graded")
        rows = []
        for sh, cap in zip(shots, caps):
            st = A.frame_stats(A.load_rgb(cap))
            rows.append({"shot": sh["idx"], **st})
            S.log(f"  shot {sh['idx']:2d}: luma p1/50/99 {st['p1']:.3f}/{st['median']:.3f}/{st['p99']:.3f} sat {st['sat']:.3f}")
        A.contact_sheet(caps, work / "graded_contact.jpg")
        report = {"connected": info, "preset": a.preset, "version": version, "shots": rows}
        await S.save(r)
        if a.export:
            name = a.export_name or f"{info['project']}_FilmEmulation_{'4K' if a.resolution == 2160 else 'HD'}".replace(" ", "_")
            ver = await S.render(r, "h264_2160p_web" if a.resolution == 2160 else "h264_1080p_web", a.export_dir, name)
            chk = A.export_frames_check(ver["output_path"], shots, work / "export_frames")
            report["export"] = {"file": ver["output_path"], **{k: v for k, v in chk.items() if k != "shots"}}
            S.log(f"  export: {chk['codec']} {chk['width']}x{chk['height']} {chk['frames']} frames")
        A.write_json(report, work / "report.json")
        S.log(f"DONE. report: {work / 'report.json'}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preset", default="slog3_polished", choices=sorted(F.PRESETS))
    p.add_argument("--mcp-config", default=os.environ.get("DAVINCI_MCP_CONFIG", ".mcp.json"))
    p.add_argument("--clip")
    p.add_argument("--import", dest="import_path")
    p.add_argument("--timeline-name", default="Film Emulation")
    p.add_argument("--work-dir", default="work/film_emulation")
    p.add_argument("--grain", type=float, default=0.25)
    p.add_argument("--preview-only", action="store_true", help="no Resolve: build LUTs + previews from --source")
    p.add_argument("--source", help="video file for --preview-only")
    p.add_argument("--export", action="store_true")
    p.add_argument("--export-dir", default=str(Path.home() / "Videos" / "Resolve Exports"))
    p.add_argument("--export-name")
    p.add_argument("--resolution", type=int, default=2160, choices=[2160, 1080])
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
