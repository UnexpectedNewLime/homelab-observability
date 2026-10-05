"""Validate synthetic rendered configs in isolated containers; never touch live state."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from fixtures import VALUES

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("generator", ROOT / "scripts/generate-config.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

PROM = "prom/prometheus@sha256:508729e0e2d18e11fd742a5a5ca70e557b940a93948c3c95fd0123a6fd538b69"
AM = "prom/alertmanager@sha256:9e082985f56f4c8c9f724e18f2288c6708f472e56a5286b8863d080434ea065d"
LOKI = "grafana/loki@sha256:1107dd5274e0ada47e42472b7a7e71f3b2a2fe878878108f3e2f9e51528f0193"
ALLOY = "grafana/alloy@sha256:2aa2099af76c0098d4af7a4d6e48f86cb66dc1a000222ad927a1c67c6542d13f"
NGINX = "nginx@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94"


def run(*command, **kwargs):
    subprocess.run(command, check=True, timeout=180, **kwargs)


with tempfile.TemporaryDirectory(prefix="observability-tests-") as directory:
    scratch = Path(directory)
    scratch.chmod(0o755)  # Native validators run as unprivileged container users.
    generator.generate(ROOT, scratch, VALUES)
    for name in ("tests/prometheus-rules.yml", "alertmanager/alertmanager.yml", "loki/config.yml",
                 "loki/rules/fake/homelab.yml", "docker-compose.yml"):
        target = scratch / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    (scratch / ".env").write_text("".join(f"{key}={value}\n" for key, value in VALUES.items()))
    # Check local paths inside this disposable test tree, not /etc on the host.
    config = scratch / "prometheus/prometheus.yml"
    config.write_text(config.read_text().replace("/etc/prometheus/rules/", "/work/prometheus/rules/"))

    def tool(image, entrypoint, *args, mounts=(), extra=()):
        run("docker", "run", "--rm", "--network", "none", "--read-only",
            "--tmpfs", "/tmp", "-v", f"{scratch}:/work:ro", "-w", "/work",
            *mounts, *extra, "--entrypoint", entrypoint, image, *args)

    # Ignore caller-provided Compose variables; these tests use only fake .env values.
    env = {key: value for key, value in os.environ.items()
           if key not in VALUES and not key.startswith("COMPOSE_")}
    run("docker", "compose", "--project-directory", directory, "--env-file", str(scratch / ".env"),
        "-f", str(scratch / "docker-compose.yml"), "config", "--quiet", env=env)
    tool(PROM, "/bin/promtool", "check", "config", "/work/prometheus/prometheus.yml")
    tool(PROM, "/bin/promtool", "test", "rules", "/work/tests/prometheus-rules.yml")
    tool(AM, "/bin/amtool", "check-config", "/work/alertmanager/alertmanager.yml")
    for labels, receivers in ((["severity=critical"], "alert-dump,ntfy-critical"),
                              (["severity=warning"], "alert-dump,ntfy-warning"),
                              (["severity=unknown"], "alert-dump,ntfy-warning"),
                              (["alertname=NoSeverityTest"], "alert-dump,ntfy-warning")):
        tool(AM, "/bin/amtool", "config", "routes", "test",
             "--config.file=/work/alertmanager/alertmanager.yml",
             "--verify.receivers=" + receivers, *labels)
    tool(LOKI, "/usr/bin/loki", "-config.file=/work/loki/config.yml", "-verify-config=true",
         mounts=("-v", f"{scratch}/loki/rules:/etc/loki/rules:ro"))
    for config in ("alloy/config.alloy", "proxmox/config.alloy"):
        tool(ALLOY, "/bin/alloy", "validate", "--stability.level=experimental", "/work/" + config)
    tool(NGINX, "nginx", "-t", mounts=("-v", f"{scratch}/loki/ingress.conf:/etc/nginx/conf.d/default.conf:ro"),
         extra=("--add-host", "loki:127.0.0.1", "--tmpfs", "/var/cache/nginx", "--tmpfs", "/var/run"))
    print("PASS: isolated config validation, rule behaviour and four routing cases")
