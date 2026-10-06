# Kitty Download Manager — backend 8.47 Windows x64

Windows 10/11 x64 et Firefox. Aucun Python préinstallé ni droit administrateur requis. Une connexion Internet est nécessaire pour préparer les dépendances.

## Installation

1. Extraire `kitty-backend-v8.47-windows-x64.zip`.
2. Dans le dossier extrait `kitty-download-manager`, double-cliquer sur `Install.cmd`.
3. Saisir le dossier d’installation, par exemple `D:\KittyDownloadManager`, puis appuyer sur Entrée. Entrée sans texte conserve le dossier proposé.
4. Attendre le message **Installation terminee**. Rouvrir Kitty dans Firefox et utiliser **Vérifier la connexion** dans les réglages.

La correction complète utilise le backend 8.47 et l’extension 8.53. L’archive backend seule ne contient pas l’extension. Avec l’archive complète v8.53, lancer Install.cmd puis charger ou recharger extension/manifest.json dans about:debugging → Ce Firefox.

## Session YouTube sous Windows

Le backend 8.47 retire le refus de Windows dans la configuration de session. Dans Kitty → Réglages → Cookies, cliquer sur Configurer YouTube. Une fenêtre Firefox dédiée utilise un profil temporaire et des dossiers USERPROFILE/APPDATA/LOCALAPPDATA séparés. Se connecter à YouTube, ouvrir youtube.com/robots.txt dans le même onglet, fermer cette fenêtre puis rouvrir Kitty. Kitty conserve uniquement les cookies du domaine YouTube et supprime le profil temporaire. La fenêtre Firefox habituelle peut rester ouverte.

L’extension 8.53 conserve les erreurs de configuration à l’écran et réactive le bouton pour réessayer. Une ancienne réponse d’état ne peut plus effacer le résultat de la tentative. Un échec de renouvellement conserve la session précédente.

Tests du correctif : cinq scénarios Python hors réseau et scénarios Node de réponses différées, erreurs et nouvelle tentative. Le lancement de Firefox est simulé ici ; l’ouverture et la connexion réelles sous Windows restent à vérifier. Voir docs/WINDOWS-YOUTUBE-SESSION-V8.47.md.

Depuis le backend 8.46, l’installateur vérifie les imports YouTube, réseau et post-traitement, les empreintes des fichiers Python de yt-dlp, et l’origine privée des paquets. Ces contrôles ont lieu après pip puis avant l’activation du backend. Une installation incomplète est refusée avec un détail explicite.

En cas de `No module named 'yt_dlp.postprocessor'`, relancer l’installation depuis cette archive pour préparer un nouveau runtime. `Diagnose.cmd` dans l’archive examine le backend actuellement enregistré, sans télécharger ni modifier les paquets, les cookies ou la file. Copier sa sortie si l’erreur persiste ; elle indique la version active, les chemins de chargement et les fichiers manquants/modifiés.

Python privé, yt-dlp, Mutagen, psutil, FFmpeg/ffprobe, Deno, configuration et historique résident dans le dossier choisi. Le stage, le Python de préparation et les fichiers temporaires de pip restent sur ce disque. Les variables temporaires ne sont modifiées que pour le processus d’installation, puis restaurées.

Le dossier choisi doit être dédié à Kitty, sur un disque local NTFS ou ReFS, avec au moins 2 Gio libres pour la préparation. Les dossiers non vides sans marqueur Kitty, les racines de disque et les chemins contenant une jonction ou un lien sont refusés avant la création des fichiers.

Le dossier des vidéos/audio est un réglage indépendant : le dossier Téléchargements de Windows reste proposé par défaut. Avec C: plein, choisir aussi un dossier sur D: dans les réglages Kitty pour les prochains médias.

## Commande avec dossier explicite

Depuis le dossier extrait, dans PowerShell :

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -InstallDir 'D:\KittyDownloadManager'
```

`-NonInteractive` permet de réutiliser le dossier enregistré, ou le dossier par défaut, sans demande de saisie. Il est utilisé par la CI.

## Mise à jour et changement de disque

Extraire la nouvelle archive dans un dossier distinct de l’installation, puis relancer `Install.cmd`. Le dossier déjà enregistré est proposé. La mise à jour sur place conserve les réglages et l’historique.

Depuis le backend 8.45, le nouveau runtime est préparé directement dans son dossier unique `versions/8.48-…`, sans renommer ce dossier après les vérifications. Le lanceur ne l’active qu’une fois le protocole Firefox validé. Cela retire l’opération `stage-… → versions/…` qui échouait avec `WinError 5`. En cas d’échec, l’ancien runtime reste actif et la file reste en pause.

En choisissant un autre dossier, l’installateur met en pause l’ancienne file, arrête les tâches selon les contrôles existants, copie configuration/cache et enregistre le nouveau backend pour Firefox. Les réglages, cookies et historique sont copiés. Les fichiers téléchargés restent à leur emplacement et le dossier de sortie configuré reste identique. La file reste en pause après l’installation : la reprendre dans Kitty.

L’ancien dossier est conservé après le changement de disque. Si la copie, la validation du backend ou l’enregistrement échoue, l’ancien backend reste enregistré et les copies nouvelles sont retirées. Un déplacement vers un dossier avec des données Kitty existantes est refusé pour éviter leur écrasement.

## Désinstallation

Utiliser Applications installées → Kitty Download Manager → Désinstaller, ou `Uninstall.cmd` dans le dossier choisi. Les réglages, l’historique, les téléchargements et le marqueur d’emplacement sont conservés.

## Audit Windows 8.48 / extension 8.54

Cette version vérifie l’API et l’intégrité de psutil, protège les réglages simultanés, gère les conflits de partage de fichiers Windows et les chemins contenant `%`, et stabilise la configuration/suppression des sessions YouTube et leurs erreurs dans la popup. Réinstaller avec `Install.cmd` pour remplacer les dépendances privées puis recharger l’extension 8.54.

Les tests locaux et simulations ont réussi. La CI sur les deux Windows dédiés est préparée mais n’a pas été exécutée : l’autorisation d’envoyer le commit GitHub reste nécessaire. Consulter `docs/WINDOWS-AUDIT-V8.48.md` dans l’archive complète pour chaque problème, les scénarios, les preuves disponibles et les limites.

## Validations historiques

Validation de la correction 8.45 exécutée sur Linux : 12 tests de dossier/migration/rollback et 30 tests portables Windows réussis, ainsi que 3 tests de packaging/installation Linux. Cinq tests natifs Windows sont ignorés ici. Les 95 contrôles de régression avaient réussi lors de la correction précédente 8.44.

La validation native PowerShell et la vraie installation Windows ne sont pas exécutables dans cet environnement. Le workflow `.github/workflows/windows-validation.yml` inclut la validation des chemins en PowerShell 5.1, une installation dans un dossier distinct de LOCALAPPDATA contenant espaces et caractères spéciaux, une réinstallation dans un dossier de version définitif et un test avec un vrai handle Win32 qui bloque le renommage. Ce workflow reste à lancer pour cette modification. Voir `docs/WINDOWS-REINSTALL-V8.46.md` dans l’archive complète.

Validation 8.46 : 7 tests des paquets/imports et erreurs structurées, 12 tests d’installation, 6 tests des limites de durée et 95 contrôles de régression réussis. La vraie installation Windows et le diagnostic PowerShell restent à exécuter sur Windows. Voir `docs/WINDOWS-RUNTIME-V8.46.md`.
