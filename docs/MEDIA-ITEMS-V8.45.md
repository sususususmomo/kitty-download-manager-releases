# Kitty v8.45 — médias logiques et sélection batch

Frontend **8.45**, backend **8.38**, protocole Native Messaging **1**. Travail réalisé à partir du dépôt v8.44, commit `65b5a7a`, inspecté avant modification. L’ancien XPI non suivi 8.36 a été conservé. Livraison locale, XPI non signé, sans publication GitHub/Mozilla.

## Résultat vérifié

Une galerie locale reproduisant la structure Wikimedia `.gallerybox > .thumb + .gallerytext` affiche **deux médias**, avec leurs deux captions et posters. Le premier lecteur déclare WebM 720p et MP4 1080p ; ces deux sources restent dans **un MediaItem**. Le deuxième lecteur reste un autre MediaItem, en 360p.

La vraie popup Firefox permet de sélectionner les deux médias, les ajoute à la queue existante en pause, puis le worker les télécharge successivement après reprise. Les fichiers finaux ont été inspectés avec ffprobe : vidéo + audio dans chacun, premier film en 1080p, deuxième en 360p, titres conservés dans les fichiers et l’historique. Il y a un job et une entrée d’historique par média, aucun téléchargement complet concurrent de ses variantes.

Le test vérifie également un lecteur unique : la vue reste compacte, les sources techniques sont masquées, le probe yt-dlp de la page participe à Automatic et un fichier final audio/vidéo est produit.

## Architecture et fichiers

Le détecteur HLS/DASH/direct, leurs parsers et les extracteurs yt-dlp restent ceux de la v8.44. La nouvelle couche contient uniquement l’identité DOM, la présentation et le périmètre des sources d’un média.

`DOM → MediaItem + catalogue réseau existant → Automatic existant → scorer existant → pipeline existante`

| Fichiers | Changement |
| --- | --- |
| `extension/media-dom.js` — nouveau | Lecture DOM, captions/posters, reconnaissance des vrais embeds, URLs déclarées par chaque lecteur. |
| `extension/media-items.js` — nouveau | Catalogue logique par onglet/frame, regroupement et corrélation, candidats DOM classifiés par le détecteur existant. |
| `extension/media-context.js` | Snapshots avec MutationObserver, événements metadata/load, restauration et navigation de l’historique. |
| `extension/hls-detector.js` | Conservation de `frame_id`, des frames observées et de `document_url` dans les candidats existants. |
| `extension/background.js` | Liste privée/publique des MediaItems, métadonnées à la demande, dispatch par média et batch séquentiel vers la queue. |
| `extension/popup-items.js` — nouveau | Contrôle compact, titres/miniatures, sélection individuelle et batch. |
| `extension/popup-hls.js`, `popup.js`, `popup.html`, `i18n.js`, `shared.js` | Intégration de la vue logique, routage du bouton existant, traductions et contrôle du backend minimum. |
| `native-host/media_item.py` — nouveau | Validation du contexte logique, priorité des captions/posters sur les métadonnées de téléchargement. |
| `native-host/host.py` | Contexte MediaItem dans enqueue/retry, métadonnées d’embed via l’extracteur supervisé existant. |
| `native-host/download_planner.py` | Les variantes déclarées par le même lecteur DOM restent comparables même si leurs URLs diffèrent. Le filtre de ressources communes à yt-dlp reste actif pour les associations par frame/blob. |
| `native-host/worker.py` | Application des captions/posters avant le nommage et le téléchargement existants. |
| `native-host/windows_install.py`, `macos_install.py`, `maintenance.py`, `install.sh` | Installation/mise à niveau du nouveau module backend. |
| `backend.json`, `Install.ps1`, `extension/manifest.json` | Versions 8.38 / 8.45 ; script DOM dans les frames HTTP(S), séparé du pill. |
| `tests/test-media-items.js` — nouveau | Groupes, isolation, qualité, blob, contexte frame, URLs privées et batch. |
| `tests/test-media-item-download.py` — nouveau | Fixtures de galerie et vérification réelle du worker, titres et qualité. |
| `tests/test-hls-firefox.py`, `test-backend-packaging.py` | Parcours DOM/batch Firefox et présence du nouveau module dans les installateurs. |
| `README.md`, `tests/README.md`, ce rapport, `docs/validation-media-items-v8.45.json` | Usage, commandes, preuves et limites. |

## Structure MediaItem

Le catalogue logique contient notamment :

```js
{
  id,                   // identité stable du média dans l’onglet
  title,
  titleSource,
  thumbnail,            // URL HTTP(S) ou null
  tabId,
  frameId,
  pageUrl,
  mediaKind,            // video | audio
  duration,             // secondes ou null
  candidates: [
    {
      sourceType,       // ytdlp | hls | dash | direct
      type,             // type interne conservé : direct_video/direct_audio/etc.
      url,              // URL complète utilisable, conservée dans le background
      title,
      maxHeight,
      hasVideo,
      hasAudio,
      container,
      confidence,
      // headers, MIME, variantes/groupes et contexte du catalogue existant
    }
  ],
  extractionUrl,         // URL du média pour les pages multiples ; page pour un seul lecteur
  downloadable
}
```

Les champs inconnus restent inconnus ; un MIME vidéo ne prouve pas l’absence d’audio. Les probes existants renseignent codecs, audio et qualité avant le scoring. La copie destinée à la popup ne contient ni URL média complète ni headers/tokens : elle expose les identifiants et informations de présentation nécessaires.

La queue conserve un petit contexte `media_item` : identité, page, titre, origine du titre, poster, type audio/vidéo et preuve de sources DOM explicites. Elle conserve aussi les fallbacks réseau existants. Aucun nouveau réglage de qualité, destination ou codec n’a été créé.

## Titres et miniatures

Titres : **caption locale → aria-label → title → texte du lien associé → alt de l’image locale → métadonnées résolues → nom de fichier**.

La recherche se limite au même figure, card, thumb ou gallery item avec un seul lecteur. La caption Wikimedia située à côté du `.thumb` est cherchée dans la `.gallerybox` extérieure. Une caption globale d’une figure contenant plusieurs lecteurs n’est pas arbitrairement appliquée à tous.

Miniatures : **poster → image du même item, avec sources lazy/srcset → miniature fournie par les métadonnées**. Les URLs non HTTP(S) sont exclues. Les titres passent par `textContent`, pas par injection HTML. Un média sans poster ni miniature disponible garde une place discrète sans image inventée.

À l’ouverture du sélecteur multiple, seuls les détails manquants sont résolus, avec au plus **deux probes simultanés**. Les extracteurs et la supervision backend existants sont réutilisés ; aucune vidéo complète n’est téléchargée pour ces détails.

## Embeds et détection dynamique

Les vrais lecteurs `<video>` et `<audio>` possèdent leurs `<source>` ; ces dernières ne deviennent pas des médias indépendants. Les vrais iframes YouTube, YouTube-nocookie et Vimeo sont convertis en URLs de média reconnues par yt-dlp. `object/embed` sont pris en compte lorsqu’ils portent ces mêmes vrais URLs de player.

Les simples liens ne sont pas parcourus comme des vidéos. Les lecteurs des éléments de recommandation YouTube identifiés (`#related`, renderers de recommandations/preview) sont exclus du scan.

Le script DOM est injecté dans les frames HTTP(S). Le background prend `tabId`, `frameId` et l’URL du document depuis l’expéditeur Firefox. MutationObserver est débouncé à **150 ms** ; changements de sources, poster, texte et labels, événements metadata/load, hash/popstate et pageshow/pagehide actualisent les snapshots. Les modifications du pill sont ignorées. Le scan n’ajoute aucune requête de manifest ou de segments.

## Corrélation et déduplication

- Les URL/currentSrc et sources déclarées sont rapprochées des URLs du catalogue, variantes directes et références des masters HLS comprises. Les tokens variables servent à l’identité via la fonction existante ; les vraies URLs de téléchargement restent intégrales.
- `<video> + <source> + requêtes Range + formats yt-dlp` conserve une seule ligne DOM et plusieurs sources internes.
- Deux lecteurs avec les mêmes sources, ou l’iframe et le player de son document YouTube/Vimeo, sont regroupés. Des vidéos différentes restent distinctes.
- Sans URL exacte, la frame et son document doivent correspondre. Durée, résolution et proximité temporelle fournissent des indices supplémentaires. Un CDN commun fournit seulement un petit indice, jamais une preuve suffisante.
- Un seul lecteur blob dans sa frame peut recevoir les ressources observées de ce document. Plusieurs blobs ambigus restent non corrélés sans indice permettant de distinguer leur contenu. Aucun téléchargement de `blob:` n’est lancé.
- Les enfants HLS déjà attachés à un master ne sont pas recréés comme MediaItems.
- Pour une page multiple, Automatic reçoit uniquement les sources du média sélectionné et une URL d’extraction propre à ce média. Pour un lecteur unique, yt-dlp peut analyser la page, en parallèle de ses sources réseau.
- Le filtre du planner basé sur les ressources communes à yt-dlp reste disponible pour les associations heuristiques. Il est levé pour les variantes explicitement déclarées par le même lecteur, afin qu’un WebM 720p ne masque pas son MP4 1080p.

## UI et pipeline

Avant : la popup présentait HLS, DASH et directs comme des choix techniques.

Après : un lecteur donne une ligne discrète titre/poster ; plusieurs lecteurs donnent **« N médias détectés »**, ouvrant les lignes de sélection. Les types techniques restent internes. Le choix d’une ligne définit le média du bouton principal ; les cases permettent un batch. Les sources techniques restent accessibles dans l’ancien sélecteur lorsqu’aucun élément DOM ne peut être identifié.

Le batch envoie des ajouts séquentiels, puis le scheduler existant conserve sa pause, son ordre et son exclusivité. Queue, progression, ETA, annulation, dossier de destination, FFmpeg et historique restent ceux du backend existant. Le mode image historique garde son routage de page ; le batch de médias est destiné aux modes audio/vidéo.

Les poids de scoring n’ont pas été modifiés : qualité demandée et audio dominent ; yt-dlp départage des résultats équivalents. Timeouts Automatic conservés : page **30 s**, source réseau **20 s**, grâce de comparaison **5 s**, sockets **8 s**, ffprobe **15 s**. Les probes lazy d’embed sont bornés à **20 s**. Le fallback précoce existant est conservé, avec ses exclusions annulation/disque/FFmpeg/transfert déjà important.

## Tests réellement exécutés

| Suite | Résultat |
| --- | --- |
| `test-media-items.js` | Succès : groupes de variantes, MP4/Range, vidéos séparées, frames/documents, durée/résolution, blob/HLS, blobs ambigus, embeds, URLs privées, batch et contrat metadata. |
| Nouveaux tests worker MediaItem | **2/2**, dont transfert réel avec caption, poster et sélection 1080p au lieu de 720p ; fichier inspecté avec ffprobe. |
| Firefox MediaItems réel | **6 parcours vérifiés**, couvrant tous les cas DOM minimum, galerie, batch, fichiers finaux et lecteur unique. |
| Scorer/planner | **30/30**. |
| Automatic existant | **14/14**. |
| Automatic direct existant | **11/11**, dont annulation, historique, MIME-only, qualité face à HLS et timeout. |
| HLS réel | **12/12**. |
| Groupes HLS avec audio séparé | **6/6**. |
| DASH réel | **15/15**, manifests locaux réels et fusion. |
| Détecteurs Node et resolver de page | Succès : direct, DASH, **13 scénarios de groupes HLS**, background et **38 assertions** du resolver. |
| Queue store | **22/22**. |
| Packaging et installation Linux fraîche/mise à niveau | **3/3**, nouveau module inclus dans les packages Linux/Windows/macOS. |
| Régression générale finale | **95 succès, 0 échec, 5 ignorés** dans ce banc (Chromium indisponible). |
| Firefox groupes HLS et Automatic | **7 vérifications par parcours**, regroupement master/audio, fichier 1080p, fallback, isolation d’onglets et sources multiples. |
| Mozilla web-ext lint 10.6.0 | **0 erreur**, **1 avertissement Android préexistant**. |
| Syntaxe JS/Python et `git diff --check` | Succès. |

Un défaut de contrat a été reproduit pendant le test du lecteur unique : la nouvelle source DOM mettait `height: null` dans les métadonnées natives, refusées par le validateur direct existant. Le producteur omet désormais le champ inconnu ; un test verrouille ce contrat. Le validateur et le downloader direct n’ont pas été assouplis.

Les premiers échecs Firefox liés au binaire incomplet, au charset et aux commandes de pause de la fixture ont été corrigés. Seules les exécutions finales réussies sont retenues comme validation.

## Limites restantes

- Galerie Wikimedia **reproduite localement** avec son HTML caractéristique, pas validation manuelle d’une page Wikipedia publique précise. Les vrais embeds sont reconnus dans Firefox ; les téléchargements connectés YouTube/Vimeo ne sont pas validés par cette campagne.
- Les Shadow DOM non parcourus, players canvas/custom, frames inaccessibles ou pages interdites aux content scripts peuvent fournir moins d’informations DOM. Le catalogue réseau et la voie de page existante restent disponibles selon le contexte.
- Le rattachement blob par frame est une heuristique ; des players ambigus ne sont pas fusionnés. Des publicités ou sources distinctes sans relations vérifiables nécessitent parfois un choix ou la relance de la lecture.
- Une miniature non fournie ou un resolver indisponible ne peut pas être inventé. Les métadonnées lazy sont lancées à l’ouverture du sélecteur multiple.
- Bornes : **100 éléments DOM par frame**, **12 sources déclarées par lecteur**, **3 alternatives réseau + probe yt-dlp** par demande Automatic. Les alternatives réseau privilégient les familles puis les qualités déjà connues ; une très grande collection de qualités inconnues peut demander une sélection plus précise.
- Les URLs signées peuvent expirer entre détection et téléchargement ; la logique de fallback existante reste applicable. Un nouvel onglet/rechargement peut nécessiter un nouveau scan/une nouvelle lecture.
- La fermeture de la popup interrompt la collecte lazy des détails suivants, pas les jobs déjà ajoutés ni les probes supervisés déjà lancés. Les ajouts batch sont possédés par le background.
- Installateurs livrés pour les trois OS, essais réels **Linux/Firefox** ici. Windows/macOS n’ont pas été exécutés nativement dans cet environnement.
