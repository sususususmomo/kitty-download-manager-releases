# Kitty Download Manager — publication publique Mozilla

L’extension Firefox v8.34 est le frontend. Les installateurs GitHub contiennent le backend v8.31, sans extension. Leurs versions peuvent évoluer séparément tant que le protocole natif reste compatible.

## Fichier à soumettre

Utilise `kitty-download-manager-v8.34-unsigned.xpi`, et choisis **On this site** pour une fiche publique sur addons.mozilla.org. Ce fichier contient uniquement les fichiers de `extension/`, avec `manifest.json` à la racine. N’envoie pas l’archive complète de développement ni un installateur backend.

L’extension n’est pas encore signée ou publiée. Le dépôt du XPI et les renseignements de la fiche se font depuis le compte Mozilla du propriétaire. Aucun secret API n’est nécessaire pour un dépôt manuel. La signature et l’examen Mozilla interviennent après soumission.

## Description proposée

Kitty Download Manager permet de télécharger des vidéos et des fichiers audio avec yt-dlp depuis Firefox. Choisis le format, ajoute une page ou une playlist à la file, suis les téléchargements et retrouve ton historique. Un bouton flottant et le menu contextuel permettent aussi d’ajouter un média depuis une page.

**Un backend local est nécessaire.** Après avoir installé l’extension, ouvre ses réglages et clique sur **Télécharger**. Kitty sélectionne l’installateur GitHub adapté à Linux, Windows x64 ou macOS. Décompresse l’archive, lance l’installateur indiqué, puis clique sur **Vérifier la connexion**. Le backend conserve les fichiers, la file et les réglages sur ton ordinateur.

## Liens du backend

- [Linux](https://github.com/sususususmomo/kitty-download-manager-releases/raw/refs/heads/backend-installers-v8.31/kitty-backend-v8.31-linux.zip)
- [Windows 10/11 x64](https://github.com/sususususmomo/kitty-download-manager-releases/raw/refs/heads/backend-installers-v8.31/kitty-backend-v8.31-windows-x64.zip)
- [macOS Intel / Apple Silicon](https://github.com/sususususmomo/kitty-download-manager-releases/raw/refs/heads/backend-installers-v8.31/kitty-backend-v8.31-macos.zip)

Ces fichiers sont hébergés dans une branche de distribution GitHub. Ils ne sont pas des assets ajoutés à l’ancienne release v8.18. Les liens sont publics et les empreintes figurent dans `SHA256SUMS` de cette branche.

## Notes aux reviewers — à copier dans AMO

This extension is the Firefox frontend of Kitty Download Manager. It requires a separately installed local native host (`com.kitty.download_manager`). Its settings show an explicit GitHub Download link for the current platform even when the native host is missing. Downloading does not execute the installer; users extract the archive and run the installer themselves. The extension never downloads or executes remote JavaScript.

To test: install the extension on Firefox 140 or later, open its toolbar popup, open Settings, download and install the linked backend, then click Check connection. Windows supports x64 Windows 10/11; macOS supports Intel and Apple Silicon. Windows/macOS installers prepare a private per-user Python, yt-dlp, FFmpeg and Deno. Linux uses an existing Python 3, yt-dlp, FFmpeg/ffprobe and Mutagen; on Arch/CachyOS the README provides package installation commands. The backend is registered only for `kitty-download-manager@local`.

The extension sends the URLs selected for downloads and requested download operations to this local native host. The host contacts the selected media websites to obtain metadata and download the media. The manifest declares required `websiteActivity` because Native Messaging transmission must be declared even when the receiver is local. Kitty does not send browsing history, analytics or telemetry to its developer. The separate privacy statement describes local history and optional YouTube sessions.

Source JavaScript is human-readable and included directly in the XPI; there is no minification, transpilation or external build step. The complete source and tests are available on the `frontend-test-v8.34-20261003` branch of the linked GitHub repository. `python tools/build-packages.py` creates the frontend XPI and the three backend-only ZIPs. Test harness files are included only in temporary CI XPIs, not in the distributed XPI.

## Confidentialité et permissions

Copie `docs/CONFIDENTIALITE.md` dans le champ de politique de confidentialité de la fiche si AMO le demande.

Firefox 140 minimum est déclaré pour le consentement intégré. `websiteActivity` est déclaré comme nécessaire : les URLs choisies sont transmises au backend local. Il ne faut donc pas sélectionner une déclaration « aucune transmission » dans le formulaire.

Permissions : `activeTab` pour la page sélectionnée, `menus` pour le menu contextuel, `nativeMessaging` pour le backend local, `storage` pour les préférences et `clipboardWrite` pour la copie volontaire du diagnostic. Les scripts de contenu recherchent localement les médias pour le bouton flottant sur les pages HTTP/HTTPS. Le lien d’installation fonctionne sans nouvelle permission de téléchargements ou de réseau pour l’extension.

La validation automatique et les tests de Firefox facilitent l’examen mais ne remplacent pas la décision de Mozilla.

## Résultat du validateur Mozilla

`web-ext 10.6.0` : **0 erreur, 13 avertissements**. Le rapport complet est fourni dans `docs/amo-lint-v8.34.json`.

Un avertissement concerne Firefox Android 140, où le champ de consentement est plus récent. Kitty cible Firefox sur ordinateur, puisque ses trois backends sont pour Linux, Windows et macOS. La soumission doit donc viser Firefox desktop, sans annoncer Android comme compatible.

Les douze autres avertissements concernent des affectations existantes à `innerHTML`. Le rendu a été relu : les titres, messages d’erreur, valeurs de diagnostic, URLs et attributs dynamiques sont encodés par `escapeHtml`; les positions sont produites comme des nombres validés dans `shared.js`. Les icônes et aperçus de styles proviennent de constantes locales. Il n’y a pas de HTML arbitraire fourni par un site ou de JavaScript externe exécuté. Ces avertissements restent dans le rapport pour l’examen humain; ils ne sont pas masqués par une configuration du validateur.
