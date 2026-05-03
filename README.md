# watch_to_pdf

`watch_to_pdf.py` watches an input directory for new subfolders of JPEG images, waits until the file count stays stable, converts each folder into a single PDF, and deletes processed folders after a delay.

## What it does

- Watches immediate subfolders of an input root
- Counts `.jpg` and `.jpeg` files
- Waits for the count to stay unchanged for the configured stability window
- Converts the folder into one PDF
- Resizes images to a configurable preset before PDF creation
- Names PDFs like `YYYY-MM-DD-folder-name.pdf`
- Reuses the same dated filename on reruns instead of creating timestamp-suffixed copies
- Writes a `.processed_to_pdf` marker file in the source folder
- Deletes processed folders after the configured retention window
- Keeps state in SQLite so it can resume after restart

## Requirements

- Python 3.14
- `uv`
- Dependencies:
  - `click`
  - `pillow`
  - `python-dotenv`

## Install `uv`

If you do not already have `uv`, install it first:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your shell if needed so `uv` is on `PATH`.

## Python with `uv`

This project targets Python `3.14.x`.

Recommended setup:

```bash
uv python install 3.14
```

Then run the script with a uv-managed interpreter:

```bash
uv run --managed-python watch_to_pdf.py start-watch
```

By default, `uv` can automatically download a missing Python version when needed. In practice, if the project requires Python `3.14` and you do not already have a suitable interpreter, `uv` will usually fetch it for you and continue.

If you want to force `uv` to use only uv-managed Python installations and never fall back to a system Python, use `--managed-python`.

## Run

```bash
uv run watch_to_pdf.py start-watch
```

The script reads configuration from CLI flags and from `.env`.

## Configure with `.env`

Copy `.env.example` to `.env` and fill in the required paths:

```bash
cp .env.example .env
```

Required values:

- `WATCHPDF_INPUT_ROOT`
- `WATCHPDF_OUTPUT_ROOT`

Optional values:

- `WATCHPDF_POLL_SECONDS`
- `WATCHPDF_STABLE_SECONDS`
- `WATCHPDF_DELETE_AFTER_HOURS`
- `WATCHPDF_DB_PATH`
- `WATCHPDF_SIZE_PRESET`
- `WATCHPDF_DRY_RUN`

Example:

```env
WATCHPDF_INPUT_ROOT=/Users/you/Pictures/incoming
WATCHPDF_OUTPUT_ROOT=/Users/you/Pictures/pdfs
WATCHPDF_DB_PATH=
WATCHPDF_POLL_SECONDS=10
WATCHPDF_STABLE_SECONDS=60
WATCHPDF_DELETE_AFTER_HOURS=24
WATCHPDF_SIZE_PRESET=720p
WATCHPDF_DRY_RUN=false
```

## CLI examples

Run once and exit:

```bash
uv run --managed-python watch_to_pdf.py start-watch --once
```

Override paths on the command line:

```bash
uv run --managed-python watch_to_pdf.py start-watch \
  --input-root /path/to/incoming \
  --db-path /path/to/watch_to_pdf.sqlite3 \
  --output-root /path/to/output
```

Dry run:

```bash
uv run --managed-python watch_to_pdf.py start-watch --dry-run --once
```

Keep looping with a different poll interval:

```bash
uv run --managed-python watch_to_pdf.py start-watch --poll-seconds 5 --stable-seconds 90
```

Use a different PDF size preset:

```bash
uv run --managed-python watch_to_pdf.py start-watch --size-preset 1080p
```

Available presets:

- `480p`
- `720p` (default)
- `1080p`

## Stability timing

The script only looks at the number of JPEG files in each folder.

- If the count changes, the folder is treated as unstable and the timer resets.
- If the count stays the same for `WATCHPDF_STABLE_SECONDS`, the folder is processed.
- Empty folders are ignored.

This means the script is designed for folders that are still being filled or copied into place.

## PDF size preset

Before building the PDF, each image is downscaled to fit inside the selected preset while preserving aspect ratio.

- `480p` fits within `854x480`
- `720p` fits within `1280x720`
- `1080p` fits within `1920x1080`

The default is `720p`, which is a reasonable tradeoff between slide readability and file size. Use `1080p` if you want larger output files with higher detail.

## SQLite database path

By default, the watcher stores state in:

```text
watch_to_pdf.sqlite3
```

next to `watch_to_pdf.py`.

You can override that with `--db-path` or `WATCHPDF_DB_PATH` if you want the state file somewhere else.

## Cleanup

After a folder is successfully converted:

- a `.processed_to_pdf` marker file is written into the source folder
- the database records when the folder should be deleted
- once `WATCHPDF_DELETE_AFTER_HOURS` has elapsed, the whole folder is removed

The default retention is 24 hours.

## SQLite database

The SQLite database is ignored by git and survives restarts so the watcher can continue from previous state.

## Debug logs

The script logs to stdout with timestamps. You will see:

- folder detection
- image count changes
- processing start and end
- cleanup activity
- errors

If you run it under launchd or another supervisor, capture stdout and stderr so you can inspect failures.

## Make it executable

```bash
chmod +x watch_to_pdf.py
```

After that you can still run it with:

```bash
uv run watch_to_pdf.py start-watch
```

## macOS launchd

`launchd` is the right way to keep this watcher running across logins and reboots on macOS. Use a per-user `LaunchAgent` unless you specifically need a system-wide daemon.

### Recommended setup

This is the setup pattern used for this project:

- Keep the generated plist outside the repo in `~/Library/LaunchAgents/`
- Keep `launchd` logs inside the repo in `logs/`
- Let the script generate the plist so the command arguments stay correct

Create the repo-local log directory first:

```bash
cd "$HOME/src/images2pdf"
mkdir -p logs
```

Generate the LaunchAgent plist:

```bash
uv run --managed-python watch_to_pdf.py build-plist \
  --input-root "$HOME/Pictures/incoming" \
  --output-root "$HOME/Pictures/pdfs" \
  --size-preset 720p \
  --plist-path "$HOME/Library/LaunchAgents/com.zwing99.watch-to-pdf.plist" \
  --launchd-label com.zwing99.watch-to-pdf \
  --launchd-uv-path "$(which uv)" \
  --launchd-stdout "$(pwd)/logs/watch-to-pdf.out.log" \
  --launchd-stderr "$(pwd)/logs/watch-to-pdf.err.log"
```

Run that command from the project directory so `$(pwd)` points at the repo you want to manage.

### Load or reload it

Use `bootout` and `bootstrap` so updates to the plist are picked up cleanly:

```bash
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.zwing99.watch-to-pdf.plist" 2>/dev/null
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.zwing99.watch-to-pdf.plist"
```

### Restart after `git pull`

If you update the code with `git pull`, restart the LaunchAgent so the running process picks up the new script version:

```bash
cd "$HOME/src/images2pdf"
git pull
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.zwing99.watch-to-pdf.plist" 2>/dev/null
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.zwing99.watch-to-pdf.plist"
```

If you changed any watcher arguments or log paths, regenerate the plist before the restart:

```bash
uv run --managed-python watch_to_pdf.py build-plist \
  --input-root "$HOME/Pictures/incoming" \
  --output-root "$HOME/Pictures/pdfs" \
  --size-preset 720p \
  --plist-path "$HOME/Library/LaunchAgents/com.zwing99.watch-to-pdf.plist" \
  --launchd-label com.zwing99.watch-to-pdf \
  --launchd-uv-path "$(which uv)" \
  --launchd-stdout "$(pwd)/logs/watch-to-pdf.out.log" \
  --launchd-stderr "$(pwd)/logs/watch-to-pdf.err.log"
```

### Check status

```bash
launchctl list | grep com.zwing99.watch-to-pdf
tail -f "$(pwd)/logs/watch-to-pdf.out.log"
tail -f "$(pwd)/logs/watch-to-pdf.err.log"
```

### Notes

- The generated plist uses `KeepAlive` and `RunAtLoad`
- The plist sets `WorkingDirectory` to the project directory so `uv run watch_to_pdf.py` resolves correctly
- The generated plist runs `watch_to_pdf.py start-watch`
- The plist embeds the watcher arguments directly, so it does not need `.env`
- The generated plist also captures the selected `--size-preset`
- Logging stays on standard output and standard error; `launchd` redirects those streams to the configured log files
- Future improvement: switch the log files to a rotated logging strategy if they grow too large over time
- `logs/` and generated `*.plist` files are gitignored in this repo
