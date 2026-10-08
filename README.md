# decodex

A Bash script for removing stored macOS permission decisions for Codex Computer Use. Run it after a Computer Use session to make macOS forget the selected bundles' authorizations.

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

The script looks for `Codex Computer Use.app` under `${CODEX_HOME:-$HOME/.codex}/computer-use/`, reads bundle IDs from the application and its nested `.app` and `.xpc` bundles, and displays them. Select identity numbers separated by spaces, then confirm the reset. Press Enter at the selection prompt to cancel.

By default it resets Accessibility and Screen Recording decisions for the selected identities. Include Automation decisions with:

```bash
bash decodex.sh --automation
```

List discovered identities without changing permissions:

```bash
bash decodex.sh --diagnose
```

Supply a different installation path:

```bash
bash decodex.sh --app "/path/to/Codex Computer Use.app"
```

Run `bash decodex.sh --help` for all options.

## What resetting means

The script uses macOS `tccutil reset` with a specific service and bundle ID. It forgets stored allow **and deny** decisions. It does not grant access, explicitly toggle System Settings switches, or prevent Codex from requesting permission again. macOS may prompt again the next time the selected component requests access.

Quit Computer Use before resetting. Restart it afterward if necessary. The script reports individual reset failures and returns a nonzero exit status if any reset fails.

## Current limitations

- Bundle discovery does not determine which identity owns a particular permission. Match your selections to entries in System Settings → Privacy & Security.
- Discovery covers the selected Computer Use application and its nested bundles, not the main Codex application or other installations.
- Automation currently requires `--automation`; the intended default scope is still being refined.
- The script does not inspect or directly edit the TCC database, disable macOS security protections, or uninstall Codex.
- Reset behavior has not been verified end to end. Bash syntax and read-only discovery have been checked on macOS.

## License

MIT. See [LICENSE](LICENSE).

An independent project, not affiliated with or endorsed by OpenAI.
