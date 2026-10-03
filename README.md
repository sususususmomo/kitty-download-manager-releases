# Kitty Download Manager — macOS v8.31

Première distribution macOS, pour Mac Intel et Apple Silicon. Le même ZIP choisit
les dépendances natives adaptées au Mac. Il exige macOS 13 Ventura ou plus récent
et une connexion Internet pendant l’installation. La validation GitHub Actions
est configurée sur macOS 15, pour les deux architectures.

## Installer sur un Mac

1. Décompresser `kitty-download-manager-v8.31-macos.zip`.
2. Ouvrir `Install.command`, ou lancer dans Terminal :

   ```sh
   cd ~/Downloads/kitty-download-manager
   /bin/bash ./Install.command
   ```

L’installation se fait avec le compte habituel, sans `sudo`, dans :

```text
~/Library/Application Support/KittyDownloadManager
```

Python, yt-dlp, Mutagen, psutil, FFmpeg, ffprobe et Deno sont privés à Kitty.
Homebrew et une installation préalable de Python ne sont pas nécessaires.
Les archives Python et les exécutables téléchargés sont vérifiés par SHA-256.
Les versions et sources téléchargées sont conservées dans la version installée.

Le manifeste Native Messaging de Firefox est enregistré à l’emplacement macOS :

```text
~/Library/Application Support/Mozilla/NativeMessagingHosts/com.kitty.download_manager.json
```

Dans Firefox : `about:debugging` → **Ce Firefox** → **Charger un module temporaire**,
puis choisir :

```text
~/Library/Application Support/KittyDownloadManager/extension/manifest.json
```

Le XPI fourni est **non signé** : cette installation temporaire doit être rechargée
après le redémarrage de Firefox. Une signature Mozilla reste nécessaire pour une
installation permanente. `Install.command` est un installateur Terminal ; cette
distribution n’est pas un paquet Apple `.pkg` signé et notarié.

## Mise à jour et désinstallation

Relancer `Install.command` depuis la nouvelle archive. L’installateur prépare
et vérifie la nouvelle version avant de la publier. Il met la file en pause et
arrête les workers Kitty dont l’identité a été vérifiée. Les réglages, cookies,
historique et fichiers téléchargés sont conservés. Recharger l’extension et
reprendre la file depuis Kitty après installation.

En cas d’échec de publication, le lanceur, le manifeste Firefox et l’extension
précédents sont restaurés. Les anciennes versions sont limitées à la version
courante et à la précédente, en conservant aussi un runtime encore utilisé.

Pour désinstaller, ouvrir `Uninstall.command` ou exécuter :

```sh
"$HOME/Library/Application Support/KittyDownloadManager/Uninstall.command"
```

La désinstallation enlève le backend, ses dépendances et l’enregistrement Firefox.
Les répertoires `config` et `cache`, ainsi que les téléchargements, sont conservés.
Supprimer l’extension séparément dans Firefox lorsqu’une version signée est utilisée.

## Validation GitHub Actions depuis Linux / fish

Le ZIP peut être extrait dans l’unique dossier `~/Downloads/kitty-download-manager`
déjà utilisé pour Windows. Conserver son répertoire Git. La commande ci-dessous
crée une branche macOS distincte, sans modifier la branche de tests Windows.

```fish
cd ~/Downloads
and test -f kitty-download-manager-v8.31-macos.zip
and test -d kitty-download-manager/.git
and unzip -o kitty-download-manager-v8.31-macos.zip
and cd kitty-download-manager
and rm -f -- kitty-download-manager-v8.28-unsigned.xpi kitty-download-manager-v8.29-unsigned.xpi
and git switch -c macos-test-v8.31-(date +%s)
and set kitty_login (gh api user --jq '.login')
and set kitty_account_id (gh api user --jq '.id')
and git add .
and git -c user.name="$kitty_login" \
    -c user.email="$kitty_account_id+$kitty_login@users.noreply.github.com" \
    -c commit.gpgsign=false \
    commit -m "Ajoute l installation macOS v8.31"
and git push -u origin HEAD
```

Dans **Actions**, ouvrir **Kitty macOS validation**. Les deux jobs macOS vérifient :

- l’installation complète avec les dépendances réellement téléchargées ;
- le lanceur natif et les réponses binaires de Firefox, avec un PATH minimal ;
- la bonne architecture de Python, Intel ou Apple Silicon ;
- la mise à jour et la conservation des réglages / historique ;
- le remux audio hors ligne et les chemins avec espaces, accents et apostrophes ;
- l’arrêt et l’annulation d’un vrai worker, sans téléchargement réseau ;
- la désinstallation avec conservation des données ;
- les captures de la vraie popup Firefox dans un profil CI isolé.

Les artifacts `kitty-macos-Intel-firefox-captures` et
`kitty-macos-Apple-Silicon-firefox-captures` contiennent les PNG, un `index.html`,
le diagnostic natif et les logs. Ils sont disponibles pendant 14 jours, même si
une étape échoue après la création de fichiers. Les captures montrent des états
stabilisés ; elles ne mesurent pas les flashs très brefs ni le sélecteur AppleScript.

Cette distribution reprend les sources communes et les tests Windows/Linux.
Les releases Windows v8.29 et Linux v8.24 restent des archives séparées.

## Sources techniques

- Emplacement du manifeste : https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests
- Python privé : https://github.com/astral-sh/python-build-standalone/releases/tag/20261001
- FFmpeg / ffprobe macOS : https://ffmpeg.martin-riedl.de/
- Deno : https://github.com/denoland/deno
- Runners GitHub : https://docs.github.com/en/actions/reference/runners/github-hosted-runners
