# Popup et pill — extension 8.57 / backend 8.49

Le bouton principal de la popup et celui de la pill passent par `kitty-add-download`. Le background prépare la même demande native pour les deux : média choisi, mode, pistes, sources compatibles, file d’attente et confirmation des doublons.

## Préférences et adaptation

- Le mode et le format enregistrés restent actifs lorsque la popup est fermée. Vidéo 720p/1080p/meilleure qualité, audio original, MP3 et image conservent leur parcours existant.
- Les langues audio et les langues des sous-titres sont conservées entre les pages. Les identifiants opaques des pistes, le média sélectionné et la source réseau sont liés à leur onglet et leur page. Un identifiant absent revient à Automatique.
- Le backend 8.49 adapte les préférences après avoir analysé les pistes disponibles. Il retire seulement les options absentes de la demande effective et conserve les préférences enregistrées. Une langue absente ne supprime pas une autre langue disponible.
- Une demande vidéo revient à l’audio automatique uniquement lorsque toutes les sources analysées prouvent que le média contient seulement de l’audio. Une limite 720p n’est jamais relevée pour contourner un format vidéo indisponible.
- Automatic compare toujours les sources compatibles et utilise les replis yt-dlp/HLS/DASH/direct. Une source explicitement choisie est prioritaire, avec les autres candidats conservés. L’extraction d’une URL propre au média peut servir de repli ; la page complète d’une galerie ne remplace jamais arbitrairement un média sélectionné.
- Les téléchargements par lot adaptent aussi les préférences absentes et le mode pour les médias audio. Une URL de collection reste liée à la page où elle a été saisie.
- La confirmation d’un doublon porte sur l’identité du média et ses options. Changer le mode ou les pistes invalide cette confirmation. La clé ne contient ni cookies ni headers d’authentification.
- « Tout désélectionner » et l’animation de trois points restent présents.

## Validation du 6 octobre 2026

Les rapports sont dans `validation/shared-download-v8.57/`.

| Vérification | Résultat |
| --- | --- |
| Extension Firefox 153 réelle, vrai Native Messaging et serveur HTTP local isolé | Réussite |
| Popup puis pill avec popup fermée : minimal/chat/classique, français/anglais | Six paires de demandes natives exactement identiques et fichiers MP3 avec audio français et sous-titres français |
| Qualité depuis les deux boutons | Fichiers vidéo 720p et 1080p, audio et sous-titres vérifiés avec ffprobe |
| Navigation vers une page audio sans les langues/sous-titres précédents | MP3 valide, options absentes ignorées, préférences conservées |
| HLS et DASH avec pistes absentes et présentes | 16 tests de transferts réussis : langue absente, sous-titre disponible conservé, MP3, audio natif, pistes séparées, queue et retry |
| Médias de galerie et parcours frontend → host → worker → frontend | 16 tests réussis : identité du média, qualité/format, sources propres, repli vers son extracteur, fichier et fin de téléchargement |
| Automatic, source prioritaire expirée, conservation du MP3 et annulation | 16 tests réussis |
| Planification et choix des pistes | 33 + 20 tests réussis |
| Installation backend et paquets indépendants | 3 tests réussis |
| Régression générale hors réseau | 95 réussis, 5 ignorés car leurs dépendances/environnements dédiés ne sont pas disponibles dans ce banc |
| Contrôles du port Windows exécutables localement | 35 tests, dont 5 réservés à Windows ignorés ici |

Les tests de langues et de format emploient des médias locaux effectivement téléchargés. Les changements d’URL YouTube/SoundCloud sont simulés dans les tests frontend ; aucun téléchargement sur ces services publics n’est présenté comme validé ici.

La validation de cette nouvelle version sur une vraie machine Windows n’a pas encore été relancée. L’envoi des sources vers le dépôt GitHub de validation a été refusé par le contrôle automatique faute d’autorisation explicite pour cette destination. Le workflow `shared-download-validation.yml` est préparé, sans avoir été publié ni exécuté. Les preuves Windows 2022/2025 antérieures concernent le backend 8.48 et restent des preuves historiques.

## Installation

Installer **le backend 8.49 et l’extension 8.57**, tous deux inclus dans `packages/`, puis recharger les pages ouvertes. Sous Windows, le paquet `kitty-backend-v8.49-windows-x64.zip` contient `Install.cmd`. La réinstallation depuis ces sources conserve la configuration et les mécanismes de session du backend existant.

L’adaptation des pistes nécessite le backend 8.49. Avec un backend plus ancien et des préférences de pistes actives, l’extension demande explicitement sa mise à jour au lieu de laisser une sélection incompatible échouer silencieusement.
