"""Provisioning regressions use a fake ntfy CLI and disposable credentials only."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_repository import module

provisioning = module("provisioning", "provision-ntfy-users.py")


class FakeNtfy:
    def __init__(self):
        self.users = {}
        self.grants = {}
        self.fail = None
        self.calls = []
        self.fail_after_add = False

    def run(self, command, **kwargs):
        args = tuple(command[command.index("ntfy") + 2:])
        self.calls.append(args)
        password = kwargs["env"].get("NTFY_PASSWORD")
        assert "NTFY_PASSWORD_HASH" not in kwargs["env"]
        assert not password or password not in command
        assert kwargs["capture_output"] and kwargs["check"]
        if args == self.fail and not self.fail_after_add:
            raise subprocess.CalledProcessError(1, command)
        if args == ("user", "list"):
            output = "".join(f"user {user} (role: user, tier: none)\n" for user in self.users)
        elif args[:2] == ("user", "add"):
            user = args[2]
            if user in self.users:
                raise subprocess.CalledProcessError(1, command)
            self.users[user] = password
            output = ""
            if args == self.fail:
                raise subprocess.CalledProcessError(1, command)
        elif args[0] == "access":
            _, user, topic, permission = args
            assert user in self.users
            self.grants[user, topic] = permission
            output = ""
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")


class ProvisioningTests(unittest.TestCase):
    def test_retries_every_user_and_acl_failure_without_rotating_passwords(self):
        failures = [("user", "add", user) for user, _, _ in provisioning.ACCOUNTS]
        failures += [("access", user, topic, permission)
                     for user, _, permission in provisioning.ACCOUNTS
                     for topic in provisioning.TOPICS]
        for failure in failures:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                fake = FakeNtfy()
                fake.fail = failure
                root = Path(directory)
                with patch.object(provisioning.subprocess, "run", side_effect=fake.run):
                    with self.assertRaises(subprocess.CalledProcessError):
                        provisioning.provision(root)
                    saved = {p.name: (p.read_bytes(), p.stat().st_ino) for p in root.iterdir()}
                    fake.fail = None
                    provisioning.provision(root)
                    provisioning.provision(root)
                for filename, (content, inode) in saved.items():
                    self.assertEqual((root / filename).read_bytes(), content)
                    self.assertEqual((root / filename).stat().st_ino, inode)
                self.assertEqual(len(fake.users), 2)
                for user, filename, permission in provisioning.ACCOUNTS:
                    self.assertEqual((root / filename).read_text().strip(), fake.users[user])
                    self.assertEqual((root / filename).stat().st_mode & 0o777, 0o600)
                    for topic in provisioning.TOPICS:
                        self.assertEqual(fake.grants[user, topic], permission)

    def test_retry_after_user_created_but_command_reports_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeNtfy()
            fake.fail = ("user", "add", "alert-publisher")
            fake.fail_after_add = True
            with patch.object(provisioning.subprocess, "run", side_effect=fake.run):
                with self.assertRaises(subprocess.CalledProcessError):
                    provisioning.provision(directory)
                original = fake.users["alert-publisher"]
                fake.fail = None
                provisioning.provision(directory)
            self.assertEqual(fake.users["alert-publisher"], original)
            self.assertEqual(fake.calls.count(("user", "add", "alert-publisher")), 1)
            self.assertEqual(len(fake.grants), 4)

    def test_unavailable_service_does_not_create_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(provisioning.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["docker"])):
                with self.assertRaises(subprocess.CalledProcessError):
                    provisioning.provision(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_existing_user_without_secret_aborts_before_first_account_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeNtfy()
            fake.users["phone"] = "synthetic-saved-password"
            with patch.object(provisioning.subprocess, "run", side_effect=fake.run):
                with self.assertRaisesRegex(ValueError, "no saved credential"):
                    provisioning.provision(directory)
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertEqual(fake.calls, [("user", "list")])

    def test_invalid_second_file_is_rejected_before_mutations(self):
        for kind in ("empty", "symlink", "public"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "ntfy-phone.secret"
                if kind == "symlink":
                    path.symlink_to(root / "missing")
                else:
                    path.write_text("" if kind == "empty" else "synthetic-password\n")
                    path.chmod(0o600 if kind == "empty" else 0o644)
                with patch.object(provisioning.subprocess, "run") as run:
                    with self.assertRaises(ValueError):
                        provisioning.provision(root)
                    run.assert_not_called()
                self.assertFalse((root / "ntfy-publisher.secret").exists())

    def test_caller_credentials_do_not_override_saved_password(self):
        with patch.dict(os.environ, {"NTFY_PASSWORD": "wrong", "NTFY_PASSWORD_HASH": "wrong-hash"}):
            with patch.object(provisioning.subprocess, "run") as run:
                provisioning.ntfy("user", "add", "phone", password="synthetic-saved")
                self.assertEqual(run.call_args.kwargs["env"]["NTFY_PASSWORD"], "synthetic-saved")
                self.assertNotIn("NTFY_PASSWORD_HASH", run.call_args.kwargs["env"])
                self.assertNotIn("synthetic-saved", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
