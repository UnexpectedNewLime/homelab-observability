"""Render approved .example files; never print values or read .env implicitly."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

TEMPLATES = {
    "prometheus/prometheus.yml": ("MONITORING_IP", "PROXMOX_IP", "NEXTCLOUD_CT_IP", "DISCORD_VM_IP", "NEXTCLOUD_URL", "WATCHER_HOST_LABEL"),
    "prometheus/rules/homelab.yml": ("DISCORD_VM_ID", "NEXTCLOUD_CT_ID"),
    "prometheus/rules/logging-alerts.yml": ("WATCHER_HOST_LABEL",),
    "pve/pve.yml": ("PVE_TOKEN_VALUE",),
    "loki/ingress.conf": ("PROXMOX_IP",),
    "ntfy/server.yml": ("NTFY_BASE_URL",),
    "alloy/config.alloy": ("WATCHER_HOST_LABEL",),
    "proxmox/config.alloy": ("MONITORING_IP", "NEXTCLOUD_CT_ID", "NEXTCLOUD_JOURNAL_PATH"),
}


def checked_values(env):
    keys = {key for values in TEMPLATES.values() for key in values}
    result = {}
    for key in sorted(keys):
        value = env.get(key, "")
        valid = bool(value) and not any(ord(char) < 32 for char in value)
        if valid and key.endswith("_IP"):
            try:
                address = ipaddress.IPv4Address(value)
                valid = not (address.is_unspecified or address.is_multicast)
            except ValueError:
                valid = False
        elif valid and key.endswith("_ID"):
            valid = bool(re.fullmatch(r"[1-9][0-9]*", value))
        elif valid and key == "WATCHER_HOST_LABEL":
            valid = bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", value))
        elif valid and key == "NEXTCLOUD_URL":
            valid = bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*(?::[0-9]+)?", value))
        elif valid and key == "NTFY_BASE_URL":
            parts = urlsplit(value)
            valid = (parts.scheme == "https" and bool(parts.hostname) and not parts.username
                     and not parts.password and not parts.query and not parts.fragment
                     and parts.path in ("", "/"))
        elif valid and key == "NEXTCLOUD_JOURNAL_PATH":
            valid = value.startswith("/")
        if not valid:
            raise ValueError(f"Missing or invalid setting: {key}")
        result[key] = value
    return result


def render(root, env):
    values = checked_values(env)
    rendered = {}
    for name, keys in TEMPLATES.items():
        source = (root / (name + ".example")).read_text()
        replacements = {}
        for key in keys:
            token = "PASTE_TOKEN_SECRET_HERE" if key == "PVE_TOKEN_VALUE" else key
            if token not in source:
                raise ValueError(f"Missing placeholder {key} in {name}.example")
            replacements[token] = json.dumps(values[key], ensure_ascii=False)[1:-1]
        # Single pass: a credential containing another token must not be re-expanded.
        pattern = "|".join(re.escape(token) for token in sorted(replacements, key=len, reverse=True))
        rendered[name] = re.sub(pattern, lambda match: replacements[match.group()], source)
    return rendered


def generate(root, output, env):
    rendered = render(root, env)  # Validate all inputs/templates before any writes.
    for name in rendered:
        if (output / name).is_symlink():
            raise ValueError(f"Refusing symlink output: {name}")
    for name, text in rendered.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        # Keep the inode so running Docker bind mounts still see this file.
        # Reload services only after generation and native validation succeed.
        # PVE exporter has supplementary GID 1000; generator uses UID/GID 1000.
        mode = 0o640 if name == "pve/pve.yml" else 0o644
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(text)
    return tuple(rendered)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        names = generate(args.root, args.output or args.root, os.environ)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error) if isinstance(error, ValueError) else "Configuration generation failed; check file access")
    print(f"Generated {len(names)} local configurations from .example templates (values withheld).")
