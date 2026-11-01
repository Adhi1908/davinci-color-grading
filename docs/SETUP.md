# Setup (once per machine)

## 1. DaVinci Resolve
- **Studio**: any recent version. Set Preferences > General > External scripting using = **Local**.
- **Free edition**: install **21.0.x (21.0.3 is tested)**. Do **not** update to 21.1 or later: free 21.1
  moved Python scripting to Studio, and the bridge below stops appearing in the Scripts menu. Get older builds from
  Blackmagic's support page (Resolve & Fusion > "DaVinci Resolve 21.0.3 Update", not "Studio"). Decline
  update prompts.

## 2. The davinci-resolve MCP server
```bash
npx davinci-resolve-mcp setup        # or: git clone https://github.com/samuelgursky/davinci-resolve-mcp && python install.py
```
Copy `.mcp.json.example` to `.mcp.json` in this repo and fill in the server's Python and `server.py`
path. Use the `RESOLVE_SCRIPT_*` paths for your OS; the installer prints them. On Windows, if Python
is a per-user install, also add `"PYTHONHOME"` pointing at it. The same file works for Claude Code.

## 3. Free edition only: the in-app bridge
Free Resolve refuses outside connections. The MCP server ships a small script that runs inside Resolve:
```bash
python <davinci-resolve-mcp>/scripts/install_resolve_bridge.py
```
Restart Resolve, open a project, then run **Workspace > Scripts > resolve_bridge**.
**Repeat that last step every time Resolve starts.** It doesn't persist across restarts.

## 4. Project settings (CinePrint35 guide)
`grading.cineprint` sets these itself: timeline and output colour space **Rec.709 Gamma 2.4**, and
**Use S-curve for contrast off**. Do one by hand, because the API can't reach it:
**Project Settings > Color Management > 3D Lookup Table Interpolation = Tetrahedral**.

## 5. Python
Python 3.10+, then `pip install -r requirements.txt`.

## Checks
- `python -m grading.cineprint --help` / `python -m grading.film_emulation --help`
- "Resolve is not answering": the bridge isn't running (step 3), or Studio scripting isn't set to Local.
- A capture fails with PLAYBACK_ACTIVE: stop playback in Resolve (Space) and re-run.
