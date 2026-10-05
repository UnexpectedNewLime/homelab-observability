"""Reject deployment files/addresses and common credentials without printing values.

This guard is deliberately conservative, not a replacement for credential rotation
or a full secret scanner. Checks working-tree candidates and staged Git blobs.
"""
import argparse
import fnmatch
import ipaddress
from pathlib import Path
import re
import subprocess

PRIVATE_PATHS = {
    ".env", "pve/pve.yml", "prometheus/prometheus.yml",
    "prometheus/rules/homelab.yml", "prometheus/rules/logging-alerts.yml",
    "alloy/config.alloy", "proxmox/config.alloy", "loki/ingress.conf",
    "ntfy/server.yml", "LOGGING-ALERTING-RUNBOOK.md",
}
PRIVATE_DIRS = {"backups", "secrets", "credentials", ".ssh", ".claude", ".test-output",
                "prometheus-data", "alertmanager-data", "grafana-data", "loki-data",
                "alloy-data", "ntfy-data", "tailscale-ntfy-data"}
SUFFIXES = ("*.secret", "*.key", "*.pem", "*.db", "*.db-*", "*.sqlite*", "*.bak", "*.log")
DOC_NETS = tuple(ipaddress.ip_network(net) for net in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "2001:db8::/32"))
IPV4 = re.compile(r"(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])")
IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F]{0,4}(?![\w:])")
SENSITIVE = (
    ("private tailnet hostname", re.compile(r"\b[\w.-]+\.ts\.net\b")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("Tailscale key", re.compile(r"\btskey-[a-z]+-[A-Za-z0-9-]{15,}\b")),
    ("credential in URL", re.compile(r"https?://[^\s/:]+:[^\s/@]+@")),
    ("personal home path", re.compile(r"/home/(?!USER\b)[a-z][a-z0-9_-]+/")),
)


def private_path(name):
    path = Path(name)
    return (name in PRIVATE_PATHS or bool(set(path.parts) & PRIVATE_DIRS)
            or (path.name.startswith(".env.") and path.name != ".env.example")
            or path.name == ".env"
            or any(fnmatch.fnmatch(path.name, pattern) for pattern in SUFFIXES))


def findings(name, data):
    errors = []
    if private_path(name):
        errors.append("deployment/secret/runtime file must not be tracked")
    if b"\x00" in data:
        errors.append("binary file requires explicit security review")
        return errors
    text = data.decode("utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in SENSITIVE:
            if pattern.search(line):
                errors.append(f"line {number}: {label}")
        for match in list(IPV4.finditer(line)) + list(IPV6.finditer(line)):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            if not (address.is_loopback or address.is_unspecified
                    or any(address in net for net in DOC_NETS if address.version == net.version)):
                errors.append(f"line {number}: literal deployment IP")
        if name == ".env.example" and line.strip() and not line.lstrip().startswith("#"):
            if "=" not in line or line.split("=", 1)[1].strip():
                errors.append(f"line {number}: .env.example values must be empty")
        if name.endswith("pve.yml.example") and "token_value:" in line:
            if line.split("token_value:", 1)[1].strip() != '"PASTE_TOKEN_SECRET_HERE"':
                errors.append(f"line {number}: API token must be a placeholder")
    return errors


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def audit(root, revision=None):
    failures = []
    if revision:
        names = git(root, "ls-tree", "-rz", "--name-only", revision).decode().split("\0")
        candidates = [(name, git(root, "show", f"{revision}:{name}")) for name in names if name]
    else:
        names = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
        candidates = [(name, (root / name).read_bytes()) for name in set(names)
                      if name and (root / name).is_file() and not (root / name).is_symlink()]
        # A clean worktree can hide a bad staged version, so audit the index too.
        staged = git(root, "ls-files", "-z").decode().split("\0")
        candidates += [(name + " [index]", git(root, "show", ":" + name)) for name in staged if name]
    for name, data in candidates:
        original = name.removesuffix(" [index]")
        failures.extend(f"{name}: {error}" for error in findings(original, data))
    return sorted(set(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--revision", help="Audit a committed tree instead of worktree/index")
    args = parser.parse_args()
    errors = audit(args.root, args.revision)
    for error in errors:
        print(error)
    print(f"Repository safety: {'FAIL' if errors else 'PASS'} ({len(errors)} findings; values withheld)")
    raise SystemExit(bool(errors))
