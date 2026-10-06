# Kitty 8.50 / backend 8.41 — reprise après expiration

Le rafraîchissement renouvelle le candidat et son RequestContext dans le downloader yt-dlp actif. Il ne crée pas un nouveau DownloadJob et ne rappelle pas enqueue/retry. L’ID, le mode, la représentation choisie, le titre du job, le nom de sortie, les octets acquis et la progression restent attachés au même job.

## Cause et correction

Le chemin précédent arrêtait le job lorsque l’URL expirait après les premiers octets. Automatic permettait seulement un fallback très tôt dans le transfert. Le nettoyage générique d’un échec pouvait ensuite supprimer les fichiers `.part` et `.ytdl`. Remplacer simplement une URL et laisser `continuedl` reprendre aurait également accepté une nouvelle ressource sans preuve d’identité.

`native-host/source_refresh.py` intercepte maintenant les réponses HTTP 401/403/410 des ressources média du candidat courant. Il renouvelle les adresses dans le transport existant. Les requêtes de miniatures ne déclenchent pas une résolution du média. Les détecteurs HLS, DASH et direct ne sont pas réimplémentés.

## Résolution et portée

- Le background Firefox consulte le catalogue existant, même lorsque le popup est fermé. Une requête du worker identifie le job, un nonce, le candidat, l’onglet et, si présent, le MediaItem.
- Le backend accepte seulement un remplacement correspondant à cette requête encore active et à ce même candidat/type/onglet/page/MediaItem. Une URL d’une autre vidéo est rejetée.
- Si le catalogue n’a pas de contexte frais, le resolver existant réanalyse la page source dans un subprocess supervisé. Il retient uniquement les URLs liées à la ressource initiale.
- Aucune sélection « best » supplémentaire : la représentation déjà choisie reste fixée. Une autre résolution ou un autre média ne peut pas reprendre le même fichier partiel.
- Le RequestContext reste limité à son origine. Cookies et headers ne sont pas imprimés dans les logs ; un ancien Cookie présent dans les métadonnées yt-dlp ne remplace plus la session renouvelée. Les sessions d’autres domaines du jar restent disponibles.

## Fichiers directs

Avant le GET de reprise, un HEAD de la nouvelle URL doit retrouver le même **ETag fort** et la même **taille totale** que le transfert initial. Le GET conserve l’offset Range natif et transmet If-Range. La réponse doit être 206, conserver les validateurs et commencer à l’offset demandé. Un ETag faible, une taille différente, un HEAD indisponible ou une réponse ignorant Range interrompent la reprise avant concaténation.

La comparaison prudente des URLs conserve l’origine, le chemin et les paramètres significatifs ; seuls les paramètres de signature/expiration connus sont ignorés. Une URL déplacée vers un autre chemin/CDN ne suffit pas à confirmer la même ressource.

## HLS et DASH

L’itérateur de fragments et le fichier `.ytdl` natifs restent la référence. Le nouveau manifest n’est pas réinjecté dans un nouveau downloader : il fournit uniquement les URLs des segments manquants dans l’itérateur original.

- HLS VOD : comparaison de la séquence, des EXTINF, des discontinuités, des ranges, de l’initialisation et des identités stables des URLs.
- DASH VOD : comparaison des périodes, représentations, codecs, timescales, startNumber, SegmentTimeline, templates, initialisations et ranges, puis de la liste de fragments produite par l’extracteur existant.
- Une timeline ou une représentation différente est refusée, même si les noms de segments se ressemblent.
- Les segments déjà reçus doivent conserver leur ETag fort et leur taille. HEAD vérifie ces validateurs sans retransférer le contenu. Une timeline identique seule n’est pas une preuve suffisante.
- Un checkpoint privé (0600) garde les empreintes de manifests/timelines et les validateurs. Lors d’une reprise du worker, les identités sont à nouveau vérifiées avant de poursuivre les fichiers partiels. Le checkpoint est retiré après succès ou annulation.

## Identité incertaine et limites

Kitty conserve `.part`, `.ytdl`, le checkpoint et la progression, puis affiche **Nouvelle résolution nécessaire**. Il ne concatène pas une ressource incertaine et ne bascule pas vers un autre candidat après réception d’octets. Le fallback Automatic existant reste disponible si aucun octet n’a été transféré.

La reprise automatique est volontairement conservatrice : ETag fort et HEAD utilisable sont requis pour les données déjà reçues. Les fenêtres live glissantes, les rotations de clés HLS, les changements d’origine/chemin ou de timeline nécessitent une nouvelle résolution. Un player entièrement dynamique doit exposer un candidat renouvelé dans le catalogue ; Kitty ne fabrique pas une signature et ne recharge pas automatiquement la page. Le rafraîchissement est limité à trois générations par transfert, avec contrôles d’annulation et timeouts de résolution.

## Validation exécutée

| Vérification | Résultat |
|---|---|
| `tests/test-source-refresh.py` | 20 tests réussis |
| MP4 expiré après 128 Kio | Range à 131072, fichier identique, même job |
| Session renouvelée avec URL identique | Nouveau RequestContext appliqué, progression conservée |
| HLS/DASH expirés après un premier segment | Segments terminés : un seul GET ; suite avec URLs fraîches |
| ETag/taille/range/timeline/segment remplacé | Refus de concaténation ; fichiers partiels conservés |
| Reprise après redémarrage du worker | Contrôle des validateurs du fichier/segment conservé |
| Page courante normale avec expiration | Même job, reprise du fichier correct |
| Suites Python HLS/DASH/direct/yt-dlp/Automatic/MediaItem/RequestContext/planner/groupes/packaging | 159 tests réussis, dont les 20 tests de reprise |
| Suites Node de détection, catalogue, contexte, sélection, dispatch et rafraîchissement | 11 suites réussies |
| `bash test.sh` | 95 vérifications réussies, 0 échec, 5 ignorées (Chromium indisponible) |
| Firefox 153 : galerie MediaItems, sélection/batch/download réel | 11 groupes réussis |
| Firefox 153 : Referer/Origin/session + isolement entre origines | 2 groupes réussis |
| Installateur Windows, tests portables sous Linux | 26 tests réussis |
| Installateur macOS, tests portables sous Linux | 10 réussis, 1 ignoré (nécessite un vrai Mac) |
| web-ext lint | 0 erreur, 0 notice ; warning Android préexistant |

Les expirations sont reproduites avec un vrai serveur HTTP local, les downloaders yt-dlp installés et des médias générés par FFmpeg. Les sorties réussies sont vérifiées par ffprobe ; le fichier direct repris est également comparé octet par octet. Cela ne revendique pas un test sur tous les CDN réels.

## Fichiers modifiés

- Nouveau `native-host/source_refresh.py` ; intégration dans `worker.py`, `request_context.py`, `host.py`, `download_planner.py`, `errors.py`.
- `extension/background.js`, `i18n.js`, `manifest.json`.
- `backend.json`, `install.sh`, `Install.ps1`, `native-host/maintenance.py`, `windows_install.py`, `macos_install.py` : version et installation du module commun.
- Nouveaux `tests/test-source-refresh.py` et `tests/test-source-refresh-background.js` ; scheduler des fixtures background dans `test-dash-detector.js`, `test-direct-detector.js`, `test-hls-background.js`, `test-hls-groups.js`, `test-image-mode.js`, `test-media-items.js`.
- `README.md` et ce document.

## Installation Linux / fish

L’archive garde toujours le répertoire racine **kitty-download-manager/**.

```fish
unzip -o ~/Downloads/kitty-download-manager-v8.50-source-refresh.zip -d ~/Downloads
cd ~/Downloads/kitty-download-manager
bash install.sh
```

Recharger ensuite l’extension Firefox 8.50 avec le XPI fourni dans `packages/` (le XPI est non signé). Backend requis pour ce changement : 8.41.
