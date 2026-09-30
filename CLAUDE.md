# Project Rules

## Project

Civil 3D automation for нагорные канавы (НК-*) / corridor / gabion modeling. See
[docs/context.md](docs/context.md). Водопропуски (В-*, culverts) are a separate
project-agnostic repo, `tube_toolkit` — not here.

## Hard rules

- New script or significant change → run `/feature-prompt` before writing any code
- No "done when" criteria defined → don't start the feature
- Acceptance on one canal does not count — test on at least two
- Algorithm or input format changed → update the relevant MD in the same commit
- Bug found on a new canal → add it to `docs/process/03_testing.md` before fixing
- Unfinished function → mark `# TODO: frozen — <reason>`
- New Civil 3D API method needed → check `common/docs/platform/api_dump/` first
- Drawing script (draws layers/entities) → layers defined in `layers.json` in the script folder, grouped under a filter → [common/docs/process/07_drawing_scripts.md](common/docs/process/07_drawing_scripts.md)
- New script → `README.md` in its folder (Russian); input/output changed later → update it in the same commit → [common/docs/process/02_development.md](common/docs/process/02_development.md#script-readme)
- Commit each adequately-scoped change as it's finished (don't let unrelated work pile up into one giant commit) → [common/docs/process/02_development.md](common/docs/process/02_development.md#commit-each-adequately-scoped-change)

## Script naming

`build_` / `report_` / `help_` — verb before noun. Details → [common/docs/process/02_development.md](common/docs/process/02_development.md)

## Process

1. API exploration → [common/docs/process/01_api_exploration.md](common/docs/process/01_api_exploration.md)
2. Development → [common/docs/process/02_development.md](common/docs/process/02_development.md)
3. Testing → [docs/process/03_testing.md](docs/process/03_testing.md)
4. Acceptance → [docs/process/04_acceptance.md](docs/process/04_acceptance.md)
5. Doc maintenance → [docs/process/05_maintenance.md](docs/process/05_maintenance.md)

Generic dev workflow (01/02/07) lives in the `civil3d_common` submodule (shared with
`tube_toolkit`); project-specific process (03/04/05/06/08) stays in this repo.

---

## Conversation language
- Chat / terminal responses: **Russian**
- `README.md` files (per-script, per-repo): **Russian** — user-facing overview
- Everything else that's really your own working notes (docstrings, comments, log
  messages, code, `common/docs/platform/*.md` bug log, `.agents/prompts/*.md`): **English**
  — write these however is fastest for you to read back later (XML tags, terse
  fragments, whatever), they're not primarily for the user

## Language in code
Write all content inside scripts in **English**: log messages, comments, f-strings, error messages, variable names.
Cyrillic inside `.dyn` (JSON) files gets corrupted when edited via PowerShell 5.1.

## PowerShell file encoding
Never use `Set-Content` / `Out-File` / `Add-Content` for non-ASCII. Always use .NET directly:
```powershell
[System.IO.File]::WriteAllText($path, $content, [System.Text.Encoding]::UTF8)
[System.IO.File]::AppendAllText($path, $content, [System.Text.Encoding]::UTF8)
```
Repair snippet for already-corrupted files → [common/docs/process/02_development.md](common/docs/process/02_development.md)

## Debug scripts
Each debug script in its own subfolder: `debug/<name>/` with `logs/` inside.
Always write output to a log file, never only to `OUT`.
Structure and log pattern → [common/docs/process/01_api_exploration.md](common/docs/process/01_api_exploration.md)

## Clarify before implementing
Ambiguous requirement → ask, don't scan. Do not read files or open pictures as a substitute for asking.

## Launcher inject workflow
Never edit `.dyn` directly. Edit `launcher.py` → run `inject.ps1` immediately.
```powershell
.\common\helpers\inject.ps1 <name>\launcher.py <name>\<name>.dyn
```
Full workflow and launcher pattern → [common/docs/process/02_development.md](common/docs/process/02_development.md)

## Document errors and solutions
Non-obvious bug fixed → add to `common/docs/platform/01_civil3d_errors.md` with error message, root cause, and fix.
What goes where → [docs/process/05_maintenance.md](docs/process/05_maintenance.md)

## Type annotations
- `from __future__ import annotations` on every module
- Annotate all function signatures; Civil 3D / AutoCAD objects typed as `Any`
- Full rules and example → [common/docs/process/02_development.md](common/docs/process/02_development.md)

## Code organisation
Logic in a Python package at this repo's own root (`build_canal_model/`, `ditch/`,
`anchor/`, etc.), not in the `.dyn` node. Launcher is a thin entry point.
Package structure, hot-reload pattern → [common/docs/process/02_development.md](common/docs/process/02_development.md)

## Reference documents
All reference files indexed in [docs/context.md](docs/context.md).
