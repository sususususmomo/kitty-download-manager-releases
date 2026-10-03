#!/bin/bash
set -euo pipefail
if [ "$(/usr/bin/uname -s)" != Darwin ]; then
    echo 'Cette désinstallation est réservée à macOS.' >&2
    exit 1
fi
exec "$HOME/Library/Application Support/KittyDownloadManager/Uninstall.command"
