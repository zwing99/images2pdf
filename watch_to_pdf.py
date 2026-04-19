#!/usr/bin/env python3
from __future__ import annotations

import logging
import plistlib
import re
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

DB_PATH = Path(__file__).resolve().with_name("watch_to_pdf.sqlite3")
MARKER_NAME = ".processed_to_pdf"
IMAGE_SUFFIXES = {".jpg", ".jpeg"}
SIZE_PRESETS: dict[str, tuple[int, int]] = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}


@dataclass(slots=True)
class FolderState:
    folder_path: Path
    status: str
    image_count: int
    last_change_time: float
    processed_time: float | None
    delete_after_time: float | None
    output_pdf_path: str | None
    last_error: str | None


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("watch_to_pdf")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def now_ts() -> float:
    return time.time()


def timestamp_label(ts: float | None = None) -> str:
    moment = datetime.fromtimestamp(ts if ts is not None else now_ts(), tz=timezone.utc)
    return moment.astimezone().strftime("%Y%m%d-%H%M%S")


def date_label(ts: float | None = None) -> str:
    moment = datetime.fromtimestamp(ts if ts is not None else now_ts(), tz=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d")


def natural_key(path: Path) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def is_jpeg(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES


def list_jpeg_files(folder: Path) -> list[Path]:
    return sorted((path for path in folder.iterdir() if is_jpeg(path)), key=natural_key)


def marker_path(folder: Path) -> Path:
    return folder / MARKER_NAME


def ensure_output_path(output_root: Path, folder_name: str) -> Path:
    base_name = f"{date_label()}-{folder_name}"
    candidate = output_root / f"{base_name}.pdf"
    if not candidate.exists():
        return candidate

    stamp = timestamp_label()
    suffixed = output_root / f"{base_name}-{stamp}.pdf"
    if not suffixed.exists():
        return suffixed

    counter = 2
    while True:
        numbered = output_root / f"{base_name}-{stamp}-{counter}.pdf"
        if not numbered.exists():
            return numbered
        counter += 1


def resize_for_preset(image: Image.Image, size_preset: str) -> Image.Image:
    max_width, max_height = SIZE_PRESETS[size_preset]
    width, height = image.size
    scale = min(max_width / width, max_height / height, 1.0)
    if scale >= 1.0:
        return image.copy()

    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    return image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)


def open_state_connection(dry_run: bool) -> sqlite3.Connection:
    if dry_run:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        init_db(connection)
        if DB_PATH.exists():
            source = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
            try:
                source.row_factory = sqlite3.Row
                copy_existing_state(source, connection)
            finally:
                source.close()
        return connection

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    init_db(connection)
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS folders (
            folder_path TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            image_count INTEGER NOT NULL,
            last_change_time REAL NOT NULL,
            processed_time REAL,
            delete_after_time REAL,
            output_pdf_path TEXT,
            last_error TEXT
        )
        """
    )
    connection.commit()


def copy_existing_state(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    rows = source.execute(
        """
        SELECT folder_path, status, image_count, last_change_time,
               processed_time, delete_after_time, output_pdf_path, last_error
        FROM folders
        """
    ).fetchall()
    for row in rows:
        target.execute(
            """
            INSERT INTO folders (
                folder_path, status, image_count, last_change_time,
                processed_time, delete_after_time, output_pdf_path, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["folder_path"],
                row["status"],
                row["image_count"],
                row["last_change_time"],
                row["processed_time"],
                row["delete_after_time"],
                row["output_pdf_path"],
                row["last_error"],
            ),
        )
    target.commit()


def fetch_state(connection: sqlite3.Connection, folder: Path) -> FolderState | None:
    row = connection.execute(
        """
        SELECT folder_path, status, image_count, last_change_time,
               processed_time, delete_after_time, output_pdf_path, last_error
        FROM folders
        WHERE folder_path = ?
        """,
        (str(folder),),
    ).fetchone()
    if row is None:
        return None
    return FolderState(
        folder_path=Path(row["folder_path"]),
        status=row["status"],
        image_count=row["image_count"],
        last_change_time=row["last_change_time"],
        processed_time=row["processed_time"],
        delete_after_time=row["delete_after_time"],
        output_pdf_path=row["output_pdf_path"],
        last_error=row["last_error"],
    )


def upsert_watching_state(connection: sqlite3.Connection, folder: Path, image_count: int, changed_at: float) -> None:
    connection.execute(
        """
        INSERT INTO folders (
            folder_path, status, image_count, last_change_time,
            processed_time, delete_after_time, output_pdf_path, last_error
        ) VALUES (?, 'watching', ?, ?, NULL, NULL, NULL, NULL)
        ON CONFLICT(folder_path) DO UPDATE SET
            status='watching',
            image_count=excluded.image_count,
            last_change_time=excluded.last_change_time,
            processed_time=NULL,
            delete_after_time=NULL,
            output_pdf_path=NULL,
            last_error=NULL
        """,
        (str(folder), image_count, changed_at),
    )
    connection.commit()


def mark_processing(connection: sqlite3.Connection, folder: Path) -> None:
    connection.execute(
        """
        UPDATE folders
        SET status='processing',
            last_error=NULL
        WHERE folder_path = ?
        """,
        (str(folder),),
    )
    connection.commit()


def mark_done(
    connection: sqlite3.Connection,
    folder: Path,
    image_count: int,
    processed_at: float,
    delete_after_hours: float,
    output_pdf_path: Path,
) -> None:
    connection.execute(
        """
        INSERT INTO folders (
            folder_path, status, image_count, last_change_time,
            processed_time, delete_after_time, output_pdf_path, last_error
        ) VALUES (?, 'done', ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(folder_path) DO UPDATE SET
            status='done',
            image_count=excluded.image_count,
            processed_time=excluded.processed_time,
            delete_after_time=excluded.delete_after_time,
            output_pdf_path=excluded.output_pdf_path,
            last_error=NULL
        """,
        (
            str(folder),
            image_count,
            processed_at,
            processed_at,
            processed_at + (delete_after_hours * 3600.0),
            str(output_pdf_path),
        ),
    )
    connection.commit()


def mark_error(connection: sqlite3.Connection, folder: Path, message: str) -> None:
    connection.execute(
        """
        UPDATE folders
        SET status='error',
            last_error=?
        WHERE folder_path = ?
        """,
        (message, str(folder)),
    )
    connection.commit()


def mark_deleted(connection: sqlite3.Connection, folder: Path) -> None:
    connection.execute(
        """
        UPDATE folders
        SET status='deleted'
        WHERE folder_path = ?
        """,
        (str(folder),),
    )
    connection.commit()


def process_folder_images(
    folder: Path,
    images: list[Path],
    output_path: Path,
    dry_run: bool,
    size_preset: str,
) -> None:
    if dry_run:
        return

    converted_images: list[Image.Image] = []
    try:
        for image_path in images:
            with Image.open(image_path) as image:
                converted_images.append(resize_for_preset(image.convert("RGB"), size_preset))

        first_image = converted_images[0]
        first_image.save(
            output_path,
            format="PDF",
            save_all=True,
            append_images=converted_images[1:],
        )
    finally:
        for image in converted_images:
            image.close()


def write_marker(folder: Path, output_path: Path, dry_run: bool) -> None:
    if dry_run:
        return

    marker_path(folder).write_text(
        "\n".join(
            [
                f"output_pdf={output_path}",
                f"written_at={datetime.now(timezone.utc).isoformat()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def remove_folder(folder: Path, dry_run: bool) -> None:
    if dry_run:
        return

    shutil.rmtree(folder)


def default_uv_path() -> str:
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path
    return "/opt/homebrew/bin/uv"


def build_launchd_plist(
    *,
    label: str,
    working_directory: Path,
    uv_path: str,
    input_root: Path,
    output_root: Path,
    poll_seconds: int,
    stable_seconds: int,
    delete_after_hours: float,
    size_preset: str,
    dry_run: bool,
    stdout_path: Path,
    stderr_path: Path,
) -> bytes:
    command = [
        uv_path,
        "run",
        "watch_to_pdf.py",
        "--input-root",
        str(input_root),
        "--output-root",
        str(output_root),
        "--poll-seconds",
        str(poll_seconds),
        "--stable-seconds",
        str(stable_seconds),
        "--delete-after-hours",
        str(delete_after_hours),
        "--size-preset",
        size_preset,
    ]
    command.append("--dry-run" if dry_run else "--no-dry-run")
    command.append("--loop")

    plist_data: dict[str, object] = {
        "Label": label,
        "ProgramArguments": command,
        "WorkingDirectory": str(working_directory),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
    }
    return plistlib.dumps(plist_data, fmt=plistlib.FMT_XML, sort_keys=False)


def write_launchd_plist_file(
    destination: Path,
    *,
    label: str,
    uv_path: str,
    input_root: Path,
    output_root: Path,
    poll_seconds: int,
    stable_seconds: int,
    delete_after_hours: float,
    size_preset: str,
    dry_run: bool,
    stdout_path: Path,
    stderr_path: Path,
) -> None:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    stdout_path = stdout_path.expanduser().resolve()
    stderr_path = stderr_path.expanduser().resolve()
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    plist_bytes = build_launchd_plist(
        label=label,
        working_directory=Path(__file__).resolve().parent,
        uv_path=uv_path,
        input_root=input_root,
        output_root=output_root,
        poll_seconds=poll_seconds,
        stable_seconds=stable_seconds,
        delete_after_hours=delete_after_hours,
        size_preset=size_preset,
        dry_run=dry_run,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    destination.write_bytes(plist_bytes)


def scan_folders(
    connection: sqlite3.Connection,
    input_root: Path,
    output_root: Path,
    *,
    stable_seconds: int,
    delete_after_hours: float,
    size_preset: str,
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    now = now_ts()
    seen_folders: set[Path] = set()

    folders = sorted((path for path in input_root.iterdir() if path.is_dir()), key=natural_key)
    for folder in folders:
        folder = folder.resolve()
        seen_folders.add(folder)

        images = list_jpeg_files(folder)
        image_count = len(images)
        state = fetch_state(connection, folder)

        if image_count == 0:
            if state is None:
                logger.info("Ignoring empty folder: %s", folder)
            continue

        if state is None:
            logger.info("Detected folder: %s (%d image(s))", folder, image_count)
            upsert_watching_state(connection, folder, image_count, now)
            continue

        if state.status == "deleted":
            logger.info("Folder reappeared: %s (%d image(s))", folder, image_count)
            upsert_watching_state(connection, folder, image_count, now)
            continue

        if image_count != state.image_count:
            logger.info(
                "Image count changed for %s: %d -> %d",
                folder,
                state.image_count,
                image_count,
            )
            upsert_watching_state(connection, folder, image_count, now)
            continue

        marker = marker_path(folder)
        if state.status == "done" and marker.exists():
            continue

        stable_for = now - state.last_change_time
        if state.status in {"watching", "error", "processing"} and stable_for >= stable_seconds:
            logger.info("Stable for %.0f seconds, processing: %s", stable_for, folder)
            try:
                mark_processing(connection, folder)
                output_path = ensure_output_path(output_root, folder.name)
                process_folder_images(folder, images, output_path, dry_run, size_preset)
                write_marker(folder, output_path, dry_run)
                mark_done(connection, folder, image_count, now_ts(), delete_after_hours, output_path)
                logger.info("Finished %s -> %s", folder, output_path)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to process %s", folder)
                mark_error(connection, folder, str(exc))

    cleanup_folders(connection, seen_folders, dry_run=dry_run, logger=logger)


def cleanup_folders(
    connection: sqlite3.Connection,
    seen_folders: set[Path],
    *,
    dry_run: bool,
    logger: logging.Logger,
) -> None:
    now = now_ts()
    rows = connection.execute(
        """
        SELECT folder_path, status, delete_after_time
        FROM folders
        WHERE status != 'deleted'
        """
    ).fetchall()

    for row in rows:
        folder = Path(row["folder_path"])
        status = row["status"]
        delete_after_time = row["delete_after_time"]
        exists = folder.exists()

        if not exists:
            if status != "deleted":
                logger.info("Folder missing, marking deleted: %s", folder)
                mark_deleted(connection, folder)
            continue

        if status == "done" and delete_after_time is not None and now >= delete_after_time:
            logger.info("Deleting processed folder: %s", folder)
            remove_folder(folder, dry_run)
            mark_deleted(connection, folder)
        elif folder not in seen_folders and status == "done" and delete_after_time is None:
            logger.info("Processed folder has no delete timer, leaving in place: %s", folder)


@click.command()
@click.option(
    "--input-root",
    type=click.Path(path_type=Path, exists=True, file_okay=False, dir_okay=True, readable=True),
    envvar="WATCHPDF_INPUT_ROOT",
    show_envvar=True,
    help="Directory whose immediate subfolders are watched for JPEGs.",
)
@click.option(
    "--output-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    envvar="WATCHPDF_OUTPUT_ROOT",
    show_envvar=True,
    help="Directory where generated PDFs are written.",
)
@click.option(
    "--poll-seconds",
    type=click.IntRange(min=1),
    default=10,
    show_default=True,
    envvar="WATCHPDF_POLL_SECONDS",
    show_envvar=True,
    help="How long to sleep between scans.",
)
@click.option(
    "--stable-seconds",
    type=click.IntRange(min=1),
    default=60,
    show_default=True,
    envvar="WATCHPDF_STABLE_SECONDS",
    show_envvar=True,
    help="How long the JPEG count must stay unchanged before processing.",
)
@click.option(
    "--delete-after-hours",
    type=click.FloatRange(min=0.0),
    default=24.0,
    show_default=True,
    envvar="WATCHPDF_DELETE_AFTER_HOURS",
    show_envvar=True,
    help="How long to keep successfully processed folders before deleting them.",
)
@click.option(
    "--size-preset",
    type=click.Choice(sorted(SIZE_PRESETS), case_sensitive=False),
    default="720p",
    show_default=True,
    envvar="WATCHPDF_SIZE_PRESET",
    show_envvar=True,
    help="Resize images before PDF creation using a standard target resolution.",
)
@click.option(
    "--dry-run/--no-dry-run",
    default=False,
    envvar="WATCHPDF_DRY_RUN",
    show_envvar=True,
    help="Log actions without writing PDFs, markers, or folder deletions.",
)
@click.option(
    "--once/--loop",
    default=False,
    help="Run one scan pass and exit instead of looping forever.",
)
@click.option(
    "--write-launchd-plist",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Write a launchd plist for this watcher and exit.",
)
@click.option(
    "--launchd-label",
    default="com.example.watch-to-pdf",
    show_default=True,
    help="launchd label to embed in the generated plist.",
)
@click.option(
    "--launchd-uv-path",
    default=default_uv_path,
    show_default="auto-detect or /opt/homebrew/bin/uv",
    help="Absolute path to the uv executable used by launchd.",
)
@click.option(
    "--launchd-stdout",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("/tmp/watch-to-pdf.out.log"),
    show_default=True,
    help="launchd stdout log path for the generated plist.",
)
@click.option(
    "--launchd-stderr",
    type=click.Path(path_type=Path, dir_okay=False),
    default=Path("/tmp/watch-to-pdf.err.log"),
    show_default=True,
    help="launchd stderr log path for the generated plist.",
)
def main(
    input_root: Path | None,
    output_root: Path | None,
    poll_seconds: int,
    stable_seconds: int,
    delete_after_hours: float,
    size_preset: str,
    dry_run: bool,
    once: bool,
    write_launchd_plist: Path | None,
    launchd_label: str,
    launchd_uv_path: str,
    launchd_stdout: Path,
    launchd_stderr: Path,
) -> None:
    logger = configure_logging()
    size_preset = size_preset.lower()
    if input_root is None:
        raise click.ClickException("--input-root or WATCHPDF_INPUT_ROOT is required")
    if output_root is None:
        raise click.ClickException("--output-root or WATCHPDF_OUTPUT_ROOT is required")

    input_root = input_root.expanduser().resolve()
    output_root = output_root.expanduser().resolve()

    if write_launchd_plist is not None:
        if not input_root.is_dir():
            raise click.ClickException(f"Input root does not exist or is not a directory: {input_root}")
        write_launchd_plist_file(
            write_launchd_plist,
            label=launchd_label,
            uv_path=launchd_uv_path,
            input_root=input_root,
            output_root=output_root,
            poll_seconds=poll_seconds,
            stable_seconds=stable_seconds,
            delete_after_hours=delete_after_hours,
            size_preset=size_preset,
            dry_run=dry_run,
            stdout_path=launchd_stdout.expanduser(),
            stderr_path=launchd_stderr.expanduser(),
        )
        click.echo(f"Wrote launchd plist to {write_launchd_plist.expanduser().resolve()}")
        return

    if not input_root.is_dir():
        raise click.ClickException(f"Input root does not exist or is not a directory: {input_root}")

    if dry_run:
        logger.info("Dry-run mode enabled")
        connection = open_state_connection(True)
    else:
        output_root.mkdir(parents=True, exist_ok=True)
        connection = open_state_connection(False)

    logger.info("Watching %s", input_root)
    logger.info("Writing PDFs to %s", output_root)
    logger.info("Database: %s", DB_PATH)
    logger.info("Size preset: %s (%sx%s)", size_preset, *SIZE_PRESETS[size_preset])

    try:
        while True:
            scan_folders(
                connection,
                input_root,
                output_root,
                stable_seconds=stable_seconds,
                delete_after_hours=delete_after_hours,
                size_preset=size_preset,
                dry_run=dry_run,
                logger=logger,
            )
            if once:
                break
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        logger.info("Stopped")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
