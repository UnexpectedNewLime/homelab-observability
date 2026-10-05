"""Check receiver permissions and verify Alertmanager delivery using local credentials."""
import argparse
import base64
import datetime
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

DIRECTORY = Path(os.environ.get("NTFY_CREDENTIALS_DIR", Path.home() / ".config/homelab-alerting"))


def auth(user):
    filename = "ntfy-phone.secret" if user == "phone" else "ntfy-publisher.secret"
    password = (DIRECTORY / filename).read_text().strip()
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def request(url, *, user=None, data=None):
    headers = {"Content-Type": "application/json"}
    if user:
        headers["Authorization"] = auth(user)
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as result:
        return result.read()


def cached(topic, since):
    raw = request(f"http://127.0.0.1:8090/{topic}/json?poll=1&since={int(since)}", user="phone")
    return [json.loads(line) for line in raw.splitlines() if line]


def wait_for(title, since, timeout):
    for _ in range(timeout // 2):
        for topic in ("homelab-critical", "homelab-warning"):
            for message in cached(topic, since):
                if title in message.get("title", ""):
                    print(json.dumps({k: message.get(k) for k in ("topic", "title", "priority", "time")}))
                    print(f"Delivery delay from test start: {message['time'] - int(since)} seconds")
                    return
        time.sleep(2)
    raise SystemExit(f"No matching notification within {timeout}s: {title}")


def check():
    checks = [
        ("anonymous subscription", None, "/homelab-critical/json?poll=1", None),
        ("phone publishing", "phone", "/homelab-critical", b"must be rejected"),
        ("publisher subscription", "alert-publisher", "/homelab-critical/json?poll=1", None),
    ]
    for label, user, path, data in checks:
        try:
            request("http://127.0.0.1:8090" + path, user=user, data=data)
        except urllib.error.HTTPError as error:
            if error.code not in (401, 403):
                raise
            print(f"PASS: {label} rejected ({error.code})")
        else:
            raise SystemExit(f"FAIL: {label} was allowed")
    since = int(time.time())
    ends = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=2)
    data = [{"labels": {"alertname": "HomelabNotificationTest", "severity": "warning", "service": "acceptance-test"},
             "annotations": {"summary": "Test: Alertmanager to ntfy delivery is working"},
             "endsAt": ends.isoformat()}]
    request("http://127.0.0.1:9093/api/v2/alerts", data=json.dumps(data).encode())
    wait_for("[FIRING] HomelabNotificationTest", since, 40)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check", "wait", "list"))
    parser.add_argument("--title", default="[FIRING] ServiceDown")
    parser.add_argument("--since", type=int, default=int(time.time()))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    if args.mode == "check":
        check()
    elif args.mode == "wait":
        wait_for(args.title, args.since, args.timeout)
    else:
        for topic in ("homelab-critical", "homelab-warning"):
            for msg in cached(topic, args.since):
                print(json.dumps({k: msg.get(k) for k in ("topic", "title", "priority", "time")}))
