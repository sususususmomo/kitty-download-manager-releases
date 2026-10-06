# Kitty v8.44 — correction Automatic / médias directs

Frontend 8.44, backend 8.37, protocole Native Messaging 1. Validation du 5 octobre 2026 sous Linux, Python 3.12.14, yt-dlp 2026.08.19, FFmpeg/ffprobe 6.1.1 et Firefox 153.0.

## État initial et cause reproduite

Le dépôt a été inspecté avant modification : HEAD `46e8b5c`, aucune modification suivie en attente. L'ancien XPI 8.36 non suivi a été conservé. HLS, DASH, médias directs et le planner parallèle existaient déjà. Les 14 tests Automatic initiaux passent, y compris un MP4 simple : il ne manquait pas de downloader direct.

Le test de reproduction utilise les vrais `KittyMedia.Store`, `KittyMediaResolver` et `background.js`. Il place un MP4 dans le catalogue d'un onglet Reddit à l'adresse complète `/r/videos/comments/abc123/video_title/?share_id=tracking`, puis soumet l'adresse canonique `/comments/abc123`, comme le fait le resolver historique de la popup. Avant correction, le catalogue contient bien `direct_video`, mais le payload envoyé au backend ne contient **aucun `media_fallbacks`**. L'assertion échoue : `undefined !== 1`.

La perte se produit dans `withHlsFallbacks`, à la frontière **catalogue → Native Messaging**, avant Candidate Resolver, scorer et planner. La comparaison stricte `candidate.page_url === payload.url` confondait une adresse canonique du même post avec un lien externe sans rapport. Si l'extracteur de page échouait ensuite, aucune alternative réseau n'arrivait au backend.

Cette reproduction identifie un défaut concret correspondant au cas Reddit décrit. Aucun post Reddit réel n'a été téléchargé pendant cette validation ; sans l'URL exacte du cas manuel, cela ne garantit pas que tout autre échec Reddit ait cette même cause.

## Correction ciblée et architecture conservée

Le background charge maintenant `media-resolver.js` et réutilise sa canonicalisation existante. Deux URLs sont acceptées si elles sont identiques, ou si elles désignent le même permalink connu. Aucun nouvel extracteur ni détecteur n'a été créé.

Lorsque le permalink est équivalent, le payload garde **l'URL de page réellement observée**. Le backend conserve cette URL comme `source_page_url` et canonicalise déjà l'URL utilisée pour l'extraction classique. Les candidats conservent leurs URL média intégrales et leurs headers. Le resolver peut donc les accepter sans assouplir sa protection contre les pages sans rapport.

Un autre post Reddit et une page de feed restent exclus de cette équivalence. Être sur le même domaine ne suffit pas à prouver une relation avec la vidéo demandée. La correction concerne toutes les familles réseau : `hls`, `dash`, `direct_video`, `direct_audio`.

Le parcours demeure : **catalogue par onglet → probes supervisées en parallèle → MediaCandidate → scoreCandidate → candidats classés → worker existant**. Le planner réutilise le résultat metadata du gagnant. Le worker appelle `process_ie_result(info, download=True)` ; cette voie commune couvrait déjà les directs, HLS, DASH et yt-dlp. Un seul transfert démarre dans les cas réussis testés. Le fallback séquentiel précoce reste possible sans téléchargement complet concurrent.

## Scoring, audio et dispatch

Aucun bonus artificiel aux MP4, aucune modification des poids de scoring. La qualité demandée domine les petits bonus de conteneur, codecs et métadonnées. À égalité exacte, yt-dlp conserve son tie-break existant. Les tests réels vérifient MP4 1080p > HLS 720p et HLS 1080p > MP4 720p.

Les codecs et pistes des directs sont déterminés par l'analyse existante yt-dlp + ffprobe borné ; `video/mp4` ne signifie pas automatiquement « sans audio ». Les fichiers finaux MP4, WebM et MIME-only sont vérifiés par ffprobe et contiennent les pistes attendues. Une demande avec `audioRequired=True` accepte le MP4 avec audio et rejette le MP4 effectivement muet. Les modes vidéo historiques gardent l'audio facultatif pour conserver les vidéos muettes ; aucun nouveau réglage UI n'est introduit.

Le dispatch n'avait pas de branche manquante. Il a été vérifié plutôt que remplacé. Queue, destination, progression, ETA/vitesse, annulation, nettoyage du partiel, FFmpeg et historique restent ceux du worker existant. Les tests enregistrent les appels de transfert réel et exigent un seul appel réussi, puis vérifient le fichier final et une seule entrée d'historique.

## Range, headers et sécurité

Le détecteur existant regroupe les réponses Range/206 : 100 requêtes simulées et 30 requêtes réelles Firefox produisent une seule ressource avec la taille totale. Le téléchargement conserve l'URL complète, jamais une représentation de morceau. Le header Range du navigateur n'est pas rejoué comme instruction de téléchargement partiel.

Les URLs sans extension suivent le même pipeline grâce au Content-Type. Referer, Origin et User-Agent restent transmis par le mécanisme existant et validés au backend. Un serveur local exigeant ces trois headers est testé. Les paramètres signés sont conservés pour les requêtes réelles ; les nouveaux logs ne contiennent ni URLs ni cookies/tokens.

Les logs ajoutés indiquent : acceptation/rejet du catalogue, acceptation du resolver, score, raison de rejet, sélection, plan créé et downloader démarré. Les motifs sont bornés et lisibles : `unrelated_page`, `duplicate`, `source_expired`, `no_video_format_under_requested_cap`, `audio_required_but_absent`, `transcode_not_allowed`, ou code d'erreur backend. L'échec du probe de page reste interne lorsqu'une alternative réussit.

## Timeouts et DRM

Protections existantes conservées : probe page 30 s, probe réseau 20 s, grâce de comparaison 5 s lorsqu'un candidat satisfait la demande, socket 8 s, ffprobe 15 s, opérations FFmpeg 600 s. Les probes yt-dlp sont des sous-processus supervisés ; fin de sélection, timeout et annulation arrêtent leurs ressources. Les tests externes utilisent également une limite globale.

Aucun changement de DRM : détection/classification uniquement, aucun contournement. Le test Firefox DASH affiche une erreur de protection compréhensible tout en conservant le candidat brut. Les blobs sans ressource HTTP observable restent non téléchargeables.

## Tests réellement exécutés

| Suite | Résultat |
| --- | --- |
| Reproduction background avant correction | Échec attendu : MP4 dans le catalogue, absent du payload Automatic |
| Background après correction | Succès : permalink Reddit, MP4/WebM/MIME-only/audio/HLS/DASH, autre post/feed exclus |
| Scorer et planner | 30/30 |
| Nouveaux tests Automatic directs, transferts locaux réels | 11/11 |
| Automatic existant, transfert/merge/fallback et contrôles | 14/14 |
| HLS réel | 12/12 |
| Groupes HLS avec audio séparé | 6/6 |
| DASH réel | 15/15 |
| Médias directs existants | 21/21 |
| Queue store | 22/22 |
| Timeouts de production | 6/6 |
| Packaging backend et installation Linux fraîche/mise à niveau | 3/3 |
| Régression générale | 95 succès, 0 échec, 5 ignorés : Chromium indisponible |
| Node : détecteurs direct/DASH, groupes HLS et resolver de page | Succès ; 13 scénarios de hiérarchie HLS |
| Firefox réel, directs | 10 vérifications réussies |
| Firefox réel, Automatic HLS/DASH/direct | 7 vérifications réussies |
| Firefox réel, DASH | 9 vérifications réussies |
| web-ext lint 10.6.0 | 0 erreur, 1 avertissement Android déjà présent |
| git diff --check | Aucun défaut |

Les 11 nouveaux tests couvrent MP4 avec audio/historique, WebM, URL MIME-only, Range non rejoué, headers et token, comparaison des deux qualités MP4/HLS, audio natif, page en timeout, tous les candidats en échec et annulation d'un transfert direct avec suppression du partiel. Les tests existants vérifient également la vidéo muette, la fusion audio/vidéo DASH, l'erreur disque sans fallback, le token HLS expiré suivi d'un fallback, la queue en pause et la destination.

Firefox exécute la vraie extension avec ses API webRequest et Native Messaging dans un profil isolé. Le scénario MIME-only suit explicitement **MP4 détecté → catalogue → Automatic → direct sélectionné → fichier final audio/vidéo valide → historique**. Le scénario WebM démarre depuis le choix automatique de page après échec yt-dlp. Les tests HLS conservent la hiérarchie master/variantes/audio et la sélection 1080p. DASH est vérifié avec un vrai MPD local, pistes séparées et fusion FFmpeg.

Les deux échecs intermédiaires de régression générale provenaient des libellés d'installateur non encore mis à jour après le bump backend ; corrigés puis suite relancée. Une première exécution Automatic s'est terminée sans résumé unittest malgré ses cas affichés réussis ; elle n'est pas retenue comme preuve finale. La relance isolée affiche bien `Ran 14 tests` et `OK`.

## Fichiers modifiés

- Production : `extension/background.js`, `extension/manifest.json`, `native-host/download_planner.py`, `native-host/worker.py`.
- Versions : `backend.json`, `native-host/host.py`, `install.sh`, `Install.ps1`.
- Tests : nouveau `tests/test-direct-automatic.py` ; `tests/test-hls-background.js`, `tests/test-download-planner.py`, `tests/test-hls-firefox.py`, `tests/test-direct-detector.js`, `tests/test-dash-detector.js`, `tests/test-hls-groups.js`.
- Documentation : `README.md`, `tests/README.md`, ce rapport et `docs/validation-direct-automatic-v8.44.json`.

Les parsers/détecteurs HLS/DASH/direct, `hls.py`, `direct_media.py`, les downloaders et les mécanismes de contrôle n'ont pas été réimplémentés.

## Limitations restantes et livraison

- Vérification manuelle du cas Reddit réel encore nécessaire. Certains MP4 Reddit sont réellement vidéo-only ; le correctif n'invente pas une piste audio absente et ne fusionne pas deux ressources indépendantes sans relation prouvée.
- Les feeds à plusieurs posts ne sont pas assimilés arbitrairement au post résolu ; un choix manuel reste pertinent lorsque cette relation ne peut pas être établie.
- DASH : détection, resolver/scorer, planner, transfert et merge vérifiés sur des manifests locaux réels, pas validation générale de sites DASH en production.
- ffprobe peut échouer ou atteindre son timeout : les détails audio/résolution peuvent rester inconnus ; aucun téléchargement complet supplémentaire de métadonnées n'est ajouté.
- Pas d'exécution native Windows/macOS dans cet environnement. Les packages sont construits, mais aucune nouvelle preuve CI de publication multi-OS n'est créée.
- Le warning lint concerne Firefox Android 140 et `data_collection_permissions` ; aucune erreur lint de bureau.
- Archive locale complète v8.44 avec backend 8.37 et XPI non signé. Aucune publication GitHub ni soumission/signature Mozilla effectuée.
