---
name: davinci-film-grade
description: Film-emulation colour grading in DaVinci Resolve via the davinci-resolve MCP server. Use when asked to colour grade, apply CinePrint35, give footage a film look, match the Testing3/Polished reference exports, or export a graded video. Reproduces the reference results with this repo's one-command pipelines.
---

# davinci-film-grade

## Before anything
1. Check the connection: `resolve_control get_version`. If it fails on the free edition, tell the user to open a
   project and run **Workspace > Scripts > resolve_bridge**, then wait for it. Never update free Resolve past 21.0.x.
2. Ask what to grade only if it's unclear: which project or clip, CinePrint35 or the engine, and which stock.

## Run the pipeline (preferred; it encodes every verified value)
- Genuine CinePrint35 look (user's own pack; never commit or upload its files):
  `python -m grading.cineprint --cineprint-dir "<their pack>" --camera "<camera>" --stock 250D --gauge 35mm --export`
- No-asset Polished look: `python -m grading.film_emulation --preset slog3_polished --export`
- Both read `.mcp.json` (or `--mcp-config` / `DAVINCI_MCP_CONFIG`) and write `work/<pipeline>/report.json` plus contact sheets.

## Then verify and report honestly
- Open `graded_contact.jpg` and look at it. Read `report.json`: every shot's watermark must be "none"
  (score < 0.3), with the right frame count and resolution.
- Fix by re-running with knobs (`--exposure-target`, `--contrast`, `--warmth`, `--saturation`, `--grain`).
  Don't hand-edit nodes unless asked.
- Exports with grain are large. Offer an H.265 copy for sharing.

## Rules learned the hard way (details: docs/LESSONS.md)
- **Free edition:** disable Denoise, Gate Wv, Grain*, Dust in CinePrint35. Their Halation is free. Replace grain with Fusion FilmGrain 0.25.
- Grade on **rendered frames**, never metadata. Stop and tell the user if playback is running (captures fail; page switches can hang Resolve).
- Every new grade goes on a **new version**. The user's existing grades must stay one click away.
- **Frame rate:** the project's timeline rate must match the clip before any timeline exists. The pipelines handle it.
  If a project already has timelines at another rate, use a new project.
- **Skies:**
  - No hue/saturation threshold weights in LUTs (blotches).
  - Warmth must skip blue (purple or mint skies).
  - No auto-WB from mid-tones on sea/sky footage.
- **Licensing:** CinePrint35 is paid. Never commit `.drx`, the OSM LUTs, or the PDF and its text. Each user brings their own copy.
