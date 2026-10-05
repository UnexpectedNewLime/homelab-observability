import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from fixtures import VALUES

ROOT = Path(__file__).resolve().parent.parent


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


generator = module("generator", "generate-config.py")
safety = module("safety", "check-repo-safety.py")


class GeneratorTests(unittest.TestCase):
    def test_all_templates_render_without_changing_go_templates(self):
        rendered = generator.render(ROOT, VALUES)
        self.assertEqual(len(rendered), 8)
        self.assertIn('{{ $labels.name }}', rendered["prometheus/rules/logging-alerts.yml"])
        self.assertIn('lxc/901', rendered["prometheus/rules/homelab.yml"])
        self.assertNotIn("lxc/101", rendered["prometheus/rules/homelab.yml"])
        self.assertIn("allow " + VALUES["PROXMOX_IP"], rendered["loki/ingress.conf"])

    def test_credentials_are_escaped_without_recursive_expansion(self):
        value = 'synthetic&|"\\MONITORING_IP'
        rendered = generator.render(ROOT, {**VALUES, "PVE_TOKEN_VALUE": value})
        line = next(line for line in rendered["pve/pve.yml"].splitlines() if "token_value:" in line)
        self.assertEqual(json.loads(line.split(":", 1)[1]), value)

    def test_missing_input_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            values = {key: value for key, value in VALUES.items() if key != "NTFY_BASE_URL"}
            with self.assertRaisesRegex(ValueError, "NTFY_BASE_URL"):
                generator.generate(ROOT, Path(directory), values)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_rejects_injection_without_echoing_value(self):
        for key, value in (("PROXMOX_IP", "bad; allow all"),
                           ("NEXTCLOUD_CT_ID", "1|.*"),
                           ("WATCHER_HOST_LABEL", 'bad"label'),
                           ("NTFY_BASE_URL", "http://alerts.example.invalid"),
                           ("PVE_TOKEN_VALUE", "sensitive\nextra")):
            with self.subTest(key=key), self.assertRaises(ValueError) as error:
                generator.render(ROOT, {**VALUES, key: value})
            self.assertNotIn(value, str(error.exception))

    def test_generation_preserves_inode_and_restricts_token_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            generator.generate(ROOT, output, VALUES)
            config = output / "pve/pve.yml"
            inode = config.stat().st_ino
            generator.generate(ROOT, output, VALUES)
            self.assertEqual(config.stat().st_ino, inode)
            self.assertEqual(config.stat().st_mode & 0o777, 0o640)

    def test_symlink_output_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "ntfy").mkdir()
            (output / "ntfy/server.yml").symlink_to(output / "victim")
            with self.assertRaises(ValueError):
                generator.generate(ROOT, output, VALUES)
            self.assertFalse((output / "prometheus/prometheus.yml").exists())


class SafetyTests(unittest.TestCase):
    def test_real_addresses_are_rejected_without_printing_them(self):
        address = ".".join(("192", "168", "7", "8"))
        errors = safety.findings("config.yml", address.encode())
        self.assertTrue(errors)
        self.assertNotIn(address, str(errors))
        self.assertTrue(safety.findings("config.yml", ":".join(("fd12", "3456", "", "1")).encode()))

    def test_safe_test_addresses_and_loopback_are_allowed(self):
        for value in (VALUES["PROXMOX_IP"], "127.0.0.1", "0.0.0.0", "::1", "2001:db8::1"):
            self.assertEqual(safety.findings("test.py", value.encode()), [])

    def test_domain_keys_and_credentials_are_rejected(self):
        for value in ("private.tail1234." + "ts.net", "tskey-auth-" + "x" * 30,
                      "ghp_" + "x" * 40, "-----BEGIN " + "PRIVATE KEY-----",
                      "https://" + "user:password@example.invalid"):
            self.assertTrue(safety.findings("test.txt", value.encode()))

    def test_secret_paths_and_filled_env_examples_are_rejected(self):
        for name in (".env", ".env.production", "ntfy/server.yml", "credentials/password", "auth.db", "phone.secret"):
            self.assertTrue(safety.findings(name, b""))
        self.assertTrue(safety.findings(".env.example", b"PVE_TOKEN_VALUE=not-empty"))
        self.assertEqual(safety.findings(".env.example", b"PVE_TOKEN_VALUE=\n"), [])

    def test_guard_catches_bad_staged_content_even_after_worktree_is_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            file = root / "config.txt"
            file.write_text("private.tail1234." + "ts.net")
            subprocess.run(["git", "-C", directory, "add", "config.txt"], check=True)
            file.write_text("safe now")
            self.assertTrue(any("[index]" in item for item in safety.audit(root)))

    def test_generated_files_and_state_are_ignored_but_templates_are_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            (root / ".gitignore").write_bytes((ROOT / ".gitignore").read_bytes())
            for name in sorted(safety.PRIVATE_PATHS | {".env.production", "auth.db", "ntfy-data/cache.db", "backups/file"}):
                result = subprocess.run(["git", "-C", directory, "check-ignore", "-q", name])
                self.assertEqual(result.returncode, 0, name)
            for name in [".env.example", "LOGGING-ALERTING-RUNBOOK.md.example"] + [name + ".example" for name in generator.TEMPLATES]:
                result = subprocess.run(["git", "-C", directory, "check-ignore", "-q", name])
                self.assertEqual(result.returncode, 1, name)


if __name__ == "__main__":
    unittest.main()
