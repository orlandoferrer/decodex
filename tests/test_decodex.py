"""Exercise the CLI with real bundle metadata and a mocked tccutil on macOS."""

import os
from pathlib import Path
import plistlib
import pty
import shlex
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "darwin" and os.geteuid() != 0,
                     "requires macOS and a non-root user")
class DecodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="decodex tests ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "codex home" / "computer-use" / "Codex Computer Use.app"
        self.bundle(self.app, "com.example.computeruse")
        helpers = self.app / "Contents" / "SharedSupport"
        self.bundle(helpers / "Client.app", "com.example.client")
        self.bundle(helpers / "Worker.xpc", "com.example.worker")
        self.bundle(helpers / "Duplicate.app", "com.example.client")
        self.bundle(helpers / "Invalid.app", "invalid id")
        (helpers / "Missing.app").mkdir()
        self.log = self.root / "resets.log"
        mock = self.root / "mock-tccutil"
        mock.write_text(
            '#!/bin/bash\n'
            'printf "%s %s %s\\n" "$1" "$2" "$3" >> "$RESET_LOG"\n'
            'if [ "${FAIL_SERVICE:-}" = "$2" ]; then exit 1; fi\n'
        )
        mock.chmod(0o755)
        source = (Path(__file__).resolve().parents[1] / "decodex.sh").read_text()
        # Only the temporary test copy can call the mock. Never run the source
        # script's actual reset command during tests.
        self.assertEqual(source.count("/usr/bin/tccutil"), 1)
        self.script = self.root / "decodex.sh"
        self.script.write_text(source.replace("/usr/bin/tccutil", shlex.quote(str(mock))))

    @staticmethod
    def bundle(path, identifier):
        contents = path / "Contents"
        contents.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump({"CFBundleIdentifier": identifier}, stream)

    def run_script(self, *args, reply=None, fail_service="", cwd=None):
        env = dict(os.environ, RESET_LOG=str(self.log), FAIL_SERVICE=fail_service)
        # Exercise the default CODEX_HOME discovery path as well as --app.
        env["CODEX_HOME"] = str(self.root / "codex home")
        command = ["/bin/bash", str(self.script), *args]
        if reply is None:
            return subprocess.run(command, env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=10)
        master, slave = pty.openpty()
        try:
            with subprocess.Popen(command, env=env, cwd=cwd, stdin=slave,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True) as proc:
                os.write(master, reply.encode())
                try:
                    stdout, stderr = proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    raise
                return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
        finally:
            os.close(master)
            os.close(slave)

    def resets(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_diagnose_lists_unique_valid_components_without_resets(self):
        result = self.run_script("--diagnose", "--app", str(self.app))
        self.assertEqual(result.returncode, 0, result.stderr)
        for identifier in ("com.example.computeruse", "com.example.client", "com.example.worker"):
            self.assertEqual(result.stdout.count(identifier), 1)
        self.assertNotIn("invalid id", result.stdout)
        self.assertIn("AppleEvents (Automation)", result.stdout)
        self.assertEqual(self.resets(), [])

    def test_one_confirmation_resets_all_components_and_services(self):
        result = self.run_script(reply="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {
            f"reset {service} {identifier}"
            for service in ("Accessibility", "ScreenCapture", "AppleEvents")
            for identifier in ("com.example.computeruse", "com.example.client", "com.example.worker")
        }
        self.assertEqual(set(self.resets()), expected)
        self.assertEqual(len(self.resets()), 9)
        self.assertEqual(result.stderr.count("[y/N]"), 1)
        self.assertNotIn("Select identity", result.stdout + result.stderr)

    def test_decline_or_empty_confirmation_cancels(self):
        for reply in ("n\n", "\n"):
            with self.subTest(reply=reply):
                result = self.run_script("--app", str(self.app), reply=reply)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Cancelled.", result.stdout)
                self.assertEqual(self.resets(), [])

    def test_noninteractive_reset_is_rejected(self):
        result = self.run_script("--app", str(self.app))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Interactive terminal required", result.stderr)
        self.assertEqual(self.resets(), [])

    def test_failures_are_reported_and_remaining_resets_continue(self):
        result = self.run_script("--app", str(self.app), reply="yes\n",
                                 fail_service="AppleEvents")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.resets()), 9)
        self.assertIn("3 reset(s) failed", result.stderr)

    def test_removed_automation_flag_is_rejected(self):
        result = self.run_script("--automation")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown option: --automation", result.stderr)
        self.assertEqual(self.resets(), [])

    def test_no_valid_identities_fails_without_reset(self):
        empty = self.root / "Empty.app"
        self.bundle(empty, "invalid id")
        result = self.run_script("--app", str(empty), reply="y\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("No bundle identifiers found", result.stderr)
        self.assertEqual(self.resets(), [])

    def test_traversal_failure_stops_before_confirmation_or_resets(self):
        helpers = self.app / "Contents" / "SharedSupport"
        self.addCleanup(helpers.chmod, 0o755)
        helpers.chmod(0)
        result = self.run_script(reply="y\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not completely discover", result.stderr)
        self.assertNotIn("[y/N]", result.stderr)
        self.assertNotIn("Discovered identities", result.stdout)
        self.assertEqual(self.resets(), [])

    def test_equivalent_app_paths_reset_the_same_complete_target_set(self):
        linked = self.root / "Linked.app"
        linked.symlink_to(self.app, target_is_directory=True)
        expected = {
            f"reset {service} {identifier}"
            for service in ("Accessibility", "ScreenCapture", "AppleEvents")
            for identifier in ("com.example.computeruse", "com.example.client", "com.example.worker")
        }
        for path in (str(self.app), str(self.app) + "/.", ".", str(linked)):
            with self.subTest(path=path):
                if self.log.exists():
                    self.log.unlink()
                result = self.run_script("--app", path, reply="y\n", cwd=self.app)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(set(self.resets()), expected)
                self.assertEqual(len(self.resets()), 9)

    def test_nested_symlinks_do_not_expand_discovery_scope(self):
        outside = self.root / "Unrelated.app"
        self.bundle(outside, "com.example.unrelated")
        link = self.app / "Contents" / "SharedSupport" / "Linked.app"
        link.symlink_to(outside, target_is_directory=True)
        result = self.run_script("--diagnose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("com.example.unrelated", result.stdout)
        self.assertEqual(self.resets(), [])

    def test_missing_app_value_is_rejected_before_any_prompt(self):
        for suffix in ((), ("",), ("--diagnose",), ("--help",), ("-h",), ("--app",)):
            with self.subTest(suffix=suffix):
                # These replies would allow the old parser's fallback/reset flow.
                result = self.run_script("--app", *suffix, reply=f"{self.app}\ny\n")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("--app requires a path", result.stderr)
                self.assertNotIn("Enter the full path", result.stderr)
                self.assertNotIn("[y/N]", result.stderr)
                self.assertEqual(self.resets(), [])


if __name__ == "__main__":
    unittest.main()
