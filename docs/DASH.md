# Network manifests — frontend 8.40 / backend 8.34

## English

### Architecture

DASH extends the existing HLS implementation. `extension/hls-detector.js`
exports `KittyMedia`, with `KittyHls` retained as a compatibility alias. One set
of passive Firefox `webRequest` listeners and one bounded catalogue per tab
handle both types. `popup-hls.js` similarly exports `KittyMediaPopup` while
retaining its old name. Historical filenames are kept to avoid unnecessary
installer and script changes.

The default source remains the page URL and yt-dlp. A compact source selector
appears only after a network manifest is observed. Explicit HLS/DASH selection
and page fallback reuse the existing quality menu, queue, worker, controls,
destination, progress, FFmpeg postprocessing and history. There is no second
download engine. The floating button and context menu use the same page
fallback helper.

### Detection, identity and transport

GET responses with a successful status, including 304, are candidates when
their URL indicates `.mpd` or their Content-Type is `application/dash+xml`.
Parameters such as `charset` are ignored when reading the MIME type. Existing
`.m3u8` and HLS MIME detection remains enabled. Fragment paths ending in `.ts`,
`.m4s`, `.mp4`, `.m4a`, `.cmfv` or `.cmfa` are excluded, even with misleading
manifest MIME types. The extension never fetches or downloads fragments.

A candidate retains its full original URL, source page, tab, timestamp, type,
hostname, MIME and observed Referer/Origin/User-Agent. Cookie and Authorization
are not captured. The catalogue expires after 15 minutes, is limited to 20
candidates per tab, and is cleared on navigation or tab closure. Request
header records are limited to 256 and expire after one minute.

The deduplication key includes the manifest type and a conservative URL key.
Only the existing named set of signing parameters is excluded from that key;
the full newest URL is retained for requests. Quality and other query fields
remain significant. Repeated observations update the candidate without
triggering repeated popup notifications or detection logs. An MPD is ranked
as a manifest describing multiple adaptations; HLS master preference remains.

Only the trusted popup can resolve a candidate ID. Raw URLs and headers are
kept in the background catalogue rather than sent in the source-list response.
Native Messaging carries a validated `media_source`, or up to three
`media_fallbacks` for the exact same page URL. Backend 8.34 supports `media_probe`
and generic fallbacks. Backend 8.33 can still receive HLS through the previous
`hls_probe`/`hls_fallbacks` API; DASH asks the user to update it. Native protocol
version 1 and queue schema version 2 are unchanged.

### MPD, formats and DRM

The shared backend module `native-host/hls.py` checks HTTP(S) URLs, credentials,
control characters, metadata bounds and the three allowed headers. A manifest
preflight reads at most 2 MiB. DASH uses a small XML validation step: an MPD root,
at least one Representation, no DTD/entities and no ContentProtection. Any
ContentProtection conservatively produces `dash_drm`; no keys, license requests
or DRM bypass are implemented. yt-dlp DRM flags are also checked.

The original manifest URL is then passed to yt-dlp's generic extractor. yt-dlp
provides representations, heights, codecs, bitrate and separate audio/video
formats. The probe exposes those fields, while the popup shows only DASH,
resolutions and the presence of separate audio/video. No independent DASH
parser, representation selector or fragment downloader is implemented.

The existing worker selects the requested quality and audio track. yt-dlp's
normal `process_ie_result` path downloads the tracks; its FFmpeg merger joins
them. The existing audio-only and MP3 processing paths remain shared. Failures
distinguish unavailable, denied, explicitly expired, no usable formats, DRM and
timeout. A failed probe keeps the raw candidate selectable.

### Production time limits

`metadata_guard.py` runs metadata extraction in a disposable supervised Python
process using the same interpreter/dependencies as Kitty. The worker retains
queue ownership and cancellation controls. Options/results travel as JSON in
a private temporary directory; executable objects are not serialized.

| Operation | Wall-clock budget |
|---|---:|
| Source probe / queued title | 30 s |
| Extraction before download | 120 s |
| Collection metadata | 60 s |
| ffprobe / FFmpeg version detection | 15 s |
| One local FFmpeg operation | 600 s |

Manifest reads and yt-dlp retries are included in the metadata budget, with a
socket timeout capped at 10 s. A slow response cannot keep resetting the global
deadline. The supervisor stops its own child and descendants on timeout or
cancellation and cleans temporary results. yt-dlp's local FFmpeg postprocessor
is bounded through a scoped adapter, tested with yt-dlp 2026.08.19. Actual media
transfers retain their existing network/control behavior and have no total
duration cap, including live streams.

### Verification and remaining limits

See `tests/README.md` for runnable suites. Real local MPDs, separate video/audio
downloads and merges are tested with yt-dlp/FFmpeg, and the Firefox test opens
the actual popup and uses real Native Messaging. Synthetic ContentProtection
fixtures exercise classification without obtaining protected content.

Native Windows/macOS runs remain required; portability and archive checks on
Linux do not replace them. DASH live/dynamic MPDs, many external providers,
unusual cookies/authentication and all codec combinations are not exhaustively
validated. Rejecting any ContentProtection can also reject a manifest with an
otherwise usable clear representation. Signed-URL deduplication and HLS master
ranking remain heuristics. The existing dedicated YouTube cookie snapshot is
reused; generic Firefox cookie export is not implemented. FFmpeg's ten-minute
local-operation budget can reject very long processing tasks. Newer yt-dlp
builds need validation of the timeout adapter before deployment.

Direct media detection now extends the same candidate catalogue and Native
Messaging path; see [DIRECT-MEDIA.md](DIRECT-MEDIA.md). DASH still requires
backend 8.34, while direct media requires 8.35.

## Français

DASH utilise le détecteur HLS existant, son catalogue par onglet, ses headers et
son sélecteur compact. La page avec yt-dlp reste prioritaire ; les MPD deviennent
une source explicite ou un fallback dans la même tâche. Les fragments ne
deviennent jamais des candidats et les URLs signées restent complètes.

Le backend vérifie brièvement le MPD, refuse les informations ContentProtection,
puis confie les formats à yt-dlp. Les pistes vidéo/audio séparées utilisent le
téléchargement et la fusion FFmpeg existants. La file, l'annulation, la
progression, la destination et l'historique sont partagés avec HLS et les pages
classiques. Un probe en erreur conserve le candidat brut.

Les délais du tableau sont des limites réelles de production, couvrant aussi
les lectures lentes et les processus enfants. Ils ne limitent pas la durée
totale d'un téléchargement. Les tests locaux et Firefox sont reproductibles ;
les exécutions natives Windows/macOS, les MPD live et les fournisseurs externes
restent à valider. La détection directe réutilise désormais ce catalogue et
ce pipeline ; voir [DIRECT-MEDIA.md](DIRECT-MEDIA.md).
