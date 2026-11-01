"""Film-emulation LUT engine (no third-party assets) - the 'Polished' look.

Built on the 4-stage structure taught in the CinePrint35 tutorial, with targets measured from the
tutorial's own finished grades. Produces one 33-pt .cube per shot (per-shot exposure/WB baked in).

  1 PRE-EMULATION   per-shot exposure + white balance as log offsets ("printer lights"), lower
                    contrast, raise saturation, optional Y-curve holding the highlights
  2 EMULATION       print characteristic curve on the log values (steep toe, long shoulder) +
                    film colour response (hue moves) + subtractive saturation
  3 POST-EMULATION  contrast up, warm white point on everything EXCEPT sky/sea (smooth B-R weight),
                    log-wheel style shadow tint, minus-green highlights, golden mids
  4 OUTPUT          'Pastel' lifted print-black floor, Rec.709 display values

Input = the log footage exactly as Resolve's first node sees it.
Lessons baked in: hue/saturation THRESHOLD weights make skies blotchy in a LUT (use smooth RGB
weights); 33 points is smoother than 65 here; S-Log3 needs a steeper print shoulder than S-Log2.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

LUMA = np.array([0.2126, 0.7152, 0.0722])

BASE = dict(
    pivot=0.38, pre_contrast=0.92, pre_sat=1.65,
    m=0.38, k_toe=12.0, k_shoulder=7.0,
    black=(0.010, 0.016, 0.016), white=(0.975, 0.962, 0.940),
    subtractive=0.30,
    hue_moves=((240.0, 28.0, -24.0, 0.62), (66.0, 22.0, 18.0, 1.05)),
    post_pivot=0.42, post_contrast=1.06, post_sat=1.0,
    warm=(0.030, 0.006, -0.036), shadow_tint=(-0.016, 0.010, 0.004), minus_green=0.012,
    # per-shot exposure = 0.5 * (exp_target - shot median) + exp_bias   (log offset)
    exp_target=0.33, exp_bias=0.0,
)

PRESETS = {
    # The user's favourite (Testing2_FilmEmulation_4K_Polished.mp4): S-Log3 daylight, golden + cyan, Pastel blacks
    "slog3_polished": {**BASE,
        "pre_sat": 1.85, "pre_hl_knee": 0.54, "pre_hl_ratio": 0.75,
        "m": 0.40, "k_toe": 13.0, "k_shoulder": 10.5,
        "warm": (0.036, 0.010, -0.042), "shadow_tint": (0.008, 0.002, -0.010),
        "post_contrast": 1.06, "warm_mode": "b_minus_r", "mid_gold": (0.015, 0.005, -0.032),
        "pastel_floor": (0.084, 0.081, 0.071), "post_sat": 1.14,
        "hue_moves": ((325.0, 26.0, 28.0, 0.55), (272.0, 26.0, -38.0, 0.70), (235.0, 30.0, -20.0, 0.85),
                      (190.0, 25.0, 0.0, 1.25), (66.0, 22.0, 18.0, 1.05)),
        "exp_target": 0.44, "exp_bias": -0.045},
    # Flatter S-Log2-like / low-bitrate log footage (the 'testing' garden project)
    "slog2_natural": {**BASE},
}


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def print_curve(x, L):
    blend = 1.0 / (1.0 + np.exp((x - L["m"]) * 25.0))
    k = L["k_shoulder"] + (L["k_toe"] - L["k_shoulder"]) * blend
    s = 1.0 / (1.0 + np.exp(-(x - L["m"]) * k))
    lo, hi = np.array(L["black"]), np.array(L["white"])
    return lo + (hi - lo) * s


def rgb_to_hsv(c):
    mx, mn = c.max(-1), c.min(-1)
    d = mx - mn
    dd = np.where(d == 0, 1.0, d)
    r, g, b = c[..., 0], c[..., 1], c[..., 2]
    h = np.where(mx == r, ((g - b) / dd) % 6, np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4)) * 60.0
    h = np.where(d == 0, 0.0, h)
    s = np.where(mx == 0, 0.0, d / np.where(mx == 0, 1.0, mx))
    return h, s, mx


def hsv_to_rgb(h, s, v):
    h = (h % 360.0) / 60.0
    i = np.floor(h).astype(int) % 6
    f = h - np.floor(h)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    choices = [np.stack(x, -1) for x in ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))]
    out = np.zeros(h.shape + (3,))
    for k in range(6):
        out = np.where((i == k)[..., None], choices[k], out)
    return out


def colour_response(d, L):
    h, s, v = rgb_to_hsv(np.clip(d, 0, None))
    for centre, width, shift, sat in L["hue_moves"]:
        dist = (h - centre + 180.0) % 360.0 - 180.0
        w = np.exp(-(dist / width) ** 2) * np.clip(s / 0.12, 0, 1)  # leave near-greys alone
        h = h + w * shift
        s = s * (1.0 + w * (sat - 1.0))
    return hsv_to_rgb(h, np.clip(s, 0, 1), v)


def grade(rgb, trim: dict, L: dict) -> np.ndarray:
    x = np.asarray(rgb, dtype=np.float64)
    # 1 pre-emulation
    x = x + trim["exposure"] + np.array(trim.get("wb", (0.0, 0.0, 0.0)))
    x = L["pivot"] + (x - L["pivot"]) * L["pre_contrast"]
    if L.get("pre_hl_knee") is not None:
        y = x @ LUMA
        w = 0.03
        soft = w * np.log1p(np.exp((y - L["pre_hl_knee"]) / w))
        x = x - ((1.0 - L["pre_hl_ratio"]) * soft)[..., None]
    y = x @ LUMA
    x = y[..., None] + (x - y[..., None]) * L["pre_sat"]
    # 2 emulation
    d = print_curve(x, L)
    d = colour_response(d, L)
    s = d.max(-1) - d.min(-1)
    d = d * (1.0 - L["subtractive"] * s)[..., None]
    # 3 post-emulation
    d = L["post_pivot"] + (d - L["post_pivot"]) * L["post_contrast"]
    y = d @ LUMA
    d = y[..., None] + (d - y[..., None]) * L["post_sat"]
    if L.get("warm_mode") == "b_minus_r":
        keep = 1.0 - smoothstep(-0.01, 0.06, d[..., 2] - d[..., 0])  # smooth sky/sea protection
    else:
        keep = 1.0 - smoothstep(0.04, 0.18, d.max(-1) - d.min(-1))  # near-neutrals only
    wh = (smoothstep(0.50, 0.95, y) * keep)[..., None]
    ws = (np.clip(1.0 - y / 0.45, 0, 1) ** 2)[..., None]
    d = d + wh * np.array(L["warm"]) + ws * np.array(L["shadow_tint"])
    d[..., 1] -= wh[..., 0] * L["minus_green"]
    if L.get("mid_gold") is not None:
        wm = (smoothstep(0.12, 0.35, y) * (1.0 - smoothstep(0.70, 0.92, y)) * keep)[..., None]
        d = d + wm * np.array(L["mid_gold"])
    # 4 output
    if L.get("pastel_floor") is not None:
        f = np.array(L["pastel_floor"])
        d = f + np.clip(d, 0, 1) * (1.0 - f)
    return np.clip(d, 0.0, 1.0)


def mid_tint(img):
    y = img @ LUMA
    m = (y > 0.2) & (y < 0.55)
    return (img - y[..., None])[m].mean(0) if m.sum() > 50 else np.zeros(3)


def shot_trim(shot: dict, thumb_rgb: np.ndarray, L: dict) -> dict:
    """Per-shot pre-emulation trim: half-normalised exposure + half-neutralised mid-tone cast."""
    return {"exposure": round(0.5 * (L["exp_target"] - shot["luma_p50"]) + L["exp_bias"], 4),
            "wb": tuple(float(v) for v in (-0.5 * mid_tint(thumb_rgb)))}


def write_cube(path: str | Path, trim: dict, L: dict, n: int = 33):
    lin = np.linspace(0.0, 1.0, n)
    b, g, r = np.meshgrid(lin, lin, lin, indexing="ij")  # R varies fastest in .cube order
    out = grade(np.stack([r, g, b], axis=-1).reshape(-1, 3), trim, L)
    path = Path(path)
    with open(path, "w", newline="\n") as f:
        f.write(f'TITLE "{path.stem} - davinci-color-grading film emulation"\n')
        f.write(f"LUT_3D_SIZE {n}\nDOMAIN_MIN 0.0 0.0 0.0\nDOMAIN_MAX 1.0 1.0 1.0\n")
        for v in out:
            f.write(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
