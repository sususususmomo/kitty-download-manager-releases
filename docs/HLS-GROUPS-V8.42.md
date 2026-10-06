# Kitty v8.42 — regroupement des sources HLS

L'extension présente désormais une seule source pour un master HLS et ses qualités, pistes audio et sous-titres référencés. Le téléchargement utilise le master complet. Le backend reste en **v8.35** et son pipeline de téléchargement n'a pas été modifié.

## État initial vérifié

La reprise part du commit `9ebab6a40c8784ff6d3609d6b43b365f508d31fd`, frontend 8.41 / backend 8.35. Le dépôt contenait déjà le détecteur partagé HLS/DASH/direct, les fallbacks, les protections de métadonnées et les tests de téléchargement réel. Aucun changement suivi n'était en attente. Un ancien XPI v8.36 non suivi a été laissé intact et exclu de la livraison.

Le catalogue `KittyMedia.Store` de `hls-detector.js`, alias historique `KittyHls`, observait les URLs et headers par onglet. Il dédupliquait les requêtes signées mais ne lisait pas les manifests. Son classement HLS reposait donc sur les noms de fichiers. Les playlists enfants apparaissaient séparément, faute de relations connues avec le master. Les validations précédentes ont été consultées ; les résultats ci-dessous proviennent de nouvelles exécutions.

## Architecture et fichiers

| Fichiers | Changement |
|---|---|
| `extension/hls-parser.js` — nouveau | Analyse bornée des playlists et attributs HLS ; résolution des URIs relatives. |
| `extension/hls-response.js` — nouveau | Observation des corps HLS reçus par Firefox, passage immédiat des octets et nettoyage borné. |
| `extension/hls-detector.js` | Groupes et relations master/enfants dans le catalogue partagé ; classement et résumé sûr. |
| `extension/background.js` | Attachement de l'observation, mise à jour des groupes, logs raisonnables, transmission du master. |
| `extension/popup-hls.js` | Libellés de groupe, audio seul/protection, qualité et informations compactes. |
| `extension/i18n.js` | Traductions français/anglais des nouveaux libellés. |
| `extension/manifest.json` | Frontend 8.42 ; chargement des deux modules et permissions Firefox nécessaires. |
| `tests/test-hls-groups.js` — nouveau | Parser, catalogue, observation, déduplication, sécurité et payload natif. |
| `tests/test-hls-group-download.py` — nouveau | Six scénarios réels avec master vidéo/audio séparés, construits sur les fixtures existantes. |
| `tests/test-hls-firefox.py` | Nouveau mode HLS_GROUPS ; adaptation du cas HLS historique ; diagnostic et capture réels. |
| `tests/README.md` | Commandes et périmètre de validation. |
| `.github/workflows/backend-downloads.yml` | Ajout des deux suites de groupes HLS aux contrôles existants et de leur déclencheur de fichiers. |
| `docs/HLS.md`, `docs/CONFIDENTIALITE.md` | Architecture et description exacte de l'observation locale. |
| `docs/validation-hls-groups-v8.42.json` | Résultats, versions, limites et rapports Firefox. |
| `docs/HLS-GROUPS-V8.42.md` | Ce rapport. |

Aucun fichier de `native-host`, installateur ou `backend.json` n'est modifié. Aucun nouveau downloader HLS, schéma de queue ou protocole natif n'est introduit.

## Observation Firefox

Le détecteur continue de reconnaître les URLs `.m3u8` et les Content-Type HLS existants, y compris sans extension. Pour les réponses HLS réussies, `webRequest.filterResponseData` lit le corps déjà chargé par le lecteur. Il n'effectue aucune requête supplémentaire, aucun téléchargement de segment et aucun export de Cookie ou Authorization.

Chaque bloc reçu est immédiatement écrit inchangé vers Firefox. Le filtre se ferme à la fin normale ; il se détache en cas d'erreur, dépassement de limite, timeout, navigation ou fermeture d'onglet. Un échec d'observation conserve le candidat brut. Les fragments `.ts`, `.m4s` et `init.mp4` continuent d'être exclus du catalogue.

Les premiers essais dans Firefox ont identifié un point réel : un filtre attaché depuis un listener non bloquant recevait « Invalid request ID ». Le listener `onHeadersReceived` est donc synchrone, déclaré avec `blocking`, et retourne immédiatement sans Promise ni modification de headers. L'analyse asynchrone reste séparée. Les permissions MV3 `webRequestBlocking` et `webRequestFilterResponse` sont déclarées conformément à la [documentation Mozilla](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/webRequest/filterResponseData).

La validation finale du cas groupé a observé **27 corps HLS**, tous terminés, **0 filtre échoué**, **0 filtre encore actif** à la fin.

## Structure et classification

Chaque candidat HLS possède un objet interne `hls` qui tient lieu de groupe :

- `kind` : master, video, audio, subtitles ou unknown ;
- `masterUrl` et `originalMasterUrl` : URL complète actuelle et première URL du master analysé ;
- `pageUrl`, `tabId`, `timestamp` ;
- `variants[]`, `audioTracks[]`, `subtitles[]` ;
- `maxResolution`, `codecs`, indicateurs de protection et, lorsque connu, de vidéo seule.

Les variantes/renditions conservent URI résolue, largeur/hauteur, BANDWIDTH, AVERAGE-BANDWIDTH, FRAME-RATE, CODECS, AUDIO, SUBTITLES, GROUP-ID, NAME, LANGUAGE, DEFAULT et AUTOSELECT. Les virgules dans une valeur entre guillemets, notamment CODECS et NAME, sont conservées correctement.

`EXT-X-STREAM-INF` ou `EXT-X-MEDIA` identifie un master. Ses références classent les enfants vidéo/audio/sous-titres. Une media playlist avec EXTINF ou EXT-X-MAP reste valide comme fallback. Des segments AAC/MP3/AC3 apportent un signal audio ; WebVTT/TTML apporte un signal sous-titres ; I-FRAMES-ONLY apporte un signal vidéo. **TS/fMP4 seuls ne permettent pas d'affirmer vidéo-only ou audio-only** : le type reste unknown plutôt que d'inventer une information. Le téléchargement reste possible.

## Déduplication, groupes et classement

La clé de comparaison existante conserve origine, chemin et paramètres significatifs. Elle ignore uniquement la liste déjà connue de paramètres temporaires/signés, par exemple token, signature, expires et certains champs AWS. Aucun nouveau nettoyage agressif n'a été ajouté. Les paramètres d'asset et de qualité restent distincts. L'URL réellement utilisée est toujours complète ; un rechargement signé actualise cette URL sans changer l'identifiant logique.

Seules les références présentes dans un master observé attachent ses enfants. Elles sont comparées avec ces clés prudentes. Les enfants restent en mémoire mais sont masqués dans la liste normale. Les masters imbriqués sont pris en compte ; les cycles malformés ne font pas disparaître toutes les sources. Plusieurs vidéos sans relation restent plusieurs groupes, même dans un seul onglet ou sur le même CDN.

Les masters prouvés par leur contenu passent avant les noms supposant un master, DASH et les fichiers isolés. Les fallbacks audio/sous-titres isolés ont une priorité basse. Une playlist autonome n'est jamais supprimée au seul motif que le site est reconnu par yt-dlp.

## UI et téléchargement

Avant : plusieurs entrées HLS stream numérotées.

Après, pour la fixture Vimeo : **HLS · 1080p max · 3 qualités**, une seule source et le domaine. Après sélection : **360p / 720p / 1080p · vidéo + audio · Sous-titres**, sans ajouter un nouveau sélecteur de qualité.

La popup ne reçoit qu'un résumé de rôle, hauteur, nombres de qualités/pistes et protection. Les URLs signées et l'arbre des enfants restent dans le background. Si un enfant sélectionné disparaît de la liste lorsque son master est reconnu, le sélecteur revient au choix de page et invalide le probe devenu obsolète.

Le background résout l'ID choisi contre le catalogue courant et envoie `media_source.type = hls` avec **l'URL du master**, sa page et Referer/Origin/User-Agent autorisés. L'arbre n'est pas transmis au backend. L'option de page reste prioritaire et porte les sources logiques comme fallbacks, au maximum trois, uniquement pour cette page.

Le pipeline existant effectue métadonnées → formats → queue → yt-dlp → FFmpeg merge/remux → vérification → historique. Les tests prouvent la sélection 1080p et 720p avec audio séparé, l'utilisation du master dans le payload/historique, l'annulation avec suppression des partiels et la pause/reprise de la file. Les sous-titres sont reconnus dans les métadonnées ; leur téléchargement automatique n'a pas été ajouté.

## Bornes, DRM et logs

L'observation est limitée à **10 secondes au total, 2 Mio et 16 filtres simultanés**. Les collections de renditions sont limitées à 128 entrées chacune. Le catalogue conserve au plus 20 sources visibles / 128 candidats internes par onglet, avec le TTL existant de 15 minutes et 256 records de headers. Navigation et fermeture nettoient les groupes et filtres ; une réponse tardive ne ressuscite pas un ancien candidat.

Les budgets backend existants restent : probe/titre 30 s, préparation du téléchargement 120 s, collection 60 s, ffprobe/détection de version 15 s, FFmpeg local 600 s. Le téléchargement complet reste annulable, sans limite arbitraire de durée.

SAMPLE-AES et les key formats non identity signalent une protection. Une protection observée sur un enfant marque aussi le groupe. Le choix explicite d'une source protégée reçoit une erreur propre ; une source reconnue protégée est exclue des fallbacks automatiques, tandis que l'URL de page reste essayée normalement. Les contrôles backend restent actifs. L'AES-128 identity traité normalement par yt-dlp garde son comportement. Aucun contournement, récupération de clé DRM ou contact de serveur de licence n'est ajouté.

Les logs indiquent détection, classification, groupe construit, enfant attaché et doublon ignoré avec rôles/comptages/tabId uniquement. Les messages de doublons sont bornés par candidat. Les tests inspectent les logs pour exclure tokens/headers sensibles et boucles de fallback.

## Tests réellement exécutés

Environnement : Linux, Python 3.12.14, yt-dlp 2026.08.19, FFmpeg 6.1.1, Firefox 153.0, geckodriver 0.37.1, web-ext 10.6.0. Médias synthétiques locaux ; aucune extraction publique pouvant rester bloquée.

| Suite | Résultat final |
|---|---|
| `test-hls-groups.js` | 13 scénarios réussis : attributs, relations, reloads/tokens, vidéos distinctes, audio/texte, DRM, cycle, nettoyage, octets, timeout et payload master. |
| `test-hls-detector.js`, `test-hls-background.js` | Réussis. |
| `test-dash-detector.js`, `test-direct-detector.js` | Réussis, dont 100 Range requests / fragments sans pollution. |
| `test-popup-startup.js`, `test-image-mode.js` | Réussis. |
| `test-hls-group-download.py` | 6/6, vrai yt-dlp/FFmpeg : master 1080p/audio, 720p fallback, formats/sous-titres, playlists autonomes, annulation, queue/historique. |
| `test-hls-download.py` | 12/12, dont MPEG-TS, fMP4, headers, expiry/DRM, classique et annulation. |
| `test-dash-download.py` | 15/15, dont vidéo/audio séparés, merge, timeout et nouvelle connexion au backend. |
| `test-direct-download.py` | 21/21, dont MP4/WebM/audio, Range, formats, progression/vitesse/ETA et annulation. |
| `test-image-download.py` | 11/11. |
| `test-production-timeouts.py`, `test-metadata-timeout.py` | 6/6 + 6/6. |
| `test-backend-packaging.py` | 3/3, installation Linux isolée et upgrade. |
| `run-regression.py` | 95 réussis, 0 échec, 5 vérifications Chromium/Playwright ignorées dans ce banc. |
| Vrai Firefox, mode HLS_GROUPS | 7 vérifications réussies, popup capturée, master → téléchargement natif 1080p avec audio, fallback, reloads, vidéos distinctes, nettoyage. |
| Vrai Firefox, modes HLS / DASH / DIRECT | 8 / 9 / 9 vérifications réussies, exécutées séquentiellement. |
| `web-ext lint` | 0 erreur, 0 notice, 1 avertissement Android préexistant sur la version minimale et la déclaration de données. |

Les 20 cas demandés sont couverts par ces suites : trois qualités, audio séparé, sous-titres, URIs relatives, fMP4, TS, rechargements de master/enfants, signatures, playlists autonomes vidéo/audio, plusieurs vidéos, téléchargement master A/V, 1080p, annulation, queue, historique et régressions DASH/direct/classique. Les tests de queue complètent les parcours réels avec des lancements simulés ; la sortie du worker groupé est ensuite réellement téléchargée et vérifiée par ffprobe.

Les premières erreurs provenaient de l'attachement réel du filtre et du câblage de la nouvelle fixture de queue. Elles ont été corrigées puis les suites concernées et les régressions ont été relancées. Les résultats du tableau sont ceux de l'état final. Le workflow YAML et ses nouvelles commandes ont été validés localement ; GitHub Actions n'a pas été lancé ni publié pendant cette tâche. Quelques ResourceWarning de pipes lors des tests d'annulation ont été observés sans échec ; le pipeline natif inchangé n'a pas été refactoré pour cette tâche.

## Limites restantes et livraison

- Le scénario Vimeo est reproduit avec un master local de même structure ; aucun test sur Vimeo connecté ou sur une URL publique actuelle n'a été exécuté.
- Une playlist isolée TS/fMP4 peut rester unknown. Le nom media.m3u8 ou un paramètre st=audio/video n'est pas utilisé comme preuve suffisante.
- Le regroupement intervient quand le master est effectivement observé. Avant cela, ses playlists autonomes peuvent apparaître séparément. Des redirections de child vers une autre URL non référencée, des variables EXT-X-DEFINE ou des signatures propres à un CDN peuvent empêcher une association ; Kitty conserve alors le fallback brut.
- Le catalogue reste en mémoire. Un master devenu obsolète peut expirer ; ses enfants encore actifs redeviennent autonomes. Les manifests manqués, trop grands, trop lents ou non accessibles à StreamFilter ne sont pas analysés.
- Les cookies génériques Firefox ne sont pas exportés ; les sources nécessitant ce contexte peuvent rester inaccessibles au backend. Les DRM restent indisponibles.
- Aucun test natif Windows/macOS, aucune campagne complète de codecs ou de flux live longs n'a été exécuté ici. Les cinq tests Chromium ignorés ne sont pas présentés comme réussis ; la vraie popup Firefox a été vérifiée et capturée séparément.

L'archive contient le projet complet, les tests, les preuves de validation et le XPI **non signé** v8.42. Elle réutilise le dossier kitty-download-manager. Rien n'a été publié sur GitHub ou Mozilla. Le frontend reste à recharger dans about:debugging pour un test temporaire, ou à faire signer pour une mise à jour permanente.

Commande fish, après téléchargement de l'archive dans Downloads :

```fish
cd ~/Downloads
and unzip -o kitty-download-manager-v8.42-hls-groups.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

Après installation, recharger l'extension temporaire correspondant à `~/Downloads/kitty-download-manager/extension/manifest.json`. La réinstallation du backend suit son comportement existant, notamment la conservation des données et la pause de la queue.
