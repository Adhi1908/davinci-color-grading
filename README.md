# davinci-color-grading

Film-emulation colour grading for **DaVinci Resolve**, automated through the
[davinci-resolve MCP server](https://github.com/samuelgursky/davinci-resolve-mcp). It works on the **free
edition** with no watermark.

Two one-command pipelines. Each reproduces a reference export from the original grading session:

| Pipeline | Reference result | Needs |
|---|---|---|
| **`grading.cineprint`** | `Testing3_CinePrint35_250D_4K.mp4`: genuine CinePrint35 Kodak 250D 35mm print look (teal skies, olive Kodak greens, print density, grain) | **Your own licensed copy of CinePrint35** |
| **`grading.film_emulation`** | `Testing2_FilmEmulation_4K_Polished.mp4`: golden mids, cyan skies, Pastel print blacks, halation + grain | Nothing extra (this repo's own engine) |

Both pipelines do the following, and every step is verified on frames Resolve actually renders:
- detect the shots in your clip (reading the file only);
- put every shot on its own timeline item and grade each shot individually;
- add film texture through Fusion;
- check every shot, export in 4K and **re-check the exported file**: resolution, frame count, and *no watermark* on any shot.

## Quick start

```bash
# 1. one-time setup (Resolve, the MCP server, the bridge): see docs/SETUP.md
pip install -r requirements.txt
cp .mcp.json.example .mcp.json   # point it at your davinci-resolve MCP install

# 2. in Resolve: open/create a project and import your clip
#    (free edition: then Workspace > Scripts > resolve_bridge)

# 3a. genuine CinePrint35 look (bring your own licensed pack)
python -m grading.cineprint --cineprint-dir "path/to/CinePrint35 for Davinci Resolve" \
       --camera "Sony S-Log3" --stock 250D --gauge 35mm --export

# 3b. or the engine's Polished look (no extra assets)
python -m grading.film_emulation --preset slog3_polished --export
```

Every grade lands as a **new grade version** on each shot. Your existing grades stay one click away
(Color page > right-click clip > Local Versions). Results and a JSON report go to `work/`.

### Useful options
- `--camera`: the PowerGrade folder for your footage. The pack ships `Sony S-Log3`, `Apple Log`, `Arri Alexa LogC3`, `Blackmagic Design Film Gen5`, `Canon Log 2`, `Fuji F-Log2`, `Panasonic V-Log`, `RED IPP2`, `RED Komodo`, `Rec709` (non-log) and `Other Cameras` (CST).
- `--stock 250D | 500T | 160T`, `--gauge 35mm | 16mm`.
- `--exposure-target`, `--contrast`, `--saturation`, `--warmth`, `--grain`: the per-shot workflow knobs. The defaults reproduce the reference.
- `--studio`: for Resolve Studio. Keeps all PowerGrade nodes, including its own grain, denoise and dust.
- `--import <file>`, `--clip <name>`, `--resolution 2160|1080`, `--export-dir`.
- `film_emulation --preview-only --source clip.mp4`: builds the LUTs and preview stills without Resolve.

## Docs
- [docs/SETUP.md](docs/SETUP.md): Resolve version, MCP server, the free-edition bridge, project settings
- [docs/CINEPRINT35_WORKFLOW.md](docs/CINEPRINT35_WORKFLOW.md): what the CinePrint pipeline does and why each value is what it is
- [docs/FILM_EMULATION_ENGINE.md](docs/FILM_EMULATION_ENGINE.md): the engine, its presets and how to tune it
- [docs/LESSONS.md](docs/LESSONS.md): traps hit and fixed while building this (read before changing anything)
- `.claude/skills/davinci-film-grade/`: a Claude Code skill, so Claude follows the same workflow on any machine

## Licensing note
CinePrint35 (by Tom Bolles, sold at gfxpck.com) is a **paid product**. None of its files are in this
repo, and `.gitignore` blocks `.drx` files and the pack folders. Each user points `--cineprint-dir` at
their own purchased copy. Everything in this repo is original work.
