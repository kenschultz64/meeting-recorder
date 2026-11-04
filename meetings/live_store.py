"""Persist the 10-second chunks a live browser recording sends for preview.

The main recorder keeps its audio in the tab's memory, so a refresh or a
closed tab used to destroy the recording. Each preview chunk is already a
complete container uploaded for ASR; keeping a copy means an interrupted
recording can be rebuilt up to the last completed chunk.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from django.conf import settings

ACTIVE_WINDOW_SEC = 45  # last chunk newer than this => recorder probably still running
MIN_BYTES = 2048        # header-only stubs decode to nothing; ignore them


def chunk_dir(pk: int) -> Path:
    return Path(settings.MEDIA_ROOT) / "live_chunks" / str(int(pk))


def _meta_path(pk: int) -> Path:
    return chunk_dir(pk) / "meta.json"


def _read_meta(pk: int) -> dict:
    try:
        return json.loads(_meta_path(pk).read_text())
    except Exception:
        return {}


def save_chunk(pk: int, seq: int, data: bytes, start: float | None = None) -> bool:
    """Store one chunk. Never raises: a disk problem must not break the preview."""
    try:
        d = chunk_dir(pk)
        d.mkdir(parents=True, exist_ok=True)
        seq = int(seq)
        (d / f"{seq:05d}.webm").write_bytes(data)
        meta = _read_meta(pk)
        meta[str(seq)] = {"start": float(start or 0), "bytes": len(data), "at": time.time()}
        tmp = _meta_path(pk).with_suffix(".tmp")
        tmp.write_text(json.dumps(meta))
        tmp.replace(_meta_path(pk))
        return True
    except Exception:
        return False


def chunk_files(pk: int) -> list[Path]:
    d = chunk_dir(pk)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.webm") if p.stat().st_size >= MIN_BYTES)


def clear(pk: int) -> None:
    shutil.rmtree(chunk_dir(pk), ignore_errors=True)


def state(pk: int) -> dict | None:
    """Describe what is recoverable for this meeting, or None if nothing is."""
    files = chunk_files(pk)
    if not files:
        return None
    meta = _read_meta(pk)
    last = max(p.stat().st_mtime for p in files)
    starts = [float(v.get("start", 0)) for v in meta.values() if isinstance(v, dict)]
    seconds = int(max(starts) + 10) if starts else len(files) * 10
    return {
        "count": len(files),
        "seconds": seconds,
        "last_age": int(max(0, time.time() - last)),
        "active": (time.time() - last) < ACTIVE_WINDOW_SEC,
    }


def assemble(pk: int, dest: Path) -> Path:
    """Concatenate the stored chunks into one webm (same params => stream copy)."""
    files = chunk_files(pk)
    if not files:
        raise FileNotFoundError("no chunks to assemble")
    listing = chunk_dir(pk) / "concat.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in files))
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", str(dest)],
        capture_output=True,
    )
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < MIN_BYTES:
        raise RuntimeError("ffmpeg concat failed: " + proc.stderr.decode()[-400:])
    return dest
