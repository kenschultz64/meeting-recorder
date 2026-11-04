# GoGospelNow.com Meeting Recorder

A self-hosted web application that records or uploads meetings, transcribes them locally, separates up to eight speakers, creates AI-assisted minutes, and exports the results. It was built by Crosswinds Church for staff and committee meetings.

## Features

- Upload MP3, M4A, WAV, OGG, WebM, or video files, or record in the browser.
- Preview transcription in roughly 10-second intervals while recording.
- Recover server-persisted recording chunks after a closed tab or interrupted upload.
- Separate and name up to eight speakers with NVIDIA Nemotron-3-Diarization.
- Create notes and optional AI summaries with any OpenAI-compatible language-model endpoint.
- Copy or download TXT/Markdown transcripts and optionally export to Google Drive.
- Admin-created accounts with strict per-user meeting and audio ownership.
- Light/dark themes, microphone selection, input meter, and local test recording.
- Illustrated PDF guide available from the in-app **Docs** button.

## Supported platforms

**Server (official):** x86-64 Ubuntu 22.04/24.04, Debian 12, and Pop!_OS 22.04/24.04.

**Experimental:** Ubuntu under WSL2 with systemd enabled. Native Windows and macOS server installations are not currently supported because the verified NeMo diarization stack and service manager are Linux-specific.

**Clients:** any current Chrome, Edge, Firefox, or Safari browser on Windows, macOS, Linux, Android, or iOS. Microphone recording requires HTTPS (or localhost).

See [INSTALL.md](INSTALL.md) for the complete support matrix, hardware requirements, and installation choices.

## Install tool

The repository includes a guarded installer. It checks the operating system and prerequisites, creates an isolated Python environment, generates a private configuration file, migrates the database, installs hardened user services, and runs a diagnostic.

```bash
git clone https://github.com/kenschultz64/meeting-recorder.git
cd meeting-recorder
./install.sh --check
./install.sh --with-asr-container --hostname meeting.example.org
```

`--with-asr-container` starts an optional loopback-only Parakeet TDT v3 service through Docker. If you already run a compatible ASR endpoint, use `--asr-url URL` instead. AI summaries are optional; add `--llm-url URL --llm-model NAME` to enable them.

The installer never publishes a port or configures DNS/TLS. Put the loopback-only web service behind your own HTTPS reverse proxy, Tailscale Serve, or Cloudflare Tunnel.

## Architecture

```text
browser --HTTPS--> reverse proxy/tunnel --> Gunicorn/Django :18780 (loopback)
                                                |
                                  Redis :6390 --> Celery worker
                                                |--> Parakeet ASR HTTP service
                                                |--> Nemotron-3 diarization (local CPU)
                                                `--> optional OpenAI-compatible LLM
```

- SQLite is the default database; PostgreSQL can be selected with `DATABASE_URL` after installing `requirements-postgres.txt`.
- Audio is served only through an authenticated owner-checking Django view—not directly from `MEDIA_ROOT`.
- The bundled ASR option uses the MIT-licensed `parakeet.cpp` runtime with NVIDIA Parakeet TDT 0.6B v3 weights (CC-BY-4.0).
- The app also accepts the original native `POST /api/transcribe` response or OpenAI-style verbose transcription JSON with word timestamps.
- No production credentials, model weights, recordings, database, or private server addresses are included.

## Documentation

- [INSTALL.md](INSTALL.md) — operating systems, hardware, automated and manual installation.
- [DEPLOY.md](DEPLOY.md) — HTTPS, hardening, backups, upgrades, and operations.
- [SECURITY.md](SECURITY.md) — vulnerability reporting and deployment security boundaries.
- `docs/meeting-recorder-guide.pdf` — illustrated end-user guide shipped inside the app.
- `.env.example` — complete configuration reference.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(64))')"
export DJANGO_DEBUG=1
export DJANGO_SECURE_COOKIES=0
.venv/bin/python manage.py migrate
.venv/bin/python manage.py test meetings
.venv/bin/python manage.py runserver 127.0.0.1:18780
```

This lightweight setup exercises the web application. Full transcription additionally needs Redis, a Celery worker, the diarization dependencies, ffmpeg, and a compatible ASR service; [INSTALL.md](INSTALL.md) documents those steps.

## Limitations

- Diarization is limited to eight speakers by the model. Additional voices may share an existing label.
- Speaker names apply across an entire meeting; individual transcript passages cannot yet be reassigned.
- SQLite is suitable for a small team. Use PostgreSQL for heavier concurrent use.
- Deleting a meeting permanently removes its audio, transcript, notes, and export records.
- The Google Drive button requires a separately installed and authenticated `gog` CLI.

## License

The application source and documentation are licensed under Apache-2.0; see [LICENSE](LICENSE). Third-party runtimes and model weights retain their own licenses and attribution requirements; see [NOTICE](NOTICE).
