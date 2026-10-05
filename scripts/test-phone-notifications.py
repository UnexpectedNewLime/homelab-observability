"""Send one labelled test to each ntfy topic through Alertmanager."""
import datetime
import importlib.util
import json
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location("verify_alerting", Path(__file__).with_name("verify-alerting.py"))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
request, wait_for = helper.request, helper.wait_for

started = int(time.time())
ends = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=45)
alerts = []
for severity in ("critical", "warning"):
    alerts.append({
        "labels": {"alertname": f"HomelabPhone{severity.title()}Test", "severity": severity,
                   "service": "phone-acceptance-test", "instance": f"test-{started}"},
        "annotations": {"summary": f"Phone test: {severity} homelab notifications are working",
                        "description": "Synthetic commissioning test. No production service is failing."},
        "endsAt": ends.isoformat(),
    })
request("http://127.0.0.1:9093/api/v2/alerts", data=json.dumps(alerts).encode())
for severity in ("Critical", "Warning"):
    wait_for(f"[FIRING] HomelabPhone{severity}Test", started, 40)
print(f"Both tests expire automatically; recovery messages follow at the next 5-minute group interval. Test start: {started}")
