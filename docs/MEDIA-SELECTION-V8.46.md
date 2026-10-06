# Kitty v8.46 — sélection et sources Wikimedia

Frontend **8.46**, backend **8.38 inchangé**. Départ du dépôt actuel v8.45, commit `0b70bc4`. Correctif applicatif : `eea3680c118e527fb1895f8c1c637248099193be`. Aucun downloader ni extracteur réimplémenté.

## Cause reproduite avant modification

Dans Firefox 153, deux placeholders vidéo sans sources affichaient leurs captions et posters mais leurs checkboxes étaient désactivées. Les clics atteignaient bien les contrôles : `pointer-events: auto`, aucun overlay devant eux. Le blocage venait de `checkbox.disabled = !item.downloadable` dans `popup-items.js`.

Le script Wikimedia TimedMediaHandler remplace le lecteur original par un clone superficiel, sans les enfants `<source>`, puis enlève `src`. Ce clone conserve notamment le poster et le lien `resource` du fichier. Le comportement a été vérifié dans le module actuel [ext.tmh.player](https://en.wikipedia.org/w/load.php?modules=ext.tmh.player&only=scripts&lang=en), puis reproduit dans les tests.

Le scanner v8.45 ne transmettait pas cette identité de fichier. Sa corrélation reposait essentiellement sur les URLs déclarées par le lecteur, absentes du clone. Dans une galerie, les indices restants n'étaient pas suffisants pour attribuer les candidats réseau à une vidéo précise. Un test avec les vrais schémas d'URL Wikimedia produisait **0 et 0** candidat direct au lieu de **2 et 1**. Sans candidat ni URL d'extraction propre à chaque fichier, `downloadable=false` provoquait « Source unavailable ».

« Select all » filtrait également `items.filter(i => i.downloadable)` : cette collection était vide. Le bouton ne changeait jamais de libellé. Autre défaut : les IDs étaient recalculés à partir de la liste de sources, et le rafraîchissement supprimait la sélection des items temporairement sans source. Une arrivée asynchrone de source pouvait donc perdre la sélection.

## Correctif

- Le scanner lit `resource`, le lien de lecture du wrapper Wikimedia, les sources lazy `data-src` et `data-durationhint`. La hiérarchie caption/titre/poster existante est conservée.
- Le catalogue logique corrèle les posters, liens File et transcodes par **dépôt Wikimedia + nom du fichier original**, dans le bon onglet/frame/document. Il ne regroupe pas les médias par CDN seul. Les variantes MP4/WebM rejoignent le même MediaItem.
- Si Kitty a vu le lecteur avant son remplacement, ses déclarations et dimensions/durée sont conservées pour le même `resource`. Si Kitty démarre tard, l'identité du fichier permet de rattacher le catalogue réseau déjà détecté. Sans candidat observé, le lien File peut servir d'URL d'extraction propre au média.
- Les IDs sont conservés par nœud DOM et identité de ressource. Ajouter une source, changer une caption/poster ou remplacer le lecteur par son placeholder ne recrée pas l'item.
- La sélection dépend de `selectable`, indépendamment de `downloadable`. Un item en attente de source reste sélectionnable et porte un libellé d'attente. Checkbox et contenu de ligne togglent la sélection. Select all/Deselect all utilisent la même collection admissible.
- Au téléchargement d'un item encore sans source, le background demande un snapshot récent de ses frames et attend son acquittement. Il réutilise ensuite Automatic et la queue existants. Un média encore ambigu n'est pas remplacé par toute la galerie : l'échec reste explicite et sa sélection est conservée pour réessayer.
- Le flag existant `explicit_sources` reconnaît aussi les variantes prouvées par l'identité Wikimedia. Automatic peut comparer leurs qualités sans les éliminer comme des ressources sans rapport. Les sources HLS/DASH/direct/yt-dlp et leurs règles restent celles du projet.
- Après un batch, seuls les items effectivement ajoutés ou déjà présents sont décochés ; les échecs restent sélectionnés. Les contrôles sont resynchronisés et le bouton batch est protégé contre les doubles clics pendant l'ajout.

## Fichiers modifiés

| Fichier | Modification |
| --- | --- |
| `extension/media-dom.js` | Indices Wikimedia, sources lazy, durée du placeholder. |
| `extension/media-items.js` | Corrélation du fichier original, conservation des sources et IDs, admissibilité indépendante. |
| `extension/media-context.js` | Observation des attributs utiles et snapshot acquitté. |
| `extension/background.js` | Résolution par rescan lors du téléchargement, flag existant pour les variantes prouvées. |
| `extension/popup-items.js` | Checkbox/ligne, all/none, conservation de sélection, batch partiel. |
| `extension/popup.js` | Retour des résultats batch à la sélection. |
| `extension/i18n.js` | Deselect all et état de source en attente en FR/EN. |
| `extension/manifest.json` | Version frontend 8.46. |
| `tests/test-media-items.js` | Placeholders/transcodes Wikimedia, IDs stables, isolation, batch tardif et rescan. |
| `tests/test-hls-firefox.py` | Reproduction préalable et interactions dans la vraie popup Firefox. |
| `tests/test-media-item-download.py` | Galerie avec ressources de fichiers et remplacement fidèle des lecteurs. |
| `README.md` | Description et lien du correctif. |
| `docs/MEDIA-SELECTION-V8.46.md` | Ce rapport. |
| `docs/validation-media-selection-v8.46.json` | Résultats et preuves structurées. |

## Tests exécutés

| Vérification | Résultat |
| --- | --- |
| Reproduction Firefox 153 sur v8.45 | Bug confirmé : contrôles désactivés, aucune obstruction CSS, zéro sélection après checkbox + Select all. |
| `node tests/test-media-items.js` | OK : candidats Wikimedia 2/1, sans mélange entre fichiers ; batch tardif ; IDs stables ; rescan au téléchargement ; isolation ; blob/HLS ; DASH ; embeds. |
| Firefox réel, `KITTY_TEST_MEDIA_ITEMS=1 python3 tests/test-hls-firefox.py` | **7 groupes de contrôles OK** : checkbox on/off, ligne toggle, all/none, conservation async, échecs conservés, DOM dynamique, embeds/recommandations, blob/HLS, galerie, queue et téléchargements. |
| Galerie après clone superficiel sans src/source | **2 lignes**, captions et posters corrects, IDs conservés, 2 variantes du premier média regroupées ; batch = **2 jobs distincts**. |
| Fichiers batch inspectés avec ffprobe | Deux fichiers audio/vidéo valides : **A 1080p**, **B 360p**, un fichier/historique par média, noms depuis les captions. |
| Worker MediaItem | **2/2 OK**. |
| Automatic / direct Automatic / HLS / DASH | **14/14**, **11/11**, **12/12**, **15/15 OK**. |
| Planner / queue / packaging Linux + archives trois OS | **30/30**, **22/22**, **3/3 OK**. |
| Régression hors ligne | **95 OK, 0 échec, 5 ignorés** : tests Chromium faute de navigateur Chromium. |
| Détecteurs direct/DASH, groupes HLS, background, resolver | OK ; **13 scénarios HLS**, **38 assertions resolver**. |
| Démarrage popup | **9 scénarios asynchrones OK**. |
| `web-ext@10.6.0 lint` | **0 erreur**, 1 avertissement préexistant sur le minimum Firefox Android et `data_collection_permissions`. |
| Syntaxe Python/JS et `git diff --check` | OK. |

L'audit supplémentaire `test-popup-render.js` via Playwright n'a pas pu démarrer : son Firefox spécifique manque. Il n'est pas compté comme réussi. Les interactions et la capture ci-dessus ont été validées dans Firefox réel avec Selenium/Native Messaging.

## Limites et utilisation

La galerie de bout en bout est une fixture locale reproduisant la structure Wikimedia et le remplacement du player. La corrélation au démarrage tardif utilise les vrais schémas d'URL Wikimedia dans le catalogue de test. Aucune URL de galerie utilisateur précise n'a été fournie ; ce rapport ne prétend pas avoir téléchargé cette page distante.

Un player sans URL HTTP, sans identité de fichier et avec un catalogue ambigu peut être sélectionné, mais doit attendre la lecture ou une source exploitable. Son échec ne crée pas de mauvais job et conserve la sélection. Les blob URLs ne sont jamais téléchargées.

Recharger l'extension depuis `kitty-download-manager/extension/manifest.json` dans `about:debugging`, ou installer l'XPI v8.46 selon le mode de Firefox utilisé. L'XPI fourni est non signé. Le backend v8.38 déjà installé peut être conservé. L'archive contient le projet corrigé et l'XPI ; aucune publication distante n'a été effectuée.
