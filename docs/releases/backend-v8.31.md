Le backend local de Kitty pour **Linux, Windows x64 et macOS Intel/Apple Silicon**. Cette release reste « Latest » : c’est la version que le backend consulte pour ses mises à jour.

| Système | Archive | Installation après décompression |
|---|---|---|
| Linux | `kitty-download-manager-v8.31.zip` | lancer `install.sh` |
| Windows x64 | `kitty-download-manager-v8.31-windows-x64.zip` | double-cliquer sur `Install.cmd` |
| macOS Intel / Apple Silicon | `kitty-download-manager-v8.31-macos.zip` | double-cliquer sur `Install.command` |

Chaque archive contient un seul dossier `kitty-download-manager`, uniquement le backend et l’installateur du système choisi. Les noms des fichiers assurent la compatibilité avec la recherche de mises à jour des versions déjà installées. Les fichiers sont identiques aux installateurs v8.31 de la branche de distribution existante. Les SHA-256 figurent dans `SHA256SUMS` et sont vérifiés par Kitty lors d’un téléchargement de mise à jour.

Les installateurs conservent la configuration, l’historique et les téléchargements. La file reste en pause après une mise à jour; reprendre depuis Kitty. Windows et macOS préparent des dépendances privées. Linux utilise Python 3, yt-dlp, FFmpeg/ffprobe et Mutagen disponibles sur le système; psutil et Deno complètent le fonctionnement.

Sous Arch/CachyOS, si nécessaire : `sudo pacman -S python yt-dlp ffmpeg python-mutagen python-psutil deno`.

Commande complète fish, dans le même dossier :

```fish
cd ~/Downloads
and unzip -o kitty-download-manager-v8.31.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

L’interface Firefox est distribuée séparément dans la release **Kitty Firefox v8.36**. Un backend v8.31 déjà installé ne nécessite pas une nouvelle installation pour utiliser cette interface.

Validation : installation et Native Messaging Windows, macOS Intel et Apple Silicon; tests Linux; remux audio hors ligne. Les validations de la v8.36 utilisent ce même backend : [Windows](https://github.com/sususususmomo/kitty-download-manager-releases/actions/runs/37160431577), [macOS](https://github.com/sususususmomo/kitty-download-manager-releases/actions/runs/37160431505). Les téléchargements de médias en ligne et l’authentification YouTube ne sont pas couverts par ces contrôles. L’installateur macOS est un script `.command`, sans signature ni notarisation Apple.
