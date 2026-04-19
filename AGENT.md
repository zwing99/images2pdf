# AGENT.md

This repository is a small local utility, not a packaged library. Keep changes minimal, readable, and easy to run with `uv run watch_to_pdf.py`.

## Project shape

- Primary entrypoint: `watch_to_pdf.py`
- Configuration: CLI flags plus `.env` via `python-dotenv`
- State: local SQLite database `watch_to_pdf.sqlite3`
- Runtime: Python 3.14, managed with `uv`

## Working rules

- Keep the implementation in one Python file unless the user explicitly asks to split it.
- Prefer standard library behavior and simple control flow over new abstractions.
- Use `pathlib` consistently.
- Preserve Click env-var support with the `WATCHPDF_` prefix.
- Keep stdout logging straightforward and operationally useful.

## Local-state boundaries

- Do not commit `.env`, `.venv`, `uv.lock`, SQLite files, generated plist files, or `logs/`.
- Do not put user-specific machine paths, account names, or local setup details into `README.md` or tracked source files.
- If local setup requires real paths, use them in commands or generated files outside the repo, not in committed documentation.

## Launchd notes

- The script can generate a LaunchAgent plist with `--write-launchd-plist`.
- Generated plist files belong outside the repo, typically in `~/Library/LaunchAgents/`.
- Launchd stdout/stderr logs should go under the repo-local `logs/` directory, which is gitignored.

## Change discipline

- Validate Python changes with `python3 -m py_compile watch_to_pdf.py` at minimum.
- If you use `uv run` for verification, expect `.venv` and possibly `uv.lock` to appear locally; leave them untracked.
- Avoid over-editing the README. Keep it generic and reusable.
- If the user asks for a commit, stage only intentional project files and exclude local machine artifacts.
