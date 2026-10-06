<p align="center">
  <img src="extension/icons/icon-128.png" width="88" alt="Kitty logo">
</p>

# Kitty Download Manager

[English](#english) · [Français](#français)

## English

Download videos, audio and thumbnail images from Firefox, with a queue, history and a floating download button. This repository provides Kitty’s local backend, powered by **yt-dlp** and **FFmpeg**.

### Install the backend

Download the ZIP for your system from the [latest backend release](https://github.com/sususususmomo/kitty-download-manager-releases/releases/latest). Extract it, open the `kitty-download-manager` folder and run:

| System | Installer |
|---|---|
| Linux | `bash ./install.sh` in a terminal |
| Windows x64 | Double-click `Install.cmd` |
| macOS Intel / Apple Silicon | Double-click `Install.command` |

Windows and macOS installers set up private dependencies. On Linux, install Python 3, yt-dlp, FFmpeg and Mutagen; psutil and Deno are recommended.

Open Kitty in Firefox: the installed backend is detected automatically. **Image only** downloads the thumbnail or cover without audio/video, using its original image format.

**Firefox extension:** requires Firefox 140+. Mozilla signing is pending. For temporary testing, extract the [extension sources](https://github.com/sususususmomo/kitty-download-manager-releases/releases/download/frontend-v8.38/kitty-download-manager-v8.38.zip), then load `extension/manifest.json` through `about:debugging` → **This Firefox** → **Load Temporary Add-on**.

Current development sources detect HLS, DASH and direct video/audio loaded by Firefox. With backend 8.38, **Automatic** compares metadata in parallel and downloads one source that matches the selected quality or audio mode. Explicit source selection remains available. Automatic now retains detected media when a social permalink is shortened. See [selection and limits](docs/AUTOMATIC-V8.43.md) and [v8.44 validation](docs/AUTOMATIC-DIRECT-V8.44.md).

With frontend 8.45 / backend 8.38, visible DOM players are represented as **MediaItems**. A single player keeps the compact view; multiple players open a caption/poster chooser with batch queueing. Each item owns its direct variants, observed HLS/DASH groups and extractor URL. Automatic compares only that item's sources. True YouTube/Vimeo embeds are supported; ordinary links/recommendations are ignored. See [MediaItem validation and limits](docs/MEDIA-ITEMS-V8.45.md).

Frontend **8.46** fixes selection and Wikimedia's source-less TimedMediaHandler placeholders. File identity attaches observed MP4/WebM transcodes, selection survives source/metadata updates, Select all becomes Deselect all, and unresolved items can be selected and rescanned when downloading. Backend **8.38** is unchanged. See [fix and validation](docs/MEDIA-SELECTION-V8.46.md).

Frontend **8.47** / backend **8.39** fixes selected MediaItem downloads: item-owned candidates supersede page extraction, unresolved Commons files use their dedicated extractor, and an independent DownloadPlan binds the selected formats and URLs through transfer. Checkbox selection also selects the target of the main Download button. WebM output keeps its container without unsupported cover embedding. See [cause and validation](docs/MEDIA-DOWNLOAD-V8.47.md).

Frontend **8.48** strengthens logical-media grouping: frame/document checks precede URL matches, subset source lists and declared master/variant relationships share one item, and ambiguous blob or metadata matches stay unassigned. Container/CDN/title alone never merge distinct players. Merge/reject logs explain each changed decision without URLs or tokens. Backend **8.39** and all existing detectors/downloaders are unchanged. See [strategy and validation](docs/MEDIA-GROUPING-V8.48.md).

Frontend **8.49** / backend **8.40** shares a private RequestContext across HLS, DASH and direct candidates: observed Referer/Origin/User-Agent, relevant session cookies and supported application headers pass through probes and transfer under an origin policy. Redirects cannot forward these credentials to another origin; variants keep their own context and public native responses omit private context. No per-site adapter is added. See [contract, validation and installation](docs/REQUEST-CONTEXT-V8.49.md).

Frontend **8.50** / backend **8.41** renews expired media URLs inside the existing downloader. Direct files require a matching strong ETag and size before Range resume. VOD HLS/DASH keep their original fragment iterator and ledger; fresh manifests supply addresses only after timeline and previously received segment validators match. Unknown identity preserves partial files and requests source resolution. See [source refresh and validation](docs/SOURCE-REFRESH-V8.50.md).

Frontend **8.52** / backend **8.46** adds shared video/audio/subtitle tracks to MediaItems. Automatic binds the best video to the requested audio language and optional captions, using only that item's candidates. Audio original prefers native audio without downloading video; direct containers support embedded audio selection by stream copy. Track controls appear only when useful and batch jobs keep independent preferences. See [model, tests and limits](docs/MEDIA-TRACKS-V8.51.md).

### License

Kitty Download Manager is licensed under the [GNU General Public License v3.0](LICENSE) (`GPL-3.0-only`). Third-party dependencies retain their own licenses; see [Third-party notices](THIRD-PARTY-NOTICES.md).

---

## Français

Téléchargez des vidéos, de l’audio et des miniatures depuis Firefox, avec une file d’attente, un historique et un bouton de téléchargement flottant. Ce dépôt fournit le backend local de Kitty, basé sur **yt-dlp** et **FFmpeg**.

### Installer le backend

Téléchargez le ZIP correspondant à votre système dans la [dernière release du backend](https://github.com/sususususmomo/kitty-download-manager-releases/releases/latest). Décompressez-le, ouvrez le dossier `kitty-download-manager` et lancez :

| Système | Installateur |
|---|---|
| Linux | `bash ./install.sh` dans un terminal |
| Windows x64 | Double-cliquer sur `Install.cmd` |
| macOS Intel / Apple Silicon | Double-cliquer sur `Install.command` |

Les installateurs Windows et macOS préparent des dépendances privées. Sous Linux, installez Python 3, yt-dlp, FFmpeg et Mutagen ; psutil et Deno sont recommandés.

Ouvrez Kitty dans Firefox : le backend installé est détecté automatiquement. **Image uniquement** récupère la miniature ou la pochette sans audio/vidéo, dans son format image d’origine.

**Extension Firefox :** nécessite Firefox 140 ou plus récent. La signature Mozilla est en attente. Pour un test temporaire, décompressez les [sources de l’extension](https://github.com/sususususmomo/kitty-download-manager-releases/releases/download/frontend-v8.38/kitty-download-manager-v8.38.zip), puis chargez `extension/manifest.json` depuis `about:debugging` → **Ce Firefox** → **Charger un module temporaire**.

Les sources en développement détectent les flux HLS, DASH et les fichiers vidéo/audio chargés par Firefox. Avec le backend 8.38, **Automatique** compare les métadonnées en parallèle puis télécharge une source adaptée à la qualité ou au mode audio choisi. Le choix manuel reste disponible. Automatic conserve désormais les médias détectés lorsque le permalink est raccourci. Voir [la sélection et ses limites](docs/AUTOMATIC-V8.43.md) et [la validation v8.44](docs/AUTOMATIC-DIRECT-V8.44.md).

Frontend **8.52** / backend **8.46** représente les pistes vidéo/audio/sous-titres de chaque MediaItem. Automatic associe la meilleure vidéo à la langue audio et aux sous-titres demandés. Le mode audio original privilégie un flux natif sans téléchargement vidéo inutile; les pistes intégrées des fichiers directs sont sélectionnées par copie. Les contrôles restent compacts et les préférences du batch sont propres à chaque média. Voir [le modèle, les tests et les limites](docs/MEDIA-TRACKS-V8.51.md).

### Licence

Kitty Download Manager est distribué sous la [licence publique générale GNU v3.0](LICENSE) (`GPL-3.0-only`). Les dépendances tierces conservent leurs propres licences ; voir les [notices des composants tiers](THIRD-PARTY-NOTICES.md).

## Windows installation folder / Dossier Windows

Backend 8.43 asks for the installation folder when you run `Install.cmd` (for example `D:\KittyDownloadManager`). Python, FFmpeg, Deno and setup temporary files are prepared on that drive. Subsequent runs propose the registered location. See [Windows instructions](README-Windows.md).

Le backend 8.43 demande le dossier à chaque lancement de `Install.cmd`, par exemple `D:\KittyDownloadManager`. Les dépendances et fichiers temporaires de préparation restent sur ce disque. Les relances proposent le dossier enregistré. Voir [les instructions Windows](README-Windows.md).

## Provider extraction / Extraction des sites (8.52 / 8.44)

Single-player YouTube and SoundCloud media pages retain their site extractor when network sources are attached. Metadata enrichment prefers the actual extracted title over a generic player label. Explicit galleries keep their own sources. Automatic error logs preserve a redacted technical reason. See [the regression report](docs/PROVIDER-MEDIA-V8.52.md).

Les pages YouTube/SoundCloud avec un seul lecteur conservent leur extracteur, même avec des flux détectés. Le titre réel remplace les libellés de lecteur. Les galeries restent isolées et les erreurs automatiques gardent un détail technique masqué. Voir [le rapport](docs/PROVIDER-MEDIA-V8.52.md).

## Windows reinstall (backend 8.45)

The Windows installer prepares each runtime in its final unique version directory, validates it and then activates it. It no longer renames a directory containing executables after the Firefox protocol checks, avoiding that WinError 5 failure. Settings, history and the previous runtime are retained. See [validation and limits](docs/WINDOWS-REINSTALL-V8.45.md).

## Windows Python runtime (backend 8.46)

The installer checks YouTube and postprocessor imports, the private package paths and yt-dlp wheel file integrity before activation. Initialization failures preserve their structured error instead of losing the technical reason. Diagnose.cmd checks the currently installed runtime without changing the queue or packages. See [validation and limits](docs/WINDOWS-RUNTIME-V8.46.md).

## Windows audit (backend 8.48 / frontend 8.54)

Private psutil API/integrity validation, safer process checks, serialized settings/session changes, bounded Windows sharing retries, percent-sign output paths and persistent session UI errors. Local tests passed; dedicated native Windows CI is prepared and awaits authorization to send the test commit. See [the audit and validation limits](docs/WINDOWS-AUDIT-V8.48.md).

Contrôle de l’API et de l’intégrité de psutil, vérification des processus sans fausse disparition, réglages/sessions simultanés protégés, conflits de partage Windows gérés, chemins avec `%` et erreurs de popup persistantes. Les tests locaux ont réussi ; la CI Windows dédiée attend l’autorisation d’envoyer le commit de test. Voir [l’audit et ses limites](docs/WINDOWS-AUDIT-V8.48.md).
