## English

Kitty’s local backend for **Linux, Windows x64 and macOS Intel/Apple Silicon**, now supporting thumbnail/cover downloads without audio/video. Install it to use **Image only** in Kitty Firefox v8.38. Previous frontend media modes remain compatible.

Download the ZIP for your system, extract it and run the installer listed below. Windows and macOS prepare private dependencies. Linux uses Python 3, yt-dlp, FFmpeg/ffprobe and Mutagen; psutil and Deno are recommended.

Installers preserve settings, history and downloaded files. The queue remains paused after an upgrade; resume it from Kitty. GPL v3.0 license text is included. macOS uses an unsigned, unnotarized `.command` script.

## Français

Backend local de Kitty pour **Linux, Windows x64 et macOS Intel/Apple Silicon**, avec téléchargement des miniatures/pochettes sans audio/vidéo. À installer pour utiliser **Image uniquement** dans Kitty Firefox v8.38. Les formats multimédias des anciennes extensions restent compatibles.

Télécharger le ZIP du système, le décompresser puis lancer l’installateur indiqué. Windows et macOS préparent des dépendances privées. Linux utilise Python 3, yt-dlp, FFmpeg/ffprobe et Mutagen ; psutil et Deno sont recommandés.

Les installateurs conservent les réglages, l’historique et les fichiers téléchargés. La file reste en pause après mise à jour ; la reprendre depuis Kitty. Le texte GPL v3.0 est inclus. macOS utilise un script `.command` sans signature ni notarisation Apple.

| System / Système | Archive | Installer / Installateur |
|---|---|---|
| Linux | `kitty-download-manager-v8.32.zip` | `install.sh` |
| Windows x64 | `kitty-download-manager-v8.32-windows-x64.zip` | `Install.cmd` |
| macOS Intel / Apple Silicon | `kitty-download-manager-v8.32-macos.zip` | `Install.command` |

```fish
cd ~/Downloads
and unzip -o kitty-download-manager-v8.32.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

Validation details: [frontend/backend v8.38/v8.32](https://github.com/sususususmomo/kitty-download-manager-releases/blob/main/docs/validation-frontend-v8.38.json). Image integration tests use local HTTP fixtures; online media sites and YouTube authentication are outside these tests.
