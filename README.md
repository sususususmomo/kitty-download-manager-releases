<p align="center">
  <img src="extension/icons/icon-128.png" width="88" alt="Kitty logo">
</p>

# Kitty Download Manager

[English](#english) · [Français](#français)

## English

Download videos and audio from Firefox, with a queue, history and a floating download button. This repository provides Kitty’s local backend, powered by **yt-dlp** and **FFmpeg**.

### Install the backend

Download the ZIP for your system from the [latest backend release](https://github.com/sususususmomo/kitty-download-manager-releases/releases/latest). Extract it, open the `kitty-download-manager` folder and run:

| System | Installer |
|---|---|
| Linux | `bash ./install.sh` in a terminal |
| Windows x64 | Double-click `Install.cmd` |
| macOS Intel / Apple Silicon | Double-click `Install.command` |

Windows and macOS installers set up private dependencies. On Linux, install Python 3, yt-dlp, FFmpeg and Mutagen; psutil and Deno are recommended.

Open Kitty in Firefox: the installed backend is detected automatically.

**Firefox extension:** requires Firefox 140+. Mozilla signing is pending. For temporary testing, extract the [extension sources](https://github.com/sususususmomo/kitty-download-manager-releases/releases/download/frontend-v8.36/kitty-download-manager-v8.36.zip), then load `extension/manifest.json` through `about:debugging` → **This Firefox** → **Load Temporary Add-on**.

---

## Français

Téléchargez des vidéos et de l’audio depuis Firefox, avec une file d’attente, un historique et un bouton de téléchargement flottant. Ce dépôt fournit le backend local de Kitty, basé sur **yt-dlp** et **FFmpeg**.

### Installer le backend

Téléchargez le ZIP correspondant à votre système dans la [dernière release du backend](https://github.com/sususususmomo/kitty-download-manager-releases/releases/latest). Décompressez-le, ouvrez le dossier `kitty-download-manager` et lancez :

| Système | Installateur |
|---|---|
| Linux | `bash ./install.sh` dans un terminal |
| Windows x64 | Double-cliquer sur `Install.cmd` |
| macOS Intel / Apple Silicon | Double-cliquer sur `Install.command` |

Les installateurs Windows et macOS préparent des dépendances privées. Sous Linux, installez Python 3, yt-dlp, FFmpeg et Mutagen ; psutil et Deno sont recommandés.

Ouvrez Kitty dans Firefox : le backend installé est détecté automatiquement.

**Extension Firefox :** nécessite Firefox 140 ou plus récent. La signature Mozilla est en attente. Pour un test temporaire, décompressez les [sources de l’extension](https://github.com/sususususmomo/kitty-download-manager-releases/releases/download/frontend-v8.36/kitty-download-manager-v8.36.zip), puis chargez `extension/manifest.json` depuis `about:debugging` → **Ce Firefox** → **Charger un module temporaire**.
