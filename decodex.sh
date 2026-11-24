#!/bin/bash
# Discover Codex Computer Use identities and reset their macOS TCC decisions.
# Compatible with the Bash 3.2 included with macOS. Never requires sudo.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash decodex.sh [--diagnose] [--app PATH]

Discover all Computer Use bundles, then ask once before resetting their
Accessibility, Screen Recording, and Automation decisions.
--diagnose     List bundle identities only; change nothing.
--app PATH     Discover bundles inside a specific Computer Use .app.
--help         Show this help.

Resetting forgets previous allow/deny decisions. It does not grant access or
toggle switches. macOS may ask again when Computer Use next requests access.
Quit Computer Use before resetting; restart it afterward if necessary.
All discovered identities are targeted, even if they have no stored decision.
Discovery does not establish which bundle owns a particular TCC permission.
EOF
}

diagnose=0
app_path="${CODEX_HOME:-$HOME/.codex}/computer-use/Codex Computer Use.app"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --diagnose) diagnose=1 ;;
    --app)
      [ "$#" -ge 2 ] || { echo '--app requires a path.' >&2; exit 2; }
      case "$2" in
        ''|-*) echo '--app requires a path. Prefix paths beginning with - with ./.' >&2; exit 2 ;;
      esac
      app_path=$2; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[ "$(uname -s)" = Darwin ] || { echo 'This script requires macOS.' >&2; exit 1; }
[ "${EUID}" -ne 0 ] || { echo 'Run as your normal logged-in user, without sudo.' >&2; exit 1; }

if [ ! -d "$app_path" ]; then
  if [ "$diagnose" -eq 1 ] || [ ! -t 0 ]; then
    echo "Computer Use not found: $app_path. Supply --app PATH." >&2; exit 1
  fi
  read -r -p 'Enter the full path to your Computer Use .app: ' app_path
fi
[ -d "$app_path" ] && [ -f "$app_path/Contents/Info.plist" ] || {
  echo "Not an application bundle: $app_path" >&2; exit 1;
}
# Normalize relative paths, trailing /. and a symlink supplied as the root.
app_path=$(cd -- "$app_path" && pwd -P) || {
  echo 'Could not resolve the application path.' >&2; exit 1;
}

# Finish traversal and check its status before consuming any partial results.
# Nested symlinks are deliberately not followed outside the installation.
discovery_file=$(/usr/bin/mktemp "${TMPDIR:-/tmp}/decodex.XXXXXX")
trap '/bin/rm -f "$discovery_file"' EXIT
printf '%s\0' "$app_path" > "$discovery_file"
if ! /usr/bin/find "$app_path" -mindepth 1 -type d \( -name '*.app' -o -name '*.xpc' \) -print0 >> "$discovery_file"; then
  echo 'Could not completely discover Computer Use components. No permissions were reset.' >&2
  exit 1
fi

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

[ "${#ids[@]}" -gt 0 ] || { echo 'No bundle identifiers found.' >&2; exit 1; }
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
failures=0
for id in "${ids[@]}"; do
  for service in "${services[@]}"; do
    printf '\nResetting %s for %s\n' "$service" "$id"
    if ! /usr/bin/tccutil reset "$service" "$id"; then
      failures=$((failures+1))
      printf 'Reset failed: %s / %s\n' "$service" "$id" >&2
    fi
  done
done
if [ "$failures" -gt 0 ]; then
  printf '\n%d reset(s) failed; review the errors above.\n' "$failures" >&2
  exit 1
fi
printf '\nResets completed. macOS may request permission again on next use.\n'
