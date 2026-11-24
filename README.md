# decodex

A Bash script for removing stored macOS permission decisions for Codex Computer Use and its helpers, with optional support for the main ChatGPT/Codex apps. Run it to make macOS forget the discovered bundles' authorizations.

This is an early version. Discovery and the interaction flow still need refinement.

## Requirements

- macOS, with its included Bash 3.2 and command-line tools.
- An installed Codex Computer Use runtime, or a ChatGPT/Codex app with the main-app option enabled.
- Run as your normal logged-in user, without `sudo`.

No additional packages are required.

## Usage

Clone this repository, enter its directory, and run:

```bash
bash decodex.sh
```

Running without arguments also displays a reminder of optional parameters for a later run, including `--include-main-apps` and `--diagnose`.

By default, the script discovers only `Codex Computer Use.app` under `${CODEX_HOME:-$HOME/.codex}/computer-use/`, including its nested `.app` and `.xpc` bundles. Main ChatGPT/Codex apps are excluded.

To also reset main apps named `ChatGPT.app` or `Codex.app` directly in `/Applications` and `~/Applications`, opt in with:

```bash
bash decodex.sh --include-main-apps
```

It reads bundle IDs from metadata rather than guessing them from app names, combines and deduplicates all identities, and displays the target IDs and paths. No bundle selection is needed. Main apps contribute their own identity; only the Computer Use installation is searched for nested helpers.

With main apps enabled, the script works with either type of installation alone. A missing default Computer Use runtime is reported and skipped; the script never falls back to main apps without opt-in. If no valid identities are found, it exits without resetting anything. An invalid explicitly supplied path is an error, even if other apps were discovered.

It asks for one confirmation before resetting all three services for every listed identity:

- Accessibility (`Accessibility`)
- Screen Recording (`ScreenCapture`)
- Automation (`AppleEvents`)

Enter `y` or `yes` to proceed, or press Enter to cancel. Automation is always included; the former `--automation` flag has been removed. Reset mode requires an interactive terminal.

List discovered identities without changing permissions:

```bash
bash decodex.sh --diagnose
```

Supply a different Computer Use installation path (main apps still require opt-in):

```bash
bash decodex.sh --app "/path/to/Codex Computer Use.app"
```

Add main apps installed elsewhere or renamed on disk using `--main-app`. This option is repeatable, implies `--include-main-apps`, and adds the supplied paths to automatic main-app discovery:

```bash
bash decodex.sh --main-app "/Volumes/Apps/ChatGPT.app" --main-app "/path/to/Codex.app"
```

You can combine these options with `--diagnose` to preview every target.

Relative paths, paths ending in `/.`, and symlinks to the root application are resolved before discovery. Nested symlinks are not followed. If directory traversal fails, the script stops before confirmation and resets nothing.

Run `bash decodex.sh --help` for all options.

## What resetting means

The script uses macOS `tccutil reset` with a specific service and bundle ID. It forgets stored allow **and deny** decisions. It does not grant access, explicitly toggle System Settings switches, or prevent Codex from requesting permission again. macOS may prompt again the next time the component requests access.

Quit Computer Use before resetting. If including main apps, quit ChatGPT/Codex too. Restart them afterward if necessary. The script reports individual reset failures and returns a nonzero exit status if any reset fails. Resetting the main app's permissions can also affect features outside Computer Use, such as screenshots and Work with Apps.

## Current limitations

- Bundle discovery identifies installed components, not existing permission grants. The script attempts all three resets for every discovered identity, including helpers that may have no stored decisions.
- Automatic main-app discovery is limited to the exact names and directories above. Use `--main-app` for other locations or names. The script does not search the whole disk or discover permission entries for uninstalled apps.
- The installation path limits discovery only. Resets target a service and bundle ID, so copies sharing a bundle ID cannot have their permissions reset independently by installation path.
- The script does not inspect or directly edit the TCC database, disable macOS security protections, or uninstall Codex.
- Actual permission resets have not been verified end to end. Tests use a mock reset command so they do not change macOS permissions.

## Development checks

On macOS, with Python 3 installed:

```bash
bash -n decodex.sh
python3 -m unittest discover -s tests -v
```

The tests create temporary application bundles and run a temporary copy of the script with `/usr/bin/tccutil` replaced by a mock. Automatic main-app discovery is redirected to fixture directories, so tests do not depend on apps installed on the test machine. They cover main apps being excluded by default, explicit opt-in, main apps and Computer Use together or separately, custom main-app paths, cross-installation duplicate IDs, equivalent application paths, symlink scope, traversal failures, missing option values, all three reset services, confirmation and cancellation, diagnostic mode, and reset failures. The production script has no command override for permission resets.

## License

MIT. See [LICENSE](LICENSE).

An independent project, not affiliated with or endorsed by OpenAI.
