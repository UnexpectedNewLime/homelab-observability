import json
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import app


def alert(severity="critical", status="firing"):
    return {"status": status, "labels": {"alertname": "ServiceDown", "severity": severity, "ct": "host"},
            "annotations": {"summary": "Service stopped", "runbook_hint": "Inspect the journal"}}


class BridgeTests(unittest.TestCase):
    def test_warning_priority_and_missing_severity_fallback(self):
        self.assertEqual(app.messages({"alerts": [alert("warning")]})[0]["priority"], 3)
        item = alert()
        del item["labels"]["severity"]
        self.assertEqual(app.messages({"alerts": [item]})[0]["topic"], "homelab-warning")

    def test_mixed_firing_and_resolved_remains_urgent(self):
        result = app.messages({"alerts": [alert(), alert(status="resolved")]})[0]
        self.assertEqual(result["priority"], 5)
        self.assertTrue(result["title"].startswith("[FIRING]"))
        self.assertIn("[RESOLVED]", result["message"])

    def test_invalid_alerts_are_rejected(self):
        for payload in ({}, {"alerts": []}, {"alerts": [None]},
                        {"alerts": [{"labels": []}]},
                        {"alerts": [{"status": "unknown"}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                app.messages(payload)

    def test_grouping_and_recovery_priority(self):
        result = app.messages({"alerts": [alert(), alert(), alert("warning", "resolved")]})
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["priority"], 5)
        self.assertEqual(result[1]["priority"], 2)
        self.assertEqual(result[1]["topic"], "homelab-warning")
        self.assertIn("Inspect the journal", result[0]["message"])

    def test_unknown_severity_still_notifies(self):
        self.assertEqual(app.messages({"alerts": [alert("unexpected")]})[0]["topic"], "homelab-warning")

    def test_unicode_message_fits_ntfy_limit(self):
        value = alert()
        value["annotations"]["summary"] = "🚨" * 3000
        result = app.messages({"alerts": [value]})[0]
        self.assertLess(len(result["message"].encode()), 4096)

    def test_delivery_failure_is_retryable_http_error(self):
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/alertmanager",
                data=json.dumps({"alerts": [alert()]}).encode(), method="POST")
            with patch.object(app, "publish", side_effect=OSError("upstream unavailable")):
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(request, timeout=5)
                self.assertEqual(failure.exception.code, 502)
                failure.exception.close()
            with patch.object(app, "publish") as publish:
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                publish.assert_called_once()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_http_rejects_malformed_and_oversized_requests_without_publishing(self):
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(app, "publish") as publish:
                for body, expected in ((b"not-json", 400), (b"[]", 400),
                                       (b"{}", 400), (b"x" * 262145, 413)):
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{server.server_port}/alertmanager",
                        data=body, method="POST")
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(request, timeout=5)
                    self.assertEqual(error.exception.code, expected)
                    error.exception.close()
                publish.assert_not_called()
            for path, expected in (("/healthz", b"ok"), ("/metrics", b"ntfy_bridge_failures_total")):
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=5) as response:
                    self.assertIn(expected, response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
