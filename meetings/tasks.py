import os
import subprocess
import tempfile
from pathlib import Path

import logging
import requests
from celery import Celery

logger = logging.getLogger(__name__)
from django.conf import settings

app = Celery("meeting_recorder")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["meetings"])


@app.task(bind=True)
def transcribe_meeting(self, meeting_id: int):
    from .models import Meeting
    from .pipeline import transcribe_audio_file

    meeting = Meeting.objects.get(pk=meeting_id)
    meeting.status = Meeting.Status.PROCESSING
    meeting.error = ""
    meeting.save(update_fields=["status", "error"])
    try:
        result = transcribe_audio_file(Path(meeting.audio.path))
        meeting.transcript_json = result
        meeting.duration_sec = result.get("duration_sec")
        meeting.status = Meeting.Status.TRANSCRIBED
        meeting.save(update_fields=["transcript_json", "duration_sec", "status"])
    except Exception as exc:
        meeting.status = Meeting.Status.FAILED
        meeting.error = f"{type(exc).__name__}: {exc}"
        meeting.save(update_fields=["status", "error"])
        raise


@app.task(bind=True)
def summarize_meeting(self, meeting_id: int):
    from .models import Meeting
    from .llm import summarize_transcript

    meeting = Meeting.objects.get(pk=meeting_id)
    if not meeting.transcript_json:
        return
    meeting.summary = summarize_transcript(meeting.title, meeting.transcript_json)
    meeting.save(update_fields=["summary"])


def gog(*args: str) -> str:
    """Run the gog CLI, return stdout; raise on failure."""
    r = subprocess.run([settings.GOG_BIN, *args, "--no-input"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"gog failed: {r.stderr.strip()[:500]}")
    return r.stdout


def export_to_gdrive(meeting, content: str, filename: str, folder_name: str = "Meeting Transcripts") -> dict:
    """Upload text content to Google Drive under a named folder. Returns {id, link}."""
    # find or create the folder
    out = gog("drive", "search", f"name = '{folder_name}' AND mimeType = 'application/vnd.google-apps.folder'",
              "--json", "--max", "5")
    import json
    folders = json.loads(out).get("files", [])
    if folders:
        folder_id = folders[0]["id"]
    else:
        out = gog("drive", "mkdir", folder_name, "--json")
        folder_id = json.loads(out)["folder"]["id"]

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(content)
        tmp = f.name
    try:
        out = gog("drive", "upload", tmp, "--name", filename,
                  "--parent", folder_id, "--json")
        file = json.loads(out)["file"]
        # verify readback
        check = json.loads(gog("drive", "get", file["id"], "--json"))["file"]
        if str(check.get("size")) != str(os.path.getsize(tmp)):
            raise RuntimeError("Drive upload size mismatch after readback")
        return {"id": file["id"], "link": file.get("webViewLink") or file.get("webContentLink", "")}
    finally:
        os.unlink(tmp)


@app.task(bind=True)
def transcribe_chunk(self, meeting_id: int, seq: int, audio_bytes: bytes,
                     start_offset: float, end_offset: float):
    """Live-preview chunk: ASR only (no diarization), appended as a LiveSegment."""
    from .models import LiveSegment, Meeting
    from .pipeline import transcribe_chunk_bytes
    meeting = Meeting.objects.get(pk=meeting_id)
    try:
        text = transcribe_chunk_bytes(audio_bytes)
    except Exception as exc:
        # transient chunk failures are skipped silently; the full transcription
        # after recording covers everything. Log for diagnosis.
        logger.warning("live chunk %s for meeting %s failed: %s: %s",
                       seq, meeting_id, type(exc).__name__, exc)
        return
    if text.strip():
        LiveSegment.objects.get_or_create(
            meeting=meeting, seq=seq,
            defaults={"start": start_offset, "end": end_offset, "text": text})
