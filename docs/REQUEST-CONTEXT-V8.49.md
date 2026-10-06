# Kitty v8.49 — RequestContext partagé

Frontend **8.49**, backend **8.40**, protocole natif **1**. Base : v8.48 actuelle. La logique de détection, de regroupement MediaItem, de sélection Automatic, de DownloadPlan et les downloaders yt-dlp restent en place.

## Contexte commun

Chaque candidat réseau conserve un `requestContext` privé ; le payload natif le normalise en `request_context`. Les sources DOM qui n'ont pas encore de requête observée sont normalisées à partir de leurs headers existants. Le modèle natif MediaCandidate expose également `requestContext`, exclu de sa représentation de diagnostic.

Structure du contexte :

```json
{
  "version": 1,
  "source_url": "URL exacte de la requête observée",
  "headers": {
    "Referer": "si présent",
    "Origin": "si présent",
    "User-Agent": "si présent",
    "Authorization": "valeur privée si présente",
    "x-media-key": "exemple de header applicatif"
  },
  "cookies": "snapshot privé du Cookie effectivement envoyé, si présent"
}
```

Les valeurs ne sont ni ajoutées à la liste publique du catalogue, ni affichées dans la popup. Aucune lecture globale du profil Firefox ou de son cookie store n'est ajoutée ; aucune nouvelle permission cookies n'est demandée.

## Conservation et transmission

- Le même module JS capture les headers de la requête HTTP du player pour HLS, DASH et direct, puis le même module Python valide et applique ce contexte.
- Les seuls headers reconnus sont Referer, Origin, User-Agent, Accept, Accept-Language, Authorization et les headers applicatifs X-*. X-Forwarded, X-Real-IP et X-Proxy sont exclus.
- Range, Host, headers conditionnels/cache, headers de connexion et contrôles du navigateur ne sont pas rejoués. Le downloader conserve son propre fonctionnement Range.
- Les headers absents ne sont pas inventés. Le contexte reste associé à l'URL exacte du candidat ; une autre URL de source dans ce contexte est refusée. Chaque variante direct conserve son propre contexte.
- Le contexte passe dans le probe supervisé, Automatic, puis le transfert du candidat retenu. Il n'est pas injecté dans l'extraction classique de la page courante.
- Le transport HTTP urllib existant de yt-dlp reçoit une politique commune. Les credentials restent hors des headers globaux de yt-dlp. Chaque requête, y compris une redirection, est vérifiée sur le triplet scheme/hostname/port.
- Les cookies et headers contrôlés ne partent pas vers une autre origine. Une redirection sur la même origine garde les headers nécessaires et la cookiejar peut prendre en compte un renouvellement de session.
- Les choix des variantes restent indépendants ; un test réel MP4 720p/1080p vérifie qu'Automatic télécharge la variante haute avec sa propre session et son propre header.
- Le contexte privé peut rester dans la queue protégée pendant le job et pour un retry en erreur. Il est retiré de l'historique après succès ou annulation. Toutes les réponses natives sont filtrées avant envoi à l'UI, y compris l'état d'une queue encore active.
- Les anciens payloads à trois headers restent acceptés. Pour les cookies et les headers supplémentaires, le frontend exige backend 8.40.

Aucun adaptateur par site n'est ajouté.

## Confidentialité et diagnostics

Les valeurs de cookies, Authorization et headers applicatifs ne sont pas journalisées. Les erreurs de validation et réseau restent génériques. Le modèle RequestContext masque ses champs privés dans repr ; son diagnostic contient seulement la version, les noms de headers et la présence d'une session.

Les logs bruts de trafic yt-dlp sont désactivés pour ces candidats. Les callbacks et probes continuent d'utiliser le logger silencieux existant. Le contexte traverse les fichiers temporaires du probe avec les permissions privées existantes.

Le ffprobe distant facultatif est omis pour un contexte contenant une session ou des headers supplémentaires : ce subprocess suivrait les redirections sans la politique du transport commun. Le téléchargement et la vérification locale finale restent actifs.

## Tests exécutés

| Suite | Résultat |
| --- | --- |
| `node tests/test-request-context.js` | Capture commune, exclusions transport/injection, contexte HLS/DASH/direct, variantes et résumés privés : réussi. |
| `python3 tests/test-request-context.py` | **11/11** : vrais MP4/HLS/DASH nécessitant Referer/Origin/UA + cookie/Authorization/header applicatif ; accès refusé sans contexte ; Referer/Origin seuls ; isolation de variantes 720p/1080p ; probe Automatic ; validation ; redirection inter-origines sans fuite ; redirection même origine et cookie renouvelé. |
| Firefox 153, suite MediaItems | **11 groupes** : galerie, captions/posters, variants, sélection conservée, batch → queue → plans → fichiers indépendants, blob/HLS, item unique et extraction yt-dlp de page normale. |
| Firefox 153, scénario RequestContext séparé | **2 groupes** : capture réelle des headers/session du player, Native Messaging → probe et transfert MP4 protégé → fichier valide ; statut et logs sans secrets. |
| `test-media-item-download.py` | **13/13**. |
| `test-download-planner.py` | **33/33**. |
| `test-automatic-download.py` | **14/14**. |
| `test-direct-automatic.py` | **11/11**. |
| `test-hls-download.py` | **12/12**. |
| `test-dash-download.py` | **15/15**. |
| `test-direct-download.py` | **21/21**. |
| `test-hls-group-download.py` | **6/6**. |
| Suites Node | **10 suites réussies**, incluant RequestContext, les 34 tests de corrélation et les détecteurs/résolveur/popup existants. |
| `bash test.sh` | **95 OK, 0 échec, 5 ignorés** (Chromium absent). Inclut l'updater et la conservation de la queue. |
| `test-backend-packaging.py` | **3/3** ; packaging et installation Linux fraîche/mise à jour. |
| `test-windows-port.py InstallerTests` | **26/26** tests portables d'installateur. |
| `test-macos-port.py` | **10 réussis, 1 ignoré**, sur ce runner Linux. |
| `web-ext lint` | **0 erreur, 0 notice** ; 1 warning Android préexistant. |
| Syntaxe Python/shell et `git diff --check` | Réussis. |

Les deux scénarios Firefox sont validés dans des profils de test séparés. Les fixtures sont locales ; aucune nouvelle validation live de sites publics n'est revendiquée.

Commandes Firefox :

```bash
KITTY_TEST_MEDIA_ITEMS=1 KITTY_TRACE_MEDIA_ITEMS=1 python3 tests/test-hls-firefox.py
KITTY_TEST_MEDIA_ITEMS=1 KITTY_TEST_REQUEST_CONTEXT=1 KITTY_TEST_REQUEST_CONTEXT_ONLY=1 python3 tests/test-hls-firefox.py
```

Ces commandes utilisent les variables habituelles KITTY_FIREFOX_BINARY et KITTY_GECKODRIVER et les dépendances de test du projet.

## Fichiers modifiés

- `extension/request-context.js` : contrat/capture/headers historiques partagés.
- `extension/hls-detector.js` : rattachement du contexte à chaque candidat et variante ; classement inchangé.
- `extension/background.js`, `extension/shared.js` : payload privé, compatibilité backend, contexte des sources DOM.
- `native-host/request_context.py` : validation, politique de transport commune, cookies et filtrage des réponses publiques.
- `native-host/hls.py`, `native-host/direct_media.py` : usage du contexte commun et exclusion du ffprobe distant avec credentials.
- `native-host/download_planner.py`, `native-host/metadata_guard.py`, `native-host/worker.py`, `native-host/host.py` : modèle, probe supervisé, transfert, nettoyage et statut.
- `backend.json`, `extension/manifest.json`, `install.sh`, `Install.ps1`, `native-host/maintenance.py`, `native-host/windows_install.py`, `native-host/macos_install.py` : versions et installation/mise à jour du module.
- `tests/test-request-context.js`, `tests/test-request-context.py`, `tests/test-hls-firefox.py` : tests ajoutés. Les VMs des tests de détecteurs/MediaItems chargent aussi le nouveau module commun.
- README, tests/README, présent rapport et résultats JSON : documentation.

## Limites

Le contexte est un snapshot d'une requête effectivement observée : une session expirée nécessite une nouvelle requête du player ou une actualisation. Il ne copie pas une session vers un CDN d'une autre origine qui n'a pas été observé avec ses propres credentials. La preuve de portée retenue est l'origine ; les attributs Domain/Path/SameSite d'origine des cookies ne sont pas disponibles dans un header Cookie observé et ne sont pas inventés.

Les headers applicatifs sans préfixe X-* hors de la liste standard ne sont pas encore rejoués. Les cookies partitionnés propres au navigateur ne sont pas importés globalement ; seul le snapshot déjà envoyé est utilisé pour le média. Le ffprobe distant omis peut laisser certains codecs/durées inconnus avant transfert. Les OS Windows/macOS ne sont pas exécutés nativement sur ce runner Linux.

## Installation CachyOS / fish / Firefox

**Réinstaller le backend 8.40**, puis recharger l'extension 8.49. L'archive garde toujours la racine **kitty-download-manager/** :

```fish
cd ~/Downloads
unzip -o kitty-download-manager-v8.49-request-context.zip
cd kitty-download-manager
chmod +x install.sh
./install.sh
```

Dans about:debugging → Ce Firefox, recharger/charger `~/Downloads/kitty-download-manager/extension/manifest.json`. Le dossier de décompression reste `~/Downloads/kitty-download-manager`. XPI non signé et installateurs backend Linux/Windows/macOS inclus ; aucune publication GitHub/Mozilla.
