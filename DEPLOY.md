# DEPLOY.md — production install

Written from the working deployment on `cw2` (Pop!_OS, Tailscale + Cloudflare tunnel). Substitute your
own hostnames, ports and paths.

## 0. Prerequisites

| Need | Why | Example |
|---|---|---|
| Python 3.10+ | Django 5.2 / Celery 5.6 | `python3 -m venv .venv` |
| Redis | Celery broker + result backend | `deploy/redis.compose.yaml` (bound to loopback) |
| ffmpeg + ffprobe | normalize audio, probe duration | `apt install ffmpeg` |
| Parakeet ASR service | speech-to-text over HTTP | loopback port, e.g. `127.0.0.1:18771` |
| OpenAI-compatible LLM | summaries | any `/v1` endpoint |
| NeMo + CPU torch | in-process diarization | `requirements-diarization.txt` |

## 1. Install

```bash
sudo mkdir -p /opt/meeting-recorder && sudo chown "$USER" /opt/meeting-recorder
rsync -a ./ /opt/meeting-recorder/
cd /opt/meeting-recorder
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-diarization.txt
cp .env.example .env && chmod 600 .env      # then edit it
set -a; . ./.env; set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py shell -c "from django.contrib.auth.models import User; User.objects.create_superuser('you','you@example.com', input('password: '))"
```

The first account must be created on the command line (there is no public sign-up); everybody else is
created from the in-app **Users** page by an administrator.

## 2. Secrets

`SECRET_KEY` **must** come from the environment. Never commit a real key and never ship the
development fallback. Recommended: a mode-0600 env file referenced by the systemd unit.

```bash
umask 077
printf 'SECRET_KEY=%s\n' "$(.venv/bin/python -c 'from django.core.management.utils import get_random_secret_key as g;print(g())')" \
  > ~/.config/meeting-recorder.env
chmod 600 ~/.config/meeting-recorder.env
```

Keep the same value across restarts and across web/worker processes: changing it invalidates every
session (nobody is locked out permanently, but everyone must sign in again).

## 3. Systemd user units

Templates in `deploy/`. Install and enable both:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/meeting-recorder-web.service deploy/meeting-recorder-worker.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now meeting-recorder-web meeting-recorder-worker
loginctl enable-linger "$USER"     # keep them running after logout and across reboots
```

Both units read `EnvironmentFile=%h/.config/meeting-recorder.env` and should point
`WorkingDirectory` at the install path. The web unit uses Django's development server, which is fine
behind a tunnel for a small team but is **not** a hardened public server — for an internet-facing
deployment put gunicorn (or uvicorn) behind your reverse proxy instead of `runserver`.

Verify:

```bash
systemctl --user is-enabled meeting-recorder-web meeting-recorder-worker   # enabled
systemctl --user is-active  meeting-recorder-web meeting-recorder-worker   # active
curl -sI http://127.0.0.1:18780/accounts/login/ | head -1                  # HTTP/1.1 200 OK
```

## 4. Reaching it from outside

Two supported patterns, both terminating TLS in front of the app:

- **Cloudflare tunnel** — a public hostname routed to `http://127.0.0.1:18780`. Set SSL/TLS mode to
  **Full** (the origin is plain HTTP on loopback), turn on **Always Use HTTPS**, and do not put an
  Access/WAF challenge in front of the login page.
- **Tailscale serve** — `tailscale serve --bg --https=8444 http://127.0.0.1:18780`. Use a port that is
  *different* from the app port, or the proxy and the app fight over the same listener.

Then set, in the env file or settings:

- `ALLOWED_HOSTS` — every hostname the app is reached by.
- `CSRF_TRUSTED_ORIGINS` — the same origins with scheme, e.g. `https://meeting.example.org`.

A login POST that fails with "Origin checking failed" means these two are wrong; it does not mean the
proxy is broken.

## 5. Hardening invariants (do not regress these)

- `DEBUG=0` outside development.
- `/media/...` must go through the owner-only `private_audio` view. Never let the proxy serve
  `MEDIA_ROOT` statically — that would expose every meeting recording to anyone with a URL.
- Session and CSRF cookies are `Secure`; the app is only reachable over HTTPS.
- `X-Robots-Tag: noindex` is set by `meetings/middleware.NoIndexMiddleware`.
- Django admin stays disabled (`/admin/` → 404); account management lives on the `/users/` page.
- Meeting ownership is strict: unowned/legacy rows are not listed to anyone.

## 6. Operations

```bash
# back up database + media
tar czf ~/mr-backup-$(date +%F).tar.gz -C /opt/meeting-recorder db.sqlite3 media docs

# tail logs
journalctl --user -u meeting-recorder-web -f
journalctl --user -u meeting-recorder-worker -f

# after ANY code change (units are not auto-reloading)
systemctl --user restart meeting-recorder-web meeting-recorder-worker
```

Health checks worth running after a change:

1. `curl -sI https://your-host/accounts/login/` → 200.
2. Sign in, upload a 1-minute audio file, confirm the meeting reaches **Transcribed**.
3. Confirm another account gets 404 on that meeting's URL and on `/media/...`.
4. `python manage.py test meetings` → all tests pass.

## 7. Dependencies that commonly bite

- **Diarization** is CPU-heavy: expect roughly the audio duration to be processed at several times
  real time on a modern desktop CPU. Give the worker `--concurrency 1` on modest hardware.
- **Parakeet** must be reachable from the worker, not just from your browser.
- **ffmpeg** must be on the worker's PATH; the pipeline calls `ffmpeg` and `ffprobe` directly.
- **Google Drive export** needs the `gog` CLI authenticated as the target Workspace user
  (`GOG_BIN`); without it only that one button fails.
