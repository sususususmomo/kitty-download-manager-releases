# Backend Kitty v8.31

Installe d’abord l’extension Kitty dans Firefox. Depuis ses réglages, le bouton **Télécharger** sélectionne automatiquement l’installateur adapté à ton système.

Ces archives contiennent uniquement le backend et son installateur, sans extension Firefox. Elles utilisent le protocole natif 1 et acceptent les interfaces Kitty de la série 8 compatibles avec ce protocole.

| Système | Archive | Installation après extraction |
| --- | --- | --- |
| Linux | [Télécharger](kitty-backend-v8.31-linux.zip?raw=true) | Lancer `./install.sh` dans un terminal. Python 3, yt-dlp, FFmpeg/ffprobe et Mutagen doivent être disponibles. |
| Windows 10/11 x64 | [Télécharger](kitty-backend-v8.31-windows-x64.zip?raw=true) | Double-cliquer sur `Install.cmd`. |
| macOS Intel / Apple Silicon | [Télécharger](kitty-backend-v8.31-macos.zip?raw=true) | Double-cliquer sur `Install.command`. |

Après installation, rouvre Kitty ou clique sur **Vérifier la connexion** dans les réglages. Windows et macOS préparent un Python et des dépendances privés à l’utilisateur. Le backend contacte les sites demandés pour télécharger les médias; les paramètres et l’historique restent sur l’ordinateur.

Linux avec fish, dans un seul dossier :

```fish
cd ~/Downloads
and unzip -o kitty-backend-v8.31-linux.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

Sur Arch/CachyOS, si les dépendances manquent : `sudo pacman -S python yt-dlp ffmpeg python-mutagen python-psutil deno`.

Les empreintes des archives sont disponibles dans `SHA256SUMS`. La décompression dans le dossier existant conserve les téléchargements déjà présents. L’installateur conserve les réglages et l’historique; une file active est mise en pause pendant une mise à jour.
