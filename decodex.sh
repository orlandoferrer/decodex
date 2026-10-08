#!/bin/bash
# Discover Codex Computer Use identities and reset selected macOS TCC decisions.
# Compatible with the Bash 3.2 included with macOS. Never requires sudo.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash decodex.sh [--diagnose] [--app PATH] [--automation]

By default, discover Computer Use bundles, ask which identities to target,
then confirm before resetting Accessibility and Screen Recording decisions.
--diagnose     List bundle identities only; change nothing.
--app PATH     Discover bundles inside a specific Computer Use .app.
--automation   Also reset Automation (AppleEvents) decisions.
--help         Show this help.

Resetting forgets previous allow/deny decisions. It does not grant access or
toggle switches. macOS may ask again when Computer Use next requests access.
Quit Computer Use before resetting; restart it afterward if necessary.
Discovery does not establish which bundle owns a particular TCC permission.
Match your selections to the entries shown in System Settings.
EOF
}

diagnose=0
automation=0
app_path="${CODEX_HOME:-$HOME/.codex}/computer-use/Codex Computer Use.app"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --diagnose) diagnose=1 ;;
    --automation) automation=1 ;;
    --app)
      [ "$#" -ge 2 ] || { echo '--app requires a path.' >&2; exit 2; }
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
done < <(/usr/bin/find "$app_path" -type d \( -name '*.app' -o -name '*.xpc' \) -print0)

[ "${#ids[@]}" -gt 0 ] || { echo 'No bundle identifiers found.' >&2; exit 1; }
printf '\nDiscovered identities (including helpers, which may not own permissions):\n'
for ((i=0; i<${#ids[@]}; i++)); do
  printf '\n  %d) %s\n     %s\n' "$((i+1))" "${ids[$i]}" "${paths[$i]}"
done
printf '\nServices: Accessibility, ScreenCapture (Screen Recording)'
[ "$automation" -eq 0 ] || printf ', AppleEvents (Automation)'
printf '\n'
[ "$diagnose" -eq 0 ] || exit 0
[ -t 0 ] || { echo 'Interactive terminal required. Use --diagnose for discovery.' >&2; exit 1; }

read -r -p 'Select identity numbers separated by spaces (or Enter to cancel): ' selection
[ -n "$selection" ] || { echo 'Cancelled.'; exit 0; }
selected=()
for number in $selection; do
  [[ "$number" =~ ^[1-9][0-9]*$ ]] && [ "${#number}" -le 6 ] || {
    echo "Invalid selection: $number" >&2; exit 2;
  }
  [ "$number" -le "${#ids[@]}" ] || { echo "Invalid selection: $number" >&2; exit 2; }
  id=${ids[$((number-1))]}
  duplicate=0
  for existing in "${selected[@]+${selected[@]}}"; do
    [ "$existing" != "$id" ] || duplicate=1
  done
  [ "$duplicate" -eq 1 ] || selected+=("$id")
done
printf '\nWill forget permission decisions for:\n'
printf '  %s\n' "${selected[@]}"
read -r -p 'Reset the listed services for these identities? [y/N] ' answer
case "$answer" in y|Y|yes|YES) ;; *) echo 'Cancelled.'; exit 0 ;; esac

services=(Accessibility ScreenCapture)
[ "$automation" -eq 0 ] || services+=(AppleEvents)
failures=0
for id in "${selected[@]}"; do
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
