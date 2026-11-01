"""Re-tune an existing CinePrint35 timeline in place (no re-apply): exposure, contrast, warmth, saturation, tint.

Reads the untouched-grade captures from the original run (<work-dir>/captures/default_*.png) to recompute each
shot's EXP offset, then writes new CDLs to the Exp and Primaries nodes, on a NEW grade version by default
(it copies the current grade first). It re-captures every shot and reports exposure + skin-tone numbers.

  --dark-lift    extra EXP offset for low-key shots (default median < 0.42), e.g. 0.015 = about +0.05 median
  --green        Primaries green slope; < 1 pulls skin from yellow toward peach (e.g. 0.99)

usage: python -m grading.retune --work-dir work/cineprint --warmth 0.4 --saturation 0.9 --green 0.99 \
           --dark-lift 0.015 --version-name "CinePrint35 Polished"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

import numpy as np

from . import analysis as A
from . import resolve_steps as S
from .cineprint import exposure_offset, primaries_cdl
from .filmemu import rgb_to_hsv
from .mcp_client import connect


def skin_stats(img: np.ndarray) -> dict:
    """Median hue/sat/luma of skin-like pixels (HSV hue 5-45, sat 0.18-0.75), ignoring the bottom-left caption area."""
    a = img.copy()
    H, W = a.shape[:2]
    a[int(H * 0.55):, :int(W * 0.25)] = 0
    h, s, v = rgb_to_hsv(a)
    m = (h > 5) & (h < 45) & (s > 0.18) & (s < 0.75) & (v > 0.12) & (v < 0.95)
    if m.sum() < 2000:
        return {}
    y = a @ A.LUMA
    return {"skin_hue": float(np.median(h[m])), "skin_sat": float(np.median(s[m])), "skin_luma": float(np.median(y[m]))}


async def run(a):
    work = Path(a.work_dir)
    shots = json.loads((work / "shots.json").read_text())["shots"]
    async with connect(a.mcp_config) as r:
        await S.ensure_connected(r)
        labels = await S.node_index_by_label(r, 0)
        exp_node, prim_node = labels.get("Exp") or labels.get("EXP"), labels.get("Primaries")
        prim = primaries_cdl(a.contrast, a.warmth, a.saturation)
        prim["Slope"][1] = round(prim["Slope"][1] * a.green, 4)
        S.log(f"Primaries CDL: {prim}")
        run_id = (await r.call("timeline_versioning", "begin_run", {"label": f"retune {a.version_name}"})).get("analysis_run_id")
        for sh in shots:
            item = dict(track_type="video", track_index=1, item_index=sh["idx"])
            if a.version_name:
                await r.call("timeline_item_color", "add_version", {**item, "name": a.version_name, "type": 0})
            med = A.frame_stats(A.load_rgb(work / "captures" / f"default_{sh['idx']:02d}.png"))["median"]
            off = exposure_offset(med, a.exposure_target) + (a.dark_lift if med < 0.42 else 0.0)
            ok1 = (await r.call("timeline_item_color", "safe_set_cdl", {**item, "cdl": {
                "NodeIndex": exp_node, "Slope": [1, 1, 1], "Offset": [round(off, 4)] * 3, "Power": [1, 1, 1], "Saturation": 1.0}})).get("success")
            ok2 = (await r.call("timeline_item_color", "safe_set_cdl", {**item, "cdl": {"NodeIndex": prim_node, **prim}})).get("success")
            if not (ok1 and ok2):
                raise SystemExit(f"CDL write failed on shot {sh['idx']}")
        await r.call("timeline_versioning", "end_run", {"analysis_run_id": run_id})
        caps = await S.capture_shots(r, shots, work / "captures", a.tag)
        rows = []
        for sh, cap in zip(shots, caps):
            img = A.load_rgb(cap)
            st, sk = A.frame_stats(img), skin_stats(img)
            rows.append({"shot": sh["idx"], **st, **sk})
            skin = f"skin hue {sk['skin_hue']:4.1f} sat {sk['skin_sat']:.2f} luma {sk['skin_luma']:.3f}" if sk else "skin -"
            S.log(f"  shot {sh['idx']:2d}: median {st['median']:.3f} sat {st['sat']:.3f} | {skin}")
        A.contact_sheet(caps, work / f"{a.tag}_contact.jpg")
        A.write_json(rows, work / f"{a.tag}.json")
        await S.save(r)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work-dir", required=True, help="work dir of the original grading.cineprint run")
    p.add_argument("--mcp-config", default=os.environ.get("DAVINCI_MCP_CONFIG", ".mcp.json"))
    p.add_argument("--exposure-target", type=float, default=0.52)
    p.add_argument("--dark-lift", type=float, default=0.0)
    p.add_argument("--contrast", type=float, default=1.08)
    p.add_argument("--warmth", type=float, default=1.0)
    p.add_argument("--saturation", type=float, default=1.10)
    p.add_argument("--green", type=float, default=1.0)
    p.add_argument("--version-name", default="", help="new grade version to create first ('' = edit current version)")
    p.add_argument("--tag", default="retune")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
