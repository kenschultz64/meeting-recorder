#!/usr/bin/env python3
"""Read-only installation diagnostics for Meeting Recorder."""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_env(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"FAIL env file not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key, value)


def tcp_check(label: str, raw_url: str, advisory: bool = False) -> bool:
    if not raw_url:
        print(f"SKIP {label}: not configured")
        return True
    parsed = urlparse(raw_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        level = "WARN" if advisory else "FAIL"
        print(f"{level} {label}: invalid URL {raw_url!r}")
        return False
    try:
        with socket.create_connection((host, port), timeout=3):
            pass
    except OSError as exc:
        level = "WARN" if advisory else "FAIL"
        print(f"{level} {label}: {host}:{port} is unreachable ({exc})")
        return False
    print(f"PASS {label}: {host}:{port} is reachable")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path.home() / ".config/meeting-recorder.env")
    parser.add_argument("--allow-missing-services", action="store_true")
    args = parser.parse_args()
    load_env(args.env_file)

    failures = 0
    for binary in ("ffmpeg", "ffprobe"):
        path = shutil.which(binary)
        if path:
            print(f"PASS {binary}: {path}")
        else:
            print(f"FAIL {binary}: not found")
            failures += 1

    secret = os.environ.get("SECRET_KEY", "")
    if len(secret) >= 40 and "insecure" not in secret.lower() and "removed" not in secret.lower():
        print("PASS SECRET_KEY: configured (value hidden)")
    else:
        print("FAIL SECRET_KEY: missing or unsafe placeholder")
        failures += 1

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        import django
        django.setup()
        from django.core.management import call_command
        call_command("check", verbosity=0)
        print("PASS Django system check")
    except Exception as exc:
        print(f"FAIL Django system check: {type(exc).__name__}: {exc}")
        failures += 1

    service_results = [
        tcp_check("Redis", os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6390/0"), args.allow_missing_services),
        tcp_check("Parakeet ASR", os.environ.get("PARAKEET_URL", ""), args.allow_missing_services),
        tcp_check("LLM", os.environ.get("LLM_URL", ""), args.allow_missing_services),
    ]
    if not args.allow_missing_services:
        failures += sum(not result for result in service_results)

    if failures:
        print(f"\nDoctor found {failures} blocking problem(s).")
        return 1
    print("\nDoctor passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
