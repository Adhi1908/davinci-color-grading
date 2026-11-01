"""Read-only footage analysis: shot detection, frame stats, colour fingerprints, watermark detection.

Source media is only ever READ (decoded with PyAV); nothing is written next to it.
"""
from __future__ import annotations

import json
from pathlib import Path

import av
import numpy as np
from PIL import Image

LUMA = np.array([0.2126, 0.7152, 0.0722])


# ----------------------------------------------------------------------------- shots
def detect_shots(video: str | Path, thumbs_dir: str | Path | None = None, min_len: int = 8) -> dict:
    """Hard-cut detection on a downscaled decode. Returns {fps, frames, width, height, shots:[...]}.

    A cut is where the RGB-histogram distance jumps >0.35 and >4x its local median.
    Each shot: idx, start, end (end EXCLUSIVE, matching Resolve's clip_infos), mid, luma stats.
    """
    hists, smalls = [], []
    with av.open(str(video)) as c:
        v = c.streams.video[0]
        v.thread_type = "AUTO"
        fps = float(v.average_rate)
        w, h = v.codec_context.width, v.codec_context.height
        for f in c.decode(v):
            a = f.to_ndarray(width=96, height=54, format="rgb24").astype(np.float32) / 255.0
            smalls.append(a)
            hh = np.concatenate([np.histogram(a[..., k], bins=16, range=(0, 1))[0] for k in range(3)]).astype(np.float32)
            hists.append(hh / hh.sum())
    n = len(hists)
    d = np.array([0.0] + [np.abs(hists[i] - hists[i - 1]).sum() for i in range(1, n)])
    cuts = [0]
    for i in range(1, n):
        local = np.median(d[max(1, i - 15):min(n, i + 16)])
        if d[i] > 0.35 and d[i] > 4 * max(local, 0.02) and i - cuts[-1] >= min_len:
            cuts.append(i)
    cuts.append(n)
    shots = []
    for k in range(len(cuts) - 1):
        s, e = cuts[k], cuts[k + 1]
        px = np.stack(smalls[s:e]).reshape(-1, 3)
        y = px @ LUMA
        p = np.percentile(y, [1, 50, 99])
        shots.append(dict(idx=k, start=s, end=e, mid=(s + e) // 2, dur_s=round((e - s) / fps, 2),
                          luma_p1=round(float(p[0]), 3), luma_p50=round(float(p[1]), 3), luma_p99=round(float(p[2]), 3),
                          tint=[round(float(x), 4) for x in (px - y[:, None]).mean(0)]))
    if thumbs_dir:
        save_frames(video, [s["mid"] for s in shots], thumbs_dir, "shot", width=480)
    return dict(fps=fps, frames=n, width=w, height=h, shots=shots)


def save_frames(video, frame_indices, out_dir, prefix, width=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    want = {fi: k for k, fi in enumerate(frame_indices)}
    with av.open(str(video)) as c:
        v = c.streams.video[0]
        v.thread_type = "AUTO"
        W, H = v.codec_context.width, v.codec_context.height
        for i, f in enumerate(c.decode(v)):
            if i in want:
                im = f.to_image() if not width else f.to_image(width=width, height=int(width * H / W))
                im.save(out / f"{prefix}_{want[i]:02d}.jpg", quality=88)
            if i >= max(want):
                break


# ----------------------------------------------------------------------------- stats
def load_rgb(path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB")).astype(np.float64) / 255.0


def frame_stats(img: np.ndarray) -> dict:
    y = img @ LUMA
    ch = img - y[..., None]
    mids = (y > 0.25) & (y < 0.55)
    tint = ch[mids].mean(0) if mids.sum() > 100 else np.zeros(3)
    return dict(p1=float(np.percentile(y, 1)), median=float(np.median(y)), p99=float(np.percentile(y, 99)),
                sat=float(np.sqrt((ch ** 2).sum(-1)).mean()), mid_tint=[float(t) for t in tint])


# ----------------------------------------------------------------------------- watermark
def watermark_score(img_1080: Image.Image) -> float:
    """Free-edition 'DaVinci Resolve Studio' watermark = grid of white dots every 100px (x=60.., y=40..) at 1080p.

    Returns the share of grid points that are near-white AND brighter than their ring.
    Calibrated: a watermarked frame scores ~0.9, a clean graded frame 0.0.
    """
    y = np.asarray(img_1080.convert("RGB").resize((1920, 1080))).astype(float) @ LUMA / 255
    hits = total = 0
    for gx in range(60, 1900, 100):
        for gy in range(40, 1060, 100):
            c = y[gy - 1:gy + 2, gx - 1:gx + 2].mean()
            ring = np.concatenate([y[gy - 7, gx - 7:gx + 8], y[gy + 7, gx - 7:gx + 8],
                                   y[gy - 7:gy + 8, gx - 7], y[gy - 7:gy + 8, gx + 7]]).mean()
            total += 1
            hits += (c > 0.9) and (c - ring > 0.12)
    return hits / total


def export_frames_check(video: str | Path, shots: list, out_dir: str | Path) -> dict:
    """Decode one frame per shot from a rendered file: stream facts + watermark score + stats."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with av.open(str(video)) as c:
        v = c.streams.video[0]
        fps = float(v.average_rate)
        info = dict(codec=v.codec_context.name, width=v.codec_context.width, height=v.codec_context.height,
                    fps=fps, frames=v.frames, duration=c.duration / 1e6, audio=bool(c.streams.audio))
        for sh in shots:
            t = sh["mid"] / fps
            c.seek(int(t / v.time_base), stream=v)
            for f in c.decode(v):
                if f.time >= t - 1e-3:
                    im = f.to_image().resize((1920, 1080), Image.LANCZOS)
                    break
            im.save(out / f"export_{sh['idx']:02d}.jpg", quality=85)
            rows.append(dict(shot=sh["idx"], watermark=watermark_score(im),
                             **frame_stats(np.asarray(im).astype(float) / 255)))
    info["shots"] = rows
    info["watermark_free"] = all(r["watermark"] < 0.3 for r in rows)
    return info


def contact_sheet(paths, out, cols=4, tile_w=360):
    from PIL import ImageDraw
    ims = [Image.open(p).convert("RGB") for p in paths]
    th = int(tile_w * ims[0].size[1] / ims[0].size[0])
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * th), (20, 20, 20))
    dr = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        x, y = (i % cols) * tile_w, (i // cols) * th
        sheet.paste(im.resize((tile_w, th)), (x, y))
        dr.text((x + 8, y + 6), f"#{i}", fill="white")
    sheet.save(out, quality=86)


def write_json(obj, path):
    Path(path).write_text(json.dumps(obj, indent=1), encoding="utf-8")
