# Kitty v8.48 — regroupement MediaItem / MediaCandidate

Frontend **8.48**, backend **8.39 inchangé**, protocole natif **1**. Travail sur la v8.47 actuelle. Les détecteurs HLS, DASH et direct, le Media Catalogue, le résolveur yt-dlp, Automatic et le downloader ne sont pas réécrits.

## Défauts reproduits avant correction

Sur le Store v8.47, deux déclarations DOM du même fichier avec des listes de sources [MP4] et [MP4, WebM] produisaient deux items : l'identité dépendait de la liste complète. Une URL exacte permettait aussi de rattacher un candidat d'une autre frame avant de vérifier son contexte. Enfin, un player blob unique pouvait recevoir un MP4 récent sans lien avec la vidéo.

Les trois reproductions sont reprises dans les tests v8.48 : un seul item avec ses deux variantes, candidat d'une autre frame refusé, MP4 indépendant refusé pour le blob.

## Stratégie de déduplication

1. **Contexte avant preuve.** Pour chaque candidat, tabId, page, frameId/frame_ids et document_url doivent correspondre au contexte DOM. Une URL exacte ne contourne plus ces contrôles. Les collections yt-dlp ne deviennent pas une vidéo individuelle.
2. **Identité explicite.** Regrouper les déclarations d'un même embed, d'une même ressource ou du même fichier Wikimedia (dépôt + nom original). Un poster contradictoire ne remplace pas l'identité explicite du fichier. Une iframe et son player enfant peuvent partager l'identité exacte d'un embed ; les frames ordinaires restent isolées.
3. **Sources liées.** Des listes égales ou dont l'une est incluse dans l'autre, les familles de qualité reconnues par le détecteur existant, les relations master/variant et les formats vidéo d'un candidat yt-dlp constituent des preuves. Les réponses arrivées avant leur master sont rattachées par passes successives lorsque de nouvelles relations explicites deviennent disponibles. Les pistes audio communes ne relient jamais deux présentations vidéo.
4. **Indices secondaires prudents.** Sans URL ou identité explicite, l'association nécessite une durée compatible (écart ≤ max de 0,5 seconde et 2 % de la durée la plus courte), puis un titre résolu concordant avec résolution/temps/container, ou résolution + proximité temporelle. La fenêtre temporelle est de 30 secondes, avec fraîcheur du candidat. Les labels de page des détecteurs ne servent pas de titre résolu.
5. **Ambiguïté = rejet.** Il faut un score ≥ 60 et une avance ≥ 15 sur le deuxième item. Deux vrais players ne fusionnent jamais sur leur seul titre, durée, résolution, container ou onglet. Deux listes ayant une preview commune et chacune une source propre différente restent séparées.
6. **Blob.** Une blob URL reste un indice DOM. Sans autre preuve, seule une présentation HLS/DASH récente et unique, avec un seul player dans la frame, peut être rattachée. Plusieurs manifests indépendants ou un MP4 récent quelconque sont refusés.
7. **Candidats et IDs.** Les candidates techniques sont dédupliquées par type + URL normalisée avec le normaliseur existant ; les paramètres identifiant la vidéo restent significatifs. Une URL signée actualisée remplace le doublon technique. MP4/WebM et les autres types restent des candidates distinctes dans le même item. L'ID de l'item survit aux mises à jour de titre, poster et sources compatibles. Réutiliser un nœud pour une autre ressource crée une nouvelle identité.

Le domaine/CDN seul n'est jamais une preuve de regroupement. Un container DOM reçoit un ID stable via WeakMap ; il sert d'indice complémentaire, jamais de preuve suffisante entre deux players.

## Logs

Le background émet `[Kitty MediaItem] merge/reject` avec tabId, sujet opaque, item cible, motif et signaux. Exemples : `shared_source`, `linked_candidate_url`, `wikimedia_file`, `metadata_agreement`, `wrong_frame`, `duration_conflict`, `container_without_identity`, `ambiguous_match`.

Les décisions inchangées ne sont pas répétées à chaque polling. Un rejet devenant une association après l'arrivée d'une source est journalisé. Ni URL, titre, token ni headers ne figurent dans ces logs de corrélation. Les logs de téléchargement antérieurs restent séparés.

## Fichiers modifiés

| Fichier | Rôle |
| --- | --- |
| `extension/media-items.js` | Preuves de regroupement, scope, candidates liées, IDs et diagnostics. |
| `extension/media-dom.js` | Indice container stable, sans changer les types de players détectés. |
| `extension/manifest.json` | Frontend 8.48. |
| `tests/test-media-correlation.js` | 34 tests ciblés utilisant le classifier et Store de production. |
| `tests/test-media-items.js` | Mock de version 8.48 ; suite existante conservée. |
| `tests/test-hls-firefox.py` | Deux scénarios DOM réels de regroupement/isolation et capture des motifs. |
| `README.md`, `tests/README.md` | Documentation et commandes de validation. |
| `docs/MEDIA-GROUPING-V8.48.md`, `docs/validation-media-grouping-v8.48.json` | Stratégie et résultats exécutés. |

## Tests exécutés et résultats

| Suite | Résultat |
| --- | --- |
| `node tests/test-media-correlation.js` | **34/34** : DOM/source/MP4/WebM/HLS/DASH/yt-dlp, réponses désordonnées, scope, blob, Wikimedia, variantes, audio partagé, ambiguïtés, stabilité des IDs, logs. |
| Suites Node existantes | **9 suites Node au total réussies**, incluant la précédente ; MediaItems, détecteurs HLS/DASH/direct, background/groupes HLS, résolveur (38 assertions), popup (9 scénarios). |
| Firefox 153 + Native Messaging, `KITTY_TEST_MEDIA_ITEMS=1 KITTY_TRACE_MEDIA_ITEMS=1 python3 tests/test-hls-firefox.py` | **11 groupes de vérifications réussis** : partial source sets → un item, même container → deux vidéos distinctes, checkbox/select all et updates async, galerie de deux vidéos titrées avec poster et variantes, batch → deux plans et fichiers indépendants, sélection A puis B, item unique et page yt-dlp normale. Fichiers validés avec ffprobe. |
| `python3 tests/test-media-item-download.py` | **13/13**, transferts MP4/WebM, HLS, DASH, résolution différée et isolation des plans. |
| `python3 tests/test-download-planner.py` | **33/33**. |
| `python3 tests/test-automatic-download.py` | **14/14**. |
| `python3 tests/test-direct-automatic.py` | **11/11**. |
| `python3 tests/test-hls-download.py` | **12/12**. |
| `python3 tests/test-dash-download.py` | **15/15**. |
| `python3 tests/test-direct-download.py` | **21/21**. |
| `bash test.sh` | **95 OK, 0 échec, 5 ignorés** (Chromium absent). |
| `web-ext 10.6.0 lint` | **0 erreur, 0 notice** ; 1 warning Android préexistant sur la version minimale du manifeste. |
| `git diff --check` | Réussi. |

Le test navigateur utilise une galerie locale reproduisant les players Wikimedia ; aucune nouvelle validation live de pages publiques n'est revendiquée dans cette version. Les transferts et les plans sont réels.

## Limites restantes

Les candidates sans identité explicite ni métadonnées suffisantes restent non rattachées plutôt que de risquer un mélange. Les vidéos de même durée/résolution/titre peuvent donc nécessiter une source déclarée ou le résolveur existant. Les détecteurs ne sont pas enrichis avec de nouveaux probes réseau. Les bornes existantes (100 players par frame et 12 sources DOM par player) sont conservées. Les pistes audio restent dans leur présentation mais ne servent pas à fusionner des vidéos.

## Installation CachyOS / fish / Firefox

L'archive contient toujours le dossier **kitty-download-manager/**. Décompresser depuis Downloads conserve **~/Downloads/kitty-download-manager**, sans créer un dossier par version.

```fish
cd ~/Downloads
unzip -o kitty-download-manager-v8.48-media-grouping.zip
cd kitty-download-manager
chmod +x install.sh
./install.sh
```

Dans `about:debugging` → Ce Firefox, recharger ou charger `~/Downloads/kitty-download-manager/extension/manifest.json`. Le backend 8.39 est identique à celui de la v8.47. L'archive inclut l'XPI 8.48 non signé et les installateurs backend ; aucune publication GitHub/Mozilla n'a été effectuée.
