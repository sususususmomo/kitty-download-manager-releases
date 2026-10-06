# Shared network Media Detector

## English

Frontend 8.41 and backend 8.35 add direct HTTP video/audio to the existing HLS
and DASH catalogue. The default remains page URL → Kitty → yt-dlp. A network
source can be selected explicitly or used after page extraction fails, in the
same worker job. Native protocol 1 and queue schema 2 are unchanged.

### Detection and deduplication

`extension/hls-detector.js` remains the shared `KittyMedia.Store`; its old
`KittyHls` alias is retained. The existing Firefox webRequest listeners correlate
request and response headers through requestId. They observe HTTP(S) requests
with `requestHeaders` / `responseHeaders`, without blocking or rewriting them.
No new permission, response-body interception or background media download was
added. Firefox exposes statusCode, tabId and headers through these events:
[onHeadersReceived](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webRequest/onHeadersReceived),
[onBeforeSendHeaders](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webRequest/onBeforeSendHeaders).

Classification is `hls`, `dash`, `direct_video` or `direct_audio`; classic page
downloads do not need a synthetic network candidate. HLS/DASH MIME and URL
signals are checked first. Direct candidates use video/* or audio/*, or a known
filename extension when MIME is absent/octet-stream. Contradictory image/text
MIME rejects the filename signal. Supported extensions include MP4, WebM, M4V,
MOV, MKV, MP3, M4A, OGG, Opus, WAV, FLAC and AAC.

The resource key is scoped to its tab/page, origin, path and stable query
parameters. Repeated Range/206 responses update the same candidate; the latest
complete signed URL is kept verbatim for downloading. Only the existing small
list of known signing/expiry parameters is excluded from comparison. This is
an identity heuristic, not a reconstruction of the downloadable URL.
Content-Range supplies the full size. A 206 Content-Length without a known
total is never presented as the whole-file size. Range is metadata only and is
never replayed from Firefox into the backend's whole-file download.

Clear quality markers, such as `clip_720p.mp4` / `clip_1080p.mp4` or a numeric
height/resolution/quality query, can group at most four alternatives, preserving
each URL and its headers. Other path/query identifiers must match. Arbitrary
CDN identifiers, similar titles, sizes or codecs alone do not justify grouping.
The backend excludes a variant with a clearly different measured duration.
This remains a conservative heuristic; it cannot prove video identity.

HLS master filenames and DASH MPDs rank above direct files. Direct audio is
excluded from video fallbacks; direct files are excluded from image-only
fallbacks. The catalogue keeps at most 20 candidates per tab with 15-minute
expiry, pruned on catalogue access/update. Navigation/tab closure clears it.
The request-header cache is bounded to 256 entries and one minute. No array of
range slices is retained. Detection logs contain type/tab/count, not source URLs.

### False positives, blobs and privacy

TS, M4S, CMFV/CMFA, recognizable init MP4 and explicitly numbered segment/chunk
filenames are excluded. Request contexts image/font/script/stylesheet are
excluded. A known whole size below 8 KiB is ignored; identifiable preview,
spinner, loader, icon and similar filenames below 128 KiB are also ignored.
A small Range slice does not trigger this filter when its complete resource
is larger. Small ordinary videos above 8 KiB remain eligible.

Nonstandard extensionless chunks, advertisements and previews with misleading
names may still be detected. Stronger blanket size/domain filters would hide
legitimate media. A partial-only URL is refused by backend preflight; an
independently downloadable audio/video track cannot always be associated with
its parent manifest through network headers alone.

`media-context.js` passively checks video/audio elements for blob URLs and sends
only a boolean. It does not read blob content, hook fetch or extract memory.
If the browser previously requested a real HTTP file or manifest, that source
remains usable. Otherwise the popup explains the limitation. Requests made
before the extension starts observing, some workers/iframes or protected
Firefox pages may remain unavailable.

Only the shared Referer/Origin/User-Agent allowlist is forwarded. Cookie,
Authorization and Range are rejected by backend validation. The existing
dedicated YouTube session mechanism is preserved; no generic browser cookie
export was added. URLs/tokens can remain in the private local queue/history,
as before, but detection/metadata logs omit them. Finished/cancelled jobs clear
headers from all variants and discard fallback context.

### Backend and UI

The shared `media_probe`, `media_source` and `media_fallbacks` Native Messaging
contracts now accept direct types. Only the popup may select/probe a source;
page scripts cannot ask the backend to download arbitrary candidates. Backend
validation independently checks HTTP(S), credentials, controls, bounds, headers
and conservative variant grouping. Backend 8.34 still handles HLS/DASH; direct
selection asks for 8.35 when connected to an older backend.

`native-host/direct_media.py` performs a bounded 8 KiB GET preflight and optional
ffprobe inspection through the existing hidden platform launcher, then builds
yt-dlp format metadata. yt-dlp's existing HTTP
downloader, worker, FFmpeg processing, queue, pause/cancel controls, partial-file
cleanup, byte/speed/ETA updates, destination and history remain shared. No second
downloader or progress UI was created. Names use the source-page title first,
then Content-Disposition/URL when no title is known. Matching actual format
URLs of an already identified classic job are hashed, scoped to its page, to
prevent the same resource being downloaded again via a direct candidate. This
does not remove network fallback candidates merely because a site is supported.

The existing compact source selector shows HLS, DASH, MP4/WebM direct or direct
audio, the host and grouped-quality count. Probe details use the existing
quality picker plus available heights and size. Selecting direct audio switches
the current picker to audio. A probe failure keeps the raw candidate available.
The existing pill adopts a network job through its source page.

Production metadata supervision is retained: probe/title 30 s, download metadata
120 s, collections 60 s, ffprobe/version 15 s, local FFmpeg operations 600 s.
Direct ffprobe also has an 8 s socket timeout and bounded analysis settings.
Metadata children are terminated on global timeout/cancel. Media downloads have
no whole-transfer duration cap; the existing transfer timeouts and cancellation
remain responsible for slow or interrupted transfers.

DRM refusal uses existing yt-dlp flags and manifest checks, plus recognizable
MP4 protected sample/pssh boxes in the prefix and encrypted ffprobe codec tags.
Late metadata and unusual protected formats may escape classification. These
checks do not recover keys, decrypt samples or contact license services. A
recognized protected direct source is refused with a readable DRM error.

See [tests/README.md](../tests/README.md) and
[validation-direct-v8.41.json](validation-direct-v8.41.json) for actual runs.
Real Firefox tests on Linux cover the toolbar and Native Messaging. Native
Windows/macOS, all public providers, live media and every container/codec remain
outside that verification. No dependency version/channel migration is included.

## Français

La détection directe étend le détecteur HLS/DASH existant. La page avec yt-dlp
reste prioritaire ; les sources réseau servent de choix explicite ou de fallback
dans la même tâche. Les requêtes Range d'un fichier donnent une seule entrée,
avec la taille totale tirée de Content-Range, et l'URL signée reste complète.

Les qualités sont regroupées seulement lorsque leurs chemins/paramètres portent
un marqueur clair et que le reste correspond. Les fragments identifiables et
les toutes petites ressources sont filtrés. Les headers partagent la même
validation que HLS/DASH ; Range, Cookie et Authorization ne sont pas transmis.

Le backend réutilise yt-dlp, le worker et FFmpeg pour le téléchargement, la
progression, la file, l'annulation et l'historique. Les délais de production
existants restent actifs. Une URL blob seule ne peut pas être téléchargée ;
Kitty utilise la vraie ressource HTTP observée ou affiche cette limitation.
Les protections DRM reconnaissables sont refusées, sans contournement.

Les heuristiques ne peuvent pas identifier tous les fragments, toutes les
publicités ou tous les DRM. Une session de navigateur quelconque n'est pas
exportée. Les tests Firefox réels ont été exécutés sous Linux ; ils ne remplacent
pas des essais natifs Windows/macOS ou une campagne sur les sites publics.
