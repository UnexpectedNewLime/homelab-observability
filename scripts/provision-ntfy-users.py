"""Run on watcher. Create/resume accounts without rotating or printing credentials."""
import os
import re
import secrets
import stat
import subprocess
from pathlib import Path

ACCOUNTS = (("alert-publisher", "ntfy-publisher.secret", "wo"),
            ("phone", "ntfy-phone.secret", "ro"))
TOPICS = ("homelab-critical", "homelab-warning")


def ntfy(*args, password=None):
    command = ["docker", "compose", "exec", "-T"]
    env = dict(os.environ)
    # A caller's password/hash must never override a saved credential.
    env.pop("NTFY_PASSWORD", None)
    env.pop("NTFY_PASSWORD_HASH", None)
    if password is not None:
        command += ["-e", "NTFY_PASSWORD"]
        env["NTFY_PASSWORD"] = password
    return subprocess.run(command + ["ntfy", "ntfy", *args], env=env,
                          check=True, capture_output=True, text=True)


def provision(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    passwords = {}
    # Check both files before creating either file or changing any account.
    for user, filename, _ in ACCOUNTS:
        path = directory / filename
        if path.is_symlink():
            raise ValueError(f"Refusing symlink credential file: {path}")
        if path.exists():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError(f"Credential must be a private regular file: {path}")
            password = path.read_text().removesuffix("\n")
            if not password or any(ord(char) < 32 for char in password):
                raise ValueError(f"Empty or invalid credential file: {path}")
            passwords[user] = password

    listing = ntfy("user", "list").stdout
    users = dict(re.findall(r"^user (\S+) \(role: ([^, )]+)", listing, re.MULTILINE))
    for user, filename, _ in ACCOUNTS:
        if user in users and user not in passwords:
            raise ValueError(f"Existing account {user} has no saved credential; restore {filename} first")
        if user in users and users[user] != "user":
            raise ValueError(f"Expected a regular ntfy account: {user}")

    for user, filename, permission in ACCOUNTS:
        path = directory / filename
        if user not in passwords:
            password = secrets.token_urlsafe(30)
            # Persist first: even an ambiguous Docker failure can be retried with
            # exactly the same password. Never unlink it after a remote failure.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(password + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            passwords[user] = password
        if user not in users:
            ntfy("user", "add", user, password=passwords[user])
        # Reapplying the same grants repairs interrupted provisioning.
        for topic in TOPICS:
            ntfy("access", user, topic, permission)


if __name__ == "__main__":
    os.umask(0o077)
    directory = Path(os.environ.get("NTFY_CREDENTIALS_DIR", Path.home() / ".config/homelab-alerting"))
    try:
        provision(directory)
    except subprocess.CalledProcessError:
        raise SystemExit("ntfy provisioning failed; check service readiness and rerun to resume (credentials retained).")
    except (ValueError, OSError) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else "Credential file access failed; check permissions.")
    print("Provisioned publisher (write-only) and phone (read-only) accounts. Credentials remain on watcher.")
