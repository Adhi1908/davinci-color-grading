# Film-emulation engine (`grading/filmemu.py`)

This is a standalone LUT engine with no third-party assets. Preset **`slog3_polished`** reproduces
`Testing2_FilmEmulation_4K_Polished.mp4` exactly. Its port was regression-tested at 0.0 difference across all LUT entries.

## Stages
1. **Pre-emulation (per shot).** Exposure offset `0.5·(exp_target − shot median) + exp_bias` and half-neutralised mid-tone WB.
   Then pre-contrast down, pre-saturation up, and a soft-knee Y curve that holds bright skies and sand.
2. **Emulation.** A print sigmoid on log values (steep toe, long shoulder), then film hue moves, then subtractive saturation.
3. **Post.** Contrast up, then a warm white point and **golden mids on everything except sky/sea** (smooth `B−R` weight).
   Then a warm shadow tint and minus-green in the highlights.
4. **Output.** A "Pastel" print-black floor at about 0.08 (his finished grades sit at 0.10–0.12).

Targets were measured from the CinePrint35 tutorial's own finished frames:
- black floor 0.10–0.12;
- golden mids with blue −0.08 to −0.11;
- warm bright tones with cyan skies;
- saturation 0.12–0.15.

## Presets
- `slog3_polished`: S-Log3 daylight; steeper print shoulder (k 10.5). The favourite.
- `slog2_natural`: flatter S-Log2 or low-bitrate log; gentler.

Add a preset by copying a dict in `PRESETS` and changing values. Then preview it without Resolve:
`python -m grading.film_emulation --preset NAME --preview-only --source clip.mp4`

## Texture (Fusion, per shot)
- **Halation35 (SoftGlow):**
  - Threshold = that shot's log p99 − 0.01, so only the top ~1% of highlights glow.
  - Gain 1.8, size 14, Blend 0.7.
  - Colour R 1 / G 0.42 / B 0.18, red-orange like real halation.
- **Grain35 (FilmGrain):** Blend 0.25, about 4–5 levels of noise at 1080. That's subtle 35mm, and it also dithers the
  banding that 8-bit web sources show in skies.
