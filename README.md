# decodex

A Bash script for removing stored macOS permission decisions for Codex Computer Use. Run it after a Computer Use session to make macOS forget the discovered bundles' authorizations.

This is an early version. Discovery and the interaction flow still need refinement.

## Requirements

- macOS, with its included Bash 3.2 and command-line tools.
- An installed Codex Computer Use runtime.
- Run as your normal logged-in user, without `sudo`.

No additional packages are required.

## Usage

Clone this repository, enter its directory, and run:

```bash
bash decodex.sh
```

The script looks for `Codex Computer Use.app` under `${CODEX_HOME:-$HOME/.codex}/computer-use/`, reads bundle IDs from the application and its nested `.app` and `.xpc` bundles, and displays the unique identities and their paths. It automatically targets all discovered identities; no bundle selection is needed.

It asks for one confirmation before resetting all three services for every listed identity:

- Accessibility (`Accessibility`)
- Screen Recording (`ScreenCapture`)
- Automation (`AppleEvents`)

Enter `y` or `yes` to proceed, or press Enter to cancel. Automation is always included; the former `--automation` flag has been removed. Reset mode requires an interactive terminal.

List discovered identities without changing permissions:

```bash
bash decodex.sh --diagnose
```

Supply a different installation path:

```bash
bash decodex.sh --app "/path/to/Codex Computer Use.app"
```

Relative paths, paths ending in `/.`, and symlinks to the root application are resolved before discovery. Nested symlinks are not followed. If directory traversal fails, the script stops before confirmation and resets nothing.

Run `bash decodex.sh --help` for all options.

## What resetting means

The script uses macOS `tccutil reset` with a specific service and bundle ID. It forgets stored allow **and deny** decisions. It does not grant access, explicitly toggle System Settings switches, or prevent Codex from requesting permission again. macOS may prompt again the next time the component requests access.

Quit Computer Use before resetting. Restart it afterward if necessary. The script reports individual reset failures and returns a nonzero exit status if any reset fails.

## Current limitations

- Bundle discovery identifies installed components, not existing permission grants. The script attempts all three resets for every discovered identity, including helpers that may have no stored decisions.
- Discovery covers the selected Computer Use application and its nested bundles, not the main Codex application or other installations.
- The installation path limits discovery only. Resets target a service and bundle ID, so copies sharing a bundle ID cannot have their permissions reset independently by installation path.
- The script does not inspect or directly edit the TCC database, disable macOS security protections, or uninstall Codex.
- Actual permission resets have not been verified end to end. Tests use a mock reset command so they do not change macOS permissions.

## Development checks

On macOS, with Python 3 installed:

```bash
bash -n decodex.sh
python3 -m unittest discover -s tests -v
```

The tests create temporary application bundles and run a temporary copy of the script with `/usr/bin/tccutil` replaced by a mock. They cover discovery, duplicate IDs, equivalent application paths, symlink scope, traversal failures, missing option values, all three reset services, confirmation and cancellation, diagnostic mode, and reset failures. The production script has no command override for permission resets.

## License

MIT. See [LICENSE](LICENSE).

An independent project, not affiliated with or endorsed by OpenAI.
