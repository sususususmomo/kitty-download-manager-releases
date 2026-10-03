# Kitty Download Manager v8.35

Kitty est l’interface Firefox. Le backend local réalise les téléchargements avec yt-dlp. Installe l’extension depuis Mozilla une fois sa fiche publiée, puis ouvre **Réglages → Backend Kitty → Télécharger**. L’archive GitHub correspond automatiquement à ton système : Linux, Windows x64 ou macOS Intel/Apple Silicon. Décompresse-la, lance l’installateur indiqué, Kitty reconnaît ensuite automatiquement le backend installé.

Cette version est prête pour la soumission publique à Mozilla; le XPI fourni est encore non signé. Pour la tester avant publication : Firefox → `about:debugging` → Ce Firefox → Charger un module temporaire → `extension/manifest.json`. Après une modification de l’extension temporaire, utilise Recharger à cet endroit.

L’archive de développement contient `kitty-download-manager-v8.35-unsigned.xpi`, destiné à la soumission Mozilla. Ce XPI contient uniquement l’extension, sans backend. Les étapes de publication, la description et les notes aux reviewers figurent dans [docs/PUBLICATION-MOZILLA.md](docs/PUBLICATION-MOZILLA.md), avec une politique de confidentialité distincte.

## Réglages v8.35

Toutes les sections sont repliables et conservent leur état. L’ordre commence par Langue, Dossier de destination, Pill flottant, puis Backend Kitty. La langue porte une icône bleue et la destination une petite icône de dossier. Le statut du backend devient vert lorsque la connexion et une comparaison de version réussie confirment qu’il est à jour; il reste gris avant vérification et devient orange si une mise à jour est disponible. Backend Kitty montre la connexion et propose seulement les actions utiles : télécharger l’installateur si absent, rechercher une mise à jour si connecté, télécharger une version plus récente ou réessayer une connexion interrompue. Les mises à jour des outils sont dans Dépendances; la compatibilité détaillée est uniquement dans Diagnostic. Les anciennes recherches en cache sont recalculées contre la version connectée, sans requête réseau automatique. Les archives téléchargées nécessitent toujours une installation manuelle.

## Backend

Les trois installateurs backend seuls sont disponibles dans la [branche de distribution GitHub](https://github.com/sususususmomo/kitty-download-manager-releases/tree/backend-installers-v8.31). Les archives ont un dossier racine unique `kitty-download-manager`. Windows utilise `Install.cmd`, macOS `Install.command` et Linux `install.sh`. Les installateurs Windows/macOS préparent les dépendances privées. Sous Linux, Python 3, yt-dlp, FFmpeg/ffprobe et Mutagen doivent être disponibles.

Sur Arch/CachyOS : `sudo pacman -S python yt-dlp ffmpeg python-mutagen python-psutil deno` si les dépendances ne sont pas déjà installées.

L’extension est en v8.35 et le backend en v8.31 : leurs versions sont indépendantes, avec le protocole natif 1. Les backends compatibles déjà installés sont reconnus et ne nécessitent pas une nouvelle installation pour accéder à l’interface.

## Linux avec fish, dans le même dossier

```fish
cd ~/Downloads
and unzip -o kitty-download-manager-v8.35.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

La décompression écrase les fichiers de code correspondants et conserve les médias déjà présents. Recharge ensuite l’extension temporaire dans Firefox si tu testes l’interface avant sa publication sur Mozilla.

## Validation et construction

```sh
bash test.sh
node tests/test-backend-bootstrap.js
python tests/test-backend-packaging.py
python tools/build-packages.py
```

GitHub Actions vérifie le backend installé et la vraie popup Firefox sur Windows, Mac Intel et Mac Apple Silicon, dont le parcours sans backend, les textes anglais et la reconnexion. Une vérification distincte télécharge les trois archives GitHub et compare leurs SHA-256. Le workflow de publication lance également le validateur Mozilla `web-ext lint`.

Les détails des versions et des contrôles antérieurs se trouvent dans `docs/README-v8.31.md`, `docs/validation-macos-v8.31.json` et `tests/README.md`.
