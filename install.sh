#!/usr/bin/env bash
set -Eeuo pipefail

APP_NAME="GoGospelNow.com Meeting Recorder"
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="$ROOT_DIR"
ASR_URL="http://127.0.0.1:18771/api/transcribe"
LLM_URL=""
LLM_MODEL="local-model"
HOSTNAME_VALUE="localhost"
INSTALL_DIARIZATION=1
INSTALL_ASR_CONTAINER=0
INSTALL_SYSTEM_PACKAGES=1
ENABLE_SERVICES=1
ASSUME_YES=0
CHECK_ONLY=0
FORCE_ENV=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Installs the Meeting Recorder on a supported Debian-family Linux host.
Run this script from a cloned copy of the repository.

Options:
  --check                    Check prerequisites without changing the machine
  --prefix PATH              Install/run from PATH (default: repository directory)
  --asr-url URL              Compatible transcription endpoint (native or OpenAI format)
  --llm-url URL              Optional OpenAI-compatible /v1 endpoint
  --llm-model NAME           Model served by --llm-url (default: local-model)
  --hostname HOST            Browser hostname (default: localhost)
  --no-diarization           Skip NeMo/Nemotron speaker separation dependencies
  --with-asr-container       Start the bundled loopback-only Parakeet ASR container
  --no-system-packages       Do not install missing apt packages
  --no-services              Do not create/start user systemd services
  --force-env                Replace an existing Meeting Recorder env file
  --yes                      Non-interactive mode; accept supported defaults
  -h, --help                 Show this help

Supported: Ubuntu 22.04/24.04, Debian 12, Pop!_OS 22.04/24.04 on x86_64.
Experimental: WSL2 Ubuntu (services may need systemd enabled manually).
EOF
}

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }

while (($#)); do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --prefix) shift; PREFIX="${1:?--prefix requires a path}" ;;
    --asr-url) shift; ASR_URL="${1:?--asr-url requires a URL}" ;;
    --llm-url) shift; LLM_URL="${1:?--llm-url requires a URL}" ;;
    --llm-model) shift; LLM_MODEL="${1:?--llm-model requires a name}" ;;
    --hostname) shift; HOSTNAME_VALUE="${1:?--hostname requires a hostname}" ;;
    --no-diarization) INSTALL_DIARIZATION=0 ;;
    --with-asr-container) INSTALL_ASR_CONTAINER=1; ASR_URL="http://127.0.0.1:18771/v1/audio/transcriptions" ;;
    --no-system-packages) INSTALL_SYSTEM_PACKAGES=0 ;;
    --no-services) ENABLE_SERVICES=0 ;;
    --force-env) FORCE_ENV=1 ;;
    --yes) ASSUME_YES=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

[[ "$(uname -s)" == "Linux" ]] || die "The installer supports Linux only. See INSTALL.md for client/browser support."
[[ "$(uname -m)" == "x86_64" ]] || die "The automated installer currently supports x86_64 only."
[[ -r /etc/os-release ]] || die "Cannot identify this Linux distribution (/etc/os-release missing)."
# shellcheck disable=SC1091
. /etc/os-release
DISTRO_ID="${ID:-unknown}"
DISTRO_VERSION="${VERSION_ID:-unknown}"
case "$DISTRO_ID:$DISTRO_VERSION" in
  ubuntu:22.04|ubuntu:24.04|debian:12|pop:22.04|pop:24.04) ;;
  *) die "Unsupported host: ${PRETTY_NAME:-$DISTRO_ID $DISTRO_VERSION}. Supported releases are listed in INSTALL.md." ;;
esac

if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  warn "WSL2 is experimental. Enable systemd in WSL before requesting service installation."
fi

[[ -f "$ROOT_DIR/manage.py" && -f "$ROOT_DIR/requirements.lock" ]] || die "Run install.sh from a cloned Meeting Recorder repository."
PREFIX="$(realpath -m "$PREFIX")"

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command_exists "$candidate" && "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(not ((3, 10) <= sys.version_info[:2] <= (3, 12)))
PY
  then
    PYTHON_BIN="$(command -v "$candidate")"
    break
  fi
done

missing=()
[[ -n "$PYTHON_BIN" ]] || missing+=(python3)
command_exists ffmpeg || missing+=(ffmpeg)
command_exists ffprobe || missing+=(ffmpeg)
command_exists redis-server || missing+=(redis-server)
command_exists git || missing+=(git)
command_exists curl || missing+=(curl)
if ((INSTALL_ASR_CONTAINER)) && ! command_exists docker; then
  die "Docker Engine with Compose v2 is required for --with-asr-container. Install it from docs.docker.com, then rerun."
fi

printf '%s\n' "${APP_NAME} prerequisite check"
printf '  OS:           %s\n' "${PRETTY_NAME:-$DISTRO_ID $DISTRO_VERSION}"
printf '  Architecture: %s\n' "$(uname -m)"
printf '  Python:       %s\n' "${PYTHON_BIN:-missing (need 3.10-3.12)}"
printf '  ffmpeg:       %s\n' "$(command -v ffmpeg 2>/dev/null || printf missing)"
printf '  Redis:        %s\n' "$(command -v redis-server 2>/dev/null || printf missing)"
printf '  ASR endpoint: %s\n' "$ASR_URL"
printf '  Install path: %s\n' "$PREFIX"

if ((CHECK_ONLY)); then
  ((${#missing[@]} == 0)) || die "Missing prerequisites: $(printf '%s ' "${missing[@]}")"
  log "Prerequisites passed"
  exit 0
fi

if ((${#missing[@]})); then
  ((INSTALL_SYSTEM_PACKAGES)) || die "Missing prerequisites: $(printf '%s ' "${missing[@]}")"
  command_exists sudo || die "sudo is required to install system packages."
  if ((!ASSUME_YES)); then
    read -r -p "Install required system packages with apt? [Y/n] " reply
    [[ "${reply:-Y}" =~ ^[Yy]$ ]] || die "System-package installation declined."
  fi
  log "Installing operating-system packages"
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-dev build-essential git ffmpeg libsndfile1 redis-server curl
fi

if [[ "$PREFIX" != "$ROOT_DIR" ]]; then
  [[ ! -e "$PREFIX/.git" ]] || die "Refusing to overwrite an existing Git checkout at $PREFIX"
  log "Copying application to $PREFIX"
  mkdir -p "$PREFIX"
  tar --exclude=.git --exclude=.venv --exclude=db.sqlite3 --exclude=media -C "$ROOT_DIR" -cf - . | tar -C "$PREFIX" -xf -
fi

cd "$PREFIX"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
log "Creating isolated Python environment"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install --require-hashes --requirement requirements.lock

if ((INSTALL_DIARIZATION)); then
  log "Installing CPU PyTorch and speaker-diarization dependencies (this is the large step)"
  .venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu'
  .venv/bin/pip install --requirement requirements-diarization.txt
else
  warn "Speaker separation is disabled. Transcription jobs will fail unless NeMo is installed later."
fi

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
ENV_FILE="$CONFIG_DIR/meeting-recorder.env"
mkdir -p "$CONFIG_DIR"
if [[ -e "$ENV_FILE" && $FORCE_ENV -ne 1 ]]; then
  die "$ENV_FILE already exists. Preserve it, or rerun with --force-env after backing it up."
fi

SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(64))')"
CSRF_ORIGIN=""
SECURE_COOKIES=0
if [[ "$HOSTNAME_VALUE" != "localhost" && "$HOSTNAME_VALUE" != "127.0.0.1" ]]; then
  CSRF_ORIGIN="https://$HOSTNAME_VALUE"
  SECURE_COOKIES=1
fi
umask 077
cat >"$ENV_FILE" <<EOF
SECRET_KEY=$SECRET_KEY
DJANGO_DEBUG=0
DJANGO_SECURE_COOKIES=$SECURE_COOKIES
TRUST_X_FORWARDED_PROTO=$SECURE_COOKIES
ALLOWED_HOSTS=localhost,127.0.0.1,$HOSTNAME_VALUE
CSRF_TRUSTED_ORIGINS=$CSRF_ORIGIN
PARAKEET_URL=$ASR_URL
LLM_URL=$LLM_URL
LLM_MODEL=$LLM_MODEL
LLM_FALLBACK_URL=
LLM_FALLBACK_MODEL=
CELERY_BROKER_URL=redis://127.0.0.1:6390/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6390/1
CELERY_TASK_ALWAYS_EAGER=0
GOG_BIN=gog
EOF
chmod 600 "$ENV_FILE"

export SECRET_KEY DJANGO_DEBUG=0 DJANGO_SECURE_COOKIES="$SECURE_COOKIES"
export TRUST_X_FORWARDED_PROTO="$SECURE_COOKIES"
export ALLOWED_HOSTS="localhost,127.0.0.1,$HOSTNAME_VALUE" CSRF_TRUSTED_ORIGINS="$CSRF_ORIGIN"
export PARAKEET_URL="$ASR_URL" LLM_URL LLM_MODEL
export CELERY_BROKER_URL="redis://127.0.0.1:6390/0" CELERY_RESULT_BACKEND="redis://127.0.0.1:6390/1"
log "Preparing database and validating Django configuration"
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py check
.venv/bin/python manage.py check --deploy || warn "Review the deployment warnings above before exposing the app publicly."

if ((ENABLE_SERVICES)); then
  command_exists systemctl || die "systemd is required for --services; rerun with --no-services otherwise."
  USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  mkdir -p "$USER_UNIT_DIR"
  sed -e "s|@@APP_DIR@@|$PREFIX|g" -e "s|@@ENV_FILE@@|$ENV_FILE|g" \
    deploy/meeting-recorder-web.service >"$USER_UNIT_DIR/meeting-recorder-web.service"
  sed -e "s|@@APP_DIR@@|$PREFIX|g" -e "s|@@ENV_FILE@@|$ENV_FILE|g" \
    deploy/meeting-recorder-worker.service >"$USER_UNIT_DIR/meeting-recorder-worker.service"
  cp deploy/meeting-recorder-redis.service "$USER_UNIT_DIR/meeting-recorder-redis.service"
  systemctl --user daemon-reload
  systemctl --user enable --now meeting-recorder-redis meeting-recorder-web meeting-recorder-worker
  if command_exists loginctl; then
    sudo loginctl enable-linger "$USER" || warn "Could not enable linger; services may stop after logout."
  fi
fi

if ((INSTALL_ASR_CONTAINER)); then
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required for --with-asr-container."
  log "Starting the loopback-only Parakeet ASR container (first run downloads the model)"
  docker compose -f deploy/asr.compose.yaml up -d
fi

log "Running installation doctor"
.venv/bin/python scripts/doctor.py --env-file "$ENV_FILE" --allow-missing-services

printf '\nInstallation complete.\n'
printf '1. Create the first administrator: cd %q && .venv/bin/python manage.py createsuperuser\n' "$PREFIX"
printf '2. Open locally: http://127.0.0.1:18780/accounts/login/\n'
printf '3. Configure HTTPS before using browser microphone recording. See INSTALL.md.\n'
printf '4. The ASR endpoint must be reachable at: %s\n' "$ASR_URL"
