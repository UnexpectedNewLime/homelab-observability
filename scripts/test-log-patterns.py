"""Test OOM and backup matchers in isolated synthetic Loki streams."""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:3100"
now = time.time_ns()
streams = [
    {"stream": {"host": "homelab-acceptance", "service": "kernel", "sample": "oom"}, "values": [[str(now), "Out of memory: Killed process 123 (acceptance-test)"]]},
    {"stream": {"host": "homelab-acceptance", "service": "pve-tasks", "sample": "failed"}, "values": [[str(now), "UPID:proxmox:00000001:00000001:00000001:vzdump:100:root@pam: 00000001 ERROR: synthetic backup failure"]]},
    {"stream": {"host": "homelab-acceptance", "service": "pve-tasks", "sample": "ok"}, "values": [[str(now), "UPID:proxmox:00000001:00000001:00000001:vzdump:100:root@pam: 00000001 OK"]]},
    {"stream": {"host": "homelab-acceptance", "service": "pve-tasks", "sample": "unrelated"}, "values": [[str(now), "UPID:proxmox:00000001:00000001:00000001:aptupdate::root@pam: 00000001 ERROR: unrelated task"]]},
]
request = urllib.request.Request(BASE + "/loki/api/v1/push", data=json.dumps({"streams": streams}).encode(), headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request, timeout=10) as response:
    assert response.status == 204
queries = [
    ('sum by(sample) (count_over_time({host="homelab-acceptance",service="kernel"} |~ "(?i)(out of memory: killed process|memory cgroup out of memory: killed process|oom-kill:)" [5m])) > 0', {"oom"}),
    ('sum by(sample) (count_over_time({host="homelab-acceptance",service="pve-tasks"} |= ":vzdump:" !~ " OK$" [15m])) > 0', {"failed"}),
]
for query, expected in queries:
    url = BASE + "/loki/api/v1/query?" + urllib.parse.urlencode({"query": query})
    with urllib.request.urlopen(url, timeout=30) as response:
        results = json.load(response)["data"]["result"]
    actual = {result["metric"]["sample"] for result in results}
    if actual != expected:
        raise SystemExit(f"FAIL: expected {expected}, got {actual}")
    print(f"PASS: matcher selected only {sorted(actual)}")
