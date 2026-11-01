# Lessons (each one cost a failed attempt; read before changing the pipelines)

## Resolve / MCP
- **Free 21.1+ cannot be scripted.** Python scripting moved to Studio, so the bridge script stops listing. Stay on 21.0.x.
- The **bridge stops whenever Resolve restarts**. Run Workspace > Scripts > resolve_bridge again.
- `create_timeline_from_clips`: **end_frame is exclusive**. Inclusive ends leave 1-frame black gaps.
- **A new project defaults to 24 fps.** A 25 fps clip on that timeline gets every shot resampled (247 → 237 frames)
  but keeps its record positions, which leaves gaps. The rate can only change while the project has **no timelines**,
  so the pipelines set it to the clip's rate before building anything.
- The MCP server logs `→` characters. On Windows (cp1252) consoles that spams encode errors unless `PYTHONIOENCODING=utf-8`.
- Frame capture **fails on the Deliver page** (switch to Color first) and **during playback**. Never switch pages during playback; it can hang Resolve.
- `safe_apply_drx` only loads a .drx from a temp dir by default and is confirm-token gated. It **replaces** the graph, so always add a new version first.
- **Resolve caches LUTs by file name.** Install changed LUTs under new names, then call `refresh_luts`.
- **Fusion on timeline clips renders on free 21.0.3**, but only if MediaOut descends from MediaIn and values aren't written under a comp lock.
  Prove it with a rendered frame, never with input readback.
- The bridge can't list Fusion inputs (no `GetAttrs`). Probe names with `get_input` instead.
- Fusion grain/halation is processed at the **output** resolution: a 4K render of a 1080 timeline stays true 4K. Measured.
- Grain makes exports large (about 260 Mbps for 4K H.264). Make a separate H.265 copy for sharing.

## Grading
- **Look at rendered frames, not metadata.** Every grade here was checked on Resolve's own output.
- **Hue or saturation *threshold* weights inside a LUT make skies blotchy.** Use smooth RGB weights (e.g. `B−R`). Measured: sky blotch 0.754 → 0.643.
- **Warm white points must skip blue.** Warming bright tones blindly turns skies purple (display space) or mint-yellow (log space).
- **Don't auto white-balance from mid-tone tint on sea/sky footage.** It strips real blue.
- **S-Log3 white sits only about 0.2 above grey.** It needs a steeper print shoulder than S-Log2, or whites stop at about 0.75.
- **Saturation boosts can turn underwater red algae magenta.** Pull magenta toward red-brown.
- **Pastel print blacks (about 0.10) are what reads as "film".** Crushed digital blacks don't.
- **YouTube 8-bit sources band in skies under heavy contrast.** Grain at blend 0.25 dithers it; 0.15 is too weak, 0.6 far too heavy.
- **CinePrint35 default ≠ the tutorial's finished look.** The golden warmth in his examples came from per-shot grading on top.
