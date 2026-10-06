# Audit Windows — backend 8.48 / extension 8.54

Date : 6 octobre 2026. Cette archive contient les corrections et les tests préparés pour Windows x64. La validation native Windows reste à exécuter : aucun résultat Windows natif n’est revendiqué dans ce rapport.

## Erreur signalée et diagnostic

`module 'psutil' has no attribute 'process_iter'` signifie que le module chargé n’expose pas l’API attendue. Les causes possibles comprennent un paquet incomplet, un module homonyme ou une installation endommagée. Sans la sortie de Diagnose.cmd du poste concerné, on ne peut pas choisir entre ces causes.

Le simple succès de `import psutil` était insuffisant. L’installation vérifie maintenant les fonctions réellement utilisées, les méthodes de Process, les opérations sur son propre processus, l’énumération et l’intégrité des fichiers du wheel psutil, y compris son extension native. L’origine privée des paquets est également vérifiée. Un runtime invalide n’est pas activé ; le précédent est conservé.

## Corrections et interactions testées

Les simulations locales injectent les pannes dans les fonctions de production ; les tests de l’interface exécutent les vrais gestionnaires JavaScript. Les scénarios natifs préparés utilisent un dossier isolé, le vrai CPython privé et le lanceur `.bat` avec des messages JSON UTF-8 préfixés par leur longueur. Le bridge charge les vrais scripts `shared.js`, `background.js` et les gestionnaires de session de `popup.js` ; seuls le navigateur et les éléments DOM sont simulés dans ce bridge.

| Problème | Comportement corrigé | Vérification locale | Scénario Windows dédié préparé |
|---|---|---|---|
| Python privé isolé | Les imports des helpers suivent l’ajout explicite du dossier source | Sous-processus Python `-I` chargé sans chemin du script implicite | Véritable installation PowerShell et Python embarqué |
| Session refusée sous Windows | Firefox dédié, profil séparé, APPDATA/LOCALAPPDATA/USERPROFILE propres | Cycle de session, paramètres de lancement, échec de démarrage | Lancement réel Firefox puis état `browser_open` |
| API psutil absente ou paquet incomplet | Erreur structurée, diagnostic négatif, installation refusée | API absente, binaire manquant, wheel réel et imports | Altération du paquet privé ; configure → erreur persistante avec conseil de réinstallation |
| Processus confondu avec un processus terminé | Accès refusé et API défaillante restent des erreurs ; la file n’est pas clôturée | API défaillante, accès refusé, réparation interrompue avant mutation | `status` avec psutil altéré et tâche active ; octets de la file inchangés |
| Démarrage Firefox et détection de sa fermeture | Recherche du profil exact, délai de démarrage, refus de finaliser si vérification impossible | Autre Firefox ignoré, accès refusé, démarrage, fermeture | Vrai Firefox utilisant le profil UUID ; fermeture puis snapshot |
| Réglages et contrôles simultanés | Fichiers temporaires uniques, verrou de transaction ; réglages illisibles jamais remplacés par des valeurs par défaut | 24 mises à jour concurrentes, lecture refusée, absence de temporaires | 24 appels natifs simultanés : dossier + activation de session |
| Fichiers temporairement verrouillés par Windows | Remplacement avec délai borné, conservation de l’ancien fichier en cas d’échec | Partage refusé transitoire et permanent ; remplacement sans perte | Vrai handle Win32 sans FILE_SHARE_DELETE ; changement de dossier et retour natif |
| Chemins contenant `%` | Échappement du dossier et du titre dans les modèles yt-dlp | Véritable `YoutubeDL.prepare_filename` avec caractères spéciaux | Même appel dans le CPython Windows privé ; dossier `français & 100% !` |
| Nettoyage du profil et suppression | Fichiers en lecture seule gérés, jonctions refusées, marqueur conservé pendant le nettoyage ; état inconnu ne permet pas de supprimer | Échec partiel puis nouvel essai ; ancienne session et pending conservés si état inconnu | Profil Firefox réel, cookies synthétiques YouTube/Google, fichier en lecture seule, suppression |
| Deux configurations concurrentes | Verrou de session partagé entre start/status/toggle/delete | Huit demandes simultanées n’ouvrent qu’un Firefox | Test de concurrence exécuté dans chaque runner Windows |
| Annulation malgré un échec de nettoyage des enfants | Signal coopératif toujours transmis au worker | Échec de nettoyage injecté, interruption vérifiée | Contrôles réels annulation/arrêt/reprise de la suite Windows existante |
| Nettoyage des métadonnées après succès | Un processus déjà terminé n’est pas ciblé par taskkill | PID terminé simulé, aucun taskkill | Même panne injectée sous Windows ; budgets des subprocess réels |
| Erreurs qui clignotent dans la popup | Erreurs persistantes, anciennes réponses ignorées, doubles actions bloquées, état réel de la case restauré | Configurer, activer/désactiver, supprimer, transport interrompu, renouvellement raté | Aller-retour frontend → background → lanceur natif → frontend, mode sain et psutil altéré |
| Exceptions natives non encadrées | Réponse Native Messaging structurée même si une API backend lève une exception | Classification des erreurs, syntaxe et régressions | Contrôle d’un unique message binaire JSON dans tous les appels du bridge |

Les reprises de remplacement sont aussi appliquées aux snapshots, à l’état de la file, aux sauvegardes, aux fichiers d’installation, aux caches, à la rotation des logs et aux résultats de remux/sélection de pistes. Elles n’effacent pas le fichier précédent pour contourner un verrou.

## Résultats exécutés ici

L’environnement d’exécution est Linux, Python 3.12. Les paquets réels utilisés pour les contrôles du runtime ont été installés dans un environnement virtuel isolé : yt-dlp 2026.8.19, psutil 7.2.2, Mutagen 1.48.1 et yt-dlp-ejs 0.8.0.

- Régression principale : 95 contrôles réussis ; 5 scénarios Chromium ignorés.
- Audit Windows par injection de pannes : 15 tests réussis, dont le modèle de sortie avec le vrai yt-dlp.
- Session YouTube : 8 tests réussis, lancement Firefox simulé.
- Interface de session : parcours asynchrones configurateur/activation/suppression réussis.
- Démarrage de popup : 9 scénarios réussis.
- Port Windows existant : 30 tests portables réussis ; 5 tests natifs Windows ignorés.
- Dossier d’installation, migration et rollback : 12 tests réussis.
- Packaging et installation Linux : 3 tests réussis.
- Imports, intégrité et pannes du runtime réel : 7 tests réussis.
- Extraction YouTube/SoundCloud : 9 tests réussis.
- Budgets des processus et traitements : 6 tests réussis avec les dépendances réelles.
- Compilation des fichiers Python et vérification syntaxique JavaScript réussies.

Le runtime de test Linux utilise un namespace PID avec un `/proc` de l’hôte. Le contrôle signale cette particularité et n’y teste pas les appels de vivacité par PID ; les imports, empreintes, getters et énumération sont vérifiés. Sous Windows, ce contournement Linux ne s’applique pas et le test natif exige le contrôle complet de vivacité.

Les journaux de cette version sont regroupés dans `validation/windows-audit-v8.48/`. Les validations plus anciennes sont historiques.

## Validation native restant à exécuter

Le workflow `.github/workflows/windows-audit.yml` prépare deux runners distincts : Windows Server 2022 et Windows Server 2025, x64, Python 3.13 et Node 22. Ces images ne sont pas des postes Windows 10/11. Chaque runner installe les dépendances privées, Firefox vérifié par signature Mozilla, exécute les pannes portables sous Windows, puis les six tests natifs dédiés et les tests existants d’installation/réinstallation, annulation, remux, image et désinstallation. Une capture de la vraie popup Firefox est également prévue.

`tests/test-windows-native-audit.py` travaille sur une copie temporaire de l’installation CI. Les comptes/cookies de l’utilisateur ne sont pas utilisés. Le scénario de session lance réellement Firefox mais injecte ensuite des cookies synthétiques : il ne valide pas une connexion réelle à un compte Google ou l’effet d’un VPN.

Les preuves du bridge sont écrites dans `artifacts/windows-audit/`; les captures réelles dans `artifacts/windows-firefox/`. Le workflow les conserve comme artefacts lorsqu’il est exécuté.

L’envoi du commit sur la branche de test GitHub a été refusé par le contrôle automatique d’autorisation. Motif : dépôt considéré comme non vérifié et absence d’autorisation explicite d’y envoyer le code. Le commit et les tests CI n’ont pas été exécutés. Aucun correctif n’a été publié sur la branche principale ni dans une release. La branche de test créée avant ce refus est restée sur le commit de base.

## Installation de la correction

1. Extraire cette archive dans un dossier distinct de l’installation actuelle.
2. Exécuter `kitty-download-manager/Install.cmd` et conserver le dossier proposé pour une mise à jour sur place. Le nouveau runtime est préparé et vérifié avant activation ; réglages et historique restent conservés.
3. Recharger l’extension 8.54 dans Firefox. Pour un chargement temporaire : `about:debugging` → Ce Firefox → Charger un module temporaire → `extension/manifest.json` de cette archive.
4. Si la vérification des dépendances échoue, consulter la sortie de l’installation ou lancer `Diagnose.cmd`. Modifier seulement host.py ne restaure pas un psutil endommagé : la réinstallation du runtime est nécessaire.

Les paquets spécifiques sont également présents dans `packages/`, avec leurs SHA-256. Le XPI est non signé.

## Références techniques

- API psutil : https://psutil.readthedocs.io/en/latest/
- Isolation du Python embarqué Windows : https://docs.python.org/3/using/windows.html
- Images des runners GitHub : https://github.com/actions/runner-images
