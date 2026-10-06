# Backend 8.46 — yt_dlp.postprocessor introuvable

Le message signalé est `No module named 'yt_dlp.postprocessor'`. Le sous-paquet existe dans la distribution officielle yt-dlp testée (2026.8.19). Ce message indique une erreur d’import du runtime, mais ne permet pas à lui seul de savoir si les fichiers ont été supprimés, si une installation est incomplète ou si un autre paquet masque le bon emplacement. Aucun fichier ni journal provenant du PC Windows n’a été consulté ici.

Une copie réelle de yt-dlp privée de son dossier `postprocessor` reproduit exactement le message. Le précédent installeur Windows ne chargeait pas yt-dlp dans ses contrôles `get_settings` et `compatibility` : ces contrôles pouvaient donc réussir avec des dépendances inutilisables.

## Modifications

- Vérification immédiate après pip, puis à travers le même Native Messaging que Firefox avant activation : imports yt-dlp, YouTube, réseau, postprocessors, SSL, Mutagen, psutil et EJS.
- Vérification que les modules tiers Windows viennent du dossier privé de la nouvelle version, sans recours au Python système.
- Lecture directe du RECORD de la roue yt-dlp et vérification des fichiers Python/empreintes. Certaines versions de `importlib.metadata.Distribution.files` omettent les fichiers supprimés : ce raccourci n’est donc pas utilisé pour ce contrôle.
- Vérification des fabriques `FFmpegMerger`, `FFmpegMetadata` et `EmbedThumbnail`, sans téléchargement de média.
- Refus d’activer le runtime si ces vérifications échouent. Une réinstallation crée toujours une nouvelle version et de nouvelles dépendances, en conservant les données utilisateur.
- L’initialisation du processus de métadonnées est incluse dans son traitement d’erreur : un sous-module absent renvoie maintenant une erreur structurée avec son détail technique, au lieu de disparaître avant l’écriture du résultat.
- Les sous-modules yt-dlp/EJS absents sont classés comme dépendance manquante.
- `Diagnose.cmd` contrôle le Python du backend effectivement enregistré et affiche sa version, ses chemins de modules et les résultats d’intégrité. Aucun paquet, cookie, téléchargement ou état de file n’est modifié.

La correction du dossier Windows 8.45 est conservée. L’extension reste en 8.52.

## Validation

| Suite | Résultat |
| --- | --- |
| Runtime réel, suppression du postprocessor, fichier modifié, mauvais emplacement, erreur d’initialisation | 7 réussis |
| Installation, activation et rollback | 12 réussis |
| Packaging / installation Linux | 3 réussis |
| Limites de durée et nettoyage des processus | 6 réussis |
| Régression générale | 95 réussis, 5 Chromium ignorés |

Le contrôle positif vérifie 1 046 fichiers Python dans la distribution utilisée pour les tests. Les tests ne téléchargent aucune vidéo publique. Les résultats prouvent la détection de paquets incomplets, la disponibilité des imports sur le runtime local sain et la conservation de l’ancienne installation sur échec. Ils ne prouvent pas la cause exacte sur le PC signalé ni la réussite d’un téléchargement YouTube public.

PowerShell 5.1 et la vraie installation Windows restent à valider sur Windows. Le workflow Windows inclut les tests du runtime et de l’installation ; son smoke test appelle désormais le contrôle d’intégrité du backend installé.

Références : [paquet postprocessor officiel](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/postprocessor/__init__.py), [Python embarqué Windows et dépendances privées](https://docs.python.org/3/using/windows.html#the-embeddable-package).

## Utilisation

Extraire la nouvelle archive dans un dossier distinct, fermer Firefox, lancer `Install.cmd` et conserver le dossier d’installation proposé. Attendre la réussite des contrôles et le message de fin avant de rouvrir Firefox.

Pour examiner le runtime existant avant une réinstallation, ou si le problème persiste, lancer `Diagnose.cmd` depuis l’archive. Un dossier explicite peut être fourni à `Diagnose.ps1` avec `-InstallDir 'E:\download\Kitty-Download-Manager'`. Le diagnostic examine le backend actif, y compris une version antérieure à 8.46, car le script de contrôle est fourni dans la nouvelle archive.
