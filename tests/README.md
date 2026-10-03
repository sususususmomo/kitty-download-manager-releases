# Tests de régression — Kitty Download Manager

Depuis la racine du projet :

```bash
./test.sh
```

Le banc de tests est volontairement **hors-ligne** et n'écrit rien dans le vrai
`$HOME`. Les essais d'installation, de configuration et de queue sont réalisés
dans des répertoires temporaires isolés.

Il vérifie notamment :

- manifest Firefox et Native Messaging
- syntaxe Python et JavaScript
- cohérence des numéros de version
- contraintes de coût du Universal Media Resolver
- canonicalisation TikTok / Instagram / X / Reddit / Facebook / YouTube /
  Dailymotion / Twitch
- `canonical`, `og:url`, JSON-LD et fallback générique du resolver
- installation dans un faux HOME
- protocole Native Messaging
- persistance du dossier de destination
- migration, sauvegarde et récupération de `queue.json`
- pause des jobs encore en file et pause globale de la file
- détection des doublons
- reset sûr sans effacer les réglages
- noms propres `Titre`, `Titre (2)`, `Titre (3)`
- nettoyage ciblé des `.part` lors d'une annulation
- écritures atomiques et limite de l'historique

## Node.js

La majorité des tests n'a besoin que de Python 3. Les tests JavaScript du
resolver utilisent Node.js s'il est présent. Si Node.js n'est pas installé,
ils sont indiqués comme `ignorés` au lieu de faire échouer toute la suite.

Aucun téléchargement réel n'est lancé par cette suite : les spawns du worker
sont simulés pour les tests de queue. Cela rend les tests rapides,
reproductibles et sans dépendance aux changements des sites.


## Stockage partagé et concurrence (V8.19)

`run-regression.py` lance également `test-queue-store.py`. Pour le lancer seul :

```bash
python3 tests/test-queue-store.py
```

Cette suite couvre les lectures sans écriture, les mutations sans effet, les
migrations, la conservation d'un schéma futur/corrompu, l'échec de sauvegarde ou
d'écriture, les interruptions, l'historique borné, les workers obsolètes, les
réservations de métadonnées et l'échec de lancement. Deux tests démarrent six
processus réels pour vérifier l'absence de pertes d'écriture et de doublons.

Les tests visuels sont indiqués comme ignorés si Chromium ou Playwright est
absent. Ils restent nécessaires pour valider l'interface; les autres tests ne
prouvent pas son bon fonctionnement. Les téléchargements réels ne sont pas
lancés par le banc de tests.


## Démarrage asynchrone de la popup (V8.23)

`node tests/test-popup-startup.js` exerce le coordinateur et la requête de statut
avec des réponses retardées : l'interface n'est révélée qu'une fois le statut et
les préférences traités, et la lecture native possède une sortie sur timeout.
La suite vérifie aussi l'ordre du démarrage des polls et des réglages cachés.
Ce test ne remplace pas la vérification du premier rendu dans Firefox.

## Captures Firefox sur Windows (V8.28)

Le job `windows-visual` de `.github/workflows/windows-validation.yml` installe
Firefox officiel et Kitty sur un runner Windows neuf. Selenium 4.50.0 charge
une extension temporaire dont les fichiers de production sont inchangés; seule
une page de pilotage est ajoutée à ce XPI de test, dans un profil isolé.

`capture-windows-firefox.py` ouvre la vraie popup de la barre d’outils, vérifie
Native Messaging depuis Firefox et capture son viewport avec le moteur Gecko.
La file est en pause, les titres sont complets et l’historique est marqué
« Exemple CI »; aucun téléchargement de média ni probe réseau n’est lancé.
Le fichier de file original est restauré après la fermeture de Firefox.

Le script exige Windows, `GITHUB_ACTIONS=true` et `KITTY_VISUAL_TEST=1`. Il est
ignoré ailleurs. Il produit sept PNG, une galerie `index.html`, un rapport JSON
et le journal geckodriver, publiés dans l’artefact
`kitty-windows-firefox-captures` même après un échec de capture.

Le mode headless conserve le rendu Firefox et les polices de Windows, mais
les images représentent des états stabilisés : elles ne valident pas les
flashs très brefs, le sélecteur de dossier natif ni une installation manuelle
sur un bureau Windows 10/11. Les versions Firefox et geckodriver sont inscrites
dans le rapport. Les tests d’installation existants ont leur propre job.


### Attente des diagnostics (V8.30)

Le pilote attend la fin de la requête et le rendu d’une liste dans le groupe
ouvert, puis accepte les trois états terminaux : prêt, avertissement et erreur.
Il conserve le diagnostic natif complet, capture le groupe puis vérifie que
les dépendances requises et les fichiers de runtime sont disponibles. L’état
global peut être une erreur sur une installation fraîche dont la destination
n’a pas encore été créée; cet état reste visible dans l’image et le rapport.

`python3 tests/test-visual-capture.py` couvre les avertissements, les erreurs,
les diagnostics encore en cours et les véritables défaillances du backend.
