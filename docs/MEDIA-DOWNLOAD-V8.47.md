# Kitty v8.47 — téléchargement des MediaItems sélectionnés

Frontend **8.47**, backend **8.39**, protocole natif **1**. Correctif réalisé sur le dépôt v8.46 actuel (`42d24cc`). HLS, DASH, direct media et yt-dlp restent les extracteurs et downloaders existants.

## Cause exacte et reproduction

La capture de référence correspond aux captions de `https://en.wikipedia.org/wiki/Wikipedia:Videos` (34 vidéos dans le HTML vérifié). Sans lecture préalable, TimedMediaHandler laisse un placeholder : poster Commons et attribut `resource` vers `en.wikipedia.org/wiki/File:…`, mais aucun `<source>` exploitable.

En v8.46, ce lien Wikipedia File devenait l'URL d'extraction du MediaItem. La page File vérifiée contient un player principal et un second player de prévisualisation du **même fichier**. Le résolveur générique de yt-dlp renvoie donc une collection. `candidate_from_info()` refuse correctement cette collection dans le mode média individuel et lève `MetadataError('format_unavailable')`. Le message français affiché est « Format demandé indisponible ». La fixture à deux players reproduit exactement ce code avant correction ; ce n'est pas un défaut CSS ni une preuve que le MP4/WebM manque.

Deux autres défauts de routage ont été identifiés : un item unique utilisait systématiquement la page courante, même avec un candidat direct, et le résolveur ajoutait toujours un probe de page aux candidats de l'item. Le worker réappliquait ensuite le sélecteur global au transfert sans plan liant explicitement les formats choisis à leurs URLs.

La sélection checkbox était également distincte du média courant du bouton principal : cocher B pouvait laisser A comme cible de « Télécharger ». Le clic sur une checkbox cochée définit maintenant aussi le média courant, tout en conservant le toggle et la sélection batch.

Le test public a révélé un échec supplémentaire **après transfert** : `EmbedThumbnail` de yt-dlp refuse WebM. Pour un plan vidéo dont le conteneur ne supporte pas cette opération, Kitty conserve la vidéo et son poster dans l'UI et omet l'intégration de couverture. Le conteneur et les codecs de la meilleure variante sont conservés. Les modes audio/MP3 et le chemin de téléchargement normal restent inchangés.

## Chemin corrigé

1. Le background retrouve le MediaItem par son ID stable et rescane ses frames si les sources techniques sont encore absentes.
2. Les candidats appartiennent exclusivement à cet item. Les requêtes natives transmettent `media_item_id` sur chaque source ; le host refuse un autre item ou une autre page.
3. Une source technique exploitable passe avant la page, même avec un seul item. Sans source, le dépôt et le nom original du poster/source Wikimedia identifient la page **Commons File du même fichier** ; l'extracteur Wikimedia existant résout ses formats. Les embeds utilisent leur URL propre. Une galerie sans URL propre reste une erreur explicite.
4. Avec des candidats techniques attachés, Automatic ne lance aucun probe de la page courante. Il compare ces candidats seulement : jusqu'à 12 candidats, au plus 4 probes simultanés. Le chemin page normal conserve son probe yt-dlp et ses 3 fallbacks.
5. Pour les plans vidéo d'items, la résolution compatible la plus haute passe avant les petits bonus audio/conteneur. `best` n'impose aucun plafond. Les modes 720/1080 respectent leur plafond pour les hauteurs connues.
6. yt-dlp sélectionne les formats du candidat gagnant **sans transfert**. Le plan lie ce résultat au média et aux URLs. Le downloader consomme ensuite ce choix via son sélecteur callable existant, sans interpréter à nouveau le mode global. Un éventuel fallback reste limité aux candidats de cet item.
7. Chaque élément batch entre dans la queue existante et obtient son propre plan au démarrage de son worker.

Le modèle `MediaItem` existant est conservé : `id`, `title`, `thumbnail`, `tabId`, `frameId`, `pageUrl`, `mediaKind`, `duration`, `candidates[]`, avec les champs de contexte déjà présents. Titres, posters, IDs et corrélation/déduplication ne sont pas réimplémentés.

Le résumé `DownloadPlan` enregistré dans le job/historique contient :

```text
mediaItemId, candidateId, sourceType, sourceUrl, downloadUrls[],
selectionPolicy, formatSelector
```

Le plan garde aussi en mémoire les formats exacts sélectionnés. Pour la vidéo best : `bv*+ba/bv*` (vidéo meilleure qualité, avec son audio si disponible). Pour 720/1080 : filtre `height<=?N`, permettant une source dont la hauteur est encore inconnue. Le sélecteur final utilise les formats déjà choisis, par exemple `direct-0-0` ou la paire DASH vidéo+audio. Aucun format de deux candidats ou de deux items n'est fusionné.

## Fichiers modifiés

| Fichiers | Modification |
| --- | --- |
| `extension/media-items.js` | Source propre prioritaire ; résolution du dépôt Commons depuis le poster/source et le nom du fichier ; ID du candidat extracteur. |
| `extension/background.js` | Rescan des sources manquantes ; jusqu'à 12 candidats appartenant à l'item ; transmission de `media_item_id`. |
| `extension/popup-items.js` | Checkbox cochée définit la cible du bouton Télécharger. |
| `extension/shared.js`, `extension/manifest.json` | Backend minimum 8.39 pour le chemin corrigé ; frontend 8.47. |
| `native-host/download_planner.py` | Scope par item, probes bornés, classement vidéo, DownloadPlan et sélection par yt-dlp puis choix lié au transfert. |
| `native-host/hls.py` | Validation des IDs/contextes et limite de candidats paramétrée ; downloaders inchangés. |
| `native-host/host.py` | Validation de l'appartenance des sources ; backend 8.39. |
| `native-host/media_item.py` | Diagnostic temporaire optionnel et URLs de log sans query string. |
| `native-host/worker.py` | Création/utilisation du plan ; diagnostic ; couverture WebM omise ; version du worker. |
| `backend.json`, `install.sh`, `Install.ps1` | Version backend/installateurs 8.39. |
| `tests/test-media-items.js` | Routage froid Commons, single direct, isolation des IDs, toutes les variantes et compatibilité 8.39. |
| `tests/test-download-planner.py` | Sources d'un autre item rejetées, quatrième variante et priorité à la meilleure résolution. |
| `tests/test-media-item-download.py` | Reproduction File, téléchargements A/B, WebM/MP4, source différée, HLS/DASH, audio/MP3, plans batch et guards natifs. |
| `tests/test-hls-firefox.py` | Checkbox A puis B → Télécharger ; batch best → plans distincts ; vraie page normale ; traces. |
| `README.md`, `tests/README.md` | Description et commandes de vérification. |
| `docs/MEDIA-DOWNLOAD-V8.47.md`, `docs/validation-media-download-v8.47.json` | Rapport et preuves structurées. |

## Tests exécutés

| Vérification | Résultat |
| --- | --- |
| Reproduction v8.46, page File à deux players | `format_unavailable` confirmé, aucun transfert. |
| Worker MediaItem réel | **13 tests OK** : A best 1080p, B 360p, source différée, WebM+poster, HLS, DASH séparé/fusion, audio original/MP3, batch/queue, guards et sélection du meilleur format silencieux. |
| Planner | **33/33 OK**, sources isolées et aucune URL de page probée lorsqu'un item possède des candidats techniques. |
| Firefox réel + Native Messaging | **9 groupes de contrôles OK** : checkbox/ligne, all/none, mises à jour async, DOM/embeds/recommandations, blob/HLS, galerie après clone, batch, téléchargements individuels A/B, page normale, logs. |
| Fichiers de la galerie locale | A **1080p MP4**, B **360p MP4**, avec audio, bonnes captions/posters et une occurrence par vidéo ; plans et URLs distincts, aucune source mélangée. |
| Wikimedia public : deux fichiers réels | Glow discharge et Snowman, fichiers distincts et valides, téléchargés depuis `upload.wikimedia.org`. La variante Glow discharge **WebM 1080p VP9/Opus** a aussi fini avec succès (8 191 880 octets après métadonnées). |
| Metadata Commons existant | `File:Columbia_Glacier,_Alaska.webm` : extracteur Wikimedia, 6 formats prêts, sans transfert. |
| Automatic / direct Automatic | **14/14**, **11/11 OK**. |
| HLS / DASH / direct | **12/12**, **15/15**, **21/21 OK**. |
| Queue / packaging | **22/22**, **3/3 OK** (installation Linux isolée et archives trois OS). |
| Banc hors ligne | **95 OK**, 0 échec, 5 ignorés faute de Chromium. |
| Node | 8 suites OK : MediaItems, détecteurs HLS/DASH/direct, background, groupes HLS (13 scénarios), resolver (38 assertions), démarrage popup (9 scénarios). |
| `web-ext 10.6.0 lint` | 0 erreur, 0 notice, 1 avertissement Android préexistant. |
| Syntaxe et `git diff --check` | OK. |

Le test de navigation/sélection de la galerie est exécuté dans Firefox contre une fixture locale fidèle ; les téléchargements publics réutilisent séparément les vraies URLs des fichiers extraites du HTML Wikimedia. La capture fournie montre les deux lignes de la vraie popup de test. Ce rapport distingue ces preuves d'une session complète sur la page distante.

Le contrôle public a utilisé le magasin CA système de cet environnement, avec TLS vérifié. Ce réglage de QA n'est pas intégré au backend distribué. Les probes publics ont parfois échoué ou dépassé leur budget : Automatic a alors utilisé une autre variante du **même fichier**. La qualité maximale est prouvée de manière déterministe par les fixtures ; le WebM public 1080p a été validé dans un essai séparé.

## Diagnostic et limites restantes

Les logs temporaires sont activés par `KITTY_TRACE_MEDIA_ITEMS=1` dans l'environnement du host/worker. Ils montrent l'ID/titre sélectionné, les IDs/types/qualités des candidats, le gagnant, les URLs de transfert et le sélecteur généré. Ils sont désactivés par défaut ; les query strings et headers sont omis. Un extrait de la validation est inclus dans l'archive.

Les players sans URL propre et dont les sources restent ambiguës ne sont pas téléchargés via une autre vidéo. Les blob URLs restent des indices DOM uniquement. La résolution est bornée à 12 candidats et 4 probes simultanés ; les hauteurs inconnues dépendent des métadonnées et du ffprobe existants. Un timeout réseau peut conduire à la meilleure variante effectivement résolue. La couverture WebM reste affichée dans Kitty, mais n'est pas intégrée au fichier. L'XPI reste non signé ; Windows/macOS ont été vérifiés par packaging, sans session native dans ces OS.

## Installation CachyOS / fish / Firefox

Télécharger `kitty-download-manager-v8.47-media-download.zip`, puis dans fish :

```fish
cd ~/Downloads
unzip -o kitty-download-manager-v8.47-media-download.zip -d kitty-v8.47
cd kitty-v8.47/kitty-download-manager
chmod +x install.sh
./install.sh
```

Réinstaller le backend est nécessaire : le correctif du plan est dans **8.39**. Dans `about:debugging` → Ce Firefox, charger/recharger le `extension/manifest.json` de ce dossier. La racine de l'archive contient aussi l'XPI 8.47 non signé et les installateurs backend 8.39 Linux/Windows/macOS. Aucune publication GitHub/Mozilla effectuée.
