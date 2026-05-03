# AGENT.md

This repository is a small local utility, not a packaged library. Keep changes minimal, readable, and easy to run with `uv run watch_to_pdf.py start-watch`.

## Project shape

- Primary entrypoint: `watch_to_pdf.py`
- Configuration: CLI flags plus `.env` via `python-dotenv`
- State: local SQLite database, defaulting to `watch_to_pdf.sqlite3` next to the script unless `--db-path` is set
- Runtime: Python 3.14, managed with `uv`
- Output naming: `YYYY-MM-DD-folder-name.pdf`
- Default output sizing: `--size-preset 720p`

## Working rules

- Keep the implementation in one Python file unless the user explicitly asks to split it.
- Prefer standard library behavior and simple control flow over new abstractions.
- Use `pathlib` consistently.
- Preserve Click env-var support with the `WATCHPDF_` prefix.
- Use `uv run` for project Python commands instead of calling the system Python directly.
- Keep stdout logging straightforward and operationally useful.
- Preserve the current output behavior unless asked otherwise:
  - reruns overwrite the same dated PDF filename
  - image resizing uses standard presets `480p`, `720p`, `1080p`

## Local-state boundaries

- Do not commit `.env`, `.venv`, `uv.lock`, SQLite files, generated plist files, or `logs/`.
- Do not put user-specific machine paths, account names, or local setup details into `README.md` or tracked source files.
- If local setup requires real paths, use them in commands or generated files outside the repo, not in committed documentation.

## Launchd notes

- The script has explicit Click subcommands: `start-watch` and `build-plist`.
- Generated plist files belong outside the repo, typically in `~/Library/LaunchAgents/`.
- Launchd stdout/stderr logs should go under the repo-local `logs/` directory, which is gitignored.
- If watcher arguments change, regenerate the plist and reload the LaunchAgent.
- Logging should continue to write to stdout/stderr; `launchd` handles redirection to files.
- Future TODO: consider log rotation if the repo-local log files grow too large.

## Change discipline

- Validate Python changes with `uv run python -m py_compile watch_to_pdf.py` at minimum.
- Prefer `uv run` for runtime checks and script execution so the managed project interpreter is used.
- If you use `uv run` for verification, expect `.venv` and possibly `uv.lock` to appear locally; leave them untracked.
- Avoid over-editing the README. Keep it generic and reusable.
- If the user asks for a commit, stage only intentional project files and exclude local machine artifacts.
