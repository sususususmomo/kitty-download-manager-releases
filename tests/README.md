# Tests de régression — Kitty Download Manager

## RequestContext (frontend 8.49 / backend 8.40)

`node tests/test-request-context.js` vérifie la capture et le contrat commun. `python3 tests/test-request-context.py` exécute 11 tests HTTP réels : MP4/HLS/DASH protégés par headers/session, Referer/Origin seuls, variantes indépendantes, validation, renouvellement de cookie et absence de fuite sur redirection. Pour la capture depuis une vraie page Firefox : `KITTY_TEST_MEDIA_ITEMS=1 KITTY_TEST_REQUEST_CONTEXT=1 KITTY_TEST_REQUEST_CONTEXT_ONLY=1 python3 tests/test-hls-firefox.py`. La suite MediaItems normale reste exécutée séparément. Voir [le rapport](../docs/REQUEST-CONTEXT-V8.49.md).

## Corrélation des MediaItems (frontend 8.48 / backend 8.39)

`node tests/test-media-correlation.js` exécute 34 cas sur le classifier et Store de production : listes de sources incluses, liens master/variant et formats yt-dlp, ordre d'arrivée, scope tab/frame/document, Wikimedia, blob, ambiguïtés, audio partagé, IDs stables et logs sans secrets. `KITTY_TEST_MEDIA_ITEMS=1 KITTY_TRACE_MEDIA_ITEMS=1 python3 tests/test-hls-firefox.py` vérifie aussi le regroupement de vrais nœuds DOM et l'isolation de deux vidéos dans le même figure, puis le batch jusqu'aux fichiers réels. Voir [stratégie et résultats](../docs/MEDIA-GROUPING-V8.48.md).

## Téléchargement des MediaItems (frontend 8.47 / backend 8.39)

`node tests/test-media-items.js` vérifie le routage Commons, la priorité aux sources de l'item, leur isolation et le batch. `python3 tests/test-media-item-download.py` reproduit la page File à deux players, puis vérifie les plans et fichiers réels A/B, MP4/WebM best, WebM avec poster, HLS, DASH, audio/MP3, résolution différée et queue indépendante. `python3 tests/test-download-planner.py` couvre aussi les sources associées à un autre item, la quatrième variante et la qualité maximale.

`KITTY_TEST_MEDIA_ITEMS=1 KITTY_TRACE_MEDIA_ITEMS=1 python3 tests/test-hls-firefox.py` utilise la vraie popup Firefox et Native Messaging : checkbox A puis B → bouton Télécharger, batch → queue, plans distincts et fichiers inspectés avec ffprobe. Les logs de diagnostic omettent les query strings et headers et sont désactivés par défaut. Voir [le rapport](../docs/MEDIA-DOWNLOAD-V8.47.md).

## Hiérarchie HLS (frontend 8.42 / backend 8.35 inchangé)

`node tests/test-hls-groups.js` teste le parser et le catalogue de production,
les relations réellement déclarées, trois qualités/audio/sous-titres, les URLs
signées, les rechargements, plusieurs vidéos, les masters imbriqués/cycliques,
le passage inchangé des octets et les limites/timeout du StreamFilter.

`python3 tests/test-hls-group-download.py` ajoute six cas réels au banc HLS
existant : master à trois vidéos fMP4 et audio séparé, formats/sous-titres,
fusion 1080p/720p, fallbacks isolés, annulation/nettoyage, file en pause/reprise
et historique. Le backend de production n'est pas modifié.

Avec les mêmes variables Firefox/geckodriver que ci-dessous, exécuter
`env KITTY_TEST_HLS_GROUPS=1 python3 tests/test-hls-firefox.py`. Ce parcours
vérifie la vraie popup, Native Messaging et le fichier vidéo/audio fusionné.
Les captures et le rapport sont dans `artifacts/hls-groups`. Exécuter ensuite
les modes HLS, DASH et DIRECT existants, séquentiellement. Le HLS historique
attend désormais une seule source pour le master et son enfant référencé.

Consulter [HLS.md](../docs/HLS.md) pour la structure et les limites.

## Détection réseau HLS + DASH (frontend 8.40 / backend 8.34)

La même observation webRequest et le même catalogue par onglet prennent en
charge les manifests HLS et DASH. `node tests/test-dash-detector.js` couvre MPD,
MIME, déduplication, headers, compatibilité, fermeture et absence de boucle.
L'architecture et les limites sont décrites dans [DASH.md](../docs/DASH.md).
`python tests/test-dash-download.py` utilise le vrai yt-dlp et FFmpeg contre des
fixtures locales, y compris vidéo/audio séparés, fusion, audio seul, MPD signé,
DRM synthétique, lenteur, timeout, annulation et nouvelle connexion au backend.
`python tests/test-production-timeouts.py` vérifie aussi les délais FFmpeg/ffprobe.
La suite HLS reste exécutée séparément : `python tests/test-hls-download.py`.

Avec Selenium, Firefox et geckodriver disponibles, le parcours natif complet
est exécuté par `python tests/test-hls-firefox.py` ; définir `KITTY_TEST_DASH=1`
pour le parcours DASH. Les variables `KITTY_FIREFOX_BINARY` et
`KITTY_GECKODRIVER` pointent vers les exécutables de test. Ces essais n'utilisent
pas de compte connecté et restaurent l'enregistrement Native Messaging initial.

Budgets de production : 30 s pour un probe ou le titre en file, 120 s pour
l'extraction avant téléchargement, 60 s pour une collection, 15 s pour ffprobe
et la détection des versions, 600 s pour une opération FFmpeg locale. La durée
globale des téléchargements n'est pas limitée. Les tests utilisent des budgets
courts injectés localement pour prouver l'arrêt réel, sans attendre ces délais.

## Contrôle public facultatif, avec durée bornée

`python tests/check-public-metadata.py --timeout 60 --report artifacts/public-youtube.json`
vérifie les métadonnées et formats d’une vidéo YouTube publique avec le pipeline
existant, sans télécharger de média et sans modifier la file utilisateur. Une URL
différente peut être fournie en argument. Le processus parent impose une limite
globale de 60 secondes, en plus du timeout réseau de 8 secondes et des retries
désactivés pour ce contrôle. Il arrête aussi les processus enfants et renvoie le
code 124 ainsi qu’un rapport `status: timeout` si la limite est dépassée.

Les erreurs de certificat sont explicites. Un environnement CI dont l’autorité
de certification est installée dans le magasin système peut ajouter
`--system-ca` pour ce contrôle seulement ; la vérification TLS reste active.
Ce réglage n’est pas appliqué au backend distribué. Le test public ne fait pas
partie de la régression hors ligne : une panne du site ne bloque pas cette suite.

`python tests/test-metadata-timeout.py` vérifie avec de vrais processus le succès,
les résultats invalides, les budgets invalides, l’interruption du contrôle,
l’arrêt d’un enfant et le cas
d’un serveur qui envoie continuellement des données lentement. Il exige yt-dlp
pour ce dernier cas.

## Mode Image uniquement (frontend v8.38 / backend v8.32)

`python tests/test-image-download.py` exige le vrai module yt-dlp et utilise uniquement un serveur HTTP local. Les tests couvrent les miniatures et les pochettes de collections, l’absence de requêtes audio/vidéo, les images manquantes/invalides, le repli sur une miniature disponible, le format d’origine, les noms uniques et l’annulation. Les validations Windows et macOS exécutent cette suite avec le Python et le backend réellement installés.

`node tests/test-image-mode.js` vérifie le choix du mode pour le pill et le clic droit. `tests/test-popup-render.js` teste aussi les options grisées, la persistance, le retour au format précédent et le message de mise à jour pour un ancien backend dans Firefox, en français et en anglais, y compris avec une petite popup. Les captures des vraies popups Windows/macOS incluent le nouveau menu et la restauration après réouverture.

Depuis la racine du projet :

```bash
./test.sh
```

Le banc de tests est volontairement **hors-ligne** et n'écrit rien dans le vrai
`$HOME`. Les essais d'installation, de configuration et de queue sont réalisés
dans des répertoires temporaires isolés.

Il vérifie notamment :

- manifest Firefox et Native Messaging
- syntaxe Python et JavaScript
- cohérence des numéros de version
- contraintes de coût du Universal Media Resolver
- canonicalisation TikTok / Instagram / X / Reddit / Facebook / YouTube /
  Dailymotion / Twitch
- `canonical`, `og:url`, JSON-LD et fallback générique du resolver
- installation dans un faux HOME
- protocole Native Messaging
- persistance du dossier de destination
- migration, sauvegarde et récupération de `queue.json`
- pause des jobs encore en file et pause globale de la file
- détection des doublons
- reset sûr sans effacer les réglages
- noms propres `Titre`, `Titre (2)`, `Titre (3)`
- nettoyage ciblé des `.part` lors d'une annulation
- écritures atomiques et limite de l'historique

## Node.js

La majorité des tests n'a besoin que de Python 3. Les tests JavaScript du
resolver utilisent Node.js s'il est présent. Si Node.js n'est pas installé,
ils sont indiqués comme `ignorés` au lieu de faire échouer toute la suite.

Aucun téléchargement réel n'est lancé par cette suite : les spawns du worker
sont simulés pour les tests de queue. Cela rend les tests rapides,
reproductibles et sans dépendance aux changements des sites.


## Stockage partagé et concurrence (V8.19)

`run-regression.py` lance également `test-queue-store.py`. Pour le lancer seul :

```bash
python3 tests/test-queue-store.py
```

Cette suite couvre les lectures sans écriture, les mutations sans effet, les
migrations, la conservation d'un schéma futur/corrompu, l'échec de sauvegarde ou
d'écriture, les interruptions, l'historique borné, les workers obsolètes, les
réservations de métadonnées et l'échec de lancement. Deux tests démarrent six
processus réels pour vérifier l'absence de pertes d'écriture et de doublons.

Les tests visuels sont indiqués comme ignorés si Chromium ou Playwright est
absent. Ils restent nécessaires pour valider l'interface; les autres tests ne
prouvent pas son bon fonctionnement. Les téléchargements réels ne sont pas
lancés par le banc de tests.


## Démarrage asynchrone de la popup (V8.23)

`node tests/test-popup-startup.js` exerce le coordinateur et la requête de statut
avec des réponses retardées : l'interface n'est révélée qu'une fois le statut et
les préférences traités, et la lecture native possède une sortie sur timeout.
La suite vérifie aussi l'ordre du démarrage des polls et des réglages cachés.
Ce test ne remplace pas la vérification du premier rendu dans Firefox.

## Captures Firefox sur Windows (V8.28)

Le job `windows-visual` de `.github/workflows/windows-validation.yml` installe
Firefox officiel et Kitty sur un runner Windows neuf. Selenium 4.50.0 charge
une extension temporaire dont les fichiers de production sont inchangés; seule
une page de pilotage est ajoutée à ce XPI de test, dans un profil isolé.

`capture-windows-firefox.py` ouvre la vraie popup de la barre d’outils, vérifie
Native Messaging depuis Firefox et capture son viewport avec le moteur Gecko.
La file est en pause, les titres sont complets et l’historique est marqué
« Exemple CI »; aucun téléchargement de média ni probe réseau n’est lancé.
Le fichier de file original est restauré après la fermeture de Firefox.

Le script exige Windows, `GITHUB_ACTIONS=true` et `KITTY_VISUAL_TEST=1`. Il est
ignoré ailleurs. Il produit sept PNG, une galerie `index.html`, un rapport JSON
et le journal geckodriver, publiés dans l’artefact
`kitty-windows-firefox-captures` même après un échec de capture.

Le mode headless conserve le rendu Firefox et les polices de Windows, mais
les images représentent des états stabilisés : elles ne valident pas les
flashs très brefs, le sélecteur de dossier natif ni une installation manuelle
sur un bureau Windows 10/11. Les versions Firefox et geckodriver sont inscrites
dans le rapport. Les tests d’installation existants ont leur propre job.


### Attente des diagnostics (V8.31)

Le pilote attend la fin de la requête et le rendu d’une liste dans le groupe
ouvert, puis accepte les trois états terminaux : prêt, avertissement et erreur.
Il conserve le diagnostic natif complet, capture le groupe puis vérifie que
les dépendances requises et les fichiers de runtime sont disponibles. L’état
global peut être une erreur sur une installation fraîche dont la destination
n’a pas encore été créée; cet état reste visible dans l’image et le rapport.

`python3 tests/test-visual-capture.py` couvre les avertissements, les erreurs,
les diagnostics encore en cours et les véritables défaillances du backend.


## Rendu DOM sécurisé et comparaison Firefox (v8.37)

`test-popup-render.js` charge les vrais fichiers de la popup dans Gecko avec des réponses natives hors-ligne. Il compare la géométrie des éléments et les pixels avec la v8.36 : 15 vues × français/anglais × trois hauteurs (320, 520 et 900 px). Les captures figent les animations à un instant identique ; elles ne mesurent pas leur fluidité. Les essais vérifient aussi les clics source/pause/suppression/relance, les URLs HTTP/HTTPS, les titres et erreurs contenant du HTML, les namespaces SVG et la conservation des nodes entre deux états identiques.

Le job `popup-render` de `backend-downloads.yml` prépare Playwright et publie l’artefact `kitty-firefox-render-comparison`, avec les PNG avant/après et `report.json`. Les captures existantes Windows/macOS vérifient séparément la vraie popup installée et Native Messaging.

## HLS

See [HLS.md](../docs/HLS.md) for the passive Firefox detector and real download fixtures.
Run `node tests/test-hls-detector.js` and `python tests/test-hls-download.py` with yt-dlp, Mutagen and FFmpeg/ffprobe available. On Linux, `tests/test-hls-firefox.py` additionally exercises the actual Firefox popup and Native Messaging with isolated data; it requires Selenium and the `KITTY_FIREFOX_BINARY` / `KITTY_GECKODRIVER` environment variables.


## Shared HLS / DASH / direct media checks (frontend 8.41, backend 8.35)

See [DIRECT-MEDIA.md](../docs/DIRECT-MEDIA.md) for architecture and heuristics.
Tests use local synthetic media, real yt-dlp and FFmpeg/ffprobe; they require
`yt-dlp[default]` and the existing backend dependencies. No protected media or
license server is accessed. The regression suite remains separate and offline.

```sh
node tests/test-direct-detector.js
python3 tests/test-direct-download.py
python3 tests/test-hls-download.py
python3 tests/test-dash-download.py
python3 tests/test-production-timeouts.py
python3 tests/test-backend-packaging.py
python3 tests/run-regression.py
```

The direct backend suite covers MP4/WebM/audio, MIME-only URLs, complete signed
URLs, mandatory headers, optional probe failure, real truncation/cancellation,
byte/speed/ETA updates, source naming, quality grouping and synthetic CENC DRM.
The Node suite loads the production shared detector/background and exercises
many 206 ranges, deduplication, notifications/log counts, source cleanup, mode
compatibility, blob context, fragment exclusions and source-page pill adoption.

On Linux, with Selenium, Firefox and geckodriver available, run the same real
Firefox/native-host harness in each mode **sequentially**. Set
`KITTY_FIREFOX_BINARY` and `KITTY_GECKODRIVER` to the executable paths.

```sh
KITTY_TEST_DIRECT=1 python3 tests/test-hls-firefox.py
KITTY_TEST_DASH=1 python3 tests/test-hls-firefox.py
python3 tests/test-hls-firefox.py
```

These commands are POSIX shell examples; in fish use `env KITTY_TEST_DIRECT=1
python3 tests/test-hls-firefox.py`. Each run restores the user's previous native
registration in `finally`, uses isolated queue/data and produces a JSON report
and a real toolbar PNG under `artifacts/direct`, `artifacts/dash` or
`artifacts/hls`. The harness has finite Selenium waits and local ffprobe timeouts.
For an additional whole-run bound use `timeout --kill-after=5s 180s` before
Python. Native Windows/macOS runs and public-provider coverage remain separate.

Automatic direct-media regression (local HTTP, real yt-dlp/FFmpeg/ffprobe):

```sh
python tests/test-direct-automatic.py
node tests/test-hls-background.js
```

The background test reproduces the Reddit full-permalink/canonical-permalink mismatch, checks all network families and rejects unrelated posts/feeds. The worker suite checks real MP4/WebM/MIME-only files, AV metadata, quality scoring against HLS, headers, Range context, cancellation and history. Firefox direct QA additionally downloads the MIME-only source through Automatic.


MediaItem DOM/catalogue/Automatic/batch regression:

```sh
node tests/test-media-items.js
python3 tests/test-media-item-download.py
KITTY_TEST_MEDIA_ITEMS=1 python3 tests/test-hls-firefox.py
```

The Firefox command uses the same isolated registration and local HTTP fixtures as the other modes. It checks native DOM scans, dynamic updates, real embed recognition, blob/HLS correlation, captions and posters in a Wikimedia-style gallery, distinct paused queue entries and real final files inspected with ffprobe. It also checks the single-player UI. Set `KITTY_FIREFOX_BINARY` and `KITTY_GECKODRIVER` to complete executable installations; supply yt-dlp and Selenium in the Python environment. Public Wikimedia/YouTube/Vimeo coverage and native Windows/macOS validation are separate.

## Audit Windows 8.48

`python tests/test-windows-audit.py` injecte les défauts Windows ; son test de modèle de sortie exige le vrai yt-dlp. `python tests/test-youtube-session.py` teste huit cas de session isolée, dont la concurrence et les échecs de nettoyage. `node tests/test-youtube-session-ui.js` exécute les vrais gestionnaires de session contre les réponses tardives et erreurs. Ces tests font partie de `test.sh`.

Sur des runners Windows dédiés seulement, après installation privée : `KITTY_WINDOWS_AUDIT=1` et `GITHUB_ACTIONS=true`, puis `python tests/test-windows-native-audit.py`. Le workflow `windows-audit.yml` prépare les environnements, le vrai Firefox et les captures. Le bridge JavaScript passe par le véritable lanceur `.bat`. Les résultats natifs ne sont pas disponibles tant que ce workflow n’a pas été exécuté. Voir [le rapport détaillé](../docs/WINDOWS-AUDIT-V8.48.md).
