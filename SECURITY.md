# Security policy

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose meeting audio, transcripts, credentials, or another user's data. Use GitHub's private vulnerability-reporting feature for this repository. Include affected versions, reproduction steps, impact, and any proposed mitigation. Do not include real meeting recordings or production secrets.

## Supported version

Security fixes are applied to the current default branch. This project does not presently maintain older release branches.

## Deployment boundary

The application stores sensitive meeting audio and transcripts. Operators are responsible for:

- HTTPS and exact host/origin configuration;
- keeping Gunicorn, Redis, and ASR endpoints private;
- filesystem permissions, encrypted off-host backups, retention, and deletion policy;
- operating-system, Python, container, and model-runtime updates;
- selecting an LLM endpoint and obtaining consent before transcript text leaves the host;
- protecting admin accounts and using strong unique passwords.

Never configure a reverse proxy to serve `media/` directly. The Django media view performs ownership checks. Never commit `.env`, the systemd environment file, `db.sqlite3`, `media/`, recordings, or backups.

Run before a release or production change:

```bash
.venv/bin/python manage.py check --deploy
.venv/bin/python manage.py test meetings
.venv/bin/python scripts/doctor.py
```
