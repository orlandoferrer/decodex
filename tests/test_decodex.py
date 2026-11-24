"""Exercise the CLI with real bundle metadata and a mocked tccutil on macOS."""

import os
from pathlib import Path
import plistlib
import pty
import shlex
import shutil
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
        self.applications = self.root / "Applications"
        self.user_home = self.root / "home"
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
        # Isolate automatic discovery from apps installed on the test machine.
        self.assertEqual(source.count('"/Applications"'), 1)
        source = source.replace('"/Applications"', shlex.quote(str(self.applications)))
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
        env["HOME"] = str(self.user_home)
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
        self.assertNotIn("Optional parameters for another run:", result.stdout)
        self.assertEqual(self.resets(), [])

    def test_one_confirmation_resets_all_components_and_services(self):
        result = self.run_script(reply="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Optional parameters for another run:", result.stdout)
        for option in ("--include-main-apps", "--diagnose", "--app PATH", "--main-app PATH", "--help"):
            self.assertIn(option, result.stdout)
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
        for option in ("--app", "--main-app"):
            for suffix in ((), ("",), ("--diagnose",), ("--help",), ("-h",), ("--app",), ("--main-app",), ("--include-main-apps",)):
                with self.subTest(option=option, suffix=suffix):
                    result = self.run_script(option, *suffix, reply=f"{self.app}\ny\n")
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn(f"{option} requires a path", result.stderr)
                    self.assertNotIn("[y/N]", result.stderr)
                    self.assertEqual(self.resets(), [])

    def install_main_apps(self):
        # App names need not resemble their dynamically read bundle IDs.
        chatgpt = self.applications / "ChatGPT.app"
        codex = self.user_home / "Applications" / "Codex.app"
        self.bundle(chatgpt, "com.example.mainchat")
        self.bundle(codex, "com.example.maincode")
        self.bundle(self.applications / "Unrelated.app", "com.example.unrelated")
        self.bundle(chatgpt / "Contents" / "SharedSupport" / "Helper.app", "com.example.mainhelper")
        return chatgpt, codex

    def test_main_apps_and_computer_use_share_one_confirmation(self):
        self.install_main_apps()
        result = self.run_script("--include-main-apps", reply="yes\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("[y/N]"), 1)
        expected_ids = {"com.example.computeruse", "com.example.client", "com.example.worker",
                        "com.example.mainchat", "com.example.maincode"}
        self.assertEqual(set(self.resets()), {
            f"reset {service} {identifier}"
            for service in ("Accessibility", "ScreenCapture", "AppleEvents")
            for identifier in expected_ids
        })
        self.assertEqual(len(self.resets()), 15)

    def test_main_apps_are_listed_in_diagnose_without_resets(self):
        self.install_main_apps()
        result = self.run_script("--diagnose", "--include-main-apps")
        self.assertEqual(result.returncode, 0, result.stderr)
        for identifier in ("com.example.mainchat", "com.example.maincode"):
            self.assertIn(identifier, result.stdout)
        self.assertNotIn("com.example.unrelated", result.stdout)
        self.assertNotIn("com.example.mainhelper", result.stdout)
        self.assertEqual(self.resets(), [])

    def test_cancellation_covers_main_apps_and_computer_use(self):
        self.install_main_apps()
        result = self.run_script("--include-main-apps", reply="\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("com.example.mainchat", result.stdout)
        self.assertEqual(result.stderr.count("[y/N]"), 1)
        self.assertEqual(self.resets(), [])

    def test_main_apps_work_without_computer_use(self):
        self.install_main_apps()
        shutil.rmtree(self.app)
        result = self.run_script("--include-main-apps", reply="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Computer Use not found", result.stderr)
        self.assertEqual(len(self.resets()), 6)
        self.assertEqual({line.split()[2] for line in self.resets()},
                         {"com.example.mainchat", "com.example.maincode"})

    def test_missing_all_installations_fails_without_prompt(self):
        shutil.rmtree(self.app)
        result = self.run_script(reply="y\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("No bundle identifiers found", result.stderr)
        self.assertNotIn("[y/N]", result.stderr)
        self.assertEqual(self.resets(), [])

    def test_custom_main_paths_and_cross_installation_ids_are_deduplicated(self):
        chatgpt, _ = self.install_main_apps()
        custom = self.root / "Custom Main.app"
        self.bundle(custom, "com.example.client")  # Already in Computer Use.
        other = self.root / "Renamed.app"
        self.bundle(other, "com.example.custom")
        result = self.run_script("--main-app", str(chatgpt) + "/.",
                                 "--main-app", str(custom), "--main-app", str(other), reply="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.resets()), 18)
        self.assertEqual(len(set(self.resets())), 18)
        self.assertIn("reset AppleEvents com.example.custom", self.resets())

    def test_explicit_missing_paths_fail_even_when_other_apps_exist(self):
        self.install_main_apps()
        for option in ("--app", "--main-app"):
            with self.subTest(option=option):
                result = self.run_script(option, str(self.root / "Missing.app"), reply="y\n")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Not an application bundle", result.stderr)
                self.assertNotIn("[y/N]", result.stderr)
                self.assertEqual(self.resets(), [])

    def test_default_reset_excludes_installed_main_apps(self):
        self.install_main_apps()
        result = self.run_script(reply="y\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.resets()), 9)
        self.assertEqual({line.split()[2] for line in self.resets()},
                         {"com.example.computeruse", "com.example.client", "com.example.worker"})
        self.assertNotIn("com.example.mainchat", result.stdout)
        self.assertNotIn("com.example.maincode", result.stdout)
        self.assertEqual(result.stderr.count("[y/N]"), 1)

    def test_default_diagnose_excludes_installed_main_apps(self):
        self.install_main_apps()
        result = self.run_script("--diagnose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("com.example.mainchat", result.stdout)
        self.assertNotIn("com.example.maincode", result.stdout)
        self.assertEqual(self.resets(), [])

    def test_default_does_not_fall_back_to_main_apps_without_computer_use(self):
        self.install_main_apps()
        shutil.rmtree(self.app)
        result = self.run_script(reply="y\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("[y/N]", result.stderr)
        self.assertNotIn("com.example.mainchat", result.stdout)
        self.assertEqual(self.resets(), [])


if __name__ == "__main__":
    unittest.main()
