#!/bin/bash
# Install (or uninstall) the Shakespeare wallpaper LaunchAgents for this checkout.
#
#   ./install.sh                 set up .venv, install both agents (daily wallpaper + menu bar app)
#   ./install.sh --hour 7        change the wallpaper at 07:00 instead of 04:00
#   ./install.sh --no-menubar    daily wallpaper only (removes the menu bar agent if installed)
#   ./install.sh --dry-run DIR   only write the generated plists to DIR; installs nothing
#   ./install.sh --uninstall     unload and remove both agents
#
# Set PYTHON to use another interpreter for the venv (default: /usr/bin/python3).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PYTHON="${PYTHON:-/usr/bin/python3}"
LABELS=(com.shakespeare.wallpaper com.shakespeare.menubar)
DOMAIN="gui/$(id -u)"

hour=4
menubar=1
dry_run_dir=""
uninstall=0

die() { echo "error: $*" >&2; exit 1; }

usage() { sed -n '2,10s/^# \{0,1\}//p' "$0"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hour)
            [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] && (( 10#$2 <= 23 )) || die "--hour needs a value from 0 to 23"
            hour=$((10#$2)); shift 2 ;;
        --no-menubar) menubar=0; shift ;;
        --dry-run)
            [[ $# -ge 2 ]] || die "--dry-run needs a directory"
            dry_run_dir="$2"; shift 2 ;;
        --uninstall) uninstall=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown option: $1" ;;
    esac
done

[[ "$(uname -s)" == "Darwin" ]] || die "this project only works on macOS"

unload() {
    launchctl bootout "$DOMAIN/$1" 2>/dev/null || true
    # bootout returns before a running job has fully stopped; bootstrapping it again too
    # early fails with "Input/output error"
    for _ in {1..50}; do
        launchctl print "$DOMAIN/$1" >/dev/null 2>&1 || break
        sleep 0.1
    done
    rm -f "$AGENTS_DIR/$1.plist"
}

if (( uninstall )); then
    for label in "${LABELS[@]}"; do
        unload "$label"
        echo "Removed $label"
    done
    echo "Left in place: $PROJECT_DIR/.venv and the images in ~/Pictures/ShakespeareDaily/"
    exit 0
fi

# render TEMPLATE OUTPUT: fill in @PROJECT_DIR@ / @HOUR@, escaping the path for XML
render() {
    "$PYTHON" -I - "$1" "$2" "$PROJECT_DIR" "$hour" <<'EOF'
import sys
from xml.sax.saxutils import escape
template, output, project_dir, hour = sys.argv[1:]
with open(template, encoding="utf-8") as f:
    text = f.read()
text = text.replace("@PROJECT_DIR@", escape(project_dir)).replace("@HOUR@", hour)
with open(output, "w", encoding="utf-8") as f:
    f.write(text)
EOF
    plutil -lint -s "$2" || die "generated plist is invalid: $2"
}

[[ -x "$PYTHON" ]] || die "$PYTHON not found (install the Xcode Command Line Tools: xcode-select --install)"

if [[ -n "$dry_run_dir" ]]; then
    mkdir -p "$dry_run_dir"
    for label in "${LABELS[@]}"; do
        render "$PROJECT_DIR/launchd/$label.plist.template" "$dry_run_dir/$label.plist"
        echo "Wrote $dry_run_dir/$label.plist"
    done
    exit 0
fi

echo "Setting up $PROJECT_DIR/.venv"
"$PYTHON" -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/python" -m pip install -q --upgrade pip
"$PROJECT_DIR/.venv/bin/python" -m pip install -q -r "$PROJECT_DIR/requirements.txt"

mkdir -p "$PROJECT_DIR/logs" "$AGENTS_DIR"
for label in "${LABELS[@]}"; do
    unload "$label"
    if [[ "$label" == com.shakespeare.menubar ]] && (( ! menubar )); then
        continue
    fi
    render "$PROJECT_DIR/launchd/$label.plist.template" "$AGENTS_DIR/$label.plist"
    launchctl bootstrap "$DOMAIN" "$AGENTS_DIR/$label.plist"
    echo "Installed $label"
done

printf 'Done. The wallpaper changes daily at %02d:00 and at login (it just changed now too).\n' "$hour"
echo "Logs: $PROJECT_DIR/logs/   Uninstall: $0 --uninstall"
