(() => {
  const VALID_LANGUAGES = new Set(["fr", "en"]);
  const FR_EN = Object.freeze(
{
  "Lancer le diagnostic": "Run diagnostics",
  "Fichiers du backend :": "Backend files:",
  "Mise à jour Kitty :": "Kitty update:",
  "Mises à jour des dépendances :": "Dependency updates:",
  "« Vérifier les mises à jour » utilise le réseau uniquement quand tu le demandes pour comparer Kitty et les dépendances.": "Check updates uses the network only when you ask to compare Kitty and its dependencies.",
  "Le diagnostic normal reste entièrement local : aucune URL, aucun titre et aucun cookie ne sont copiés.": "Normal diagnostics stay entirely local: no URL, title or cookie is copied.",
  "Backend Kitty": "Kitty backend",
  "Vérification de la connexion…": "Checking connection…",
  "Backend connecté": "Backend connected",
  "Backend non installé": "Backend not installed",
  "Connexion au backend impossible": "Cannot connect to backend",
  "Backend à mettre à jour": "Backend update required",
  "Installer le backend Kitty": "Install the Kitty backend",
  "Le backend est nécessaire pour télécharger tes médias.": "The backend is required to download your media.",
  "Configurer Kitty": "Set up Kitty",
  "Le backend s’installe sur ton ordinateur et effectue les téléchargements.": "The backend is installed on your computer and downloads your media.",
  "Vérifier la connexion": "Check connection",
  "Après l’installation, rouvre Kitty ou clique sur Vérifier la connexion.": "After installation, reopen Kitty or click Check connection.",
  "Décompresse l’archive, puis lance install.sh dans un terminal.": "Extract the archive, then run install.sh in a terminal.",
  "Décompresse l’archive, puis double-clique sur Install.cmd.": "Extract the archive, then double-click Install.cmd.",
  "Décompresse l’archive, puis double-clique sur Install.command.": "Extract the archive, then double-click Install.command.",
  "Aucun installateur disponible pour ce système.": "No installer is available for this system.",
  "Ouvre les réglages pour installer le backend ou vérifier la connexion.": "Open Settings to install the backend or check the connection.",
  "Installe le backend depuis les réglages pour commencer.": "Install the backend from Settings to get started.",
  "Le backend Kitty ne répond pas. Vérifie la connexion dans les réglages.": "The Kitty backend is not responding. Check the connection in Settings.",
  "Réglages": "Settings",
  "Ouvrir les réglages": "Open settings",
  "Retour": "Back",
  "Téléchargement": "Download",
  "Prêt": "Ready",
  "Prêt.": "Ready.",
  "En file": "Queued",
  "En pause": "Paused",
  "Pause": "Paused",
  "En cours": "In progress",
  "Téléchargé": "Downloaded",
  "Terminé": "Done",
  "Déjà téléchargé": "Already downloaded",
  "Déjà présent": "Already present",
  "Erreur": "Error",
  "Annulé": "Cancelled",
  "Télécharger": "Download",
  "Télécharger cette page": "Download this page",
  "Masquer sur cette page": "Hide on this page",
  "Masquer": "Hide",
  "Retélécharger quand même": "Download again anyway",
  "Téléchargement dans la file": "Download queued",
  "Récupération des métadonnées": "Fetching metadata",
  "Récupération des métadonnées…": "Fetching metadata…",
  "Métadonnées": "Metadata",
  "Métadonnées…": "Metadata…",
  "Téléchargement en cours": "Downloading",
  "Téléchargement terminé": "Download complete",
  "Vidéo non détectée": "Video not detected",
  "Impossible de détecter la vidéo.": "Could not detect the video.",
  "Relance…": "Retrying…",
  "Ajout…": "Adding…",
  "Nouveau téléchargement…": "New download…",
  "Démarrage…": "Starting…",
  "Annulation et nettoyage du fichier partiel…": "Cancelling and cleaning the partial file…",
  "Aucun téléchargement actif": "No active download",
  "Titre indisponible": "Title unavailable",
  "Récupération du titre…": "Fetching title…",
  "Dernier téléchargement réussi": "Last download succeeded",
  "Dernier téléchargement en erreur": "Last download failed",
  "Vidéo — jusqu’à 1080p": "Video — up to 1080p",
  "Vidéo — jusqu’à 720p": "Video — up to 720p",
  "Vidéo — meilleure qualité": "Video — best quality",
  "Audio — format original": "Audio — original format",
  "Audio — MP3": "Audio — MP3",
  "Meilleure qualité": "Best quality",
  "Ajouter au téléchargement": "Add download",
  "Ajouter la playlist": "Add playlist",
  "Annuler": "Cancel",
  "📁 Dossier": "📁 Folder",
  "File d’attente": "Queue",
  "Historique": "History",
  "Vider la file": "Clear queue",
  "Effacer l’historique": "Clear history",
  "Vide": "Empty",
  "La file est vide.": "The queue is empty.",
  "La file d’attente est déjà vide.": "The queue is already empty.",
  "Reprendre la file": "Resume queue",
  "Mettre la file en pause": "Pause queue",
  "⏸ File": "⏸ Queue",
  "▶ File": "▶ Queue",
  "prochain": "next",
  "prioritaire": "priority",
  "file": "queue",
  "pause": "paused",
  "Playlist": "Playlist",
  "Utiliser le format sélectionné": "Use selected format",
  "URL de la playlist / collection": "Playlist / collection URL",
  "Entre une URL HTTP/HTTPS valide.": "Enter a valid HTTP/HTTPS URL.",
  "✓ Playlist YouTube prête": "✓ YouTube playlist ready",
  "✓ URL YouTube prête · yt-dlp vérifiera la collection": "✓ YouTube URL ready · yt-dlp will verify the collection",
  "✓ URL SoundCloud prête · profil, playlist ou collection": "✓ SoundCloud URL ready · profile, playlist or collection",
  "✓ URL de collection prête · yt-dlp vérifiera son contenu": "✓ Collection URL ready · yt-dlp will verify its contents",
  "✓ URL prête · yt-dlp vérifiera si c’est une collection": "✓ URL ready · yt-dlp will check whether it is a collection",
  "Colle d’abord l’URL de la playlist.": "Paste the playlist URL first.",
  "URL de playlist ou collection invalide.": "Invalid playlist or collection URL.",
  "Lecture de la collection…": "Reading collection…",
  "Analyse de la collection avec yt-dlp…": "Analyzing collection with yt-dlp…",
  "Collection": "Collection",
  "Aucun nouvel élément à ajouter.": "No new items to add.",
  "Ce téléchargement est déjà pris en charge.": "This download is already being handled.",
  "Ce média a déjà été téléchargé": "This media has already been downloaded",
  "Déjà téléchargé — clique à nouveau pour le retélécharger.": "Already downloaded — click again to download it again.",
  "Langue": "Language",
  "Langue de l’interface": "Interface language",
  "Change uniquement les textes affichés": "Only changes displayed text",
  "Destination": "Destination",
  "Dossier de destination": "Destination folder",
  "Chargement…": "Loading…",
  "Le backend Kitty ne répond pas.": "The Kitty backend is not responding.",
  "Choisir…": "Choose…",
  "Les nouveaux jobs utilisent ce dossier. Les jobs déjà en file gardent leur destination.": "New jobs use this folder. Jobs already queued keep their original destination.",
  "Pill flottant": "Floating pill",
  "Afficher le pill": "Show pill",
  "Bouton de téléchargement sur les pages": "Download button on pages",
  "Afficher sur": "Show on",
  "Tous les sites": "All sites",
  "Sites médias connus": "Known media sites",
  "Où afficher le pill flottant": "Where to show the floating pill",
  "Style": "Style",
  "Apparence du pill sur les pages": "Pill appearance on pages",
  "Choisir le style du pill": "Choose pill style",
  "Style du pill": "Pill style",
  "Minimal": "Minimal",
  "Kitty": "Kitty",
  "Classique": "Classic",
  "Cookies": "Cookies",
  "Session dédiée YouTube": "Dedicated YouTube session",
  "Configurer YouTube…": "Set up YouTube…",
  "Supprimer": "Delete",
  "Utiliser la session": "Use session",
  "Uniquement pour les téléchargements YouTube": "Only for YouTube downloads",
  "Utiliser la session YouTube dédiée": "Use dedicated YouTube session",
  "Kitty crée un Firefox jetable totalement séparé de ton profil habituel. Aucun mot de passe Firefox n'est importé.": "Kitty creates a disposable Firefox completely separate from your regular profile. No Firefox passwords are imported.",
  "Dépendances": "Dependencies",
  "Vérification…": "Checking…",
  "Actualiser": "Refresh",
  "Lecture…": "Reading…",
  "Python, yt-dlp, ffmpeg et ffprobe sont requis. Mutagen est recommandé pour l’intégration des pochettes.": "Python, yt-dlp, ffmpeg and ffprobe are required. Mutagen is recommended for artwork embedding.",
  "Diagnostic": "Diagnostics",
  "Espace libre :": "Free space:",
  "Native Host :": "Native Host:",
  "État :": "Status:",
  "Compatibilité :": "Compatibility:",
  "Mises à jour :": "Updates:",
  "Migration :": "Migration:",
  "Vérifier Kitty maintenant": "Check Kitty now",
  "Vérifier les mises à jour": "Check for updates",
  "Télécharger la mise à jour": "Download update",
  "Version Kitty :": "Kitty version:",
  "Dernière release :": "Latest release:",
  "Dernière release": "Latest release",
  "État release Kitty": "Kitty release status",
  "non vérifiée": "not checked",
  "À jour": "Up to date",
  "Mise à jour disponible": "Update available",
  "Version locale plus récente": "Local version is newer",
  "Non vérifiée": "Not checked",
  "SHA-256 vérifié": "SHA-256 verified",
  "Téléchargement de la mise à jour Kitty…": "Downloading Kitty update…",
  "Archive de mise à jour téléchargée et SHA-256 vérifié.": "Update archive downloaded and SHA-256 verified.",
  "Vérification de la mise à jour Kitty impossible": "Could not check for a Kitty update",
  "Vérifie ta connexion Internet puis réessaie depuis Diagnostic.": "Check your Internet connection and try again from Diagnostics.",
  "Aucune mise à jour Kitty disponible": "No Kitty update available",
  "La version installée est déjà à jour ou plus récente que la dernière release publiée.": "The installed version is already up to date or newer than the latest published release.",
  "SHA-256 de la release indisponible": "Release SHA-256 unavailable",
  "Kitty refuse de télécharger une release qui ne peut pas être vérifiée.": "Kitty refuses to download a release that cannot be verified.",
  "Vérification SHA-256 échouée": "SHA-256 verification failed",
  "L’archive reçue ne correspond pas au hash publié par GitHub et a été rejetée.": "The received archive does not match the hash published by GitHub and was rejected.",
  "Téléchargement de la mise à jour impossible": "Could not download the update",
  "Réessaie depuis Diagnostic. Aucun fichier non vérifié n’est conservé.": "Try again from Diagnostics. No unverified file is kept.",
  "Ouvrir les logs": "Open logs",
  "Copier le diagnostic": "Copy diagnostics",
  "Le diagnostic normal reste entièrement local : aucune URL, aucun titre et aucun cookie ne sont copiés. « Vérifier les mises à jour » utilise le réseau uniquement quand tu le demandes pour comparer Kitty et les dépendances.": "Normal diagnostics stay entirely local: no URL, title or cookie is copied. “Check for updates” only uses the network when you explicitly request checks for Kitty and dependency versions.",
  "Maintenance": "Maintenance",
  "Réinitialiser Kitty": "Reset Kitty",
  "Arrête le job actif, nettoie son fichier partiel et vide file + historique. Les vidéos terminées et tes réglages restent intacts.": "Stops the active job, cleans its partial file and clears queue + history. Completed media and your settings stay untouched.",
  "Cookies actifs": "Cookies active",
  "Cookies inactifs": "Cookies inactive",
  "Configuration": "Setup",
  "Renouvellement en cours · ancienne session conservée": "Renewal in progress · previous session preserved",
  "Fenêtre Firefox dédiée ouverte": "Dedicated Firefox window open",
  "Firefox dédié ouvert": "Dedicated Firefox open",
  "Dans cette fenêtre : connecte-toi à YouTube, ouvre youtube.com/robots.txt dans le même onglet, puis ferme Firefox. Rouvre ensuite Kitty.": "In that window: sign in to YouTube, open youtube.com/robots.txt in the same tab, then close Firefox. Reopen Kitty afterwards.",
  "Finalisation": "Finalizing",
  "Firefox est fermé · préparation du snapshot…": "Firefox is closed · preparing snapshot…",
  "Finalisation…": "Finalizing…",
  "Kitty attend que Firefox ait terminé ses dernières écritures avant de lire les cookies.": "Kitty waits for Firefox to finish its last writes before reading cookies.",
  "Ancienne session OK": "Previous session OK",
  "Configuration incomplète": "Incomplete setup",
  "Renouveler…": "Renew…",
  "Recommencer…": "Try again…",
  "L'ancien snapshot n'est jamais remplacé si une nouvelle configuration échoue.": "The previous snapshot is never replaced if a new setup fails.",
  "Active": "Active",
  "Prête": "Ready",
  "Snapshot disponible": "Snapshot available",
  "Le profil de connexion jetable a été supprimé. Seul le snapshot YouTube filtré reste, en permissions privées.": "The disposable login profile has been deleted. Only the filtered YouTube snapshot remains, with private permissions.",
  "Non configurée": "Not configured",
  "Aucune session YouTube dédiée": "No dedicated YouTube session",
  "Kitty ouvre un Firefox jetable dans un HOME séparé. Ton profil Firefox habituel n'est ni lu, ni copié, ni modifié.": "Kitty opens a disposable Firefox in a separate HOME. Your regular Firefox profile is never read, copied or modified.",
  "Ouverture d'un Firefox YouTube isolé…": "Opening an isolated YouTube Firefox…",
  "Firefox dédié ouvert. Termine la connexion dans cette fenêtre.": "Dedicated Firefox opened. Finish signing in there.",
  "Session YouTube activée.": "YouTube session enabled.",
  "Session YouTube désactivée.": "YouTube session disabled.",
  "Confirmer": "Confirm",
  "Clique une seconde fois pour supprimer uniquement la session YouTube Kitty.": "Click a second time to delete only Kitty’s YouTube session.",
  "Session YouTube Kitty supprimée.": "Kitty YouTube session deleted.",
  "Dépendances prêtes": "Dependencies ready",
  "Dépendance optionnelle manquante": "Optional dependency missing",
  "Dépendance requise manquante": "Required dependency missing",
  "État des dépendances inconnu": "Dependency status unknown",
  "Kitty nécessite une intervention": "Kitty needs attention",
  "Prêt · optionnel manquant": "Ready · optional component missing",
  "Prêt · attention": "Ready · attention needed",
  "Toutes les dépendances sont prêtes": "All dependencies are ready",
  "indisponible": "unavailable",
  "requis · absent": "required · missing",
  "optionnel · absent": "optional · missing",
  "testée ✓": "tested ✓",
  "fichier manquant": "missing file",
  "queue OK": "queue OK",
  "installation fraîche": "fresh install",
  "aucune détectée": "none detected",
  "non vérifiées": "not checked",
  "Diagnostic indisponible": "Diagnostics unavailable",
  "Actualisation de l’état système…": "Refreshing system status…",
  "État système actualisé.": "System status refreshed.",
  "Auto-test local de Kitty…": "Running local Kitty self-test…",
  "Auto-test terminé : une intervention est nécessaire.": "Self-test complete: action is required.",
  "Auto-test terminé : Kitty fonctionne avec un avertissement.": "Self-test complete: Kitty is working with a warning.",
  "Auto-test terminé : tout est prêt.": "Self-test complete: everything is ready.",
  "Vérification réseau des mises à jour…": "Checking updates over the network…",
  "Dépendances à jour avec les sources disponibles.": "Dependencies are up to date according to available sources.",
  "Ouverture des logs…": "Opening logs…",
  "Logs ouverts.": "Logs opened.",
  "Préparation du diagnostic local…": "Preparing local diagnostics…",
  "Diagnostic copié · sans URL, titre ni cookie.": "Diagnostics copied · no URL, title or cookie included.",
  "Confirmer la réinitialisation": "Confirm reset",
  "Clique une seconde fois pour confirmer.": "Click a second time to confirm.",
  "Réinitialisation de Kitty…": "Resetting Kitty…",
  "Kitty a été réinitialisé. Tes vidéos et réglages sont conservés.": "Kitty has been reset. Your media and settings are preserved.",
  "Dossier inconnu": "Unknown folder",
  "Destination indisponible": "Destination unavailable",
  "Choisis le nouveau dossier…": "Choose the new folder…",
  "Dossier de destination mis à jour.": "Destination folder updated.",
  "Réglage du pill mis à jour.": "Pill setting updated.",
  "Impossible d'enregistrer le réglage du pill.": "Could not save the pill setting.",
  "Portée du pill mise à jour.": "Pill scope updated.",
  "Impossible d'enregistrer la portée du pill.": "Could not save the pill scope.",
  "Impossible d'enregistrer le style du pill.": "Could not save the pill style.",
  "Langue de l’interface mise à jour.": "Interface language updated.",
  "URL HTTP/HTTPS requise.": "HTTP/HTTPS URL required.",
  "Kitty doit être mise à jour": "Kitty needs to be updated",
  "Mets à jour le backend puis recharge Firefox.": "Update the backend, then reload Firefox.",
  "Lance l’updater puis recharge l’extension.": "Run the updater, then reload the extension.",
  "Erreur du backend": "Backend error",
  "Impossible d'ajouter le téléchargement.": "Could not add the download.",
  "Impossible d’ajouter cette playlist.": "Could not add this playlist.",
  "Impossible de vider la file.": "Could not clear the queue.",
  "Impossible de modifier la file.": "Could not modify the queue.",
  "Impossible d'ouvrir le dossier.": "Could not open the folder.",
  "Impossible d'ouvrir les logs.": "Could not open the logs.",
  "Impossible de lire les réglages.": "Could not read settings.",
  "Impossible de choisir le dossier.": "Could not choose the folder.",
  "Impossible de créer la session YouTube.": "Could not create the YouTube session.",
  "Impossible de modifier la session YouTube.": "Could not change the YouTube session.",
  "Suppression impossible.": "Could not delete.",
  "Réinitialisation impossible.": "Could not reset Kitty.",
  "Vérification des mises à jour impossible.": "Could not check for updates.",
  "Impossible de copier dans le presse-papiers.": "Could not copy to the clipboard.",
  "Aucun flux audio disponible": "No audio stream available",
  "Aucun flux vidéo disponible": "No video stream available",
  "Session YouTube expirée": "YouTube session expired",
  "Espace disque insuffisant": "Not enough disk space",
  "ffmpeg introuvable": "ffmpeg not found",
  "ffprobe introuvable": "ffprobe not found",
  "yt-dlp introuvable": "yt-dlp not found",
  "Vidéo privée": "Private video",
  "Contenu supprimé": "Content deleted",
  "Collection vide": "Empty collection",
  "Connexion interrompue": "Connection interrupted",
  "Trop de requêtes": "Too many requests",
  "Accès refusé par le site": "Access denied by site",
  "Connexion au site requise": "Site login required",
  "Contenu indisponible dans cette région": "Content unavailable in this region",
  "Contenu soumis à une restriction d’âge": "Age-restricted content",
  "Contenu protégé par DRM": "DRM-protected content",
  "Site ou URL non pris en charge": "Unsupported site or URL",
  "URL invalide": "Invalid URL",
  "Format demandé indisponible": "Requested format unavailable",
  "Fichier média invalide": "Invalid media file",
  "Permission refusée": "Permission denied",
  "Dossier de destination indisponible": "Destination folder unavailable",
  "État de la file endommagé": "Queue state is damaged",
  "Composant Kitty manquant": "Kitty component missing",
  "Firefox introuvable": "Firefox not found",
  "Session YouTube non configurée": "YouTube session not configured",
  "Fenêtre YouTube encore ouverte": "YouTube window still open",
  "Téléchargement déjà en cours": "Download already active",
  "Déjà dans la file": "Already queued",
  "Téléchargement introuvable": "Download not found",
  "Relance impossible": "Retry unavailable",
  "Élément introuvable dans la file": "Queue item not found",
  "Le téléchargement actif a changé": "The active download changed",
  "Pause du téléchargement actif indisponible": "Pausing the active download is unavailable",
  "Impossible d’ouvrir le dossier": "Could not open folder",
  "Impossible d’ouvrir les logs": "Could not open logs",
  "Traitement final impossible": "Final processing failed",
  "Métadonnées indisponibles": "Metadata unavailable",
  "Impossible d’analyser ce contenu": "Could not analyze this content",
  "Action non prise en charge": "Unsupported action",
  "Ce contenu ne fournit aucun flux audio téléchargeable.": "This content does not provide a downloadable audio stream.",
  "Ce contenu ne fournit aucun flux vidéo téléchargeable.": "This content does not provide a downloadable video stream.",
  "Renouvelle la session dédiée YouTube dans les réglages.": "Renew the dedicated YouTube session in Settings.",
  "Libère de l’espace dans le dossier de destination puis relance.": "Free some space in the destination folder, then retry.",
  "Installe ffmpeg puis relance Kitty.": "Install ffmpeg, then restart Kitty.",
  "Installe ffmpeg/ffprobe puis relance Kitty.": "Install ffmpeg/ffprobe, then restart Kitty.",
  "Installe le module Python yt-dlp puis relance Kitty.": "Install the yt-dlp Python module, then restart Kitty.",
  "Ce contenu n’est pas accessible avec la session actuelle.": "This content is not accessible with the current session.",
  "Le média n’est plus disponible sur le site source.": "The media is no longer available on the source site.",
  "Aucun média accessible n’a été trouvé dans cette collection.": "No accessible media was found in this collection.",
  "Vérifie la connexion Internet puis relance le téléchargement.": "Check your Internet connection, then retry the download.",
  "Le site demande de ralentir. Attends un peu avant de relancer.": "The site is asking you to slow down. Wait a little before retrying.",
  "Le serveur a refusé la requête. Une session ou un nouvel essai peut être nécessaire.": "The server rejected the request. A session or another attempt may be required.",
  "Ce contenu nécessite une session authentifiée.": "This content requires an authenticated session.",
  "Le site bloque ce média dans ta région.": "The site blocks this media in your region.",
  "Une session authentifiée autorisée peut être nécessaire.": "An authorized authenticated session may be required.",
  "Kitty Download Manager ne peut pas télécharger un média protégé par DRM.": "Kitty Download Manager cannot download DRM-protected media.",
  "yt-dlp ne reconnaît pas cette URL comme un média téléchargeable.": "yt-dlp does not recognize this URL as downloadable media.",
  "Vérifie l’adresse puis réessaie.": "Check the address, then try again.",
  "Essaie un autre format de téléchargement.": "Try another download format.",
  "Le site n’a pas produit de fichier audio/vidéo exploitable.": "The site did not produce a usable audio/video file.",
  "Kitty Download Manager ne peut pas écrire dans le dossier concerné.": "Kitty Download Manager cannot write to the target folder.",
  "Choisis un dossier de destination accessible en écriture.": "Choose a writable destination folder.",
  "Kitty Download Manager a rencontré un problème avec son état local. Consulte les logs.": "Kitty Download Manager encountered a problem with its local state. Check the logs.",
  "Réinstalle Kitty Download Manager pour restaurer le worker local.": "Reinstall Kitty Download Manager to restore the local worker.",
  "Firefox n’a pas été trouvé pour créer la session YouTube dédiée.": "Firefox was not found to create the dedicated YouTube session.",
  "Configure d’abord la session dédiée YouTube dans les réglages.": "Set up the dedicated YouTube session in Settings first.",
  "Ferme la fenêtre Firefox dédiée puis réessaie.": "Close the dedicated Firefox window, then try again.",
  "Ce média est déjà le téléchargement actif.": "This media is already the active download.",
  "Ce média attend déjà dans la file de téléchargement.": "This media is already waiting in the download queue.",
  "Ce média existe déjà dans l’historique pour ce format et cette destination.": "This media already exists in history for this format and destination.",
  "Cette entrée n’existe plus dans l’historique.": "This entry no longer exists in history.",
  "Seuls les téléchargements en erreur peuvent être relancés.": "Only failed downloads can be retried.",
  "La file a probablement changé depuis l’affichage.": "The queue has probably changed since it was displayed.",
  "Il n’y a actuellement aucun téléchargement à modifier.": "There is currently no active download to modify.",
  "Actualise l’état puis réessaie.": "Refresh the state, then try again.",
  "Kitty Download Manager désactive cette pause pour éviter les reprises HTTP instables.": "Kitty Download Manager disables this pause to avoid unstable HTTP resumes.",
  "Aucun gestionnaire de fichiers compatible n’a pu être lancé.": "No compatible file manager could be launched.",
  "Ouvre manuellement ~/.cache/kitty-download-manager/worker.log.": "Open ~/.cache/kitty-download-manager/worker.log manually.",
  "ffmpeg n’a pas pu finaliser ou convertir le média.": "ffmpeg could not finalize or convert the media.",
  "Le titre n’a pas pu être récupéré.": "The title could not be retrieved.",
  "Le site a changé ou yt-dlp n’a pas pu extraire les informations du média.": "The site changed or yt-dlp could not extract the media information.",
  "Cette action n’est pas disponible dans cette version de Kitty Download Manager.": "This action is not available in this version of Kitty Download Manager.",
  "Frontend et backend ne sont pas compatibles. Mets à jour Kitty puis recharge l’extension Firefox.": "Frontend and backend are incompatible. Update Kitty, then reload the Firefox extension.",
  "Consulte les logs pour le détail technique.": "Check the logs for technical details.",
  "Afficher le pill flottant": "Show floating pill",
  "Destination :": "Destination:",
  "Cache :": "Cache:",
  "Logs :": "Logs:",
  "Récupérable :": "Reclaimable:",
  "Partiels orphelins :": "Orphan partials:",
  "Cache local": "Local cache",
  "Nettoyer le cache": "Clean cache",
  "Supprime uniquement les fichiers temporaires Kitty, anciens backups d’update, snapshots temporaires inutiles et anciens logs. Les téléchargements et fichiers .part ne sont jamais supprimés.": "Removes only Kitty temporary files, old update backups, unused temporary snapshots and old logs. Downloads and .part files are never deleted.",
  "Nettoyage du cache…": "Cleaning cache…",
  "Nettoyage du cache impossible.": "Could not clean the cache.",
  "Rien à nettoyer dans le cache.": "Nothing to clean in the cache.",
  "aucun détecté": "none detected",
  "rien à nettoyer": "nothing to clean",
  "récupérables": "reclaimable",
  "conservé": "kept",
  "conservés": "kept",
  "libérés": "freed",
  "supprimé": "removed",
  "supprimés": "removed",
  "anciens logs": "old logs",
  "snapshots temporaires": "temporary snapshots",
  "fichiers temporaires": "temporary files",
  "Backups update": "Update backups",
  "Cache total": "Total cache",
  "Cache récupérable": "Reclaimable cache",
  "Cache temporaire": "Temporary cache",
  "Logs total": "Total logs",
  "Partiels orphelins": "Orphan partials",
  "non supprimés": "not deleted",
  "Test écriture destination": "Destination write test",
  "Mises à jour dépendances": "Dependency updates",
  "Mises à jour à vérifier": "Updates to review",
  "État global": "Overall status",
  "Protocole frontend/backend": "Frontend/backend protocol",
  "Compatibilité frontend/backend": "Frontend/backend compatibility",
  "Migration destination": "Destination migration",
  "Espace libre": "Free space",
  "Backups état": "State backups",
  "Confidentialité diagnostic:": "Diagnostics privacy:",
  "- aucun accès réseau": "- no network access",
  "- aucune URL/titre de téléchargement": "- no download URL/title",
  "- aucune valeur de cookie": "- no cookie values",
  "Aucun téléchargement terminé.": "No completed downloads.",
  "Reprendre cet élément": "Resume this item",
  "Mettre cet élément en pause": "Pause this item",
  "Ne pas télécharger cet élément": "Do not download this item",
  "Relance impossible.": "Retry unavailable.",
  "Kitty: impossible d'ouvrir la source": "Kitty: could not open the source",
  "Dernier téléchargement": "Last download",
  "Déjà présent dans le dossier.": "Already present in the folder.",
  "Téléchargement terminé.": "Download complete.",
  "Dernier téléchargement annulé.": "Last download cancelled.",
  "Erreur du host.": "Host error.",
  "Frontend/backend non vérifiés ou incompatibles · mise à jour requise": "Frontend/backend unchecked or incompatible · update required",
  "Diagnostic indisponible.": "Diagnostics unavailable.",
  "Média non détecté sur cette page. Place le média à télécharger au centre de l’écran.": "Media not detected on this page. Place the media you want to download in the center of the screen.",
  "Erreur : Impossible d'enregistrer la langue.": "Error: Could not save the language.",
  "inconnu": "unknown",
  "installé": "installed",
  "absent": "missing",
  "erreur": "error",
  "oui": "yes",
  "non": "no",
  "aucun": "none",
  "non installé": "not installed",
  "écriture OK": "write OK",
  "écriture impossible": "write failed",
  "En file • prochain": "Queued • next",
  " • déjà présent": " • already present",
  "Logs : rotation automatique": "Logs: automatic rotation",
  "fichiers maximum": "files maximum",
  "élément supprimé": "item removed",
  "éléments supprimés": "items removed",
  "Cache nettoyé": "Cache cleaned",
  "Dépendance": "Dependency",
  "dépendance": "dependency",
  "dépendances": "dependencies",
  "requise": "required",
  "requises": "required",
  "absente": "missing",
  "absentes": "missing",
  "optionnel": "optional",
  "manquant": "missing",
  "attention": "attention",
  "Aucune mise à jour détectée avec les sources disponibles": "No updates detected with available sources",
  "Relancer": "Retry",
  "déjà présent": "already present",
  "priorité": "priority",
  "Non vérifié": "Unchecked",
  "Compatible": "Compatible",
  "Incompatible": "Incompatible",
  "Mise à jour requise": "Update required",
  "Aucune mise à jour détectée avec les sources disponibles.": "No updates detected with available sources.",
  "Impossible d'enregistrer la langue.": "Could not save the language.",
  "Kitty Download Manager — diagnostic": "Kitty Download Manager — diagnostics",
  "Schéma d’état": "State schema",
  "Worker métadonnées": "Metadata worker",
  "Actif": "Active",
  "Bureau": "Desktop",
  "backend ancien · update requis": "old backend · update required",
  "update requis": "update required"
});
  const EN_FR = Object.freeze(Object.fromEntries(
    Object.entries(FR_EN).map(([fr, en]) => [en, fr])
  ));

  let language = "fr";
  let observer = null;
  const textSources = new WeakMap();
  const attributeSources = new WeakMap();

  function normalize(value) {
    return VALID_LANGUAGES.has(value) ? value : "fr";
  }

  function getLanguage() {
    return language;
  }

  function setLanguage(value) {
    language = normalize(value);
    try { document.documentElement.lang = language; } catch {}
    return language;
  }

  function translateUiTokenToEnglish(value) {
    const token = String(value || "");
    const exact = FR_EN[token];
    if (exact) return exact;
    let match;
    if ((match = token.match(/^priorité (\d+) \/ (\d+)$/))) return `priority ${match[1]} / ${match[2]}`;
    if ((match = token.match(/^priorité (\d+)\/(\d+)$/))) return `priority ${match[1]}/${match[2]}`;
    return token;
  }

  function translateUiTokenToFrench(value) {
    const token = String(value || "");
    const exact = EN_FR[token];
    if (exact) return exact;
    let match;
    if ((match = token.match(/^priority (\d+) \/ (\d+)$/))) return `priorité ${match[1]} / ${match[2]}`;
    if ((match = token.match(/^priority (\d+)\/(\d+)$/))) return `priorité ${match[1]}/${match[2]}`;
    return token;
  }

  function translatePatternToEnglish(text) {
    let match;

    if ((match = text.match(/^(\d+) en attente(?: • (\d+) pause)?$/))) {
      const count = Number(match[1]);
      const paused = match[2] ? Number(match[2]) : 0;
      return `${count} pending${paused ? ` • ${paused} paused` : ""}`;
    }
    if ((match = text.match(/^(\d+) éléments?$/))) {
      const count = Number(match[1]);
      return `${count} item${count === 1 ? "" : "s"}`;
    }
    if ((match = text.match(/^Ouvrir : (.+)$/))) return `Open: ${match[1]}`;
    if ((match = text.match(/^Ouvrir la source · (.+)$/))) return `Open source · ${match[1]}`;
    if ((match = text.match(/^Source · (.+)$/))) return `Source · ${match[1]}`;
    if ((match = text.match(/^Erreur : (.+)$/))) return `Error: ${tr(match[1], "en")}`;
    if ((match = text.match(/^Erreur collection : (.+)$/))) return `Collection error: ${tr(match[1], "en")}`;
    if ((match = text.match(/^YouTube : (.+)$/))) return `YouTube: ${tr(match[1], "en")}`;
    if ((match = text.match(/^Style du pill : (.+)\.$/))) return `Pill style: ${tr(match[1], "en")}.`;
    if ((match = text.match(/^Créée (.+)$/))) return `Created ${match[1]}`;
    if ((match = text.match(/^(\d+) cookies YouTube$/))) return `${match[1]} YouTube cookies`;

    if ((match = text.match(/^(\d+) dépendances? requises? absentes?$/))) {
      const count = Number(match[1]);
      return `${count} required dependenc${count === 1 ? "y" : "ies"} missing`;
    }
    if ((match = text.match(/^(\d+) mises? à jour à vérifier pour compatibilité$/))) {
      const count = Number(match[1]);
      return `${count} update${count === 1 ? "" : "s"} require compatibility review`;
    }
    if ((match = text.match(/^(\d+) mises? à jour de dépendance disponibles?$/))) {
      const count = Number(match[1]);
      return `${count} dependency update${count === 1 ? "" : "s"} available`;
    }
    if ((match = text.match(/^(\d+) disponible(?:s)?(?: · (\d+) à vérifier)?$/))) {
      const count = Number(match[1]);
      const risky = match[2] ? Number(match[2]) : 0;
      return `${count} available${risky ? ` · ${risky} to review` : ""}`;
    }
    if ((match = text.match(/^(\d+) mise\(s\) à jour disponible\(s\)\.$/))) {
      return `${match[1]} update(s) available.`;
    }
    if ((match = text.match(/^(\d+) mise\(s\) à jour · (\d+) demande\(nt\) une vérification de compatibilité\.$/))) {
      return `${match[1]} update(s) · ${match[2]} require compatibility review.`;
    }

    if ((match = text.match(/^Confirmer \((\d+)\)$/))) return `Confirm (${match[1]})`;
    if ((match = text.match(/^(\d+) éléments? retirés? de la file\.$/))) {
      const count = Number(match[1]);
      return `${count} item${count === 1 ? "" : "s"} removed from the queue.`;
    }
    if ((match = text.match(/^(\d+) éléments? ajoutés? à la file\.(?: (\d+) ignorés? car déjà pris(?:es)? en charge\.)?$/))) {
      const count = Number(match[1]);
      const skipped = match[2] ? Number(match[2]) : 0;
      return `${count} item${count === 1 ? "" : "s"} added to the queue.${skipped ? ` ${skipped} skipped because already handled.` : ""}`;
    }
    if ((match = text.match(/^✓ (.+) · (.+) · (\d+)\/(\d+) éléments? ajoutés?(?: · (\d+) déjà présents?)?$/))) {
      const skipped = match[5] ? ` · ${match[5]} already present` : "";
      return `✓ ${match[1]} · ${match[2]} · ${match[3]}/${match[4]} items added${skipped}`;
    }
    if ((match = text.match(/^✓ (.+) · (.+) · tous les éléments sont déjà pris en charge$/))) {
      return `✓ ${match[1]} · ${match[2]} · all items are already handled`;
    }

    if ((match = text.match(/^En file • (.+)$/))) {
      return `Queued • ${translateUiTokenToEnglish(match[1])}`;
    }
    if ((match = text.match(/^Métadonnées • (.+)$/))) {
      return `Metadata • ${translateUiTokenToEnglish(match[1])}`;
    }
    if ((match = text.match(/^Pause • (.+)$/))) {
      return `Paused • ${translateUiTokenToEnglish(match[1])}`;
    }

    if ((match = text.match(/^(\d+) détecté(?:s)? · (.+) · conservé(?:s)?$/))) {
      return `${match[1]} detected · ${match[2]} · kept`;
    }
    if ((match = text.match(/^(.+) · (.+) récupérables$/))) {
      return `${match[1]} · ${match[2]} reclaimable`;
    }
    if ((match = text.match(/^(.+) · rien à nettoyer$/))) {
      return `${match[1]} · nothing to clean`;
    }
    if ((match = text.match(/^Cache nettoyé : (.+) libérés · (\d+) éléments? supprimés?\.$/))) {
      const count = Number(match[2]);
      return `Cache cleaned: ${match[1]} freed · ${count} item${count === 1 ? "" : "s"} removed.`;
    }
    if ((match = text.match(/^Logs : rotation automatique à (.+) · (\d+) fichiers maximum$/))) {
      return `Logs: automatic rotation at ${match[1]} · ${match[2]} files maximum`;
    }

    const diagnosticPrefixes = [
      "Compatibilité frontend/backend",
      "Protocole frontend/backend",
      "Mises à jour dépendances",
      "Mises à jour à vérifier",
      "État global",
      "Migration destination",
      "Test écriture destination",
      "Espace libre",
      "Historique",
      "Cache total",
      "Cache récupérable",
      "Cache temporaire",
      "Backups update",
      "Logs total",
      "Partiels orphelins",
      "Backups état",
    ];
    for (const prefix of diagnosticPrefixes) {
      if (text.startsWith(prefix + ":")) {
        const value = text.slice(prefix.length + 1).trimStart();
        return `${FR_EN[prefix] || prefix}: ${tr(value, "en")}`;
      }
    }

    return text;
  }

  function translatePatternToFrench(text) {
    let match;

    if ((match = text.match(/^(\d+) pending(?: • (\d+) paused)?$/))) {
      return `${match[1]} en attente${match[2] ? ` • ${match[2]} pause` : ""}`;
    }
    if ((match = text.match(/^(\d+) items?$/))) {
      const count = Number(match[1]);
      return `${count} élément${count === 1 ? "" : "s"}`;
    }
    if ((match = text.match(/^Open: (.+)$/))) return `Ouvrir : ${match[1]}`;
    if ((match = text.match(/^Open source · (.+)$/))) return `Ouvrir la source · ${match[1]}`;
    if ((match = text.match(/^Error: (.+)$/))) return `Erreur : ${tr(match[1], "fr")}`;
    if ((match = text.match(/^Collection error: (.+)$/))) return `Erreur collection : ${tr(match[1], "fr")}`;
    if ((match = text.match(/^YouTube: (.+)$/))) return `YouTube : ${tr(match[1], "fr")}`;
    if ((match = text.match(/^Pill style: (.+)\.$/))) return `Style du pill : ${tr(match[1], "fr")}.`;
    if ((match = text.match(/^Created (.+)$/))) return `Créée ${match[1]}`;
    if ((match = text.match(/^(\d+) YouTube cookies$/))) return `${match[1]} cookies YouTube`;
    if ((match = text.match(/^Confirm \((\d+)\)$/))) return `Confirmer (${match[1]})`;

    if ((match = text.match(/^(\d+) items? removed from the queue\.$/))) {
      const count = Number(match[1]);
      return `${count} élément${count === 1 ? "" : "s"} retiré${count === 1 ? "" : "s"} de la file.`;
    }
    if ((match = text.match(/^(\d+) items? added to the queue\.(?: (\d+) skipped because already handled\.)?$/))) {
      const count = Number(match[1]);
      const skipped = match[2] ? Number(match[2]) : 0;
      return `${count} élément${count === 1 ? "" : "s"} ajouté${count === 1 ? "" : "s"} à la file.${skipped ? ` ${skipped} ignoré${skipped === 1 ? "" : "s"} car déjà pris${skipped === 1 ? "" : "s"} en charge.` : ""}`;
    }
    if ((match = text.match(/^✓ (.+) · (.+) · (\d+)\/(\d+) items added(?: · (\d+) already present)?$/))) {
      const skipped = match[5] ? ` · ${match[5]} déjà présent${Number(match[5]) === 1 ? "" : "s"}` : "";
      return `✓ ${match[1]} · ${match[2]} · ${match[3]}/${match[4]} éléments ajoutés${skipped}`;
    }
    if ((match = text.match(/^✓ (.+) · (.+) · all items are already handled$/))) {
      return `✓ ${match[1]} · ${match[2]} · tous les éléments sont déjà pris en charge`;
    }

    if ((match = text.match(/^Queued • (.+)$/))) return `En file • ${translateUiTokenToFrench(match[1])}`;
    if ((match = text.match(/^Metadata • (.+)$/))) return `Métadonnées • ${translateUiTokenToFrench(match[1])}`;
    if ((match = text.match(/^Paused • (.+)$/))) return `Pause • ${translateUiTokenToFrench(match[1])}`;

    if ((match = text.match(/^(\d+) detected · (.+) · kept$/))) {
      const count = Number(match[1]);
      return `${count} détecté${count === 1 ? "" : "s"} · ${match[2]} · conservé${count === 1 ? "" : "s"}`;
    }
    if ((match = text.match(/^(.+) · (.+) reclaimable$/))) return `${match[1]} · ${match[2]} récupérables`;
    if ((match = text.match(/^(.+) · nothing to clean$/))) return `${match[1]} · rien à nettoyer`;
    if ((match = text.match(/^Cache cleaned: (.+) freed · (\d+) items? removed\.$/))) {
      const count = Number(match[2]);
      return `Cache nettoyé : ${match[1]} libérés · ${count} élément${count === 1 ? "" : "s"} supprimé${count === 1 ? "" : "s"}.`;
    }
    if ((match = text.match(/^Logs: automatic rotation at (.+) · (\d+) files maximum$/))) {
      return `Logs : rotation automatique à ${match[1]} · ${match[2]} fichiers maximum`;
    }

    const diagnosticPrefixes = [
      "Frontend/backend compatibility",
      "Frontend/backend protocol",
      "Dependency updates",
      "Updates to review",
      "Overall status",
      "Destination migration",
      "Destination write test",
      "Free space",
      "History",
      "Total cache",
      "Reclaimable cache",
      "Temporary cache",
      "Update backups",
      "Total logs",
      "Orphan partials",
      "State backups",
    ];
    for (const prefix of diagnosticPrefixes) {
      if (text.startsWith(prefix + ":")) {
        const value = text.slice(prefix.length + 1).trimStart();
        return `${EN_FR[prefix] || prefix}: ${tr(value, "fr")}`;
      }
    }

    return text;
  }

  function tr(value, target = language) {
    if (value === null || value === undefined) return value;
    const text = String(value);
    const wanted = normalize(target);

    if (wanted === "en") {
      if (Object.prototype.hasOwnProperty.call(FR_EN, text)) return FR_EN[text];
      if (Object.prototype.hasOwnProperty.call(EN_FR, text)) return text;
      return translatePatternToEnglish(text);
    }

    if (Object.prototype.hasOwnProperty.call(EN_FR, text)) return EN_FR[text];
    if (Object.prototype.hasOwnProperty.call(FR_EN, text)) return text;
    return translatePatternToFrench(text);
  }

  function matches(value, frenchSource) {
    const text = String(value || "");
    return text === frenchSource || text === FR_EN[frenchSource];
  }

  function textParts(value) {
    const current = String(value || "");
    const leading = current.match(/^\s*/)?.[0] || "";
    const trailing = current.match(/\s*$/)?.[0] || "";
    const core = current.slice(leading.length, current.length - trailing.length);
    return { leading, trailing, core };
  }

  function translateTextNode(node) {
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const { leading, trailing, core } = textParts(node.nodeValue);
    if (!core) return;
    let source = textSources.get(node);
    if (source === undefined) {
      source = core;
      textSources.set(node, source);
    }
    const translated = tr(source);
    const next = leading + translated + trailing;
    if (node.nodeValue !== next) node.nodeValue = next;
  }

  function noteExternalTextMutation(node) {
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    const { core } = textParts(node.nodeValue);
    if (!core) return;
    const source = textSources.get(node);
    if (source !== undefined && core === tr(source)) return;
    textSources.set(node, core);
    translateTextNode(node);
  }

  function translateAttributes(element, externalMutation = false) {
    if (!(element instanceof Element)) return;
    let sources = attributeSources.get(element);
    if (!sources) {
      sources = new Map();
      attributeSources.set(element, sources);
    }

    for (const attr of ["title", "aria-label", "placeholder"]) {
      if (!element.hasAttribute(attr)) continue;
      const current = element.getAttribute(attr) || "";
      let source = sources.get(attr);
      if (source === undefined) {
        source = current;
        sources.set(attr, source);
      } else if (externalMutation && current !== tr(source)) {
        source = current;
        sources.set(attr, source);
      }
      const translated = tr(source);
      if (translated !== current) element.setAttribute(attr, translated);
    }
  }

  function apply(root = document.body) {
    if (!root) return;

    if (root.nodeType === Node.TEXT_NODE) {
      translateTextNode(root);
      return;
    }

    if (root instanceof Element) translateAttributes(root);

    const walker = document.createTreeWalker(
      root,
      NodeFilter.SHOW_TEXT,
      { acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || ["SCRIPT", "STYLE", "TEXTAREA"].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }}
    );

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) translateTextNode(node);

    if (root.querySelectorAll) {
      for (const element of root.querySelectorAll("[title], [aria-label], [placeholder]")) {
        translateAttributes(element);
      }
    }
  }

  function observe(root = document.body) {
    if (!root || observer) return observer;
    observer = new MutationObserver(mutations => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") noteExternalTextMutation(mutation.target);
        if (mutation.type === "attributes") translateAttributes(mutation.target, true);
        for (const node of mutation.addedNodes || []) apply(node);
      }
    });
    observer.observe(root, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["title", "aria-label", "placeholder"]
    });
    return observer;
  }


  globalThis.KittyI18n = Object.freeze({
    normalize,
    getLanguage,
    setLanguage,
    tr,
    matches,
    apply,
    observe
  });
})();
