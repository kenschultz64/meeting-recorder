# Production deployment and operations

Start with [INSTALL.md](INSTALL.md). This document covers the production boundary after the installer has created the app, database, environment file, and user services.

## Deployment layout

- Gunicorn/Django: `127.0.0.1:18780`
- Private Redis: `127.0.0.1:6390`
- Optional Parakeet ASR: `127.0.0.1:18771`
- Celery worker: local process, concurrency 1 by default
- Configuration: `~/.config/meeting-recorder.env` (`0600`)
- SQLite database: `db.sqlite3`; recordings and recoverable chunks: `media/`

Only an HTTPS reverse proxy or tunnel should be network-accessible. Never publish Redis or the ASR endpoint to the internet.

## Required production configuration

```text
SECRET_KEY=<long random value; never commit it>
DJANGO_DEBUG=0
DJANGO_SECURE_COOKIES=1
TRUST_X_FORWARDED_PROTO=1
ALLOWED_HOSTS=localhost,127.0.0.1,meeting.example.org
CSRF_TRUSTED_ORIGINS=https://meeting.example.org
PARAKEET_URL=http://127.0.0.1:18771/v1/audio/transcriptions
```

Use the same `SECRET_KEY` for web and worker services. Rotating it signs out all users. The application refuses to start in production with a missing or obvious placeholder key.

Run Django's production checks after every configuration change:

```bash
set -a; . ~/.config/meeting-recorder.env; set +a
.venv/bin/python manage.py check --deploy
```

The generated values are shell-safe. If you manually add values containing whitespace or shell metacharacters, quote them correctly for both systemd's `EnvironmentFile` syntax and your shell.

## TLS and reverse proxy

Terminate TLS in front of Gunicorn and proxy to `http://127.0.0.1:18780`. Forward the original host and `X-Forwarded-Proto: https`. Do not serve `/media/` as static files: audio authorization is enforced by Django.

Supported patterns include Caddy/nginx, Tailscale Serve, and Cloudflare Tunnel. Browser recording needs HTTPS. A proxy health check should request `/accounts/login/` and expect HTTP 200.

## Service management

```bash
systemctl --user status meeting-recorder-redis meeting-recorder-web meeting-recorder-worker
journalctl --user -u meeting-recorder-web -f
journalctl --user -u meeting-recorder-worker -f
systemctl --user restart meeting-recorder-web meeting-recorder-worker
```

The installer enables user lingering so services continue after logout. Verify it with `loginctl show-user "$USER" -p Linger`.

## Security invariants

- `DEBUG=0` on any shared or internet-accessible installation.
- Secure, HttpOnly, SameSite cookies over HTTPS.
- Exact `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`; never use `*`.
- Gunicorn, Redis, and ASR remain loopback-only.
- `/media/...` always passes through `private_audio`; another user receives 404.
- Public sign-up and Django admin remain disabled.
- The environment file, database, recordings, and backups are never committed.
- The optional LLM sees meeting transcript text. Use a private endpoint or obtain informed consent before using a third party.
- Apply operating-system and Python dependency security updates regularly and test before deployment.

## Backups

Back up the database and media together while writes are paused or after creating a consistent SQLite copy:

```bash
mkdir -p "$HOME/meeting-recorder-backups"
.venv/bin/python - <<'PY'
import sqlite3
source = sqlite3.connect('db.sqlite3')
target = sqlite3.connect('/home/' + __import__('getpass').getuser() + '/meeting-recorder-backups/db.sqlite3')
source.backup(target)
target.close(); source.close()
PY
tar czf "$HOME/meeting-recorder-backups/media-$(date +%F-%H%M%S).tar.gz" media
```

Store copies off-host, encrypt backups containing meetings, test restores, and set a retention policy. A code checkout is not a backup of recordings or the database.

## Upgrade

```bash
git fetch --all --prune
git pull --ff-only
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py test meetings
systemctl --user restart meeting-recorder-web meeting-recorder-worker
.venv/bin/python scripts/doctor.py
```

Back up first. Review release notes before changing the pinned NeMo/PyTorch stack or ASR image digest.

## Health verification

1. `scripts/doctor.py` reports Django, Redis, ASR, ffmpeg, and the optional LLM state.
2. The login page returns HTTP 200 through the HTTPS hostname.
3. Upload a short audio file and confirm **Transcribed** with speaker labels.
4. A different ordinary account receives 404 for the meeting and its audio URL.
5. Generate a summary if an LLM is configured.
6. Download TXT/Markdown and verify the named speakers.
7. `python manage.py test meetings` passes.

## Capacity notes

The default Celery worker is deliberately serial. This prevents multiple CPU-heavy diarization jobs from exhausting a modest host, but queued meetings wait for earlier work. SQLite also serializes writes. For a larger installation, benchmark first, move to PostgreSQL, and separate live-preview and full-transcription Celery queues before increasing concurrency.
