# HLS detection — introduced in frontend 8.39 / backend 8.33

Frontend 8.40 / backend 8.34 extend this same detector to DASH and add supervised
production metadata timeouts. See [DASH.md](DASH.md) for the shared architecture,
generic API, compatibility aliases and time budgets. The HLS behavior below is
retained; new backends receive `media_fallbacks` and accept the legacy API too.
Frontend 8.41 / backend 8.35 add direct video/audio to this catalogue; see
[DIRECT-MEDIA.md](DIRECT-MEDIA.md).

Frontend **8.42**, with the unchanged backend **8.35**, groups HLS sources
by observed master → child relationships. The existing yt-dlp downloader,
native protocol and queue schema are unchanged.

## HLS groups — English

`hls-response.js` observes successful HLS responses already loaded by Firefox,
using `webRequest.filterResponseData`. The synchronous `onHeadersReceived`
listener attaches it and returns immediately. Every chunk is passed unchanged
to the player before inspection. Completion closes the filter; errors,
navigation, closure, a **10-second total timeout** or **2-MiB limit** disconnect
it, leaving further delivery to Firefox. At most 16 filters coexist. MV3 needs
`webRequestBlocking` and `webRequestFilterResponse`. No extra HTTP fetch occurs.

`hls-parser.js` handles quoted attribute lists and resolves relative HTTP(S)
URLs. A candidate's `hls` group contains `kind`, `masterUrl`,
`originalMasterUrl`, `pageUrl`, `tabId`, `timestamp`, `variants`, `audioTracks`,
`subtitles`, `maxResolution` and `codecs`. Variant/rendition records retain
resolution, bandwidth, average bandwidth, frame rate, codec and group
references, group ID, name, language, default and autoselect. Each collection
has at most 128 records; signed URLs stay complete.

Only real master references hide children in `Store.list()`. Nested masters
are supported, malformed cycles are retained, and unrelated videos are never
merged by tab or hostname alone. Children remain internally available. There
are at most 20 visible sources and 128 stored candidates per tab, with the
existing 15-minute TTL and navigation/closure cleanup.

STREAM-INF or MEDIA identifies a master; its references identify video/audio/
subtitle children. AAC/MP3/AC3 media segments provide standalone audio evidence,
WebVTT/TTML identifies subtitles, and I-FRAMES-ONLY provides video evidence.
TS/fMP4 alone does not prove video-only: these standalone candidates remain
`unknown` and downloadable. Failed/unavailable body inspection retains the
raw candidate. Unresolved EXT-X-DEFINE variables cannot establish a relation.

Deduplication reuses the existing named signing-parameter comparison key.
Other parameters, including asset/quality identifiers, remain significant.
The newest complete signed master URL is used; its first URL is retained
internally. Proven masters rank above guessed master filenames, DASH and
standalone media. The popup receives only safe role/height/count/protection
summaries, never the group tree or signed URLs.

The source label becomes **HLS · 1080p max · 3 qualities**. Explicit selection
and default page fallback send the **master**, allowed Referer/Origin/User-Agent
and page context through the existing Native Messaging protocol. Group trees
are omitted. yt-dlp supplies formats; the existing worker handles separate
audio/video selection, FFmpeg merge, progress, cancellation, queue and history.
No second HLS downloader or generic cookie export is added.

SAMPLE-AES or non-identity key formats flag protected manifests, including
observed protected children. Explicit protected-source requests receive a
clean error and known protected sources are excluded from automatic fallbacks;
normal page extraction and backend DRM checks remain intact. Identity AES-128 behavior is
unchanged. Safe debug output contains roles/counts/tab IDs only; duplicate
messages are bounded per candidate.

Tests: `node tests/test-hls-groups.js`, `python tests/test-hls-group-download.py`
and `env KITTY_TEST_HLS_GROUPS=1 python tests/test-hls-firefox.py`. They cover
three qualities, separate fMP4 audio, subtitles, relative/signed URLs, reloads,
independent videos, standalone audio/video, real 1080p/720p merge, cancellation,
queue/history, byte pass-through, observer timeout/limits and lifecycle cleanup.
The existing HLS/DASH/direct/classic suites remain separate regression checks.

## Groupes HLS — Français

La v8.42 lit uniquement les manifests déjà reçus par Firefox, sans requête
supplémentaire et en transmettant immédiatement les octets inchangés au lecteur.
L'observation se détache après 10 secondes ou 2 Mio, et lors d'une fermeture ou
navigation. Une source brute reste disponible si l'analyse échoue.

Les relations déclarées dans le master réunissent ses qualités vidéo, pistes
audio et sous-titres sous une seule entrée. Les enfants restent connus en
interne, les vidéos distinctes restent séparées. La déduplication utilise les
clés existantes sans retirer de tokens des URLs utilisées. Les vrais masters
sont prioritaires ; une playlist TS/fMP4 isolée reste téléchargeable avec un
type inconnu si son contenu ne permet pas d'affirmer la présence de vidéo/audio.

La popup affiche par exemple **HLS · 1080p max · 3 qualités**. Le master complet
est transmis au backend existant, avec les headers autorisés. yt-dlp récupère
les formats, et la file, FFmpeg, la progression, l'annulation et l'historique
restent partagés. Le backend est toujours en v8.35. Les DRM restent refusés.

## Comportement initial et pipeline conservé

## English

Kitty still tries the page with yt-dlp first. While an authorized Firefox tab loads media, passive `webRequest` listeners recognize `.m3u8` URLs and HLS response Content-Types. A small source selector appears only when HLS candidates exist. Selecting a stream probes its formats; the existing 720p, 1080p, best-quality and audio menu is reused.

The background owns a per-tab, in-memory catalogue: full manifest URL, page URL, tab ID, timestamp, content type, and observed Referer/Origin/User-Agent. It never captures Cookie or Authorization. Candidates expire after 15 minutes and are cleared on navigation or tab closure. Requests without an attributable tab are ignored. Fragment URLs ending in `.ts`, `.m4s` or `.mp4` cannot become candidates. HLS bodies already received are inspected by the bounded observer described above; no extra request or media download is performed by the detector.

Repeated requests share a candidate ID. Only a small named set of signing parameters is excluded from the deduplication key; the complete newest URL remains untouched for download. Other query parameters, including quality identifiers, remain significant. Parsed masters take priority; filename ranking remains a fallback for unobserved bodies. The catalogue is capped at 20 visible sources, 128 internal candidates per tab and 256 outstanding header records.

Only the extension popup can ask for a selected candidate by ID. The background resolves the ID against its current tab catalogue and passes a validated `media_source` object through Native Messaging. Page downloads can carry up to three `hls_fallbacks`, only when the requested URL matches their source page; unrelated clicked links retain their original behaviour. Older compatible backends continue their normal page path, but explicit HLS requires backend 8.33.

`native-host/hls.py` validates HTTP(S) URLs, headers, source metadata and bounds; preflights a manifest up to 2 MiB; rejects unsupported encryption/DRM; then invokes the yt-dlp generic extractor on the original URL. yt-dlp owns HLS variants, segments and downloads. The existing worker owns quality, progress, queue, cancellation, FFmpeg/remux, file verification and history. A page extraction failure may try the ranked HLS candidates in the same job; authentication, region and DRM failures never cause an automatic alternate path.

The existing dedicated YouTube cookie snapshot is reused only for YouTube source pages, with normal cookie-domain scoping. There is no generic export of cookies from the user's Firefox profile. HLS logs and error details omit signed URLs and headers. Private queued/error jobs retain their context for execution/retry; completed/cancelled jobs drop headers and fallback lists. Source buttons return to the page instead of opening a signed manifest.

### Tests

- `node tests/test-hls-detector.js`: URL/MIME detection, fragment exclusion, signed-URL deduplication, separate qualities, master preference, allowed headers, tab isolation, navigation/closure and TTL.
- `python tests/test-hls-download.py`: 12 real local yt-dlp/FFmpeg cases, TS and fMP4, master/media/MIME-only playlists, 720p output, multiple formats, signed tokens, required Referer/Origin/User-Agent, page fallback, ordinary HTML video, expiry/access/no-format/DRM errors and cancellation during both manifest retrieval and media transfer. Requires yt-dlp, Mutagen and FFmpeg/ffprobe; cancellation integration uses Linux signals.
- `tests/test-hls-firefox.py`: isolated Linux Firefox + Selenium + geckodriver test, including the actual extension, popup, Native Messaging host, worker, remux, audio/video validation, default page fallback, switching tabs, navigation and source-tab closure. Temporary native registration is restored in `finally`. Set `KITTY_FIREFOX_BINARY` and `KITTY_GECKODRIVER`.
- Existing regression, popup rendering, image mode, packaging and platform portability suites remain applicable.

### Limits

DASH and direct MP4/audio capture now share this detector; see the linked documents. No DRM bypass or decoding of protected proprietary sessions. AES-128 HLS supported natively by yt-dlp is allowed; SAMPLE-AES and non-identity key formats are rejected. Some cookie-authenticated, IP-bound or unusual signed streams remain unavailable. HTTP 403 alone cannot establish that a token expired. Multiple unrelated players may require choosing the correct source. Only manifests observed after the extension is running can be listed; reload the page/start playback if necessary. Live streams can continue until cancellation. Native Windows/macOS runs are required before publishing this version for those systems.

## Français

Le téléchargement par URL de page reste prioritaire. Le détecteur observe passivement les requêtes des onglets autorisés et reconnaît les URLs `.m3u8` ou un Content-Type HLS. Les fragments ne deviennent jamais des médias séparés. Un sélecteur compact apparaît lorsqu’un flux est trouvé ; les qualités utilisent le menu existant.

Les candidats restent en mémoire, par onglet, pendant 15 minutes au maximum. Une navigation ou la fermeture de l’onglet les supprime. Les doublons sont regroupés sans modifier l’URL réellement envoyée : les tokens sont conservés. Les masters observés sont prioritaires ; leur structure regroupe les enfants référencés. Les noms de fichiers ne restent qu’une heuristique de fallback.

Le background transmet le manifest complet et seulement les headers observés autorisés — Referer, Origin et User-Agent — au backend par Native Messaging. La session YouTube dédiée existante reste utilisable pour une page source YouTube ; les cookies du profil Firefox habituel ne sont pas exportés. Le backend valide le candidat, vérifie le manifest et délègue ses variants/fragments à yt-dlp. La file, la progression, l’annulation, FFmpeg/remux et l’historique sont partagés avec les téléchargements actuels.

Une extraction de page non reconnue peut basculer vers les manifests détectés dans la même tâche. Le choix explicite d’un HLS reste disponible. Les erreurs d’authentification, de région ou de DRM ne déclenchent pas de fallback automatique. Les erreurs HLS distinguent flux indisponible, accès refusé, expiration explicite et absence de formats ; les logs HLS ne contiennent ni URLs signées ni headers.

Les tests ci-dessus couvrent les 12 scénarios demandés pour HLS. DASH utilise désormais le même fallback, avec les limites détaillées dans le document associé. Aucun contournement DRM ou export générique de cookies n'est ajouté. Si plusieurs lecteurs existent, il peut être nécessaire de choisir le bon flux. La version doit encore passer les exécutions natives Windows/macOS avant publication sur ces plateformes.
