# Kitty v8.43 — sélection automatique d’une source

Frontend **8.43**, backend **8.36**, protocole Native Messaging **1**, schéma de queue inchangé. Point de départ inspecté : commit `72b2dd0`, frontend 8.42/backend 8.35. Aucun changement suivi n’était en attente ; l’ancien XPI 8.36 non suivi a été conservé.

Le mode **Automatique** compare les métadonnées de la page et des médias réseau puis utilise un seul downloader. Les échecs des analyses restent internes. Une seule demande, une seule entrée de queue, une seule entrée finale d’historique : aucun téléchargement complet concurrent pour chercher un gagnant.

## Architecture trouvée et conservée

- `KittyMedia.Store` dans `hls-detector.js` : catalogue par onglet, HLS, DASH et médias directs, URLs signées intactes, Range/déduplication, nettoyage à la navigation et à la fermeture.
- `hls-parser.js` et `hls-response.js` : lecture bornée du manifeste déjà reçu par Firefox, relations master/variantes/audio/sous-titres, une source logique par groupe HLS. Ces trois fichiers n’ont pas été modifiés.
- `background.js` : contexte de navigation et trois headers autorisés, choix manuel de source, Native Messaging, popup/pill/clic droit.
- `hls.py` / `direct_media.py` : validation des entrées et des DRM, analyse avec yt-dlp, support des formats directs. Aucun nouvel extracteur ni downloader.
- `metadata_guard.py` : processus jetable supervisé pour yt-dlp ; délais FFprobe/FFmpeg existants. Il est réutilisé sans modification.
- `worker.py` : formats, progression, ETA/vitesse/octets, FFmpeg, audio original, contrôle d’annulation, destination, queue et historique existants.

La nouvelle séparation est : **catalogue → résolveurs de métadonnées → scorer → plan classé → worker existant**. Le scoring ne se trouve ni dans le parser HLS ni dans l’extracteur yt-dlp.

## DownloadRequest

Le backend construit et valide la demande à partir du mode UI existant ; le navigateur ne peut pas injecter de commandes yt-dlp ou d’options arbitraires.

| Champ | Valeur issue des réglages actuels |
| --- | --- |
| `mode` | `video` ou `audio` |
| `maxHeight` | 720, 1080, ou `None` pour meilleure qualité/audio |
| `preferredContainer` | MP4 pour la vidéo ; MP3 pour la conversion MP3 ; aucune préférence de conteneur pour l’audio original |
| `audioRequired` | `True` en audio/MP3 ; `False` en vidéo, pour conserver le support historique des vidéos muettes |
| `preferOriginalCodec` | `True`, sauf conversion MP3 explicitement choisie |
| `allowTranscode` | `True` uniquement pour le mode MP3 |

Pas de nouvelle option UI redondante. Pas de préférence de sous-titres ajoutée : l’UI n’en propose pas actuellement. La destination reste le `output_dir` du job existant.

## MediaCandidate

Le modèle commun conserve :

| Informations | Champs |
| --- | --- |
| Source et contexte | `sourceType`, `url`, `pageUrl`, `tabId`, `title`, `timestamp` |
| Capacités utilisables pour la demande | `maxHeight`, `resolutions`, `hasVideo`, `hasAudio`, `nativeAudio` |
| Formats | `videoCodec`, `audioCodec`, `container`, `bitrate`, `fps`, `estimatedSize` |
| Structure et traitement | `isMaster`, `isPartial`, `requiresMerge`, `requiresTranscode` |
| Fiabilité | `confidence`, `completeness`, `expiryTime`, propriété `expiryKnown` |
| Résultat interne | `score`, `info` yt-dlp complet, `source` validée avec ses headers |

Les types sont `ytdlp`, `hls`, `dash`, `direct_video`, `direct_audio`. Le plafond demandé limite les hauteurs utilisées par le scorer ; tous les formats restent disponibles dans `info` pour le sélecteur historique. La présence audio est évaluée dans les formats vidéo compatibles avec ce plafond et les vraies pistes audio séparées. L’audio d’un MP4 1080p ne devient pas artificiellement une piste audio séparée pour une variante 720p silencieuse.

Les URLs et headers restent en mémoire pour l’exécution ; les logs ne contiennent que le type, le score et l’état. Les fichiers temporaires privés des probes sont supprimés. Aucun cookie ou token n’est affiché dans les nouveaux logs.

## Résolution parallèle et réutilisation

Le frontend transmet l’URL de page et jusqu’à trois candidats du catalogue, avec priorité à une source de chaque famille. Pour l’audio, une ressource audio directe passe avant une vidéo directe. Un master HLS est envoyé à la place de ses enfants ; le type interne de manifeste est conservé comme petit indice validé.

Quand le worker prend le job, il lance jusqu’à **quatre analyses simultanées** : page, HLS, DASH, direct. Chacune utilise son propre processus supervisé, avec `skip_download=True`, aucune miniature écrite et aucune progression de transfert. Les headers Referer/Origin/User-Agent et la session YouTube dédiée déjà existante sont réutilisés.

Les titres, headers, groupes et variantes déjà détectés sont réutilisés. Le backend revalide la source au début du job, car les URLs signées peuvent expirer dans la queue. Les résultats complets des probes sont ensuite transmis au downloader choisi : aucune deuxième extraction de la source gagnante. Les probes de titre séparés ne sont plus lancés pendant l’attente des jobs automatiques ; cela évite les extractions en doublon et les courses sur leur statut.

La résolution se fait au démarrage du job, pas en amont de toute une longue queue. Les échecs d’un résolveur ne créent aucune carte Error. Si aucun candidat compatible ne reste, le worker produit une seule erreur finale.

## Scoring central

`scoreCandidate(candidate, request)` utilise les règles suivantes :

- Source expirée, audio absent lorsqu’il est requis, vidéo absente en mode vidéo, ou transcodage interdit : candidat incompatible.
- Base 60 ; métadonnées complètes jusqu’à +4 ; validation réussie +2.
- Vidéo plafonnée : jusqu’à +90 proportionnellement à la hauteur utilisable. Passer de 720 à 1080 pour une demande 1080 vaut **30 points**.
- « Meilleure qualité » : progression logarithmique sans plafonner le score à 2160p ; une source 4320p peut donc battre 2160p.
- Hauteur inconnue : −15. Audio confirmé : +12 ; audio inconnu lorsque requis : −25.
- Conteneur préféré : +2 ; codecs courants compatibles MP4 : jusqu’à +2.
- Source complète/master : +1 ; playlist partielle : −4.
- Expiration explicite à moins de 60 secondes : −25. Seules les dates d’expiration epoch explicites sont interprétées ; pas de décodage arbitraire des tokens.
- Audio : piste native directe +70, piste native HLS/DASH +60, piste native yt-dlp +50 ; extraction sans réencodage depuis une vidéo +10 ; transcodage nécessaire −30.

**yt-dlp gagne seulement comme départage à score identique.** Il n’a pas de priorité qui puisse neutraliser l’écart 720p/1080p. Le conteneur est une préférence : les fichiers directs ne sont pas forcés à être convertis, et le remux/merge historique reste responsable du résultat.

Les pistes vidéo et audio sont choisies dans le résultat d’UNE source, jamais dans deux lecteurs différents. Si le résultat de la page partage des URL de formats avec un candidat réseau, ce lien positif permet de limiter le classement au lecteur correspondant ; une publicité indépendante ne gagne pas simplement par sa résolution. La comparaison utilise les identités existantes, sans modifier les URLs réellement utilisées.

## Timeouts et arrêt des probes

| Opération | Limite |
| --- | --- |
| Résolveur de page yt-dlp | 30 s |
| Chaque résolveur réseau | 20 s |
| Socket d’un probe | 8 s, sans retries supplémentaires |
| Attente des autres probes après une source vidéo atteignant le plafond ou une piste audio native prête | 5 s supplémentaires, sans dépasser la limite globale |
| FFprobe | 15 s, également contenu dans le délai du résolveur direct |
| Post-traitement FFmpeg | 600 s, protection existante |
| Manifest HLS observé dans Firefox | 10 s / 2 Mio, protection existante |

Après sélection, les analyses restantes sont arrêtées, leurs processus et descendants terminés et les threads rejoints. L’annulation/pause/interruption du worker déclenche le même nettoyage. Le transfert lui-même n’est pas limité à 20 ou 30 secondes.

## Un seul transfert et fallback runtime

Le résultat sélectionné est envoyé une seule fois à `process_ie_result(..., download=True)`. Le downloader yt-dlp, ses formats, ses hooks, FFmpeg et la finalisation sont ceux de Kitty. DASH ou un master HLS peuvent sélectionner une piste vidéo et une piste audio puis les fusionner normalement.

Un candidat suivant peut être essayé **séquentiellement** si le premier échoue pour une erreur de source : accès HTTP refusé, expiration, URL/format indisponible ou interruption de réseau pendant l’initialisation. Conditions supplémentaires : au plus **64 Kio**, au plus **10 secondes** dans l’essai, et aucune piste média déjà terminée. Les petits fichiers temporaires du premier essai sont supprimés, le statut est réinitialisé, et le job conserve le même ID.

Aucun fallback après Annuler, pause, arrêt du worker, disque plein, permission/filesystem, FFmpeg/FFprobe manquant ou post-traitement défaillant, piste déjà terminée ou transfert important. Le succès suivant produit une seule entrée finished ; les erreurs intermédiaires ne sont pas ajoutées à Error. Retry conserve la stratégie automatique, la destination et l’URL de page originale, au lieu de figer la précédente source échouée.

## UI avant / après

Avant : « Page active · yt-dlp en priorité », suivi d’un fallback après erreur de la page.

Après, avec backend 8.36 : **« Automatique · meilleure source »**, « Sources détectées comparées automatiquement », puis **« Recherche de la meilleure source… »** et **« Source sélectionnée · HLS · 1080p »**, ou yt-dlp/DASH/direct selon le résultat. En audio, aucune hauteur vidéo n’est affichée comme qualité téléchargée. Le choix manuel d’une source reste une sélection explicite.

Avec un ancien backend, le libellé et le chemin historique restent visibles ; l’extension ne prétend pas utiliser un planificateur qu’il ne possède pas. Le mode image et le mode Playlist ne sont pas redirigés vers ce planificateur.

## Fichiers modifiés

- Nouveau module : `native-host/download_planner.py`.
- Intégration : `native-host/worker.py`, `host.py`, `hls.py` (petit champ de classification validé).
- Extension/UI : `extension/background.js`, `shared.js`, `popup-hls.js`, `popup.js`, `i18n.js`, `manifest.json`.
- Installation/maintenance et versions : `install.sh`, `Install.ps1`, `backend.json`, `native-host/windows_install.py`, `macos_install.py`, `maintenance.py`.
- Tests : nouveaux `tests/test-download-planner.py`, `test-automatic-download.py` ; mises à jour `test-hls-background.js`, `test-hls-firefox.py`, `test-backend-packaging.py`.
- CI et documentation : `.github/workflows/backend-downloads.yml`, `README.md`, ce rapport et `docs/validation-automatic-v8.43.json`.

## Vérifications réellement exécutées

Environnement : Linux, Python 3.12.14, yt-dlp stable 2026.08.19, FFmpeg/FFprobe 6.1.1, Firefox 153.0. Les téléchargements réels utilisent des fixtures HTTP locales générées avec FFmpeg, puis des contrôles FFprobe sur les résultats.

| Suite | Résultat |
| --- | --- |
| Modèles, scoring, concurrence, délais, groupes et exclusions | 29/29 |
| Worker automatique : vrais probes, transfert, merge/remux et fallback | 14/14 |
| HLS historique | 12/12 |
| Master HLS avec audio séparé, sous-titres, qualité, annulation et queue | 6/6 |
| DASH | 15/15 |
| Médias directs | 21/21 |
| Miniatures/images | 11/11 |
| Supervision/FFmpeg/FFprobe | 6/6 |
| Timeouts des métadonnées | 6/6 |
| Packaging et installation Linux fresh/upgrade | 3/3 |
| Régression hors ligne queue/historique/destination/session/clic droit | 95 réussis, 0 échec, 5 scénarios Chromium ignorés |
| Tests du port Windows exécutables sur Linux | 28 réussis, 4 ignorés ; pas un test sur Windows natif |
| Tests du port macOS exécutables sur Linux | 10 réussis, 1 ignoré ; pas un test sur macOS natif |

Une vidéo directe muette a également été téléchargée réellement, avec vérification FFprobe et un seul transfert. Les cas demandés sont couverts : égalité page/HLS ; page 720 vs HLS 1080 ; page en erreur avec HLS/DASH/direct valides ; absence audio ; audio natif et extraction depuis MP4 ; timeout de page avec HLS prêt ; expiration après probe ; annulation sans fallback ; erreur disque sans fallback ; plusieurs lecteurs distincts ; queue, destination et historique. L’erreur disque est injectée avec `OSError(ENOSPC)` : le disque n’a pas été rempli.

Firefox réel : **7 contrôles Automatic**, **8 HLS**, **7 groupes HLS**, **9 DASH**, **9 direct** réussis. La popup réelle a été capturée au repos, pendant la recherche et après sélection HLS 1080p. Native Messaging, fichiers finaux, séparation des onglets, navigation/fermeture et absence de boucle ont été vérifiés. Les observations HLS n’ont laissé aucun filtre actif ni erreur de capture.

Node : suites HLS detector/background/groupes (13 scénarios de hiérarchie), DASH, direct/Range, image/pill/clic droit, bootstrap et 9 scénarios de démarrage popup réussis. Python compile et `git diff --check` réussis.

Mozilla `web-ext 10.6.0` : **0 erreur, 0 notice, 1 avertissement préexistant** concernant la version minimale Firefox Android et `data_collection_permissions`.

Les preuves JSON, les logs de suites et les captures sont fournis dans l’archive. Des ResourceWarning yt-dlp après certains tests d’annulation existent déjà ; ils n’ont pas fait échouer les assertions. Ils ne constituent pas une validation native de chaque plateforme.

## Limites restantes

- Maximum trois candidats réseau analysés par demande, avec diversité de familles ; ce n’est pas une analyse illimitée de tous les lecteurs d’une page.
- Sans relation de ressources prouvée, l’extension ne peut pas garantir quel lecteur est le principal parmi une publicité, une preview et plusieurs vidéos. Les sources restent distinctes et la sélection manuelle permet de lever l’ambiguïté.
- Le délai de grâce favorise une source déjà conforme ; une source plus lente peut ne pas terminer son analyse avant sélection. Cela permet d’éviter un blocage global.
- Le mode vidéo accepte les vidéos muettes comme avant. À qualité égale l’audio est favorisé ; si une demande exige explicitement l’audio, une source silencieuse est écartée. Aucun nouveau bouton audioRequired n’a été ajouté.
- Hauteur/codec/taille/expiration peuvent rester inconnus. Le scorer réduit leur confiance pratique ; il ne fabrique pas de métadonnées. Les URLs signées ne sont jamais reconstruuites.
- Pas de cache persistant de résultats yt-dlp entre demandes : la validation se refait au démarrage du job. Les résultats de cette validation sont réutilisés pour son transfert.
- Le contexte authentifié reste celui pris en charge par Kitty : trois headers autorisés et session YouTube dédiée. Aucun export général de tous les cookies Firefox n’a été ajouté.
- Pas de nouvelle prise en charge blob mémoire, fragments téléchargés par Firefox, ni contournement DRM. Les limitations HLS/DASH/direct existantes restent applicables.
- Pas de campagne publique YouTube/Vimeo/CDN, ni exécution native Windows/macOS dans cet environnement. Les exemples Vimeo sont des fixtures locales de structure comparable.
- L’XPI est non signé. Aucune publication GitHub ou Mozilla n’a été effectuée pour cette version.

## Installation dans le dossier Downloads existant (fish)

```fish
cd ~/Downloads
and unzip -o kitty-download-manager-v8.43-automatic.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

Recharge ensuite l’extension temporaire depuis `about:debugging` → « Ce Firefox ». Le manifest est dans `~/Downloads/kitty-download-manager/extension/manifest.json`. L’archive contient aussi les installateurs backend 8.36 Linux/Windows/macOS et l’XPI frontend 8.43 non signé. Les configurations, l’historique et la destination sont conservés par l’installateur existant.
