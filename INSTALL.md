# Installation guide

## 1. Platform support

### Server

| Status | Operating system | Architecture | Notes |
|---|---|---|---|
| Supported | Ubuntu 22.04 LTS / 24.04 LTS | x86-64 | Automated installer and test target |
| Supported | Debian 12 | x86-64 | Automated installer and test target |
| Supported | Pop!_OS 22.04 / 24.04 | x86-64 | Automated installer and production reference |
| Experimental | Ubuntu on WSL2 | x86-64 | Enable systemd; browser microphone still needs HTTPS |
| Not supported as a server | Native Windows | — | Use a Linux VM or WSL2 |
| Not supported as a server | macOS | Intel/Apple Silicon | Browser client works; Linux server stack is not verified |
| Not supported | ARM Linux, NAS appliances, mobile OSes | — | Some dependencies may work, but this release is not tested there |

The web client works in current desktop and mobile browsers on Windows, macOS, Linux, Android, and iOS.

### Hardware

- 4 modern CPU cores minimum; 8 or more recommended.
- 16 GB RAM minimum for the full local stack; 32 GB recommended for long recordings or concurrent users.
- 10 GB free disk space plus room for recordings and backups.
- No GPU is required. The reference ASR and diarization paths run on CPU.
- A GPU-backed OpenAI-compatible LLM can improve summary speed, but summaries are optional.

## 2. What the installer does

`install.sh`:

1. Refuses unsupported operating systems and CPU architectures.
2. Checks Python 3.10–3.12, ffmpeg/ffprobe, Redis, Git, and curl.
3. Optionally installs missing Debian/Ubuntu packages through `apt` after approval.
4. Creates `.venv` and installs pinned Python dependencies.
5. Installs CPU PyTorch and the verified NeMo revision for speaker diarization.
6. Generates `~/.config/meeting-recorder.env` with a random secret and mode `0600`.
7. Runs migrations and Django configuration checks.
8. Creates loopback-only systemd user services for Redis, Gunicorn, and Celery.
9. Optionally starts a loopback-only Parakeet ASR container.
10. Runs `scripts/doctor.py` without printing secret values.

It does **not** configure DNS, open firewall ports, install TLS certificates, or expose Redis/ASR publicly.

## 3. Automated installation

### Prerequisites

- A supported Linux host and a normal non-root user with `sudo`.
- Internet access during installation for Python packages and model downloads.
- Docker Engine plus Compose v2 only if using `--with-asr-container`. Install Docker from its official instructions: <https://docs.docker.com/engine/install/ubuntu/>.

### Complete local stack

```bash
git clone https://github.com/kenschultz64/meeting-recorder.git
cd meeting-recorder
./install.sh --check
./install.sh --with-asr-container --hostname meeting.example.org
```

The ASR model download is about 1–2 GB and occurs the first time the container starts. Its endpoint is `http://127.0.0.1:18771/v1/audio/transcriptions` and is not published outside the host.

### Use an existing ASR service

```bash
./install.sh \
  --asr-url http://127.0.0.1:18771/api/transcribe \
  --hostname meeting.example.org
```

Compatible responses are either:

- native JSON with `segments[].start/end/text/words[]`, or
- OpenAI verbose transcription JSON with top-level word timestamps.

### Enable AI summaries

```bash
./install.sh \
  --with-asr-container \
  --llm-url http://127.0.0.1:8080/v1 \
  --llm-model your-model-name \
  --hostname meeting.example.org
```

The LLM endpoint receives meeting transcript text. Keep it local unless users have knowingly consented to a third-party service processing their meetings.

### Useful installer options

```text
--check                 Read-only prerequisite check
--prefix PATH           Install into another directory
--no-diarization        Skip the large NeMo dependency installation
--no-system-packages    Refuse rather than use apt
--no-services           Install files/database but do not create systemd services
--force-env             Replace the existing env file (back it up first)
--yes                   Accept supported non-destructive defaults
```

The installer protects an existing environment file. It will not overwrite one unless `--force-env` is explicitly supplied.

## 4. First sign-in

Create the first administrator after installation:

```bash
.venv/bin/python manage.py createsuperuser
```

Then open `http://127.0.0.1:18780/accounts/login/` locally. Once HTTPS is configured, use the public hostname. Additional accounts are created from the in-app **Users** page; public sign-up is intentionally disabled.

## 5. HTTPS is required for recording

Browsers allow microphone access only in a secure context (HTTPS or localhost). The app binds to loopback by default. Put it behind one of:

- Caddy or nginx with a TLS certificate;
- Tailscale Serve for tailnet-only access;
- Cloudflare Tunnel for a public hostname.

Set these values in `~/.config/meeting-recorder.env`:

```text
ALLOWED_HOSTS=localhost,127.0.0.1,meeting.example.org
CSRF_TRUSTED_ORIGINS=https://meeting.example.org
DJANGO_SECURE_COOKIES=1
TRUST_X_FORWARDED_PROTO=1
```

Then restart:

```bash
systemctl --user restart meeting-recorder-web meeting-recorder-worker
```

Do not proxy `/media/` directly from disk. Django's authenticated media view enforces meeting ownership.

## 6. Manual installation

Use this path if you do not want the install script.

```bash
sudo apt install python3-venv python3-dev build-essential git ffmpeg libsndfile1 redis-server curl
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu'
.venv/bin/pip install -r requirements-diarization.txt
cp .env.example ~/.config/meeting-recorder.env
chmod 600 ~/.config/meeting-recorder.env
# Edit every placeholder and endpoint before continuing.
.venv/bin/python manage.py migrate
.venv/bin/python manage.py check
.venv/bin/python manage.py createsuperuser
```

The service files under `deploy/` contain `@@APP_DIR@@` and `@@ENV_FILE@@` placeholders. The automated installer safely renders them; manual installers must replace both before copying the units into `~/.config/systemd/user/`.

For PostgreSQL, additionally run `.venv/bin/pip install -r requirements-postgres.txt` and set `DATABASE_URL`.

## 7. Verification

```bash
.venv/bin/python scripts/doctor.py
.venv/bin/python manage.py test meetings
systemctl --user is-active meeting-recorder-redis meeting-recorder-web meeting-recorder-worker
curl -I http://127.0.0.1:18780/accounts/login/
```

Then sign in, upload a short audio file, wait for **Transcribed**, name a speaker, and download the TXT transcript. If summaries are configured, generate one and confirm the result.

## 8. Troubleshooting

- **Login POST gives CSRF 403:** `CSRF_TRUSTED_ORIGINS` must contain the exact HTTPS origin.
- **Recording button cannot access the microphone:** use HTTPS or localhost and grant browser microphone permission.
- **Meeting remains Processing:** inspect `journalctl --user -u meeting-recorder-worker`; verify ASR reachability with `scripts/doctor.py`.
- **No speaker labels:** confirm NeMo installed successfully and that the worker can download/load `nvidia/Nemotron-3-Diarization`.
- **ASR container is still starting:** the first model download can take several minutes; inspect `docker compose -f deploy/asr.compose.yaml logs -f`.
- **Google Drive export fails:** install/authenticate `gog`, or ignore that optional feature.
