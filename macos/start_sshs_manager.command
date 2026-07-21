#!/bin/zsh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/sshfs_mount_manager_macos.py"

if command -v python3 >/dev/null 2>&1; then
    python3 "$APP_PATH"
    STATUS=$?
elif command -v python >/dev/null 2>&1; then
    python "$APP_PATH"
    STATUS=$?
else
    echo "Python 3 was not found."
    echo "Install Python 3 with tkinter and try again."
    read "?Press Enter to close..."
    exit 1
fi

if [ "$STATUS" -ne 0 ]; then
    echo
    echo "The application exited with status $STATUS."
    read "?Press Enter to close..."
fi

exit "$STATUS"
