"""Translate grouped Alertmanager webhooks; failed delivery returns 502 for retry."""
import base64
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = os.environ.get("NTFY_BASE", "http://ntfy:80").rstrip("/")
USER = os.environ.get("NTFY_USER", "alert-publisher")
PASSWORD_FILE = os.environ.get("NTFY_PASSWORD_FILE", "/run/secrets/ntfy-publisher")
TOPICS = {"critical": "homelab-critical", "warning": "homelab-warning"}
COUNTERS = {"requests": 0, "published": 0, "failures": 0}
LOCK = threading.Lock()


def messages(payload):
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        raise ValueError("alerts must be a nonempty list")
    groups = {}
    for alert in alerts:
        if not isinstance(alert, dict):
            raise ValueError("invalid alert")
        labels, annotations = alert.get("labels", {}), alert.get("annotations", {})
        if not isinstance(labels, dict) or not isinstance(annotations, dict):
            raise ValueError("invalid labels or annotations")
        status = alert.get("status", payload.get("status", "firing"))
        if status not in ("firing", "resolved"):
            raise ValueError("invalid status")
        severity = labels.get("severity", "warning")
        if severity not in TOPICS:
            severity = "warning"
        groups.setdefault(severity, []).append((status, labels, annotations))
    result = []
    for severity, group in groups.items():
        firing = sum(status == "firing" for status, _, _ in group)
        state = "FIRING" if firing else "RESOLVED"
        names = sorted({str(labels.get("alertname", "Homelab alert")) for _, labels, _ in group})
        lines = []
        for status, labels, annotations in group:
            summary = annotations.get("summary", labels.get("alertname", "Homelab alert"))
            target = ", ".join(f"{key}={labels[key]}" for key in ("instance", "host", "ct", "vm", "service") if key in labels)
            detail = annotations.get("description", "")
            hint = annotations.get("runbook_hint", annotations.get("runbook", ""))
            lines.append("\n".join(str(x) for x in (f"[{status.upper()}] {summary}", target, detail, hint) if x))
        body = "\n\n".join(lines)
        # ntfy's default message limit is 4096 bytes; retain room for a truncation note.
        raw = body.encode("utf-8")
        if len(raw) > 3800:
            body = raw[:3700].decode("utf-8", errors="ignore") + "\n[More details in Alertmanager]"
        result.append({
            "topic": TOPICS[severity],
            "title": f"[{state}] {', '.join(names)}"[:180],
            "message": body,
            "priority": (5 if severity == "critical" else 3) if firing else 2,
            "tags": ["rotating_light" if firing else "white_check_mark"],
        })
    return result


def publish(message):
    password = Path(PASSWORD_FILE).read_text().strip()
    auth = base64.b64encode(f"{USER}:{password}".encode()).decode()
    req = urllib.request.Request(BASE, data=json.dumps(message).encode(), headers={
        "Content-Type": "application/json", "Authorization": "Basic " + auth,
    }, method="POST")
    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status != 200:
            raise OSError("ntfy rejected notification")


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, fmt, *args):
        # Never log request payloads, headers or credentials.
        print(fmt % args, flush=True)

    def reply(self, status, body, content_type="text/plain; charset=utf-8"):
        body = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(200, "ok\n")
        if self.path == "/metrics":
            with LOCK:
                body = "".join(f"# TYPE ntfy_bridge_{name}_total counter\nntfy_bridge_{name}_total {value}\n" for name, value in COUNTERS.items())
            return self.reply(200, body)
        self.reply(404, "not found\n")

    def do_POST(self):
        if self.path != "/alertmanager":
            return self.reply(404, "not found\n")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 262144:
                return self.reply(413, "invalid request size\n")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("invalid payload")
            outgoing = messages(payload)
        except (ValueError, TypeError):
            return self.reply(400, "invalid Alertmanager payload\n")
        with LOCK:
            COUNTERS["requests"] += 1
        try:
            for message in outgoing:
                publish(message)
                with LOCK:
                    COUNTERS["published"] += 1
        except (OSError, urllib.error.URLError):
            with LOCK:
                COUNTERS["failures"] += 1
            return self.reply(502, "notification delivery failed; retry\n")
        self.reply(200, "delivered\n")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
