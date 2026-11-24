#!/bin/bash
# Discover ChatGPT/Codex and Computer Use identities and reset TCC decisions.
# Compatible with the Bash 3.2 included with macOS. Never requires sudo.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash decodex.sh [--diagnose] [--app PATH] [--include-main-apps]
                      [--main-app PATH ...]

By default, target only Computer Use and its helpers. Ask once before
resetting Accessibility, Screen Recording, and Automation decisions.
--diagnose     List bundle identities only; change nothing.
--app PATH     Discover bundles inside a specific Computer Use .app.
--include-main-apps  Also discover and target the main ChatGPT/Codex apps.
--main-app PATH  Add a main app path; repeatable; implies --include-main-apps.
--help         Show this help.

With --include-main-apps, main apps are found in /Applications and
~/Applications. Bundle IDs are read from metadata. A missing default
Computer Use runtime is skipped; no main apps are targeted without opt-in.

Resetting forgets previous allow/deny decisions. It does not grant access or
toggle switches. macOS may ask again when Computer Use next requests access.
Quit ChatGPT/Codex and Computer Use before resetting; restart afterward.
All discovered identities are targeted, even if they have no stored decision.
Discovery does not establish which bundle owns a particular TCC permission.
EOF
}

if [ "$#" -eq 0 ]; then
  cat <<'EOF'
Default run: reset permissions for Computer Use and its helpers only.
Optional parameters for another run:
  --include-main-apps  Also reset permissions for ChatGPT/Codex.
  --diagnose           Preview targets without changing permissions.
  --app PATH           Use a different Computer Use installation.
  --main-app PATH      Add a main app path (implies --include-main-apps).
  --help               Show full usage.
Example: bash decodex.sh --include-main-apps

EOF
fi

diagnose=0
explicit_app=0
include_main_apps=0
main_apps=()
app_path="${CODEX_HOME:-$HOME/.codex}/computer-use/Codex Computer Use.app"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --diagnose) diagnose=1 ;;
    --include-main-apps) include_main_apps=1 ;;
    --app|--main-app)
      option=$1
      [ "$#" -ge 2 ] || { echo "$option requires a path." >&2; exit 2; }
      case "$2" in
        ''|-*) echo "$option requires a path. Prefix paths beginning with - with ./." >&2; exit 2 ;;
      esac
      if [ "$option" = --app ]; then
        app_path=$2
        explicit_app=1
      else
        main_apps+=("$2")
        include_main_apps=1
      fi
      shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[ "$(uname -s)" = Darwin ] || { echo 'This script requires macOS.' >&2; exit 1; }
[ "${EUID}" -ne 0 ] || { echo 'Run as your normal logged-in user, without sudo.' >&2; exit 1; }

# Finish traversal and check its status before consuming any partial results.
# Nested symlinks are deliberately not followed outside the installation.
discovery_file=$(/usr/bin/mktemp "${TMPDIR:-/tmp}/decodex.XXXXXX")
trap '/bin/rm -f "$discovery_file"' EXIT

add_root() {
  local root=$1
  local include_helpers=$2
  [ -d "$root" ] && [ -f "$root/Contents/Info.plist" ] || {
    echo "Not an application bundle: $root" >&2; exit 1;
  }
  # Include the root explicitly, regardless of its name or path spelling.
  root=$(cd -- "$root" && pwd -P) || {
    echo "Could not resolve the application path: $root" >&2; exit 1;
  }
  printf '%s\0' "$root" >> "$discovery_file"
  if [ "$include_helpers" -eq 1 ]; then
    if ! /usr/bin/find "$root" -mindepth 1 -type d \( -name '*.app' -o -name '*.xpc' \) -print0 >> "$discovery_file"; then
      echo 'Could not completely discover Computer Use components. No permissions were reset.' >&2
      exit 1
    fi
  fi
}

if [ "$explicit_app" -eq 1 ] || [ -e "$app_path" ] || [ -L "$app_path" ]; then
  add_root "$app_path" 1
else
  echo "Computer Use not found: $app_path (skipping). Use --app PATH for another location." >&2
fi

if [ "$include_main_apps" -eq 1 ]; then
  application_dirs=("/Applications" "$HOME/Applications")
  for directory in "${application_dirs[@]}"; do
    for name in ChatGPT.app Codex.app; do
      candidate="$directory/$name"
      if [ -e "$candidate" ] || [ -L "$candidate" ]; then
        main_apps+=("$candidate")
      fi
    done
  done
fi
for main_app in "${main_apps[@]+${main_apps[@]}}"; do
  add_root "$main_app" 0
done

ids=()
paths=()
while IFS= read -r -d '' bundle; do
  id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$bundle/Contents/Info.plist" 2>/dev/null) || continue
  [[ "$id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || continue
  duplicate=0
  for existing in "${ids[@]+${ids[@]}}"; do
    [ "$existing" != "$id" ] || duplicate=1
  done
  [ "$duplicate" -eq 0 ] || continue
  ids+=("$id")
  paths+=("$bundle")
done < "$discovery_file"

[ "${#ids[@]}" -gt 0 ] || { echo 'No bundle identifiers found. Use --app PATH or --main-app PATH for another location.' >&2; exit 1; }
printf '\nDiscovered identities (including helpers, which may not own permissions):\n'
for ((i=0; i<${#ids[@]}; i++)); do
  printf '\n  %d) %s\n     %s\n' "$((i+1))" "${ids[$i]}" "${paths[$i]}"
done
printf '\nServices: Accessibility, ScreenCapture (Screen Recording), AppleEvents (Automation)\n'
[ "$diagnose" -eq 0 ] || exit 0
[ -t 0 ] || { echo 'Interactive terminal required. Use --diagnose for discovery.' >&2; exit 1; }

if ! read -r -p 'Reset all three services for every identity listed above? [y/N] ' answer; then
  echo 'Cancelled.'
  exit 0
fi
case "$answer" in y|Y|yes|YES) ;; *) echo 'Cancelled.'; exit 0 ;; esac

services=(Accessibility ScreenCapture AppleEvents)
successes=0
failures=0
not_found=0
for id in "${ids[@]}"; do
  for service in "${services[@]}"; do
    printf '\nResetting %s for %s\n' "$service" "$id"
    if reset_output=$(LC_ALL=C /usr/bin/tccutil reset "$service" "$id" 2>&1); then
      [ -z "$reset_output" ] || printf '%s\n' "$reset_output"
      successes=$((successes+1))
    else
      [ -z "$reset_output" ] || printf '%s\n' "$reset_output" >&2
      failures=$((failures+1))
      case "$reset_output" in
        *'No such bundle identifier'*) not_found=$((not_found+1)) ;;
      esac
      printf 'Reset failed: %s / %s\n' "$service" "$id" >&2
    fi
  done
done
printf '\nReset summary: %d succeeded, %d failed (%d attempted).\n' "$successes" "$failures" "$((successes+failures))"
if [ "$not_found" -gt 0 ]; then
  printf '\n%d failed reset(s) targeted bundle IDs that macOS could not find.\n' "$not_found"
  printf 'Those reset attempts did not complete. Finding a helper on disk does not\nnecessarily mean macOS recognizes its bundle ID for permission resets.\n'
fi
other_failures=$((failures-not_found))
if [ "$other_failures" -gt 0 ]; then
  printf '\n%d reset(s) failed for other reasons; review the errors above.\n' "$other_failures" >&2
fi
if [ "$successes" -gt 0 ]; then
  printf '\nThe %d successful reset(s) completed. macOS may request permission again on next use.\n' "$successes"
fi
if [ "$failures" -gt 0 ]; then
  exit 1
fi
