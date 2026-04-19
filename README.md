# watch_to_pdf

`watch_to_pdf.py` watches an input directory for new subfolders of JPEG images, waits until the file count stays stable, converts each folder into a single PDF, and deletes processed folders after a delay.

## What it does

- Watches immediate subfolders of an input root
- Counts `.jpg` and `.jpeg` files
- Waits for the count to stay unchanged for the configured stability window
- Converts the folder into one PDF
- Resizes images to a configurable preset before PDF creation
- Names PDFs like `YYYY-MM-DD-folder-name.pdf`
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

## Run

```bash
uv run watch_to_pdf.py
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
- `WATCHPDF_SIZE_PRESET`
- `WATCHPDF_DRY_RUN`

Example:

```env
WATCHPDF_INPUT_ROOT=/Users/you/Pictures/incoming
WATCHPDF_OUTPUT_ROOT=/Users/you/Pictures/pdfs
WATCHPDF_POLL_SECONDS=10
WATCHPDF_STABLE_SECONDS=60
WATCHPDF_DELETE_AFTER_HOURS=24
WATCHPDF_SIZE_PRESET=720p
WATCHPDF_DRY_RUN=false
```

## CLI examples

Run once and exit:

```bash
uv run watch_to_pdf.py --once
```

Override paths on the command line:

```bash
uv run watch_to_pdf.py \
  --input-root /path/to/incoming \
  --output-root /path/to/output
```

Dry run:

```bash
uv run watch_to_pdf.py --dry-run --once
```

Keep looping with a different poll interval:

```bash
uv run watch_to_pdf.py --poll-seconds 5 --stable-seconds 90
```

Use a different PDF size preset:

```bash
uv run watch_to_pdf.py --size-preset 1080p
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

## Cleanup

After a folder is successfully converted:

- a `.processed_to_pdf` marker file is written into the source folder
- the database records when the folder should be deleted
- once `WATCHPDF_DELETE_AFTER_HOURS` has elapsed, the whole folder is removed

The default retention is 24 hours.

## SQLite database

The database lives next to the script:

```text
watch_to_pdf.sqlite3
```

It is ignored by git and survives restarts so the watcher can continue from previous state.

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
uv run watch_to_pdf.py
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
uv run watch_to_pdf.py \
  --input-root "$HOME/Pictures/incoming" \
  --output-root "$HOME/Pictures/pdfs" \
  --size-preset 720p \
  --write-launchd-plist "$HOME/Library/LaunchAgents/com.example.watch-to-pdf.plist" \
  --launchd-label com.example.watch-to-pdf \
  --launchd-uv-path "$(which uv)" \
  --launchd-stdout "$(pwd)/logs/watch-to-pdf.out.log" \
  --launchd-stderr "$(pwd)/logs/watch-to-pdf.err.log"
```

Run that command from the project directory so `$(pwd)` points at the repo you want to manage.

### Load or reload it

Use `bootout` and `bootstrap` so updates to the plist are picked up cleanly:

```bash
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.example.watch-to-pdf.plist" 2>/dev/null
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.example.watch-to-pdf.plist"
```

### Restart after `git pull`

If you update the code with `git pull`, restart the LaunchAgent so the running process picks up the new script version:

```bash
cd "$HOME/src/images2pdf"
git pull
launchctl bootout gui/$(id -u) "$HOME/Library/LaunchAgents/com.example.watch-to-pdf.plist" 2>/dev/null
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/com.example.watch-to-pdf.plist"
```

If you changed any watcher arguments or log paths, regenerate the plist before the restart:

```bash
uv run watch_to_pdf.py \
  --input-root "$HOME/Pictures/incoming" \
  --output-root "$HOME/Pictures/pdfs" \
  --size-preset 720p \
  --write-launchd-plist "$HOME/Library/LaunchAgents/com.example.watch-to-pdf.plist" \
  --launchd-label com.example.watch-to-pdf \
  --launchd-uv-path "$(which uv)" \
  --launchd-stdout "$(pwd)/logs/watch-to-pdf.out.log" \
  --launchd-stderr "$(pwd)/logs/watch-to-pdf.err.log"
```

### Check status

```bash
launchctl list | grep com.example.watch-to-pdf
tail -f "$(pwd)/logs/watch-to-pdf.out.log"
tail -f "$(pwd)/logs/watch-to-pdf.err.log"
```

### Notes

- The generated plist uses `KeepAlive` and `RunAtLoad`
- The plist sets `WorkingDirectory` to the project directory so `uv run watch_to_pdf.py` resolves correctly
- The plist embeds the watcher arguments directly, so it does not need `.env`
- The generated plist also captures the selected `--size-preset`
- `logs/` and generated `*.plist` files are gitignored in this repo
