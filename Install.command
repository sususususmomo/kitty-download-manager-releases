#!/bin/bash
# Uses only macOS-provided tools until the private Python is verified.
set -euo pipefail
umask 077
if [ "$(/usr/bin/uname -s)" != Darwin ]; then
    echo 'Cet installateur est réservé à macOS.' >&2
    exit 1
fi
if [ "$(/usr/bin/id -u)" = 0 ]; then
    echo 'Lance cet installateur avec ton compte habituel, sans sudo.' >&2
    exit 1
fi
kitty_os_major=$(/usr/bin/sw_vers -productVersion | /usr/bin/cut -d. -f1)
if [ "$kitty_os_major" -lt 13 ]; then
    echo 'macOS 13 Ventura ou plus récent est requis.' >&2
    exit 1
fi
kitty_source="$(cd "$(dirname "$0")" && pwd -P)"
kitty_root="$HOME/Library/Application Support/KittyDownloadManager"
# Prefer native Apple Silicon even when Terminal runs through Rosetta.
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || true)" = 1 ]; then
    kitty_arch=aarch64
    kitty_digest=d00669acb53c1b014f1fcf5eaea740d8e45c3aff4b1e0244dc0f8697fb211a82
else
    kitty_arch=$(/usr/bin/uname -m)
    kitty_digest=a88bef59d9dd61ba4210772cce57a4b4cb963aa745ab956f7cc79ba60f9e2523
fi
case "$kitty_arch" in aarch64|x86_64) ;; *) echo 'Architecture Mac non prise en charge.' >&2; exit 1 ;; esac
kitty_parent="$kitty_root"
while [ "$kitty_parent" != / ]; do
    if [ -L "$kitty_parent" ]; then echo "Dossier lié refusé : $kitty_parent" >&2; exit 1; fi
    kitty_parent="$(dirname "$kitty_parent")"
done
mkdir -p "$kitty_root"
chmod 700 "$kitty_root"
kitty_stage="$(/usr/bin/mktemp -d "$kitty_root/stage-XXXXXXXX")"
kitty_cleanup() {
    if [ -n "${kitty_stage:-}" ] && [ -d "$kitty_stage" ] && [ ! -L "$kitty_stage" ]; then
        rm -rf -- "$kitty_stage"
    fi
}
trap kitty_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
kitty_download() {
    /usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
        --connect-timeout 30 --max-time 600 --retry 2 --max-filesize 350000000 \
        --output "$2" "$1"
}
echo "Kitty Download Manager V8.32 — macOS $kitty_arch"
echo 'Préparation de Python privé…'
# Digests verified against Astral's immutable 20261001 release on 2026-10-03.
kitty_asset="cpython-3.13.16+20261001-$kitty_arch-apple-darwin-install_only_stripped.tar.gz"
cat > "$kitty_stage/python-runtime.json" <<JSON
{"version":"3.13.16","release":"20261001","architecture":"$kitty_arch","asset":"$kitty_asset","sha256":"$kitty_digest","provider":"astral-sh/python-build-standalone"}
JSON
kitty_download "https://github.com/astral-sh/python-build-standalone/releases/download/20261001/$kitty_asset" "$kitty_stage/python.tar.gz"
kitty_actual=$(/usr/bin/shasum -a 256 "$kitty_stage/python.tar.gz" | /usr/bin/awk '{print $1}')
if [ "$kitty_actual" != "$kitty_digest" ]; then echo 'SHA-256 Python incorrect; installation interrompue.' >&2; exit 1; fi
# Reject traversal and unexpected archive roots before extraction.
/usr/bin/tar -tzf "$kitty_stage/python.tar.gz" > "$kitty_stage/python-files.txt"
/usr/bin/awk 'BEGIN {ok=1} /^\// || /(^|\/)\.\.(\/|$)/ || !/^python(\/|$)/ {ok=0} END {exit !ok}' "$kitty_stage/python-files.txt"
mkdir "$kitty_stage/runtime"
/usr/bin/tar -xzf "$kitty_stage/python.tar.gz" -C "$kitty_stage/runtime" --strip-components 1
rm "$kitty_stage/python.tar.gz" "$kitty_stage/python-files.txt"
kitty_python="$kitty_stage/runtime/bin/python3"
"$kitty_python" -I -B -c 'import ssl, sys; assert sys.version_info[:3] == (3, 13, 16)'
echo 'Installation de yt-dlp, Mutagen et du support des processus…'
"$kitty_python" -I -m pip --isolated install --index-url 'https://pypi.org/simple' \
    --no-cache-dir --disable-pip-version-check --no-warn-script-location --no-compile \
    --only-binary=:all: --report "$kitty_stage/python-dependencies.json" 'yt-dlp[default]' mutagen psutil
"$kitty_python" -I -u -B "$kitty_source/native-host/macos_install.py" install \
    --source "$kitty_source" --stage "$kitty_stage" --arch "$kitty_arch"
echo
echo "Installation terminée : $kitty_root"
echo 'Rouvre Kitty dans Firefox et clique sur Vérifier la connexion dans les réglages.'
