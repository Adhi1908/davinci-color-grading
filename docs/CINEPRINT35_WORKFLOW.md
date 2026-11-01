# CinePrint35 pipeline: what it does and why

Reference: `Testing3_CinePrint35_250D_4K.mp4`. This is 11 shots of sunny Mediterranean S-Log3 footage
with the Sony S-Log3 250D 35mm PowerGrade, graded on free Resolve 21.0.3. The pipeline re-runs that grade.

## The PowerGrade (21 nodes, 4 rows)
| Row | Nodes |
|---|---|
| Pre | Denoise, To LogC (camera → ARRI LogC3), **Exp**, WB, PRE |
| Emulation | Halation35, <stock> tone, <stock> color, -green HL, Gate Wv, Grain35 |
| Post | Saturation, **Primaries**, con, HSV, Pastel, TintCurves |
| Output | CineonOut, PrintOut (Kodak 2383), Warm WP, Dust |

## Free edition: which nodes must go
Measured by applying the grade, capturing a frame, and toggling nodes one at a time:
- **Studio-only (watermark the output):** Denoise, Gate Wv (Camera Shake), **Grain35/Grain16** (Film Grain), Dust (Film Damage).
- **Free:** everything else, including his **Halation**, the CSTs, tone/colour and the print LUT.

The pipeline disables nodes **by label**. That's robust across camera variants. On a 35mm Sony grade they are nodes 1, 10, 11 and 21.
Grain is replaced with **Fusion FilmGrain** (free) at blend **0.25**, on the log image before the grade.
That's the same place his grain sits relative to contrast, so later contrast shapes it the same way.

## Per-shot workflow (the guide's "adjust EXP, WB, contrast, saturation")
All values are written as CDL on named nodes and computed from **rendered** frames:

1. **Exp node Offset**: measured effect: +0.04 offset ≈ +0.12 output median, about ½ stop.
   - Daylight shots target median **0.52**.
   - Dark-content shots (median < 0.42, e.g. seaweed, rocks) target `min(0.45, median + 0.12)`, so they keep their mood.
   - Offset = `clip((target − median)/3, ±0.05) − 0.015`. The −0.015 is the final density trim of the reference.
2. **WB node: left neutral.** Auto-WB from the mid-tones read the real blue of sea and sky as a "cast", and turned the skies mint-yellow.
3. **Primaries node**: contrast **1.08** around Cineon-log pivot **0.44**, written as slope c and offset 0.44·(1−c). Plus a gentle warm white point (slope R×1.012, B×0.985; offset R+0.003, B−0.004) and saturation **1.10**.
   - Keep warmth small: a warm slope over about 1.03 in this log stage turns skies mint-yellow.

## Verification the pipeline performs
- Node count 1 → 21 per shot, and disabled labels read back.
- Every shot captured from Resolve's own render path, with stats and a **watermark detector**: the free watermark's dot grid scores about 0.9, a clean frame 0.0.
- After export, frames are decoded **from the file itself**: codec, resolution, frame count, audio, watermark on every shot.

## Choosing a stock
- **250D**: natural daylight. The reference.
- **500T**: warmer, with a sunset feel.
- **160T** (Fuji Eterna Vivid): rich colour and silvery-cool greys.
- **16mm** variants: heavier halation and grain.
