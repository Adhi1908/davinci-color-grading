"""One-command CinePrint35 grade - reproduces Testing3_CinePrint35_250D_4K.mp4 on any footage.

Requires YOUR OWN licensed copy of CinePrint35 (Tom Bolles / gfxpck.com). Its PowerGrades are not
included in this repo and must not be redistributed - point --cineprint-dir at your download.

Pipeline (all verified by readback / rendered-frame measurement):
  1  project settings from the CinePrint35 guide (Rec.709 Gamma 2.4, linear contrast)
  2  read-only shot detection on the source file -> one timeline item per shot
  3  the camera's PowerGrade applied to every shot as a NEW grade version (your other versions stay)
  4  free edition: Studio-only nodes (Denoise, Gate Wv, Grain*, Dust) disabled -> no watermark
  5  guide workflow per shot: EXP node exposure from measured rendered frames, contrast + gentle warmth
     + saturation in the Primaries node (WB left neutral: auto-WB reads real sea/sky blue as a cast)
  6  free edition: Fusion FilmGrain replaces the Studio-only grain (on log, before the grade, like his)
  7  verify: capture every shot, watermark check, stats; optional 4K export + file-level re-check

usage:
  python -m grading.cineprint --cineprint-dir "D:/CinePrint35 for Davinci Resolve" --camera "Sony S-Log3" \
      --stock 250D --gauge 35mm --export
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np

from . import analysis as A
from . import resolve_steps as S
from .mcp_client import connect

STUDIO_ONLY = ("Denoise", "Gate Wv", "Dust")  # + any label starting with 'Grain'


def find_drx(root: Path, camera: str, stock: str, gauge: str) -> Path:
    hits = [p for p in root.rglob("*.drx")
            if camera.lower() in p.parent.name.lower() and f"{stock} {gauge}".lower() in p.name.lower()]
    if not hits:
        cams = sorted({p.parent.name.replace("CinePrint35 for ", "") for p in root.rglob("*.drx")})
        raise SystemExit(f"No PowerGrade for camera '{camera}' {stock} {gauge} under {root}.\nCameras available: {cams}")
    return hits[0]


def exposure_offset(median: float, target: float) -> float:
    """EXP-node Offset from a measured rendered median. ~3x output gain per unit of log offset (measured).

    Dark-content shots (median < 0.42, e.g. seaweed, rocks) keep their mood: target min(0.45, median+0.12).
    The final -0.015 is the global density trim that produced the reference export.
    """
    t = target if median >= 0.42 else min(0.45, median + 0.12)
    return round(float(np.clip((t - median) / 3.0, -0.05, 0.05)) - 0.015, 4)


def primaries_cdl(contrast: float, warmth: float, sat: float, pivot: float = 0.44) -> dict:
    """Contrast around a Cineon-log pivot as CDL (slope c, offset p(1-c)) + gentle warm white point.

    Warmth stays small on purpose: a warm slope >~1.03 in this log stage turns skies mint-yellow.
    """
    ws = (1 + 0.012 * warmth, 1.0, 1 - 0.015 * warmth)
    wo = (0.003 * warmth, 0.0, -0.004 * warmth)
    return {"Slope": [round(w * contrast, 4) for w in ws],
            "Offset": [round(o + pivot * (1 - contrast), 4) for o in wo],
            "Power": [1.0, 1.0, 1.0], "Saturation": sat}


async def run(a):
    work = Path(a.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    drx_src = find_drx(Path(a.cineprint_dir), a.camera, a.stock, a.gauge)
    tmp = Path(tempfile.gettempdir()) / "davinci-color-grading"
    tmp.mkdir(exist_ok=True)
    drx = tmp / drx_src.name  # the server only applies .drx from a temp dir by default (safety guard)
    shutil.copy2(drx_src, drx)
    version = f"CinePrint35 {a.camera} {a.stock} {a.gauge}"
    S.log(f"PowerGrade: {drx_src}")

    async with connect(a.mcp_config) as r:
        info = await S.ensure_connected(r)
        S.log("1/7 project settings (guide)")
        await S.apply_guide_settings(r)

        S.log("2/7 shot detection (read-only) + timeline")
        clip = await S.find_clip(r, a.clip, a.import_path)
        shots_info = A.detect_shots(clip["file_path"], thumbs_dir=work / "source")
        shots = shots_info["shots"]
        A.write_json(shots_info, work / "shots.json")
        S.log(f"  {clip['name']}: {shots_info['width']}x{shots_info['height']} @ {shots_info['fps']:.3f}, {len(shots)} shots")
        tl_size = None
        if a.timeline_res == "match":
            tl_size = await S.match_resolution(r, shots_info["width"], shots_info["height"], max_h=a.resolution)
        await S.build_shot_timeline(r, clip, shots, a.timeline_name, clip_fps=shots_info["fps"])

        S.log(f"3/7 apply PowerGrade as version '{version}' + 4/7 free-edition node handling")
        labels = None
        run_id = (await r.call("timeline_versioning", "begin_run", {"label": f"cineprint {version}"})).get("analysis_run_id")
        for sh in shots:
            item = dict(track_type="video", track_index=1, item_index=sh["idx"])
            await r.call("timeline_item_color", "add_version", {**item, "name": version, "type": 0})
            res = await r.confirmed("timeline_item_color", "safe_apply_drx", {**item, "path": str(drx), "grade_mode": 0})
            g = (res or {}).get("graphs", {}).get("item", {})
            if not res.get("success"):
                raise SystemExit(f"apply failed on shot {sh['idx']}: {str(res)[:300]}")
            labels = labels or await S.node_index_by_label(r, sh["idx"])
            disabled = []
            if not a.studio:
                for lab, idx in labels.items():
                    if lab in STUDIO_ONLY or lab.startswith("Grain"):
                        await r.call("graph", "set_node_enabled", {"source": "item", **item, "node_index": idx, "enabled": False})
                        disabled.append(lab)
            S.log(f"  shot {sh['idx']:2d}: nodes {g.get('num_nodes_before')}->{g.get('num_nodes_after')} disabled {disabled}")
        await r.call("timeline_versioning", "end_run", {"analysis_run_id": run_id})

        S.log("5/7 guide workflow per shot (measured from rendered frames)")
        caps = await S.capture_shots(r, shots, work / "captures", "default")
        exp_node, prim_node = labels.get("Exp") or labels.get("EXP"), labels.get("Primaries")
        if not exp_node or not prim_node:
            raise SystemExit(f"could not find Exp/Primaries nodes in {list(labels)}")
        prim = primaries_cdl(a.contrast, a.warmth, a.saturation)
        prim["Slope"][1] = round(prim["Slope"][1] * a.green, 4)
        for sh, cap in zip(shots, caps):
            st = A.frame_stats(A.load_rgb(cap))
            off = exposure_offset(st["median"], a.exposure_target) + (a.dark_lift if st["median"] < 0.42 else 0.0)
            item = dict(track_type="video", track_index=1, item_index=sh["idx"])
            r1 = await r.call("timeline_item_color", "safe_set_cdl", {**item, "cdl": {
                "NodeIndex": exp_node, "Slope": [1, 1, 1], "Offset": [off] * 3, "Power": [1, 1, 1], "Saturation": 1.0}})
            r2 = await r.call("timeline_item_color", "safe_set_cdl", {**item, "cdl": {"NodeIndex": prim_node, **prim}})
            S.log(f"  shot {sh['idx']:2d}: default median {st['median']:.3f} -> EXP offset {off:+.4f} | "
                  f"cdl {'OK' if r1.get('success') and r2.get('success') else 'FAILED'}")

        big = shots_info["width"] > 3840 or shots_info["height"] > 2160
        if not a.studio and a.grain > 0 and big:
            S.log(f"6/7 Fusion grain SKIPPED: the {shots_info['width']}x{shots_info['height']} source is larger than UHD; on free "
                  "Resolve, Fusion double-scales it (picture shrinks to timeline/source size). Grade stays grain-free.")
        elif not a.studio and a.grain > 0:
            S.log(f"6/7 Fusion grain (free replacement for the Studio-only grain node), blend {a.grain}")
            await S.fusion_texture(r, len(shots), grain_blend=a.grain, halation=None)

        S.log("7/7 verify every shot (rendered frames)")
        caps = await S.capture_shots(r, shots, work / "captures", "graded")
        rows = []
        from PIL import Image
        for sh, cap in zip(shots, caps):
            img = A.load_rgb(cap)
            st = A.frame_stats(img)
            wm = A.watermark_score(Image.open(cap))
            box = A.content_box(img) / max(A.content_box(A.load_rgb(work / "captures" / f"default_{sh['idx']:02d}.png")), 1e-6)
            rows.append({"shot": sh["idx"], **st, "watermark": wm, "picture_area_vs_ungraded": box})
            S.log(f"  shot {sh['idx']:2d}: luma p1/50/99 {st['p1']:.3f}/{st['median']:.3f}/{st['p99']:.3f} "
                  f"sat {st['sat']:.3f} watermark {'YES' if wm > 0.3 else 'none'} picture {box:.0%}")
            if box < 0.9:
                raise SystemExit(f"shot {sh['idx']}: the picture shrank to {box:.0%} of its ungraded size - a Fusion comp is "
                                 "rescaling it. Re-run with --grain 0 (see docs/LESSONS.md).")
        A.contact_sheet(caps, work / "graded_contact.jpg")
        report = {"connected": info, "powergrade": str(drx_src), "version": version, "shots": rows,
                  "watermark_free": all(x["watermark"] < 0.3 for x in rows)}
        await S.save(r)

        if a.export:
            name = a.export_name or f"{info['project']}_CinePrint35_{a.stock}_{'4K' if a.resolution == 2160 else 'HD'}".replace(" ", "_")
            target = "h264_2160p_web" if a.resolution == 2160 else "h264_1080p_web"
            ver = await S.render(r, target, a.export_dir, name, size=tl_size)
            chk = A.export_frames_check(ver["output_path"], shots, work / "export_frames")
            S.log(f"  export: {chk['codec']} {chk['width']}x{chk['height']} {chk['frames']} frames, "
                  f"watermark-free: {chk['watermark_free']}")
            report["export"] = {"file": ver["output_path"], **{k: v for k, v in chk.items() if k != "shots"},
                                "frames_checked": chk["shots"]}
        A.write_json(report, work / "report.json")
        S.log(f"DONE. watermark-free: {report['watermark_free']} | report: {work / 'report.json'}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cineprint-dir", required=True, help="your licensed 'CinePrint35 for Davinci Resolve' folder")
    p.add_argument("--camera", default="Sony S-Log3", help="PowerGrade folder, e.g. 'Sony S-Log3', 'Apple Log', 'Rec709'")
    p.add_argument("--stock", default="250D", choices=["250D", "500T", "160T"])
    p.add_argument("--gauge", default="35mm", choices=["35mm", "16mm"])
    p.add_argument("--mcp-config", default=os.environ.get("DAVINCI_MCP_CONFIG", ".mcp.json"))
    p.add_argument("--clip", help="media-pool clip name (substring); default = first video clip")
    p.add_argument("--import", dest="import_path", help="import this video file into the current project first")
    p.add_argument("--timeline-name", default="CinePrint35")
    p.add_argument("--work-dir", default="work/cineprint")
    p.add_argument("--exposure-target", type=float, default=0.52, help="median luma for daylight shots")
    p.add_argument("--contrast", type=float, default=1.08)
    p.add_argument("--saturation", type=float, default=1.10)
    p.add_argument("--warmth", type=float, default=1.0, help="0 = none, 1 = reference look, keep <= 2")
    p.add_argument("--green", type=float, default=1.0, help="Primaries green slope; <1 pulls skin from yellow to peach")
    p.add_argument("--dark-lift", type=float, default=0.0, help="extra EXP offset for low-key shots (median < 0.42)")
    p.add_argument("--look", choices=["landscape", "portrait"], default="landscape",
                   help="landscape = reference beach look; portrait = skin-first polish (verified on ARRI Alexa faces): "
                        "warmth 0.4, saturation 0.92, green 0.985, dark-lift 0.025")
    p.add_argument("--grain", type=float, default=0.25, help="Fusion grain blend (0.25 = subtle 35mm)")
    p.add_argument("--studio", action="store_true", help="Resolve Studio: keep all PowerGrade nodes, no Fusion grain")
    p.add_argument("--export", action="store_true")
    p.add_argument("--export-dir", default=str(Path.home() / "Videos" / "Resolve Exports"))
    p.add_argument("--export-name")
    p.add_argument("--resolution", type=int, default=2160, choices=[2160, 1080], help="export (and matched timeline) height")
    p.add_argument("--timeline-res", choices=["keep", "match"], default="keep",
                   help="match = timeline + export use the SOURCE aspect (e.g. 3:2 open gate -> 3240x2160), no bars/crop")
    a = p.parse_args()
    if a.look == "portrait":  # skin-first values from the Alexa polish (skin sat 0.58-0.68 -> 0.44-0.56)
        a.warmth, a.saturation, a.green, a.dark_lift = 0.4, 0.92, 0.985, 0.025
    asyncio.run(run(a))


if __name__ == "__main__":
    main()
