#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SLUG="kitty-download-manager"
BIN_DIR="$HOME/.local/bin"
INSTALL_DIR="$HOME/.local/lib/$APP_SLUG"
NM_DIR="$HOME/.mozilla/native-messaging-hosts"
CONFIG_DIR="$HOME/.config/$APP_SLUG"
CACHE_DIR="$HOME/.cache/$APP_SLUG"
DEFAULT_DOWNLOAD_DIR="$HOME/Downloads/$APP_SLUG"
NM_FILE="$NM_DIR/com.kitty.download_manager.json"

export PYTHONDONTWRITEBYTECODE=1

echo
echo "Kitty Download Manager V8.30"
echo "Préparation de l'installation / migration…"

# Une V8 déjà installée passe par l'updater sûr : pause de file, arrêt externe
# contrôlé du worker, sauvegarde, remplacement atomique et rollback si besoin.
if [[ -f "$INSTALL_DIR/host.py" ]]; then
  echo "Installation V8 existante détectée → updater sûr."
  exec python3 -B "$ROOT/native-host/maintenance.py" update --source "$ROOT"
fi

# PREPARE only copies legacy state. It never deletes the V7 installation.
PREPARE_RESULT="$(mktemp "${TMPDIR:-/tmp}/kitty-download-manager-prepare.XXXXXX")"
python3 -B "$ROOT/native-host/migrate.py" prepare >"$PREPARE_RESULT" || {
  cat "$PREPARE_RESULT" 2>/dev/null || true
  rm -f "$PREPARE_RESULT"
  echo
  echo "Migration interrompue sans suppression de l'ancienne installation."
  exit 1
}
rm -f "$PREPARE_RESULT"

mkdir -p "$INSTALL_DIR" "$NM_DIR" "$CONFIG_DIR" "$CACHE_DIR"
chmod 700 "$INSTALL_DIR" "$CONFIG_DIR" "$CACHE_DIR" 2>/dev/null || true

for file in host.py worker.py metadata.py errors.py app_paths.py migrate.py compatibility.py maintenance.py runtime_storage.py queue_store.py platform_support.py; do
  cp "$ROOT/native-host/$file" "$INSTALL_DIR/$file"
done

chmod +x "$INSTALL_DIR/host.py" "$INSTALL_DIR/worker.py" "$INSTALL_DIR/metadata.py" "$INSTALL_DIR/migrate.py" "$INSTALL_DIR/compatibility.py" "$INSTALL_DIR/maintenance.py" "$INSTALL_DIR/runtime_storage.py"
chmod 644 "$INSTALL_DIR/errors.py" "$INSTALL_DIR/app_paths.py" "$INSTALL_DIR/queue_store.py" "$INSTALL_DIR/platform_support.py"

# Syntax/import validation before switching away from the legacy backend.
python3 -B - "$INSTALL_DIR" <<'PY'
import ast
import importlib.util
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
for name in ("host.py", "worker.py", "metadata.py", "errors.py", "app_paths.py", "migrate.py", "compatibility.py", "maintenance.py", "runtime_storage.py", "queue_store.py", "platform_support.py"):
    path = root / name
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

sys.path.insert(0, str(root))
import app_paths  # noqa: F401
import errors  # noqa: F401
import compatibility  # noqa: F401
import maintenance  # noqa: F401
PY

python3 -B - "$ROOT/native-host/manifest.json" "$NM_FILE" "$INSTALL_DIR/host.py" <<'PY'
import json
import os
import sys
from pathlib import Path

src, dst, host_path = map(Path, sys.argv[1:])
data = json.loads(src.read_text(encoding="utf-8"))
data["path"] = str(host_path)

dst.parent.mkdir(parents=True, exist_ok=True)
tmp = dst.with_name(dst.name + f".tmp-{os.getpid()}")
tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
os.chmod(tmp, 0o600)
os.replace(tmp, dst)
PY

mkdir -p "$BIN_DIR"
ln -sfn "$INSTALL_DIR/maintenance.py" "$BIN_DIR/kitty-update"
ln -sfn "$INSTALL_DIR/maintenance.py" "$BIN_DIR/kitty-uninstall"

# FINALIZE validates migrated settings/queue/auth again, migrates the old
# default Downloads folder when safe, then removes only the exact legacy paths.
FINALIZE_RESULT="$(mktemp "${TMPDIR:-/tmp}/kitty-download-manager-finalize.XXXXXX")"
python3 -B "$INSTALL_DIR/migrate.py" finalize >"$FINALIZE_RESULT" || {
  cat "$FINALIZE_RESULT" 2>/dev/null || true
  rm -f "$FINALIZE_RESULT"
  echo
  echo "V8 a été copiée mais la finalisation de migration a été arrêtée."
  echo "Les données legacy n'ont pas été supprimées de façon forcée."
  exit 1
}
MIGRATION_RESULT="$(cat "$FINALIZE_RESULT")"
rm -f "$FINALIZE_RESULT"

echo
echo "Kitty Download Manager V8.30 installée."
echo "Host       : $INSTALL_DIR/host.py"
echo "Worker     : $INSTALL_DIR/worker.py"
echo "Métadonnées: $INSTALL_DIR/metadata.py"
echo "Erreurs    : $INSTALL_DIR/errors.py"
echo "Updater    : $BIN_DIR/kitty-update"
echo "Uninstaller: $BIN_DIR/kitty-uninstall"
echo "Config     : $CONFIG_DIR"
echo "Cache      : $CACHE_DIR"
echo "Dossier    : $DEFAULT_DOWNLOAD_DIR"
echo

python3 -B - "$CONFIG_DIR/migration-v8.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    data = {}

if data.get("legacy_found"):
    print("Migration V7 → V8 : OK")
    print("Ancien backend     : supprimé après validation")
    output = data.get("output_migration")
    if output == "legacy_default_renamed":
        print("Téléchargements     : ancien dossier renommé vers kitty-download-manager")
    elif output == "legacy_destination_preserved_due_to_conflict":
        print("Téléchargements     : ancien dossier conservé (conflit avec le nouveau dossier)")
    elif output == "custom_destination_preserved":
        print("Téléchargements     : destination personnalisée conservée")
else:
    print("Installation fraîche : OK")
PY

echo
echo "Vérification du module Python yt_dlp…"
if ! python3 -B -c 'import yt_dlp' >/dev/null 2>&1; then
  echo "ATTENTION: Python ne peut pas importer yt_dlp."
  echo "Arch/Manjaro: sudo pacman -S yt-dlp"
else
  echo "yt_dlp Python OK."
fi

echo
echo "Vérification ffmpeg / ffprobe…"
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg + ffprobe OK."
else
  echo "ATTENTION: ffmpeg et ffprobe sont requis."
fi

echo
echo "Vérification Mutagen…"
if python3 -B -c 'import mutagen' >/dev/null 2>&1; then
  echo "Mutagen OK."
else
  echo "ATTENTION: Mutagen manque. Certaines pochettes audio ne pourront pas être intégrées."
  echo "Arch/Manjaro: sudo pacman -S python-mutagen"
fi

echo
echo "Important V8 : l'identifiant Firefox a changé."
echo "Dans about:debugging → Ce Firefox, charge extension/manifest.json de V8."
echo "Si l'ancienne V7 temporaire est encore affichée, supprime-la."
echo "Recharge ensuite les pages ouvertes pour mettre à jour la pill."
