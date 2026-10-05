"""Run on watcher. Generate credentials on the server without printing them."""
import os
import secrets
import subprocess
from pathlib import Path

os.umask(0o077)
directory = Path(os.environ.get("NTFY_CREDENTIALS_DIR", Path.home() / ".config/homelab-alerting"))
directory.mkdir(parents=True, exist_ok=True, mode=0o700)
for user, filename in (("alert-publisher", "ntfy-publisher.secret"), ("phone", "ntfy-phone.secret")):
    path = directory / filename
    if path.exists():
        raise SystemExit(f"Refusing to replace existing credential file: {path}")
    password = secrets.token_urlsafe(30)
    path.write_text(password + "\n")
    path.chmod(0o600)
    subprocess.run(["docker", "compose", "exec", "-T", "-e", "NTFY_PASSWORD", "ntfy", "ntfy", "user", "add", user],
                   env={**os.environ, "NTFY_PASSWORD": password}, check=True)
    for topic in ("homelab-critical", "homelab-warning"):
        subprocess.run(["docker", "compose", "exec", "-T", "ntfy", "ntfy", "access", user, topic,
                        "wo" if user == "alert-publisher" else "ro"], check=True)
print("Created publisher (write-only) and phone (read-only) accounts. Credentials remain on watcher.")
