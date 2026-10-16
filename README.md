# GoGospelNow.com Meeting Recorder

A self-hosted meeting recorder: upload a recording or record live in the browser, and get a
speaker-separated transcript, an AI summary with action items, personal notes, and one-click exports —
all running on your own hardware. No audio leaves the machine.

Deployed for Crosswinds Church at **https://meeting.acts19.us** (behind a Cloudflare tunnel).

## Features

- **Upload or record** — MP3, M4A, WAV, OGG, WebM and video files, or record straight from the browser
  (phone or desktop; needs HTTPS for microphone access).
- **Live transcript preview** — text appears roughly every 10 seconds *while* you are still recording,
  from short preview clips sent in parallel with the uninterrupted full recording.
- **Speaker separation** — up to 8 speakers per recording; the meeting page warns when that ceiling is
  reached because extra voices get folded into existing labels.
- **Speaker naming** — give each voice a real name after the fact (sample playback included); names flow
  into the transcript, downloads, and summaries.
- **AI summary** — Key Points, Decisions Made, Action Items (who / what / when), Open Questions.
- **Notes**, **copy**, **download .txt / .md**, **save to Google Drive**, click-to-seek timestamps.
- **Per-user accounts** — admin-created, no self sign-up; each user only ever sees their own meetings.
- **Built-in user guide** — the `Docs` button downloads the illustrated PDF in `docs/`.

## Architecture

```
browser ──HTTPS──> reverse proxy / tunnel ──> Django (runserver|gunicorn) :18780
                                                   │
                          Redis :6390  ── Celery worker ──> Parakeet ASR (HTTP, CPU)
                                                   │          └─> Nemotron-3 diarization (in-process, CPU)
                                                   └─> OpenAI-compatible LLM (summaries)
```

- SQLite by default; PostgreSQL if `DATABASE_URL` is set.
- ASR is a plain HTTP call (`PARAKEET_URL`) to a Parakeet service — see `meetings/pipeline.py`.
- Diarization runs inside the worker process with NVIDIA **Nemotron-3-Diarization** (Sortformer,
  8 output channels, CPU) — see `meetings/pipeline.py::diarize`.
- Summaries go to any OpenAI-compatible endpoint (`LLM_URL`, optional `LLM_FALLBACK_URL`).
- Audio is served through an owner-only view (`private_audio`), never straight from `MEDIA_ROOT`.

## Quick start (development)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-diarization.txt      # heavy: NeMo + CPU torch, only needed for diarization
export SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as g;print(g())")
python manage.py migrate
python manage.py createsuperuser                 # then create other users on the Users page
python manage.py runserver 0.0.0.0:18780
```

You also need:

- **Redis** for the Celery queue (`docker compose -f deploy/redis.compose.yaml up -d`), and
  `celery -A config worker -l info --concurrency 1` running alongside the web process.
- **ffmpeg / ffprobe** on PATH (audio normalization and duration probing).
- **A Parakeet ASR HTTP service** answering `POST /api/transcribe` with a multipart `file` field and
  returning `{"segments": [{"start","end","text","words"}], ...}`. Point `PARAKEET_URL` at it.
- **An OpenAI-compatible LLM** for summaries (`LLM_URL`, `LLM_MODEL`). Summaries are optional; the rest
  of the app works without it. `LLM_FALLBACK_URL` is tried if the primary fails.
- **Optional:** the `gog` CLI (`GOG_BIN`) with a Google Workspace account for the "Save to Google Drive"
  button. Without it, that one button errors and everything else works.

Configuration is environment-driven — see `.env.example`. Production deployment (systemd units,
secrets, HTTPS, backups) is documented in [DEPLOY.md](DEPLOY.md).

## Tests

```bash
python manage.py test meetings      # 26 tests: ownership, deletion, live chunking, exports, docs, speaker ceiling
```

## Documentation

- `docs/meeting-recorder-guide.pdf` — the illustrated user guide handed out by the in-app **Docs** button.
- `docs/meeting-recorder-guide.html` — the source of that PDF (styled HTML, screenshots embedded).
- `DEPLOY.md` — production install, hardening invariants, operational checks.

## Notes and limitations

- Diarization tops out at **8 speakers** (model limit). Beyond that, words are still transcribed
  correctly but some voices share a label.
- Speaker naming is per speaker across the whole meeting; individual lines cannot be reassigned yet.
- Deleting a meeting is permanent (audio, transcript, notes, exports).
- A meeting-chat feature ("ask this meeting a question") is designed but not built.

## License

Internal project of Crosswinds Church / GoGospelNow. Not licensed for redistribution.
