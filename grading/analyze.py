"""Inspect footage before grading (read-only): shots, levels, and a log-vs-display guess.

usage: python -m grading.analyze <video> [--out work/analyze]

How to read it
  log footage (LogC3 / S-Log3 / V-Log ...): flat - darkest ~0.08-0.20, brightest ~0.55-0.75, low saturation
      -> use that camera's CinePrint35 PowerGrade (--camera "Arri Alexa LogC3", "Sony S-Log3", ...)
  display-referred (Rec.709, already contrasty): darkest ~0.0-0.05, brightest > 0.9
      -> use --camera "Rec709"
  warm/orange cast + practical lamps -> 500T (tungsten); daylight/exteriors -> 250D; rich colour, cool greys -> 160T
"""
from __future__ import annotations

import argparse
import glob
from pathlib import Path

import numpy as np

from . import analysis as A


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video")
    p.add_argument("--out", default="work/analyze")
    a = p.parse_args()
    out = Path(a.out)
    info = A.detect_shots(a.video, thumbs_dir=out / "source")
    A.write_json(info, out / "shots.json")
    shots = info["shots"]
    print(f"{info['width']}x{info['height']} @ {info['fps']:.3f} fps, {info['frames']} frames, {len(shots)} shots")
    sats = []
    for s in shots:
        img = A.load_rgb(out / "source" / f"shot_{s['idx']:02d}.jpg")
        st = A.frame_stats(img)
        sats.append(st["sat"])
        print(f"  #{s['idx']:02d} frames {s['start']}-{s['end']} ({s['dur_s']}s)  luma p1/50/99 "
              f"{s['luma_p1']:.3f}/{s['luma_p50']:.3f}/{s['luma_p99']:.3f}  sat {st['sat']:.3f}  "
              f"tint R{s['tint'][0]:+.3f} G{s['tint'][1]:+.3f} B{s['tint'][2]:+.3f}")
    p1 = np.median([s["luma_p1"] for s in shots])
    p99 = np.median([s["luma_p99"] for s in shots])
    sat = float(np.median(sats))
    looks_log = p1 > 0.06 and p99 < 0.85 and sat < 0.09
    print(f"\nverdict: {'LOG (flat) footage' if looks_log else 'display-referred / already graded'} "
          f"(median darkest {p1:.3f}, brightest {p99:.3f}, saturation {sat:.3f})")
    A.contact_sheet(sorted(glob.glob(str(out / "source" / "shot_*.jpg"))), out / "source_contact.jpg",
                    cols=min(4, len(shots)), tile_w=480)
    print(f"contact sheet: {out / 'source_contact.jpg'}")


if __name__ == "__main__":
    main()
