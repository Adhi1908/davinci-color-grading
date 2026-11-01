"""Reusable Resolve operations (all through the MCP server). Each step verifies by readback."""
from __future__ import annotations

import asyncio
from pathlib import Path

from .mcp_client import Resolve, first_image

GUIDE_SETTINGS = {  # CinePrint35 user guide, 'Project Settings'
    "colorSpaceTimeline": "Rec.709 Gamma 2.4",
    "colorSpaceOutput": "Rec.709 Gamma 2.4",
    "colorUseContrastSCurve": "0",  # linear contrast
}


def log(msg):
    print(msg, flush=True)


async def ensure_connected(r: Resolve) -> dict:
    v = await r.call("resolve_control", "get_version")
    if "version_string" not in v:
        raise SystemExit("Resolve is not answering. Free edition: open a project, then Workspace > Scripts > "
                         "resolve_bridge (see docs/SETUP.md). Studio: Preferences > General > External scripting = Local.")
    cur = await r.call("project_manager", "get_current")
    log(f"Connected: {v.get('product')} {v['version_string']} | project '{cur.get('name')}'")
    return {"version": v["version_string"], "project": cur.get("name")}


async def apply_guide_settings(r: Resolve):
    for k, val in GUIDE_SETTINGS.items():
        await r.call("project_settings", "set_setting", {"name": k, "value": val})
        got = (await r.call("project_settings", "get_setting", {"name": k})).get("settings")
        log(f"  setting {k} = {got} {'OK' if str(got) == val else 'MISMATCH'}")
    log("  NOTE: set 3D LUT interpolation to Tetrahedral by hand (Project Settings > Color Management); "
        "the scripting API does not expose it.")


async def find_clip(r: Resolve, name: str | None = None, import_path: str | None = None) -> dict:
    if import_path:
        res = await r.call("media_pool", "safe_import_media", {"paths": [str(import_path)]})
        log(f"  imported {import_path}: {res.get('success')}")
    pool = await r.call("media_pool", "probe_media_pool", {"depth": 2})
    clips = [c for c in pool["root"]["clips"] if "Video" in c.get("type", "")]
    for sub in pool["root"].get("subfolders", []):
        clips += [c for c in sub.get("clips", []) if "Video" in c.get("type", "")]
    if name:
        clips = [c for c in clips if name.lower() in c["name"].lower()]
    if not clips:
        raise SystemExit("No video clip found in the media pool (import one, or pass --clip / --import).")
    if len(clips) > 1 and not name:
        log(f"  {len(clips)} clips in pool; using the first: {clips[0]['name']} (pass --clip to choose)")
    return clips[0]


def _rate_str(fps: float) -> str:
    for nominal in (23.976, 24, 25, 29.97, 30, 47.952, 48, 50, 59.94, 60, 119.88, 120):
        if abs(fps - nominal) < 0.01:
            return f"{nominal:g}"
    return f"{fps:g}"


async def match_frame_rate(r: Resolve, clip_fps: float):
    """Timeline rate must equal the clip rate, or Resolve resamples each shot and the cut list gets gaps.

    Resolve only lets the timeline rate change while the project has no timelines.
    """
    cur = float((await r.call("project_settings", "get_setting", {"name": "timelineFrameRate"})).get("settings"))
    if abs(cur - clip_fps) < 0.01:
        return
    if (await r.call("timeline", "list")).get("timelines"):
        raise SystemExit(f"Project timeline rate is {cur:g} fps but the clip is {clip_fps:.3f} fps, and the project already "
                         f"has timelines (Resolve then locks the rate). Use a new project, or one set to {_rate_str(clip_fps)} fps.")
    val = _rate_str(clip_fps)
    for key in ("timelineFrameRate", "timelinePlaybackFrameRate"):
        await r.call("project_settings", "set_setting", {"name": key, "value": val})
    now = float((await r.call("project_settings", "get_setting", {"name": "timelineFrameRate"})).get("settings"))
    log(f"  project frame rate {cur:g} -> {now:g} fps (matches clip)")
    if abs(now - clip_fps) > 0.01:
        raise SystemExit("could not set the project frame rate to match the clip")


async def match_resolution(r: Resolve, src_w: int, src_h: int, max_h: int = 2160) -> tuple[int, int]:
    """Timeline resolution with the SOURCE aspect (e.g. 3:2 open gate -> 3240x2160): full frame, no bars, no crop.

    CinePrint35's guide warns that halation bleeds onto letter/pillarbox bars when aspects differ.
    """
    h = min(max_h, src_h) // 2 * 2
    w = round(h * src_w / src_h / 2) * 2
    for k, v in (("timelineResolutionWidth", w), ("timelineResolutionHeight", h)):
        await r.call("project_settings", "set_setting", {"name": k, "value": str(v)})
    gw = (await r.call("project_settings", "get_setting", {"name": "timelineResolutionWidth"})).get("settings")
    gh = (await r.call("project_settings", "get_setting", {"name": "timelineResolutionHeight"})).get("settings")
    log(f"  timeline resolution -> {gw}x{gh} (source aspect {src_w}x{src_h})")
    if (int(gw), int(gh)) != (w, h):
        raise SystemExit("could not set the timeline resolution")
    return w, h


async def build_shot_timeline(r: Resolve, clip: dict, shots: list, name: str, clip_fps: float | None = None) -> dict:
    if clip_fps:
        await match_frame_rate(r, clip_fps)
    infos = [{"clip_id": clip["id"], "start_frame": s["start"], "end_frame": s["end"], "record_frame": s["start"]}
             for s in shots]  # end_frame is EXCLUSIVE in this API
    res = await r.call("media_pool", "create_timeline_from_clips", {"name": name, "if_exists": "version", "clip_infos": infos})
    if not res.get("success"):
        raise SystemExit(f"timeline creation failed: {res}")
    await r.call("timeline", "set_current", {"name": res["name"]})
    gaps = await r.call("timeline", "detect_gaps_overlaps", {"track_types": ["video"]})
    tl = await r.call("timeline", "get_current")
    log(f"  timeline '{tl['name']}': {len(shots)} shots, gaps {gaps.get('gap_count')}, overlaps {gaps.get('overlap_count')}")
    if gaps.get("gap_count") or gaps.get("overlap_count"):
        raise SystemExit("timeline has gaps/overlaps - check the cut list")
    return tl


async def node_index_by_label(r: Resolve, item: int) -> dict:
    base = dict(source="item", track_type="video", track_index=1, item_index=item)
    n = (await r.call("graph", "get_num_nodes", base)).get("count") or 0
    out = {}
    for i in range(1, n + 1):
        out[(await r.call("graph", "get_node_label", {**base, "node_index": i})).get("label") or f"#{i}"] = i
    return out


async def fusion_texture(r: Resolve, n_items: int, grain_blend: float = 0.25, halation: list | None = None):
    """Per item: MediaIn -> [Halation35 SoftGlow] -> Grain35 FilmGrain -> MediaOut.

    MediaOut MUST descend from MediaIn or Resolve bypasses / fails the comp. Values are written
    without holding a comp lock (a locked value write silently never reaches the render).
    halation: list of per-item thresholds (log-space) or None for grain only.
    """
    for i in range(n_items):
        item = dict(track_type="video", track_index=1, item_index=i)
        scope = {"timeline_item": item}
        if not (await r.call("timeline_item_fusion", "get_comp_count", item)).get("count"):
            await r.call("timeline_item_fusion", "add_comp", item)
        tools = {t["name"] for t in (await r.call("fusion_comp", "get_tool_list", scope)).get("tools", [])}
        chain = [("Grain35", "FilmGrain")] if halation is None else [("Halation35", "SoftGlow"), ("Grain35", "FilmGrain")]
        for x, (nm, typ) in enumerate(chain, 1):
            if nm not in tools:
                await r.call("fusion_comp", "add_tool", {**scope, "tool_type": typ, "name": nm, "x": x, "y": 0})
        src = "MediaIn1"
        for nm, _ in chain:
            await r.call("fusion_comp", "connect", {**scope, "target_tool": nm, "input_name": "Input", "source_tool": src})
            src = nm
        await r.call("fusion_comp", "connect", {**scope, "target_tool": "MediaOut1", "input_name": "Input", "source_tool": src})
        ops = [("Grain35", "Blend", grain_blend)]
        if halation is not None:
            ops += [("Halation35", "Threshold", halation[i]), ("Halation35", "Gain", 1.8), ("Halation35", "XGlowSize", 14.0),
                    ("Halation35", "RedScale", 1.0), ("Halation35", "GreenScale", 0.42), ("Halation35", "BlueScale", 0.18),
                    ("Halation35", "Blend", 0.7)]
        res = await r.call("fusion_comp", "bulk_set_inputs", {"ops": [
            {"timeline_item": item, "tool_name": t, "input_name": n, "value": v} for t, n, v in ops]})
        got = (await r.call("fusion_comp", "get_input", {**scope, "tool_name": "Grain35", "input_name": "Blend"})).get("value")
        log(f"  item {i:2d}: fusion {' -> '.join(n for n, _ in chain)} | inputs {res.get('succeeded')}/{len(ops)} | grain {got}")


async def capture_shots(r: Resolve, shots: list, out_dir: str | Path, tag: str) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page = (await r.call("resolve_control", "get_page")).get("page")
    if page == "deliver":  # still export fails on the Deliver page
        await r.call("resolve_control", "open_page", {"page": "color"})
    start = (await r.call("timeline", "get_current"))["start_frame"]
    paths = []
    for sh in shots:
        res = await r.raw("timeline_frame", "capture", {"frame": start + sh["mid"], "quality": "frame", "format": "png"})
        data = first_image(res)
        if data is None:
            raise SystemExit(f"capture failed for shot {sh['idx']} (is playback running? stop it and retry)")
        p = out / f"{tag}_{sh['idx']:02d}.png"
        p.write_bytes(data)
        paths.append(p)
    return paths


async def render(r: Resolve, target: str, out_dir: str | Path, name: str, poll_s: float = 3.0,
                 size: tuple[int, int] | None = None) -> dict:
    """size overrides the target's raster (e.g. a 3:2 timeline exports 3240x2160 instead of a pillarboxed 3840x2160)."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    params = {"target": target, "target_dir": str(out_dir), "custom_name": name, "require_temp_target": False}
    if size:
        params["settings"] = {"FormatWidth": size[0], "FormatHeight": size[1]}
    job = await r.call("render", "prepare_delivery_job", params)
    if not job.get("job_id"):
        raise SystemExit(f"render job failed: {job}")
    await r.call("render", "start", {"job_ids": [job["job_id"]]})
    while True:
        st = await r.call("render", "get_job_status", {"job_id": job["job_id"]})
        if st.get("JobStatus") in ("Complete", "Failed", "Cancelled"):
            break
        await asyncio.sleep(poll_s)
    ver = await r.call("render", "verify_output", {"job_id": job["job_id"]})
    log(f"  render {st.get('JobStatus')} in {st.get('TimeTakenToRenderInMs', 0) / 1000:.0f}s -> {ver.get('output_path')} "
        f"({(ver.get('output_size_bytes') or 0) / 1e6:.0f} MB), frames {ver.get('mark_range_frames')}, verified {ver.get('verified')}")
    return ver


async def save(r: Resolve):
    res = await r.call("project_manager", "save")
    log(f"  project saved: {res.get('success')}")
