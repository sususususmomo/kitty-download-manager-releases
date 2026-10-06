# Kitty frontend 8.52 / backend 8.44 — sites et titres

## Régressions reproduites

Le MediaItem d’un lecteur SoundCloud avec une source HTTP recevait l’URL du CDN comme extractionUrl et un nom technique tel que stream comme titre. Le probe de MediaItem et le resolver Automatic ne consultaient plus l’extracteur de page dès qu’une liste de sources réseau existait. Enfin, le worker Automatic écrasait le détail technique des erreurs par le message générique. Ces problèmes sont communs à Linux et Windows. Ils ne prouvent pas à eux seuls la cause exacte de l’échec YouTube signalé.

## Correction

Les pages YouTube correspondant à une vidéo et les permalinks SoundCloud avec un seul lecteur principal utilisent leur extracteur avant les sources réseau. Les embeds possèdent leur URL dédiée. Les profils, recherches, feeds et galeries ne sont pas traités comme une vidéo unique. Les pages génériques et galeries conservent les sources de chaque MediaItem.

Le probe de métadonnées consulte le site et enrichit la carte avec le titre extrait. Sur ces pages, le titre réel remplace le libellé générique du lecteur. Le téléchargement est planifié depuis les formats de l’extracteur ; les candidats CDN non confirmés restent des solutions de repli sans fournir de pistes audio/sous-titres au plan de l’extracteur. Les refus DRM/authentification du site sont conservés.

Le détail technique est transmis par le sous-processus de métadonnées et conservé dans les erreurs et journaux Automatic. Les URL et en-têtes de session sont masqués. Les messages courts de l’interface restent lisibles.

Le choix du dossier Windows du backend 8.43 est conservé. Mettre à jour backend et extension, puis recharger l’extension dans Firefox.

## Validation exécutée

| Suite | Résultat |
|---|---|
| Sites, sélection de page, titres, probe et détail masqué | 9 réussis |
| Resolver et politique de formats | 33 réussis |
| Catalogue de pistes et plans épinglés | 20 réussis |
| Galeries, HLS, DASH, direct et nouveau parcours audio de site | 14 réussis |
| Téléchargements de pistes multilingues | 12 réussis |
| Timeouts et supervision | 6 réussis |
| Packaging et installation Linux | 3 réussis |
| Dossier Windows et migration | 9 réussis sur Linux |
| Portabilité Windows | 28 réussis, 4 natifs ignorés |
| Régression historique | 95 réussis, 5 contrôles Chromium ignorés |
| Node MediaItems et transmission au backend | Réussi, nouveaux cas YouTube/SoundCloud inclus |
| Node préférences de pistes | Réussi |

Le nouveau parcours audio utilise des métadonnées de site contrôlées, le vrai worker, yt-dlp, un serveur HTTP local et FFmpeg ; le titre de fichier/historique et la piste audio ont été vérifiés. Ce n’est pas un téléchargement SoundCloud public.

Un probe public YouTube de Me at the zoo a obtenu le titre et 16 formats. La construction des plans 1080/720/best/audio/MP3 a réussi. Le téléchargement public complet a toutefois échoué lors de la finalisation : les deux réponses média reçues faisaient 195 octets et FFmpeg les a refusées. Il n’est donc pas présenté comme un succès. L’extraction sans Deno a aussi émis son avertissement de runtime JavaScript ; l’environnement ne reproduit pas le Python/Deno privé de Windows.

L’URL précise de l’utilisateur et ses journaux Windows restent nécessaires pour confirmer l’échec montré dans sa capture. Aucune validation Windows native n’a été exécutée ici. Les workflows sont complétés avec les nouveaux tests.

Journaux reproductibles : validation/provider-media/. Les rapports précédents restent des validations historiques.
