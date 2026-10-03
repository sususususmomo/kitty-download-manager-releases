# Kitty Download Manager — V8.24

Backend Python utilisant `yt_dlp`, extension Firefox et file persistante.

## Nouveautés

- titre récupéré avant le début réel des octets média
- pourcentage beaucoup plus visible
- vitesse, octets et ETA en direct
- file d'attente persistante
- le téléchargement suivant démarre automatiquement
- la file continue même si la popup Firefox est fermée
- historique des 50 derniers téléchargements
- bouton pour ouvrir `~/Downloads/kitty-download-manager`
- suppression d'un élément encore en attente
- bouton pour vider l'historique
- annulation du téléchargement actif
- icône incluse

## Installation

```bash
chmod +x install.sh
./install.sh
```

Puis Firefox :

```text
about:debugging
→ Ce Firefox
→ Recharger l'extension
```

Si tu charges l'extension pour la première fois :

```text
Charger un module complémentaire temporaire
→ extension/manifest.json
```

## Fichiers

Téléchargements :

```text
~/Downloads/kitty-download-manager
```

État de la file :

```text
~/.cache/kitty-download-manager/queue.json
```

Logs :

```text
~/.cache/kitty-download-manager/worker.log
```

## Remarque migration V4 → V5

La V5 utilise `queue.json` au lieu de l'ancien `state.json`.
L'ancien fichier peut rester présent sans gêner la V5.

Utilise yt-dlp uniquement pour des contenus que tu as le droit de télécharger.


## Correctif V5.1

Corrige un problème de course au démarrage de la file d'attente où le job pouvait
être considéré comme arrêté immédiatement après le clic sur Télécharger.

Après installation, il est conseillé de repartir d'un état propre :

```bash
rm -f ~/.cache/kitty-download-manager/queue.json
```

Puis recharge l'extension dans `about:debugging`.


## Correctif V5.2

- affiche `Déjà présent dans le dossier` lorsqu'yt-dlp termine sans télécharger d'octets
- conserve le dernier résultat dans la carte principale au lieu de repasser immédiatement sur `Prêt`
- empêche d'ajouter plusieurs fois le même URL + format dans la file


## Correctif V5.3 — UI

Cette version ne modifie pas le backend yt-dlp.

Elle corrige le flash :

```text
Téléchargement en cours...
→ Prêt
```

La popup mémorise maintenant le job actif localement et ne revient à un état
inactif que lorsque ce même job apparaît explicitement dans l'historique comme
terminé, annulé ou en erreur.


## V5.4 — ouverture du dossier

Le bouton **Dossier** n'utilise plus uniquement `xdg-open`.

Il essaie maintenant, dans l'ordre :

1. l'interface D-Bus `org.freedesktop.FileManager1`
2. `gio open`
3. `kioclient6` / `kioclient5`
4. `xdg-open` en dernier recours

Le but est d'ouvrir le gestionnaire de fichiers graphique par défaut,
sans lancer un terminal.


## V5.5 — bouton Dossier

Le bouton Dossier détecte maintenant directement les gestionnaires de fichiers
graphiques courants : Nautilus, Dolphin, Thunar, Nemo, Caja, PCManFM et PCManFM-Qt.

`gio` et `xdg-open` ne sont utilisés qu'en dernier recours.


## V5.6 — titres dans la file d'attente

Les éléments en attente récupèrent maintenant leur titre en arrière-plan.

- le téléchargement actif n'est pas interrompu
- un petit worker `metadata.py` fait uniquement `yt-dlp ... download=False`
- la popup affiche d'abord `Récupération du titre…`
- dès que le titre est disponible, il remplace automatiquement ce texte
- en cas d'échec, l'UI retombe sur le nom du site

Le worker actif continue d'utiliser sa propre extraction de métadonnées, donc on
ne lance pas de worker metadata supplémentaire pour lui.


## V5.7 — file d'attente

- tant que le titre n'est pas connu, la file affiche une petite animation
  `Récupération du titre…` au lieu du domaine
- ajout d'un badge Source à droite (`YouTube`, `Vimeo`, `TikTok`, etc.)
- aucun favicon externe n'est chargé : le badge est généré localement
- le vrai titre remplace automatiquement l'animation dès que `metadata.py`
  a mis à jour `queue.json`


## V5.8 — section En cours

La carte **En cours** reprend maintenant le même langage visuel que la file d'attente :

- animation pendant la récupération du titre
- badge Source à droite
- disparition automatique de l'animation dès que le titre est connu
- conservation du badge Source sur le dernier téléchargement terminé


## V5.9

- animations de chargement stabilisées : les spinners ne sont plus recréés à chaque poll
- après succès, `En cours` devient `Téléchargé` en vert
- le dernier mode choisi est conservé via `browser.storage.local`
- le thumbnail est toujours écrit à côté du média
- thumbnail également intégré dans MP3 et MP4 lorsque le conteneur le permet
- le mode Audio original ne transcode pas : YouTube fournit souvent de l'Opus dans un conteneur WebM


## V6 — Audio original remuxé sans perte

Le mode **Audio original** conserve maintenant le codec exact téléchargé, puis
utilise `ffprobe` + `ffmpeg -c:a copy` pour choisir un conteneur plus naturel :

| Codec détecté | Fichier final |
| --- | --- |
| Opus | `.opus` |
| AAC | `.m4a` |
| Vorbis | `.ogg` |
| FLAC | `.flac` |
| MP3 | `.mp3` |
| ALAC | `.m4a` |
| Autre codec | `.mka` |

Aucun réencodage n'est effectué pour ce mode.

Après le remux, le post-processeur officiel `EmbedThumbnail` de yt-dlp est
réutilisé pour intégrer la miniature. Le fichier thumbnail séparé est supprimé
lorsque l'intégration réussit.

Pour OPUS / OGG / FLAC, yt-dlp utilise `mutagen` pour écrire correctement la
pochette. Si `mutagen` manque, le téléchargement et le remux restent valides,
mais le thumbnail externe est conservé.


## V6.1 — interface compacte

Les trois sections principales sont maintenant repliables :

- Téléchargement
- File d'attente
- Historique

Par défaut, Téléchargement est ouvert et les deux autres sont repliés.
L'état ouvert/fermé de chaque section est sauvegardé dans `browser.storage.local`.


## V6.2 — sections réellement compactes

Les sections repliées utilisent maintenant `display: none`, donc leur contenu
ne réserve plus aucune hauteur dans la popup.

Quand une section est ouverte, son contenu apparaît avec une courte animation
d'entrée. Les entêtes repliés sont aussi rapprochés verticalement.


## V6.3 — états de téléchargement

La section Téléchargement distingue maintenant clairement :

- `Récupération des métadonnées…` avant le début réel du transfert
- `En cours` seulement une fois les octets reçus
- `Téléchargé` en vert après succès
- `Annulé` et `Erreur` pour les autres états


## V6.4 — petit chat pendant le téléchargement

Pendant l'état `En cours`, un chat ASCII est choisi aléatoirement parmi :

```text
ᓚ₍ ^. .^₎
/ᐠ｡ꞈ｡ᐟ\
ᓚᘏᗢ
₍^. .^₎⟆
```

Le même chat reste affiché pendant tout le téléchargement et une petite balle
animée apparaît à côté. L'animation est masquée pendant la récupération des
métadonnées et disparaît immédiatement à la fin, en cas d'erreur ou d'annulation.


## V6.4.1 — animation du chat

La balle se déplace maintenant sur une distance plus longue et un cycle dure
environ 2,4 secondes au lieu de 1,1 seconde. Le mouvement est donc plus lent et
plus lisible.


## V6.5 — deux chats qui se renvoient la balle

Pendant `En cours`, deux chats ASCII sont choisis aléatoirement pour le job.
La balle traverse maintenant un petit terrain entre les deux chats avec davantage
de frames. Le cycle complet dure environ 5,2 secondes dans un sens, puis CSS
`alternate` inverse automatiquement l'animation pour que le second chat renvoie
la balle au premier.


## V6.6 — animation aller-retour corrigée

- Le DOM de l'animation n'est plus recréé à chaque mise à jour de progression.
- La balle peut donc réellement atteindre le deuxième chat.
- Un aller dure maintenant environ 6,4 secondes.
- La trajectoire contient beaucoup plus d'étapes intermédiaires.
- À l'arrivée, la balle marque un petit impact/rebond sur le deuxième chat.
- `animation-direction: alternate` effectue ensuite le trajet inverse.
- Les chats ont une légère réaction au moment où ils reçoivent la balle.


## V6.7 — animation aléatoire des chats

- l'animation des chats démarre dès `Récupération des métadonnées…`
- la balle n'utilise plus une trajectoire CSS fixe
- à chaque contact avec un chat, une nouvelle trajectoire est générée :
  - durée différente
  - hauteur d'arc différente
  - légère courbure/oscillation différente
- le trajet n'est donc plus exactement le même à chaque aller-retour
- cela fonctionne pour toutes les paires de chats choisies aléatoirement


## V6.7.1 — correction du téléport de balle

Correction d'un glitch d'une frame lors du contact avec un chat.

La direction du prochain lancer n'est désormais changée qu'après la petite
pause d'impact. Pendant cette pause, la balle reste verrouillée sur le chat
qu'elle vient réellement de toucher.


## V6.7.2 — espacement et vitesse

- davantage d'espace réservé à l'animation, surtout à droite
- marge supplémentaire pour les chats ASCII les plus larges
- trajectoires accélérées : environ 3,6 à 5,2 secondes par lancer
- pause d'impact raccourcie pour un effet moins flottant


## V6.7.3 — nouveau nom

Le nom visible de l'extension est maintenant **Kitty Download Manager**.
Les identifiants techniques internes restent inchangés pour préserver la compatibilité.


## V6.7.4 — correction du titre du popup

Le titre principal affiché en haut de la popup est maintenant bien
`Kitty Download Manager`.


## V6.8 — mascotte ASCII aléatoire dans le header

Ajout d'une mascotte ASCII compacte en haut à droite, à côté de
**Kitty Download Manager**.

Une mascotte est tirée au hasard à chaque ouverture de la popup parmi la
sélection validée. Elle est indépendante de l'animation des chats pendant
le téléchargement.


## V6.8.1 — mascotte du header plus lisible

- pool réduit aux mascottes ASCII/Unicode qui restent propres dans Firefox
- taille augmentée à 13 px
- zone fixe réservée à droite du titre
- centrage vertical amélioré
- police monospace avec fallbacks plus adaptés aux glyphes utilisés


## V6.8.2 — nouvelles mascottes ASCII

Ajout au pool aléatoire du header de :

```text
A___A
(ㅇㅅㅇ)
/   >🐠

ᵐᵉᵒʷ ₍^. .^₎⟆

/'• ˕ •'\

/\__/\
  • w •
```


## V6.8.3 — pas deux fois la même mascotte

La mascotte ASCII du header mémorise maintenant son dernier index dans
`browser.storage.local`.

Conséquence : à l'ouverture suivante de la popup, le tirage aléatoire exclut la
mascotte précédente, donc **le même chat ne peut plus apparaître deux fois de suite**.


## V6.9 — prototype Mini Mode

Ajout d'un bouton `↓` dans la popup principale.

Il ouvre une petite fenêtre Firefox séparée contenant uniquement un bouton
de téléchargement. Le bouton :

- récupère l'onglet actif de la fenêtre Firefox d'origine
- utilise le dernier format sélectionné
- affiche brièvement `…`, puis `✓` en cas de succès ou `!` en cas d'erreur
- réutilise la même mini-fenêtre si elle est déjà ouverte

Ce prototype ajoute la permission `tabs` afin que la mini-fenêtre puisse lire
l'URL de l'onglet actif de la fenêtre Firefox principale.


## V7.0 — pill flottant dans les pages

Le prototype de mini-fenêtre V6.9 a été retiré complètement.

À la place, Kitty injecte un petit pill flottant directement dans les pages web :

- position fixe en haut à droite par défaut
- déplaçable à la souris / au pointeur
- position mémorisée
- `×` pour le masquer jusqu'au rechargement de la page
- bouton `↓` pour télécharger immédiatement l'URL courante
- utilise automatiquement le dernier format sélectionné dans la popup principale
- affiche `Métadonnées…`, le pourcentage pendant le transfert, puis `Terminé`
- petite animation du chat pendant le traitement
- option dans la popup principale pour activer/désactiver le pill
- option `Tous les sites` ou `Sites médias connus`

Le content script est isolé via Shadow DOM afin de limiter les conflits avec le CSS des sites.


## V7.0.1 — correction de l'état final du pill

Correction du pill qui pouvait rester figé sur le dernier pourcentage.

Le backend marque un téléchargement réussi avec le statut `finished`, alors que
la V7.0 attendait `done`. Le pill accepte désormais `finished` et retrouve le
job terminé par son ID dans l'historique, ce qui rend aussi le suivi plus fiable
avec une file d'attente.


## V7.0.2 — optimisation des performances du pill

Le polling du pill est désormais adaptatif :

- aucun polling lorsque l'onglet est en arrière-plan
- vérification environ toutes les 1 s uniquement pendant un téléchargement suivi
- environ toutes les 10 s lorsque le pill est au repos
- reprise immédiate lorsque l'onglet redevient visible
- arrêt complet lorsque le pill est masqué
- plus de `setInterval` permanent : le suivi utilise des `setTimeout` adaptatifs

Cela réduit fortement le travail effectué par les onglets ouverts lorsque Kitty
n'est pas en train de télécharger.


## V7.0.3 — séparateurs discrets des sections

Ajout d'un trait très faible en opacité entre le titre et le résumé pour :

- File d'attente
- Historique

Le trait s'étire automatiquement pour remplir l'espace disponible sans modifier
la largeur de la popup.


## V7.1 — harmonisation, doublons, relance et nettoyage

### Visuel
- bouton **Ajouter au téléchargement** en `#2A62BB`
- flèche du pill en bleu `#2A62BB`
- pill harmonisé avec les états de la popup :
  - métadonnées : jaune
  - téléchargement : blanc
  - terminé : vert
  - erreur : rouge
  - file : bleu doux

### Doublons
Un média déjà téléchargé n'est plus relancé immédiatement :
- la popup affiche clairement **Déjà téléchargé**
- le bouton devient **Retélécharger quand même**
- le pill affiche **Déjà téléchargé** et `↻`
- il faut confirmer par un deuxième clic

### Historique
Les téléchargements en erreur disposent maintenant d'un bouton **Relancer**.

### File
Quand plusieurs jobs existent, la position `x / total` apparaît :
- dans la section Téléchargement
- sur chaque élément de la file
- dans le pill lorsqu'il suit un job en file

### Architecture / performances
- ajout de `shared.js` pour centraliser états, labels, couleurs, sources, formats et positions
- popup et pill utilisent la même logique d'état
- polling adaptatif côté popup et pill
- cache Native Messaging partagé côté background
- le pill suit désormais son propre job au lieu d'adopter le job d'un autre onglet
- reprise après rechargement/redémarrage possible si la page correspond au job actif/en file
- CSS historique/dupliqué de l'animation des chats nettoyé


## V7.2 — dossier de destination configurable

Le dossier de téléchargement n'est plus hardcodé.

### Interface
La popup affiche maintenant :
- le dossier de destination courant
- un bouton **Choisir…** qui ouvre un sélecteur de dossier natif Linux

Le bouton **📁 Dossier** ouvre toujours le dossier actuellement configuré.

### Persistance
Le choix est enregistré dans :

```text
~/.config/kitty-download-manager/settings.json
```

La valeur par défaut reste :

```text
~/Downloads/kitty-download-manager
```

### File d'attente
Chaque job copie le dossier de destination au moment où il est ajouté.

Ainsi, si le dossier est modifié pendant qu'une file existe :
- les jobs déjà présents continuent vers leur dossier initial
- les nouveaux jobs utilisent la nouvelle destination

Une relance depuis l'historique conserve également la destination du job en erreur.

### Sélecteur natif Linux
Le host essaie, selon ce qui est installé :
- kdialog
- zenity
- yad
- qarma


## V7.2.1 — historique coloré

Les lignes de l'historique indiquent maintenant visuellement leur état :

- succès : fond vert sombre discret
- erreur : fond rouge sombre discret

Une petite barre colorée à gauche renforce la lecture sans rendre l'interface trop vive.


## V7.2.2 — contrôles pause / annulation (rebasée sur V7.2.1)

Cette version repart directement de V7.2.1. Aucun code de V7.3/V7.3.1 n'a été repris.

### Téléchargement actif
- `⏸` demande une pause coopérative au worker
- le worker quitte proprement en gardant le `.part`
- `▶` redémarre le même job avec `continuedl=True`, donc yt-dlp reprend le `.part`
- aucun `SIGSTOP` / `SIGCONT` n'est utilisé pour la pause
- `Annuler` conserve le mécanisme SIGTERM qui fonctionnait en V7.2.1
- lors d'une annulation, le worker supprime les `.part`, fragments et fichiers intermédiaires du job
- les contrôles disparaissent lorsque les octets média atteignent 100 %

### File d'attente
- `×` retire un élément sans le télécharger
- `⏸` / `▶` met un élément de la file en pause/reprise
- `⏸ File` / `▶ File` bloque ou reprend le démarrage automatique de la file
- les éléments en pause restent visibles et sont simplement ignorés par le worker

### Important
L'interface Historique est celle de V7.2.1, avec les fonds vert/rouge de V7.2.1 inchangés.


## V7.2.3 — annulation active uniquement, pause queue only

- suppression du bouton pause/reprise sur le téléchargement actif ;
- un téléchargement déjà lancé peut seulement être laissé finir ou être annulé ;
- `Annuler` continue de supprimer proprement le fichier partiel ;
- la file d’attente garde :
  - `×` pour retirer un élément
  - `⏸ / ▶` pour mettre en pause/reprendre un élément en attente
  - `⏸ File / ▶ File` pour bloquer / relancer le démarrage des prochains éléments ;
- le libellé de résumé à droite dans la section Téléchargement a été abaissé pour éviter les collisions avec l’ASCII des chats.


## V7.2.4 — état versionné et auto-récupération

Le moteur conserve maintenant `state_version: 2` dans `~/.cache/kitty-download-manager/queue.json`.

### Migration et downgrade

- un ancien `queue.json` sans version est migré automatiquement ;
- une sauvegarde pré-migration est créée avant toute conversion ;
- un `queue.json` JSON corrompu est mis de côté au lieu d'être écrasé silencieusement ;
- si une future version écrit un `state_version` supérieur, V7.2.4 considère le fichier incompatible, le sauvegarde puis repart sur une file propre ;
- les sauvegardes sont placées dans `~/.cache/kitty-download-manager/state-backups/` (8 maximum).

### Récupération des workers

Lors d'un `status`, Kitty vérifie qu'un job actif possède réellement le bon processus `worker.py` et le bon identifiant de job. Un PID mort ou recyclé ne peut donc plus bloquer indéfiniment la file.

Les vieux états `paused` provenant des essais V7.2.2/V7.3 sont automatiquement libérés et archivés comme erreur au lieu de rester dans `active`.

### Pause active

La pause/reprise d'un téléchargement déjà commencé est maintenant désactivée également côté backend. Seule la pause des éléments qui n'ont pas encore commencé et la pause globale de la file restent disponibles.


## V7.2.5 — retour visuel succès / erreur

- Pill : fond vert sombre discret sur succès, rouge sombre sur erreur.
- Bloc Téléchargement : fond vert/rouge cohérent avec l'historique quand le dernier job est terminé ou en erreur.
- File d'attente : flash vert/rouge pendant environ 2,2 s lorsqu'un job vient de terminer ou d'échouer.
- Le flash de la file fonctionne aussi lorsque la section est repliée.
- Une annulation reste neutre (pas de rouge), car elle est volontaire.


## V7.2.6 — couleurs pendant les états actifs

- récupération des métadonnées :
  - fond jaune discret basé sur `#E6B85C`
  - opacité de teinte : 8 %
  - appliqué à la carte Téléchargement, à la section File et au pill
- téléchargement en cours :
  - fond bleu `#4AA3DF`
  - opacité de teinte : 8 %
  - appliqué à la carte Téléchargement, à la section File et au pill
- les états finaux restent inchangés :
  - succès : vert
  - erreur : rouge
- les teintes sont superposées au fond sombre existant pour conserver le contraste de l'interface.


## V7.2.7 — File d'attente neutre + dernier résultat

- la File d'attente reste maintenant neutre pendant les métadonnées et le téléchargement actif
- le flash court de résultat est conservé :
  - vert après un succès
  - rouge après une erreur
- un petit indicateur persistant apparaît à droite du résumé :
  - `✓` vert = dernier téléchargement pertinent réussi
  - `!` rouge = dernier téléchargement pertinent en erreur
- l'indicateur est reconstruit depuis l'historique à chaque ouverture de la popup
- une annulation ne remplace pas le dernier `✓` ou `!`


## V7.2.8 — position du résumé Téléchargement

- le libellé d'état à droite de la section Téléchargement
  (`Métadonnées`, `Téléchargement`, `Terminé`, etc.) est descendu davantage
- décalage vertical porté de 7 px à 13 px
- aucun changement de largeur de popup ni du layout des chats


## V7.2.9 — noms de fichiers propres sans ID visible

Les nouveaux téléchargements n'incluent plus `[media_id]` dans leur nom.

### Noms visibles

Exemples :

```text
NEXT (SUPER SLOWED + REVERB).opus
Nom de la vidéo.mp4
Morceau.mp3
```

En cas de collision, Kitty réserve automatiquement un nouveau stem :

```text
Titre.opus
Titre (2).opus
Titre (3).opus
```

La réservation porte sur tout le stem et pas seulement l'extension, afin
d'éviter également les collisions de thumbnails et de fichiers temporaires.

### ID conservé en interne

L'identifiant YouTube/Vimeo/etc. reste enregistré dans `media_id` dans l'état
du job et l'historique. Il n'est simplement plus exposé dans le nom du fichier.

### Annulation / nettoyage

Le nettoyage ne dépend plus de `[ID]` dans le nom.

Chaque job mémorise désormais un `output_stem`, par exemple :

```text
/home/user/Downloads/kitty-download-manager/NEXT (SUPER SLOWED + REVERB)
```

Tous les fichiers associés à ce job (`.part`, média, thumbnail, fragments,
intermédiaires) peuvent ainsi être retrouvés précisément sans toucher à un
éventuel `Titre (2)` appartenant à un autre téléchargement.

Les anciens fichiers déjà téléchargés avec `[ID]` ne sont pas renommés.
Seuls les nouveaux téléchargements utilisent le nouveau schéma.


## V7.2.9.1 — correction yt-dlp `'str' object has no attribute 'get'`

Correction ciblée du nouveau système de noms propres.

La V7.2.9 modifiait `ydl.params["outtmpl"]` après la création de l'objet
YoutubeDL. Selon la version de yt-dlp, ce paramètre peut avoir été normalisé
en structure interne, et le remplacer par une chaîne provoquait ensuite :

```text
'str' object has no attribute 'get'
```

V7.2.9.1 :
- ne modifie plus les paramètres internes de yt-dlp à chaud
- utilise un second contexte YoutubeDL construit directement avec le template
  final `Titre.%(ext)s`
- conserve la réservation `Titre`, `Titre (2)`, `Titre (3)`
- conserve `media_id` uniquement en interne
- rend aussi le progress hook robuste si `info_dict` n'est pas un dictionnaire


## V7.2.10 — interface à deux niveaux + outils de maintenance

La popup principale est allégée. Les réglages occasionnels sont déplacés dans
une vue dédiée accessible via l'icône `⚙` à côté de la mascotte.

### Vue principale
- choix du format
- Ajouter au téléchargement
- Ouvrir le dossier
- Téléchargement / File d'attente / Historique

### Réglages
- dossier de destination + Choisir…
- activation du pill flottant
- portée du pill : tous les sites / sites médias connus
- Ouvrir les logs
- Copier le diagnostic
- Réinitialiser Kitty

### Diagnostic
Le diagnostic inclut les versions de Kitty, Python, yt-dlp, ffmpeg et ffprobe,
l'OS, l'environnement de bureau et l'état général de la file. Il ne copie ni
les URL ni les titres des téléchargements.

### Réinitialiser Kitty
Action protégée par un double clic de confirmation. Elle :
- sauvegarde queue.json avant reset
- arrête le worker actif
- nettoie les fichiers partiels du job actif
- vide la file et l'historique
- remet l'état interne à zéro

Elle ne supprime pas les vidéos terminées, ne modifie pas le dossier de
destination et conserve les préférences du pill.


## V7.2.11 — correction du changement de dossier

Le sélecteur de dossier n'est plus piloté par la popup.

Sous Firefox, l'ouverture d'un dialogue natif peut faire perdre le focus et
fermer la popup avant la fin de la requête. Le choix de destination est
maintenant exécuté intégralement par le background de l'extension :

- la popup demande au background d'ouvrir le sélecteur ;
- le background attend la réponse du dialogue natif ;
- il demande au Native Messaging host de persister le nouveau dossier ;
- il met également en cache le dernier chemin confirmé dans storage.local ;
- à la prochaine ouverture, la popup affiche immédiatement ce chemin puis le
  revalide auprès du backend.

Le dossier configuré reste stocké de façon autoritaire dans :
`~/.config/kitty-download-manager/settings.json`.


## V7.2.12 — resolver TikTok pour le feed

TikTok ne place pas toujours le permalink de la vidéo visible dans la barre
d'adresse. Kitty résout maintenant la vidéo réellement affichée avant de
l'envoyer à yt-dlp.

Exemple :

```text
https://www.tiktok.com/@andreea_bostanica/video/7660560870455840021?is_from_webapp=1&sender_device=pc
```

devient :

```text
https://www.tiktok.com/@andreea_bostanica/video/7660560870455840021
```

La résolution fonctionne avec le pill et avec `Ajouter au téléchargement` :

- URL vidéo directe : suppression query string + hash
- feed TikTok : sélection de la vidéo `<video>` la plus visible
- recherche du permalink `/@user/video/ID` dans sa carte DOM
- fallback sur le permalink visible le plus proche du centre de l'écran
- aucune URL générique du feed n'est envoyée à yt-dlp si la vidéo n'est pas détectée
- le Native Messaging host canonicalise également les permalinks TikTok en seconde ligne de défense


## V7.2.12.1 — resolver TikTok renforcé

Le premier resolver cherchait surtout un lien `/video/` visible, ce qui ne
fonctionne pas sur tous les layouts TikTok.

Le nouveau resolver exploite aussi les structures du lecteur TikTok :

```text
[data-e2e="recommend-list-item-container"]
[data-cinema-mode-snap-row]
.xgplayer-container
[id^="xgwrapper-"]
```

Il peut maintenant :

- récupérer un permalink déjà présent, même si l'ancre elle-même est cachée
- extraire directement l'ID depuis `data-cinema-mode-snap-row`
- extraire l'ID depuis `xgwrapper-...-VIDEO_ID`
- récupérer le username depuis les liens de profil ou les attributs `data-e2e`
- construire lui-même `https://www.tiktok.com/@user/video/ID`
- utiliser `https://www.tiktok.com/@_/video/ID` si seul l'ID est disponible,
  format explicitement accepté par yt-dlp
- supprimer systématiquement query string et hash


## V7.13 — versionnage Firefox corrigé

Aucun changement fonctionnel par rapport à V7.2.12.1.

Le numéro de version est désormais volontairement limité au format simple :

```text
X.N
```

Exemple actuel :

```text
7.13
```

Cela respecte le format de version accepté par Firefox et évite les versions
à 5 blocs comme `0.7.2.12.1`.


## V7.14 — Universal Media Resolver

Kitty ne dépend plus uniquement de `location.href` ni d'un resolver TikTok
isolé. Le content script contient maintenant un resolver universel, exécuté
uniquement à la demande.

### Signaux génériques, du moins coûteux au plus coûteux

1. URL actuelle si elle correspond déjà à un permalink média connu
2. média `<video>` / `<audio>` le plus visible
3. liens proches du média visible, en remontant au maximum 9 ancêtres
4. `<link rel="canonical">`
5. `meta[property="og:url"]` / `twitter:url`
6. JSON-LD `VideoObject`, `AudioObject`, `MediaObject` ou `Clip`
7. fallback sur l'URL de page uniquement pour les sites non ambigus

Le JSON-LD est volontairement borné : 6 scripts maximum, 48 Ko par script,
120 Ko au total et 180 noeuds parcourus. Il n'est parsé que si les signaux
moins coûteux n'ont pas déjà donné une réponse forte.

Aucune requête réseau n'est faite par le resolver. Aucun `MutationObserver`
n'est gardé actif. Un cache de 300 ms amortit le polling du pill, avec
invalidation implicite par URL et position de scroll.

### Adapters légers

- TikTok : permalink, conteneur de feed/cinema, `xgwrapper-*`, ID + username
- Instagram : `/p/`, `/reel/`, `/reels/`, `/tv/`
- X / Twitter : `/user/status/ID`, `/i/web/status/ID`, `/statuses/ID`
- Facebook : `/reel/ID`, `/watch/?v=ID`, `/videos/.../ID`
- Reddit : permalink `/comments/ID`
- YouTube : `watch?v=`, Shorts, Live, youtu.be
- Dailymotion et Twitch Clips : canonicalisation directe

Les adapters ne remplacent pas le resolver générique : ils ne servent que
quand un gros site expose un identifiant média d'une façon particulière.

### Sources de conception

Le resolver suit les formes d'URL actuellement reconnues par les extracteurs
yt-dlp pour Instagram, X/Twitter, Facebook et Reddit. Pour les signaux HTML
génériques, `rel=canonical` et `og:url` sont utilisés comme indications de
l'URL permanente, et le JSON-LD est traité comme signal secondaire.


## V7.15 — banc de tests de régression

Ajout d'une suite de tests hors-ligne exécutable en une commande :

```bash
./test.sh
```

Elle couvre le Universal Media Resolver, les canonicalisations, le protocole
Native Messaging, l'installation en HOME isolé, les réglages, la queue, les
migrations/récupérations de `queue.json`, les doublons, le reset, les noms de
fichiers et le nettoyage ciblé des fichiers partiels.

Les tests de queue ne lancent aucun téléchargement réel : le worker est simulé.
Les tests du resolver utilisent Node.js s'il est disponible.

Nettoyage également des deux anciens labels de version restés dans `install.sh`
et le log de démarrage du worker.


## V7.16 — Pinterest + pill

- Pinterest ajouté à `Sites médias connus`
- domaines nationaux supportés (`pinterest.fr`, `.de`, `.co.uk`, etc.)
- canonicalisation `/pin/ID/` et `/pin/slug--ID`
- résolution du pin associé au média visible dans le feed
- suppression des query strings de tracking
- refus d'envoyer un feed Pinterest générique si aucun pin précis n'est trouvé
- même canonicalisation côté backend pour queue et doublons


## V7.17 — Session YouTube dédiée et isolée

Ajout de `Réglages → YouTube → Configurer YouTube…`.

La configuration crée uniquement un UUID neuf sous
`~/.cache/kitty-download-manager/youtube-auth-sessions/`. Firefox est lancé avec
`-no-remote -profile <profil-jetable>` et avec un HOME/XDG séparé.

Le profil Firefox habituel n'est ni recherché, ni copié, ni modifié. Le profil
jetable désactive la sauvegarde/autofill des mots de passe et Firefox Sync.

Après fermeture du Firefox dédié, Kitty :
1. refuse le snapshot si un lock Firefox subsiste ;
2. extrait uniquement les cookies `youtube.com` ;
3. écrit un candidat en permissions `0600` ;
4. supprime le profil jetable avec un garde-fou UUID + marker ;
5. remplace atomiquement l'ancien snapshot seulement après nettoyage réussi.

Un renouvellement raté conserve donc l'ancien snapshot.

Chaque téléchargement YouTube reçoit une copie privée du snapshot dans le
cache. yt-dlp ne reçoit jamais le master directement, et la copie est supprimée
à la fin du job.

`./test.sh` ajoute des tests destructifs simulés : faux profil Firefox réel,
sentinelles `logins.json`/`key4.db`, tentative de suppression hors zone,
renouvellement invalide, filtre de domaines et immutabilité du snapshot master.


## V7.18 — finalisation de session YouTube

Correction de la détection de fermeture du Firefox dédié.

V7.17 pouvait considérer un lock Firefox orphelin ou un PID trompeur comme
preuve que la fenêtre dédiée était encore ouverte. Sous Linux, V7.18 utilise
désormais le processus Firefox dont la ligne de commande contient le chemin
exact du profil UUID jetable comme source de vérité.

Un fichier `.parentlock`/`lock` resté après fermeture ne bloque plus le
snapshot. Avant extraction, Kitty ouvre aussi `cookies.sqlite` en lecture seule
pour vérifier que Firefox a terminé ses écritures ; si la base n'est pas
encore prête, l'UI indique `Finalisation` et réessaie au prochain statut.

Un test de régression reproduit explicitement un `.parentlock` stale après
fermeture et vérifie que la session se finalise sans toucher au profil réel.


## V7.19 — mode Playlist

Le sélecteur natif de format est remplacé par un menu Kitty personnalisé.

- le format actif reste sélectionné (`1080p`, `720p`, `best`, audio ou MP3) ;
- `Playlist` est un toggle indépendant tout en bas du même menu ;
- quand Playlist est actif, le menu reste ouvert et montre simultanément les
  deux sélections en surbrillance ;
- un champ URL apparaît juste sous le sélecteur ;
- `Ajouter au téléchargement` devient `Ajouter la playlist`.

Le backend ne transmet jamais la playlist entière au worker de téléchargement.
Il utilise yt-dlp en extraction plate pour récupérer les entrées, puis crée un
job Kitty par vidéo. Un seul worker est démarré à la fois et les autres entrées
rejoignent la file existante.

Les titres issus de la playlist sont réutilisés pour éviter de lancer des
dizaines/centaines de workers de métadonnées en parallèle.

Les vidéos déjà actives, en file ou déjà terminées dans le même format et le
même dossier sont ignorées lors d'un nouvel ajout de playlist. Cela permet de
relancer une grosse playlist sans reconstruire tous les téléchargements déjà
terminés.

Si la session YouTube dédiée est active, l'extraction de la playlist utilise
elle aussi une copie privée du snapshot de cookies : le master n'est jamais
remis directement à yt-dlp.


## V7.20 — progression réelle des playlists

Correction de l'affichage `1 / x` pendant une playlist.

Pour un job de playlist, `playlist_position` et `playlist_total` ont désormais
priorité sur la position dans la file restante. Par exemple, la 123e vidéo
d'une playlist de 500 affiche `123 / 500`, même après disparition des 122 jobs
précédents.

La logique est partagée par la carte active et le pill flottant. Les lignes de
file utilisent également la position réelle de la playlist comme affichage
principal.


## V7.21 — vider toute la file d'attente

Ajout de `Vider la file` à côté de `⏸ File`.

Le premier clic affiche `Confirmer (N)` pendant 4,5 secondes. Le second clic
supprime en une seule opération tous les jobs encore en attente.

Le téléchargement actuellement actif est volontairement conservé et continue
normalement. L'état de pause globale de la file est également conservé.

Le test de régression crée 500 jobs en attente, vide la file, puis vérifie
qu'il reste exactement le job actif et zéro job en attente.


## V7.22 — logique de file playlist + téléchargements manuels

Correction du cas visible où un clic sur la pill pendant une playlist de
plusieurs centaines d'éléments plaçait le nouveau téléchargement tout au bout
de la file (`799 / 799 • file`).

La queue a désormais deux lanes stables :

1. téléchargements manuels/interactifs (popup, pill, retry), FIFO ;
2. backlog de playlists, FIFO.

Le téléchargement actif n'est jamais interrompu. Si une vidéo de playlist est
en cours, le premier ajout manuel devient simplement le prochain job. Plusieurs
ajouts manuels gardent leur ordre.

La règle vit dans `enqueue()` : le bouton principal, la pill et `Relancer`
partagent donc exactement la même logique.

`queue_paused` est maintenant respecté même lorsque `active` est vide : un
nouvel ajout ne peut plus démarrer par-dessus une file globalement en pause.

Les anciennes queues mixtes sont réparées automatiquement : les jobs manuels
appendus derrière une playlist sont remontés devant le backlog par partition
stable, sans changer l'ordre relatif des jobs manuels ni celui des playlists.

Affichage :
- playlist : `14 / 837 • Audio • playlist` ;
- manuel devant une playlist : `prochain • Audio • file`, puis
  `priorité 2 / 3 • Audio • file` si plusieurs ajouts manuels attendent ;
- la pill affiche `En file • prochain` au lieu de `En file • 799 / 799`.


## V7.23 — playlists et collections multi-sites

Le toggle `Playlist` n'est plus limité à YouTube.

Le champ accepte désormais toute URL HTTP/HTTPS que yt-dlp sait exposer comme
collection. La première intégration explicitement couverte et testée est
SoundCloud :

- profil artiste : `https://soundcloud.com/artiste`
- `/tracks`
- `/albums`
- `/sets`
- `/likes`
- `/reposts`
- `/spotlight`

Le moteur est générique et accepte également les collections yt-dlp de
Bandcamp, Vimeo, Dailymotion, Audiomack, Audius et d'autres sites lorsque
l'extracteur renvoie des entrées individuelles exploitables.

Sécurité / comportement :

- une URL de média unique est refusée en mode Playlist ;
- les sous-playlists imbriquées ne deviennent pas accidentellement des jobs ;
- chaque entrée devient toujours un job Kitty individuel ;
- la politique de priorité V7.22 reste intacte ;
- les cookies de la session YouTube dédiée ne sont copiés QUE si la collection
  source est YouTube ; ils ne sont jamais transmis à SoundCloud ou un autre site ;
- YouTube avec `?list=` conserve sa canonicalisation historique ;
- les autres URLs sont laissées intactes pour ne pas casser leurs extracteurs.

Les champs `playlist_position` / `playlist_total` sont conservés en interne
pour compatibilité avec l'UI et l'état existants, même lorsqu'il s'agit d'une
collection SoundCloud ou Bandcamp.


## V7.24 — durcissement général téléchargements + métadonnées

### Métadonnées

- `metadata_status`, `metadata_pid`, `metadata_started_at` et
  `metadata_attempts` rendent le probe observable ;
- un échec de lancement n'est plus silencieux ;
- `repair_state()` détecte un probe disparu et le relance une fois ;
- yt-dlp metadata utilise des timeouts/retries bornés ;
- l'UI affiche `Titre indisponible` après une vraie erreur au lieu de spinner
  éternellement.

### Résolution des collections

Les champs flat de yt-dlp ne sont plus tous considérés comme des pages média.

- priorité à `webpage_url` et `original_url` ;
- refus explicite des `.jpg/.png/.webp/...` ;
- refus des artwork SoundCloud `sndcdn.com/artworks-*` ;
- le fallback `url` doit rester dans la même famille de domaine que la
  collection, afin de ne pas injecter un CDN opaque dans la queue.

### Fichier final

Un job ne peut être `Téléchargé` qu'après validation d'un vrai média.

Kitty collecte les chemins post-processés et téléchargés, écarte images,
sidecars, sous-titres et `.part`, puis vérifie avec `ffprobe` :

- Audio / MP3 : présence obligatoire d'un flux audio ;
- Vidéo : présence obligatoire d'un flux vidéo.

La sélection finale préfère également :
- le `.mp3` post-processé au flux source ;
- une vidéo fusionnée audio+vidéo à un fragment vidéo seul.

Une pochette JPEG seule ne peut donc plus devenir le résultat final d'un job.


## V7.25 — état des dépendances et diagnostic local

Les réglages affichent maintenant un état structuré des dépendances runtime :

- Python — requis ;
- yt-dlp (module Python réellement utilisé par les workers) — requis ;
- ffmpeg — requis ;
- ffprobe — requis ;
- Mutagen — optionnel/recommandé pour certaines intégrations de pochette.

Le statut distingue `ready`, `warning` et `error`. Une dépendance optionnelle
absente ne bloque pas Kitty ; une dépendance requise absente est clairement
signalée.

### Auto-test local

Le bouton `Vérifier Kitty maintenant` effectue uniquement des tests locaux :

- présence du Native Host, worker et metadata worker ;
- import du module yt-dlp ;
- exécution locale de `ffmpeg -version` et `ffprobe -version` ;
- import de Mutagen ;
- validation de queue.json via la récupération d'état existante ;
- espace libre de la destination ;
- vrai test d'écriture de destination avec un minuscule fichier temporaire
  créé en `0600`, fsync puis supprimé immédiatement.

Aucun accès réseau n'est utilisé.

### Diagnostic copiable

Le diagnostic contient les versions, l'état global, la taille du log, le
nombre de backups, la queue/historique et l'état d'auth YouTube, mais :

- aucune URL de téléchargement ;
- aucun titre ;
- aucune valeur de cookie ;
- pas de chemin complet de destination ;
- les chemins sous HOME sont abrégés avec `~`.

Le popup conserve sa largeur de 410 px.


## V7.26 — messages d’erreur personnalisés

Nouvelle couche centrale `native-host/errors.py`, partagée par le Native Host,
le worker de téléchargement et le worker de métadonnées.

Chaque erreur possède désormais un code stable, un message court, un conseil,
le détail technique brut et une information de relance quand elle est utile.

Messages explicitement couverts :

- Aucun flux audio disponible
- Session YouTube expirée
- Espace disque insuffisant
- ffmpeg introuvable
- Vidéo privée
- Contenu supprimé
- Collection vide
- Connexion interrompue

Sont également couverts : aucun flux vidéo, ffprobe/yt-dlp manquant, 429,
403 générique, login requis, géoblocage, restriction d’âge, DRM, URL non
prise en charge, format indisponible, permission refusée, destination
indisponible, média invalide, erreur ffmpeg/post-traitement, état queue
endommagé, worker manquant, doublons, erreurs de file et actions invalides.

L’UI n’affiche plus l’erreur technique brute comme message principal.
Le détail reste journalisé et stocké séparément dans `error_detail`.

Le popup montre la cause dans l’historique et le conseil sur le dernier échec.
La pill affiche elle aussi le message d’erreur personnalisé.

Comme `content-pill.js` change dans cette version, recharge les pages ouvertes
après avoir rechargé l’extension.


## V8.0 — migration d’identité complète vers Kitty Download Manager

La V8.0 fige l’identité avant les premières releases publiques.

Identité définitive :

```text
Nom public          Kitty Download Manager
Slug                kitty-download-manager
Firefox ID          kitty-download-manager@local
Native Messaging    com.kitty.download_manager
```

Chemins définitifs :

```text
~/.local/lib/kitty-download-manager/
~/.config/kitty-download-manager/
~/.cache/kitty-download-manager/
~/Downloads/kitty-download-manager/
```

L’installateur V8 sait reconnaître l’ancienne installation de développement
(`firefox-ytdlp`, `videoytdlp`, l’ancien ID Firefox et l’ancien host natif).
Ces anciens noms ne servent plus qu’à la migration one-shot.

La migration se fait en deux phases : copie + validation, puis bascule. Elle
préserve `settings.json`, queue/historique, backups, logs utiles, session
YouTube dédiée et destination personnalisée. Si l’ancienne destination était
exactement le dossier par défaut `videoytdlp`, le dossier est renommé vers
`kitty-download-manager` lorsque cela peut être fait sans conflit, et les
chemins persistés dans queue/historique sont réécrits.

Un téléchargement V7 encore actif bloque l’installation afin de ne jamais
migrer un état en mouvement. Une fenêtre d’auth YouTube V7 encore ouverte
bloque également la migration.

Après validation, seuls les chemins legacy exacts sont supprimés. La V8 écrit
`~/.config/kitty-download-manager/migration-v8.json` pour garder la trace de la
migration et l’exposer dans le diagnostic.

Le changement volontaire d’ID Firefox crée un nouvel espace `storage.local`.
Les données importantes vivent/migrent côté backend ; les préférences purement
visuelles de l’ancienne extension temporaire (format sélectionné, sections
repliées, position de la pill) repartent une seule fois sur leurs valeurs par
défaut. À partir de V8, l’ID est considéré comme figé.


## V8.1 — arrêt sûr des workers

Un SIGTERM/SIGINT externe n'est plus traité comme le bouton Annuler.

**Annuler depuis Kitty**
- le host écrit `action=cancel` avant SIGTERM ;
- le worker sait que l'annulation est volontaire ;
- le partiel est nettoyé ;
- le job est marqué annulé ;
- le suivant peut démarrer normalement.

**pkill / arrêt système / maintenance / signal externe**
- `queue_paused=true` automatiquement ;
- aucun job suivant n'est lancé ;
- le job actif revient en `queued` dans sa lane ;
- un job manuel reste prioritaire sur le backlog collection ;
- les `.part` sont conservés ;
- aucune entrée annulée/erreur n'est créée dans l'historique.

La protection fonctionne même si aucun mode maintenance n'a été activé.


## V8.2 — identité visuelle des sources

Les anciens caractères Unicode (`▶`, `☁`, `♪`, etc.) ont été remplacés par
des icônes SVG locales, sans requête réseau, pour YouTube, SoundCloud, TikTok,
Instagram, X, Vimeo, Twitch, Dailymotion, Pinterest, Bandcamp, Reddit,
Facebook, Audiomack et Audius. Les autres sites utilisent un globe générique.

Le petit carré contenant l'icône est désormais un vrai bouton :

- clic => ouvre `job.url` dans un nouvel onglet Firefox ;
- une entrée de collection ouvre donc le média individuel concerné ;
- URL limitée à HTTP/HTTPS ;
- tooltip et `aria-label` `Ouvrir la source · <plateforme>` ;
- états hover, focus clavier et clic ;
- même comportement pour le téléchargement actif, la file, le dernier
  téléchargement et l'historique.

`shared.js` change dans cette version : recharge les pages ouvertes après le
reload de l'extension.


## V8.3 — capsule source simplifiée

Le badge de plateforme n'empile plus plusieurs fonds.

Avant :
`carte d'état → capsule sombre → carré d'icône coloré → icône`.

Maintenant :
`carte d'état → une seule capsule légère → icône + nom`.

- aucun fond propre à l'icône ;
- seule l'icône conserve une couleur discrète de plateforme ;
- capsule quasi transparente et bordure très légère ;
- hover/focus/clic appliqués à toute la capsule ;
- toute la capsule ouvre la source ;
- même traitement dans actif, file, dernier résultat et historique.

Le changement concerne uniquement le popup, donc les pages web ouvertes n'ont
pas besoin d'être rechargées.


## V8.4 — suppression du flash des capsules source

Le polling du popup reste actif pendant un téléchargement, mais les capsules
ne sont plus recréées si leur URL, plateforme, label et taille n'ont pas changé.

V8.3 réassignait `innerHTML` de la source active à chaque poll (~750 ms).
Sous la souris, cela détruisait puis recréait le bouton et réinitialisait
`:hover`, d'où le petit flash périodique.

V8.4 stabilise le nœud DOM avec `data-source-signature`.

L'historique visible reçoit aussi une signature : ses lignes ne sont plus
détruites/recréées à chaque poll si rien d'affiché n'a changé.

Aucun content script n'a changé.


## V8.5 — réglages repliables

Le bloc `YouTube` des réglages est renommé `Cookies`.

Les quatre blocs avancés suivants deviennent repliables :

- Cookies
- Dépendances
- Diagnostic
- Maintenance

Ils sont fermés par défaut pour garder les réglages compacts. Chaque en-tête
est un bouton accessible avec chevron et `aria-expanded`.

L’état ouvert/fermé de chaque bloc est mémorisé dans `browser.storage.local`
sous `settingsSectionStates`, donc la disposition choisie reste identique à
la prochaine ouverture du popup.

Destination et Pill flottant restent visibles en permanence.

Aucun content script n'a changé.


## V8.6 — trois styles de pill

`Réglages → Pill flottant → Style` propose maintenant trois variantes avec
aperçu visuel dans un menu déroulant :

- **Minimal** : un seul bouton rond bleu, sans texte ni mascotte. L'icône
  change avec l'état (`…`, `•`, `⏸`, `✓`, `!`, etc.).
- **Chat ASCII** : uniquement `ᓚᘏᗢ`, sans texte ni autre contrôle visible.
  C'est désormais le style par défaut.
- **Classique** : la pill complète existante avec chat, texte de statut,
  bouton et fermeture.

Les styles compacts sont aussi déplaçables : un mouvement déplace le pill,
un simple clic déclenche le téléchargement.

Les trois styles reprennent les couleurs d'état de la pill classique :
métadonnées jaune, file bleu pâle, téléchargement bleu, succès vert,
erreur rouge et doublon jaune.

Le choix est sauvegardé sous `pillStyle` et appliqué immédiatement aux pages
ouvertes via `browser.storage.onChanged`.

`content-pill.js` change : recharge les pages ouvertes après le reload de
l'extension.


## V8.7 — correction des pills compactes

Les styles **Minimal** et **Chat ASCII** déclenchent maintenant le même `kitty-pill-download` que la pill classique.

La cause du bug V8.6 était la capture immédiate du pointeur par le conteneur : elle pouvait détourner le `click` du bouton compact. La capture reste désormais sur le bouton lui-même pour les variantes compactes. Un mouvement >= 5 px est considéré comme un drag ; un appui immobile reste un vrai clic. Le clic synthétique qui suit un drag est consommé pour éviter les téléchargements accidentels.

Les contrôles compacts restent déplaçables même pendant un état occupé via `aria-disabled` / `data-action-disabled`, sans devenir des boutons HTML inertes.

Le **Chat ASCII** n'est plus sur fond transparent : il utilise une petite surface sombre, bordée et légèrement floutée. Les états métadonnées, file, pause, téléchargement, succès et erreur teintent subtilement cette surface.

La régression inclut un test UI réel sous Chromium/Playwright : clic sur les trois styles, drag des deux styles compacts sans téléchargement accidentel et vérification du fond du Chat ASCII.

`content-pill.js` change : recharge les pages ouvertes après le reload de l'extension.


## V8.8 — aperçu du sélecteur de pill

L'aperçu `Classique` du menu Réglages ne contient plus le mot `Download`.
Il fonctionne maintenant comme une vraie icône : mini capsule avec le chat
ASCII et le petit bouton bleu.

Les colonnes d'aperçu sont bornées et masquent tout dépassement, afin que
l'aperçu ne puisse jamais empiéter sur les labels `Minimal`, `Chat ASCII` ou
`Classique`, y compris dans la valeur sélectionnée du menu.


## V8.9 — aperçu Classique plus lisible

L'aperçu `Classique` du sélecteur de pill est agrandi sans réintroduire le
chevauchement corrigé en V8.8 :

- zone d'aperçu plus large ;
- mini capsule portée à 25 px de haut ;
- chat ASCII agrandi ;
- bouton bleu porté à 18 px ;
- flèche agrandie ;
- largeur toujours bornée et overflow masqué ;
- label `Classique` reste dans une colonne séparée.


## V8.10 — renommage du style Kitty

Le style de pill précédemment affiché comme `Chat ASCII` s'appelle maintenant
`Kitty` dans le sélecteur et dans les messages de réglages.

La clé interne reste `cat` pour préserver les préférences déjà enregistrées :
aucune configuration utilisateur n'est perdue.


## V8.11 — couleurs dans Réglages

Accents visuels ajoutés sans transformer le panneau en interface multicolore :

- Destination : bleu clair.
- Pill flottant : bleu Kitty.
- Cookies : `!` jaune tant que la session n'est pas active ; point vert
  uniquement lorsqu'elle est réellement configurée et activée.
- Dépendances : point vert / jaune / rouge selon le diagnostic réel.
- Diagnostic : violet doux.
- Maintenance : rouge doux.

Les sections repliables prennent une très légère teinte correspondante
lorsqu'elles sont ouvertes.

Une session YouTube seulement configurée mais désactivée reste donc en
`!` jaune ; le point vert exige `configured && enabled`, hors état pending
ou erreur.

## V8.12 — updater sûr, compatibilité et uninstaller

### Compatibilité frontend ↔ backend

Kitty possède maintenant un protocole Native Messaging versionné séparément de
la version visible de l'application. Le frontend envoie sa version et son
numéro de protocole à chaque message natif.

- même protocole + même série Kitty : compatible ;
- versions différentes mais protocole identique : compatible avec indication
  de décalage de version ;
- protocole ou série incompatibles : les actions qui modifient l'état
  (download, queue, auth, etc.) sont bloquées jusqu'à mise à jour ;
- status/diagnostic restent accessibles pour pouvoir expliquer le problème.

Cette asymétrie permet une mise à jour **backend d'abord**, puis un reload de
Firefox, sans casser brutalement un ancien frontend pendant les quelques
secondes de transition.

### Vérification des mises à jour de dépendances

Le diagnostic local reste sans réseau. Un nouveau bouton **Vérifier les mises
à jour** lance explicitement une vérification réseau :

- Arch : `checkupdates` si disponible (préféré), sinon `pacman -Qu` sur la
  base locale ;
- Debian/Ubuntu : `apt list --upgradable` sur la base locale ;
- Fedora : `dnf check-update --cacheonly` ;
- PyPI sert de fallback consultatif pour yt-dlp et Mutagen.

Kitty **n'installe jamais automatiquement** Python, ffmpeg, yt-dlp ou Mutagen,
ne lance jamais `sudo` et ne mélange jamais `pip` avec le gestionnaire de
paquets système.

Le résultat est mis en cache dans
`~/.cache/kitty-download-manager/update-check.json`, ce qui permet au
Diagnostic d'afficher l'état sans refaire de réseau à chaque ouverture.

L'icône du header Diagnostic indique :

- `↑` bleu : mise(s) à jour disponible(s), faible risque connu ;
- `↑!` jaune : au moins une mise à jour mérite un test de compatibilité
  (ex. changement de branche Python ou version majeure ffmpeg) ;
- `!` rouge : frontend/backend Kitty non compatibles ou non vérifiables.

### Updater

Deux façons d'utiliser l'updater :

```text
./update.sh --check
./update.sh
```

Après installation, les helpers sont aussi disponibles dans
`~/.local/bin/` :

```text
kitty-update
kitty-update /chemin/vers/une/nouvelle/release/kitty-download-manager
```

Sans argument, `kitty-update` vérifie le backend et les dépendances. Avec le
chemin d'une release décompressée, il applique cette release.

Une mise à jour :

1. vérifie que le frontend et le backend contenus dans la release ont la même
   version/protocole ;
2. vérifie les dépendances et signale les upgrades potentiellement sensibles ;
3. sauvegarde `queue.json` et l'ancien backend ;
4. met la file en pause **avant** d'envoyer SIGTERM ;
5. attend l'arrêt sûr du worker actif (qui requeue son job et conserve les
   fichiers partiels) ;
6. valide le nouveau backend dans un dossier de staging ;
7. remplace l'ancien backend par renommage atomique avec rollback ;
8. valide un vrai handshake Native Messaging frontend/backend ;
9. restaure la politique précédente de pause et reprend la file si elle était
   active avant la mise à jour.

Relancer `./install.sh` sur une V8 déjà installée délègue automatiquement à ce
flux au lieu d'écraser les fichiers du backend pendant qu'un worker tourne.

### Uninstaller

Désinstallation sûre :

```text
./uninstall.sh
```

ou, après installation :

```text
kitty-uninstall
```

Elle arrête les workers avec la même préparation sûre, puis supprime le
backend et le manifest Native Messaging. Elle **conserve** config, file/cache
et cookies pour permettre une réinstallation.

Purge complète des données privées Kitty :

```text
./uninstall.sh --purge
```

La purge demande de taper `PURGE` (ou `--yes` pour une automatisation) et
supprime config, cache, logs et cookies Kitty. **Aucun des deux modes ne
supprime le dossier de téléchargements ni les médias terminés.**


## V8.13 — hotfix popup V8.12

La V8.12 construisait `NATIVE_CLIENT` avec `NATIVE_PROTOCOL_VERSION` avant
l'initialisation de cette constante depuis `shared.js`. Firefox levait donc
`ReferenceError: Cannot access 'NATIVE_PROTOCOL_VERSION' before initialization`
dès le chargement du popup. Le HTML restait visible, mais aucun handler de clic
n'était attaché.

V8.13 importe maintenant les constantes partagées avant de construire le
client Native Messaging.

Un nouveau smoke test charge le vrai `popup.html`, `shared.js` et `popup.js`
dans Chromium et vérifie l'absence d'exception, le menu de format, Réglages,
le dépliage de Cookies, le menu de style du pill et le retour à la vue principale.


## V8.14 — interface Français / English

Une couche `extension/i18n.js` traduit uniquement l'affichage. Les identifiants
internes, actions Native Messaging, codes d'erreur, clés de stockage et valeurs
de style (`minimal`, `cat`, `classic`) restent inchangés.

`Réglages → Langue` propose **Français** et **English**. Français reste le
choix par défaut. Le choix est stocké sous `uiLanguage` et s'applique
immédiatement au popup et à la pill.

Les données techniques, titres de médias, URLs, chemins et identifiants
internes ne sont pas traduits.


## V8.15 — logs, cache et i18n finalisée

### Logs bornés

`worker.log` passe par un writer partagé et verrouillé entre le worker principal
et le worker de métadonnées. La rotation est automatique à **2 Mio par fichier**
avec **4 archives maximum** (`worker.log.1` à `.4`). Le log courant reste
disponible pour le diagnostic et le bouton « Ouvrir les logs ».

Le bouton de nettoyage peut supprimer les anciennes archives tournées, mais il
conserve toujours `worker.log`.

### Cache local sûr

Le Diagnostic affiche maintenant séparément :

- taille totale du cache Kitty ;
- taille totale des logs ;
- espace récupérable ;
- cache temporaire ;
- anciens backups d'update ;
- nombre et taille des fichiers partiels orphelins détectés.

`Maintenance → Nettoyer le cache` ne travaille que sous
`~/.cache/kitty-download-manager/`. Il peut retirer les snapshots temporaires
de jobs terminés, sessions YouTube jetables abandonnées, fichiers atomiques
temporaires anciens, archives de logs et anciens backups d'update. Pour les
backups d'update, les **3 groupes les plus récents** de chaque type sont
conservés.

Le nettoyage ne supprime jamais :

- les téléchargements terminés ;
- les fichiers `.part`, `.ytdl` ou `.part-frag` trouvés dans les destinations ;
- `queue.json` et les backups d'état ;
- les cookies YouTube persistants ;
- une session YouTube actuellement en cours ;
- le log courant.

Les `.part` anciens de plus de 24 h peuvent être signalés comme « orphelins »
dans Diagnostic, mais ils restent volontairement intacts : Kitty ne peut pas
savoir de façon suffisamment sûre si l'utilisateur souhaite encore les garder.

### FR / EN

La couche d'affichage FR/EN a reçu une passe complète : textes statiques,
messages dynamiques, queue/historique, playlists, cookies YouTube, dépendances,
diagnostic, maintenance, cache, logs, tooltips et catalogue d'erreurs backend.

Les identifiants internes restent inchangés : actions Native Messaging, codes
d'erreur, clés de stockage, protocole, modes et valeurs `minimal` / `cat` /
`classic` ne sont pas traduits.

Les tests couvrent désormais automatiquement tout le catalogue d'erreurs,
les textes statiques du popup et une session Chromium entièrement en anglais
pour détecter des résidus français.


## V8.17 — releases GitHub + vérification SHA-256

Kitty peut maintenant vérifier explicitement la dernière release publique publiée
sur `sususususmomo/kitty-download-manager-releases` depuis Diagnostic. Le
Diagnostic local reste hors-ligne ; l'accès réseau n'a lieu qu'après clic sur
« Vérifier les mises à jour ».

La vérification compare la version installée au tag GitHub et recherche l'asset
`kitty-download-manager-vX.Y.zip`. Lorsqu'une version plus récente est
 disponible, le bouton « Télécharger la mise à jour » apparaît.

Le téléchargement est d'abord écrit dans le cache privé de Kitty, puis son
SHA-256 est calculé et comparé au digest publié par GitHub. Une archive dont la
taille ou le SHA-256 ne correspond pas est rejetée et n'est jamais copiée dans
`~/Downloads`. Une archive valide est déposée dans `~/Downloads` avec l'état
« SHA-256 vérifié ».

## V8.18 — Télécharger avec Kitty au clic droit

- Ajoute une seule action Firefox **Télécharger avec Kitty**, sans sous-menu.
- Le clic envoie immédiatement le média au backend avec le dernier format choisi dans Kitty (`1080p`, `720p`, meilleure qualité, audio ou MP3).
- Sur YouTube, TikTok et les autres plateformes connues, Kitty privilégie l'URL de la page plutôt qu'une URL `blob:`/CDN temporaire.
- Sur un lien, Kitty télécharge directement la cible du lien ; sur une page générique avec une vraie source vidéo/audio HTTP, la source directe reste utilisable.
- Le libellé du menu suit le réglage FR/EN de l'interface.


## V8.19 — Nettoyage et fiabilisation de la file

- Stockage partagé dans `native-host/queue_store.py` pour host, worker,
  métadonnées et maintenance : verrou, schéma, migration et écritures atomiques.
- `snapshot()` et `get_state()` ne réécrivent plus une file valide. Les transactions
  sans changement ne provoquent pas d'écriture. Une lecture sans file existante
  ne crée pas `queue.json`.
- Migration et récupération effectuées une seule fois, sous verrou, avec une
  sauvegarde préalable. Un schéma futur bloque l'accès sans déplacer ni écraser
  le fichier original. Une erreur d'accès n'est pas traitée comme une corruption.
- Détection des doublons et insertion dans une transaction unique, même lorsque
  plusieurs processus ajoutent simultanément le même média.
- Progression, PID et fin de téléchargement ne peuvent modifier que le job du
  worker concerné. L'indicateur `already_present` vise l'identifiant du job,
  plutôt que le premier élément d'historique.
- Réservation commune du prochain job et maintien de la priorité manuels/FIFO.
  Si le lancement échoue, le job est remis en file et celle-ci est mise en pause.
- Réservation atomique des probes de métadonnées pour éviter les doubles
  lancements et les lancements de jobs déjà supprimés.
- Le gestionnaire de signaux n'acquiert plus le verrou des logs : un signal peut
  interrompre une écriture sans créer de blocage par réentrée.
- Fichiers temporaires uniques et privés (`0600`), `fsync` avant publication,
  nettoyage même en cas d'interruption; historique borné à chaque commit.
- Tests Chromium/Playwright explicitement ignorés quand leurs prérequis manquent.

Validation : 92 cas existants réussis, 22 tests ciblés réussis, dont deux essais
avec six processus concurrents. Les cinq tests visuels n'ont pas été exécutés
ici faute de Chromium. Aucun téléchargement réel ni test sous Windows/macOS
n'est couvert par cette validation. Cette release reste destinée à Linux.

Installation / mise à jour : extraire l'archive, exécuter `bash install.sh` dans
le dossier extrait, puis recharger `extension/manifest.json` dans Firefox
(`about:debugging`) et les pages où l'overlay était déjà affiché. Le bouton de
mise à jour de l'extension télécharge toujours l'archive sans l'installer.


## V8.20 — Fond opaque pendant les changements de popup

Le fond sombre est maintenant peint explicitement sur `html` et `body`, pour
conserver un canvas opaque quand Firefox redimensionne la popup. Les animations
d'ouverture par opacité/translation de la file, de l'historique et des groupes
de réglages sont supprimées. La taille de la popup reste adaptée au contenu.

Validation : banc de régression hors ligne réussi. Le flash signalé dans
Firefox n'a pas pu être reproduit ni vérifié visuellement dans cet environnement
sans navigateur local. Les cinq tests visuels restent ignorés.


## V8.21 — Hauteur stable et défilement interne

La popup garde désormais une hauteur fixe pendant une ouverture, calculée avant
le rendu du contenu par `extension/popup-size.js`. Elle utilise au maximum 520
pixels CSS et réserve 200 pixels de la hauteur disponible de l'écran pour les
barres du navigateur et du bureau (minimum 120 pixels). Le défilement appartient
au `body` interne; `html` ne grandit plus quand on déplie une section ou qu'on
passe aux réglages. La place de la barre de défilement est réservée pour éviter
un changement de largeur des éléments.

Cette marge vise les fenêtres de navigateur placées normalement en haut de
l'écran; elle ne mesure pas la position exacte du bouton de l'extension ni la
hauteur d'une fenêtre de navigateur réduite. La disparition du flash reste à
vérifier sur le poste où il a été observé. Les tests visuels locaux ne peuvent
pas être exécutés ici faute de Chromium.


## V8.22 — Popup compacte avec hauteur maximale

La hauteur fixe introduite en V8.21 est remplacée par une hauteur maximale sur
`html` et `body`. Les sections repliées n'imposent donc plus de vide sous
l'historique. La limite calculée selon l'écran, le fond opaque et le défilement
interne sont conservés. La popup suit le contenu tant que cette limite n'est
pas atteinte, puis son contenu défile sans agrandir la fenêtre au-delà.

Validation : banc de régression hors ligne réussi; les cinq tests visuels sont
ignorés faute de Chromium. Le maintien de l'absence de flash dans Firefox et la
réduction du vide restent à vérifier sur le poste utilisateur.


## V8.23 — Initialisation cohérente de la popup

Le HTML initial affichait ses valeurs par défaut avant la fin des chargements
indépendants du statut, des sections repliées, de la langue, du format et du chat
aléatoire. Au premier rendu, on pouvait donc apercevoir « Téléchargement » et
une disposition provisoire avant leur remplacement par l'état actuel.

Un seul coordinateur attend maintenant les préférences et le premier statut
frais du backend. Un indicateur neutre de chargement masque les vues pendant
cette préparation, sans supprimer leur géométrie. Le chat est choisi une seule
fois par ouverture. La limite de hauteur et le défilement de V8.22 restent en
place. Les premières actualisations périodiques commencent après cette étape;
les réglages natifs cachés ne concurrencent plus la requête du premier statut.

La première requête de statut a un délai maximal de cinq secondes : si le
backend ne répond pas, le chargement est libéré avec un message d'erreur et la
popup reste accessible. Une réponse tardive de cette requête ne repeint pas la
vue après son timeout; une actualisation ultérieure peut rétablir le statut.

Validation : 94 cas de régression réussis, dont les 22 tests ciblés de file et
quatre scénarios asynchrones de démarrage (préférences lentes, backend lent,
erreurs, timeout puis nouvelle réponse). Les cinq tests visuels restent ignorés
faute de Chromium; le premier rendu réel dans Firefox reste à vérifier sur le
poste utilisateur.


## V8.24 — Résumés plus lisibles

Le résumé « Terminé » est supprimé après un téléchargement réussi : le titre
vert « Téléchargé » suffit à indiquer ce résultat. Le résumé vide ne prend plus
de place. Les résumés des autres phases, dont la position dans la file, restent
affichés. « Vide » et le compteur d’éléments de l’historique sont éclaircis
(opacité 80 % au lieu de 55 %).

Validation : 94 cas de régression réussis, 0 échec. Les cinq tests visuels
sont ignorés faute de Chromium; rendu réel Firefox non vérifié ici.
