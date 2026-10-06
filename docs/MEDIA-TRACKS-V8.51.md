# Kitty 8.51 / backend 8.42 — pistes média

## Comportement

Les sorties des extracteurs existants sont normalisées en `videoTracks`, `audioTracks` et `subtitleTracks`. Elles restent attachées à leur MediaCandidate et au MediaItem déjà identifié. Les détecteurs DOM/réseau, le catalogue et les téléchargeurs HLS/DASH/direct/yt-dlp sont conservés.

Automatic construit un plan immuable à partir des sources du seul MediaItem choisi : meilleure vidéo dans la limite de qualité, audio/langue demandé, sous-titres optionnels. Une langue ou une piste absente produit `track_unavailable`, sans substitution silencieuse. Les identifiants de formats empruntés à un autre candidat du même item sont qualifiés pour éviter les collisions entre extracteurs.

Le mode audio original privilégie un flux audio natif, puis l'indicateur original, le défaut et le débit. La vidéo n'est pas demandée lorsqu'un flux audio seul existe. Les fichiers multiplexés restent une solution de repli : téléchargement du conteneur, extraction/remux par copie. Le mode MP3 reste une conversion explicitement demandée.

## Modèle

```js
MediaItem = {
  id, title, thumbnail, tabId, frameId, pageUrl,
  mediaKind, duration, candidates,
  videoTracks: [{
    id, sourceId, sourceType, formatIds,
    language, label, default, original,
    codec, bitrate, width, height, fps, container, muxed
  }],
  audioTracks: [{
    id, sourceId, sourceType, formatIds,
    language, label, role, default, original,
    codec, bitrate, native, muxed,
    representations: [{formatId, codec, bitrate, container, native}],
    embedded, audioIndex, streamCount
  }],
  subtitleTracks: [{
    id, sourceId, sourceType, language, label,
    default, original, automatic, codec, bitrate, formats,
    // Si le sous-titre appartient au fichier direct :
    embedded, streamIndex, formatIds
  }]
}
```

Les débits sont en kbit/s. Les informations absentes restent `null`; original n'est pas déduit de la langue de la page. Les identifiants sont opaques, associés à la source et indépendants des URLs signées, du titre et du poster. Aucun header, cookie ou URL technique n'est placé dans les listes de pistes publiques. Le backend conserve également les listes normalisées dans le MediaItem de l'historique.

Les variantes de qualité audio d'une même langue/libellé/rôle sont les représentations d'une piste. L'UI regroupe les choix équivalents provenant de plusieurs sources du même MediaItem. Les options portant des libellés/rôles distincts restent distinctes.

## Sélection et DownloadPlan

```json
{
  "track_selection": {
    "audioLanguage": "fr",
    "subtitleLanguages": ["fr", "de"]
  }
}
```

L'API accepte aussi `audioTrackId`, `subtitleTrackIds` et `preferOriginal`. Une langue peut viser ses variantes régionales; les codes disponibles viennent des extracteurs. Un identifiant de piste vise précisément la source associée. Les paramètres sont validés à l'enqueue, conservés pour retry, et participent à la détection des doublons. Un batch transmet un dictionnaire `trackSelections` indexé par MediaItem, puis crée un job et un plan indépendant pour chaque item.

Le plan épingle les IDs, les URLs des formats choisis, la piste/langue audio et les sous-titres. Le callable de sélection yt-dlp reçoit ce résultat; il ne réinterprète pas une préférence globale. Un candidat audio seul reste disponible pour composer le plan vidéo du même item. Les fichiers contenant déjà de l'audio peuvent fournir leur vidéo : FFmpegMerger omet leur ancienne piste audio et ajoute uniquement la piste demandée, par copie.

HLS conserve les langues/libellés et récupère DEFAULT et les codecs déclarés grâce aux utilitaires yt-dlp déjà utilisés pour les attributs du manifest. DASH conserve les métadonnées des représentations et récupère les Role/Label disponibles. yt-dlp conserve formats, langues, codecs, notes, sous-titres manuels et automatiques. Le probe direct existant conserve les langues/dispositions et les pistes intégrées quand ffprobe les fournit. La sélection locale d'une piste intégrée utilise FFmpeg par copie, avant les postprocesseurs habituels.

Les sources auxiliaires réutilisent RequestContext. URL exacte et répertoire de la rendition distinguent leurs contextes sur un même CDN; les protections de redirection/origine restent actives. Le renouvellement de source vérifie les métadonnées originales de la ressource, sans confondre le format sélectionné avec l'identité du fichier ni recréer le job.

## UI

La sélection de langue audio apparaît uniquement s'il existe plusieurs choix sémantiques. Une seule piste audio et ses variantes de qualité n'ajoutent pas de contrôle. Un sous-titre propose une case facultative; plusieurs sous-titres sont dans une section compacte. Les choix sont mémorisés par ID de MediaItem et survivent aux mises à jour asynchrones du titre, de la miniature et des sources. Le menu de qualité vidéo existant reste utilisé.

## Validation

- 234 tests Python : 233 réussis, 1 ignoré sur Linux (test nécessitant macOS).
- 12 suites Node réussies, dont contrôles conditionnels, déduplication des options, plusieurs sous-titres, choix conservés après update et préférences distinctes en batch.
- `bash test.sh` : 95 contrôles réussis, 0 échec, 5 contrôles Chromium ignorés.
- Firefox 153 réel + Native Messaging : HLS et DASH multilingues, vidéo 1080p + audio français + sous-titres; audio original AAC sans requête de segments vidéo; sélection conservée après update DOM.
- Firefox réel : galerie de plusieurs MediaItems, cases, sélection globale, titres/miniatures, candidats isolés, batch vers la file et téléchargements des bons fichiers.
- Fichier direct MP4 avec deux langues et un sous-titre intégré : bonne piste sélectionnée, AAC sans réencodage (paquets compressés identiques), sous-titre extrait, conversion MP3 de la bonne langue vérifiée par le signal audio.
- Plan mixte : meilleure vidéo d'un MP4 avec sa propre ancienne piste audio écartée, plus la seconde piste d'un autre candidat M4A du même item; URLs et paquets AAC vérifiés.
- Non-régressions : HLS, DASH, direct, yt-dlp, Automatic, RequestContext, URL expirée/reprise, isolation des MediaItems, queue, installateurs Linux/Windows/macOS et packages.

Les tests yt-dlp utilisent des métadonnées contrôlées et son vrai sélecteur/téléchargeur sur des fixtures locales; ils ne prétendent pas vérifier les sites distants.

## Limites

- Les choix dépendent des métadonnées réellement disponibles. Le probe ffprobe distant reste désactivé pour les contextes sensibles; les langues internes inconnues ne sont pas inventées.
- Si la seule source audio est multiplexée avec de la vidéo, le conteneur complet doit être reçu avant extraction.
- Les sous-titres sont livrés en fichiers annexes. Un sous-titre intégré au conteneur direct est extrait lorsque ce conteneur est sélectionné. La combinaison d'un sous-titre intégré et d'un plan fusionnant plusieurs fichiers est refusée explicitement; elle requiert une résolution dédiée.
- Le renouvellement strict des URLs reste en place. Une source auxiliaire d'un plan utilisant plusieurs candidates qui expire peut nécessiter une nouvelle résolution; aucune concaténation n'est faite sans identité confirmée.
- Les limites HLS/DASH existantes, notamment DRM et les changements de timeline/identité pendant la reprise, restent applicables.

## Fichiers

- Modèle/sélection : `native-host/media_tracks.py`, `media_item.py`, `download_planner.py`.
- Métadonnées/transfert : `hls.py`, `direct_media.py`, `request_context.py`, `worker.py`, `host.py`, `errors.py`.
- UI et transmission : `extension/media-items.js`, `background.js`, `popup-items.js`, `popup.js`, `popup.html`, `shared.js`, `i18n.js`.
- Versions/installation : `extension/manifest.json`, `backend.json`, `install.sh`, `Install.ps1`, `native-host/maintenance.py`, `windows_install.py`, `macos_install.py`.
- Tests : `test-media-tracks.py`, `test-media-track-download.py`, `test-direct-tracks.py`, `test-popup-tracks.js`, `test-request-context.py`, `test-backend-packaging.py`, `test-hls-firefox.py`.
- Documentation : `README.md`, ce rapport.

## Installation Linux

L'archive se décompresse toujours dans `kitty-download-manager/`.

```fish
unzip -o kitty-download-manager-v8.51-media-tracks.zip
cd kitty-download-manager
bash ./install.sh
```

Charger ensuite `extension/manifest.json` dans `about:debugging` → Ce Firefox → Charger un module temporaire. Le XPI livré est non signé. Windows : `Install.cmd`. macOS : `Install.command`.
