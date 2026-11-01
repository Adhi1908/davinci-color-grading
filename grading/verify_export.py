"""Verify a rendered file (read-only): streams, frame count, resolution, and NO free-edition watermark on every shot.

usage: python -m grading.verify_export <rendered.mp4> <work/.../shots.json> [--out work/verify]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import analysis as A


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("video")
    p.add_argument("shots_json")
    p.add_argument("--out", default="work/verify")
    a = p.parse_args()
    shots = json.loads(Path(a.shots_json).read_text())["shots"]
    chk = A.export_frames_check(a.video, shots, a.out)
    print(f"{chk['codec']} {chk['width']}x{chk['height']} @ {chk['fps']:.3f} fps, {chk['frames']} frames, "
          f"{chk['duration']:.2f}s, audio={'yes' if chk['audio'] else 'no'}")
    for r in chk["shots"]:
        print(f"  shot {r['shot']:2d}: watermark {'YES' if r['watermark'] > 0.3 else 'none'} "
              f"(score {r['watermark']:.2f})  luma median {r['median']:.3f}")
    A.contact_sheet(sorted(Path(a.out).glob("export_*.jpg")), Path(a.out) / "export_contact.jpg")
    print("VERDICT:", "watermark-free" if chk["watermark_free"] else "WATERMARK FOUND - a Studio-only node is enabled")
    A.write_json(chk, Path(a.out) / "verify.json")


if __name__ == "__main__":
    main()
