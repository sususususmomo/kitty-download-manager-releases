# Releases Kitty

Le workflow **Kitty releases** prépare les archives, vérifie les versions et les sources validées, puis crée les releases GitHub. Il ne soumet pas l’extension à Mozilla.

## Releases actuelles

- [Kitty Backend v8.31](https://github.com/sususususmomo/kitty-download-manager-releases/releases/tag/v8.31) : trois installateurs, `SHA256SUMS`, release « Latest ».
- [Kitty Firefox v8.37](https://github.com/sususususmomo/kitty-download-manager-releases/releases/tag/frontend-v8.37) : XPI non signé, archive complète, validation et `SHA256SUMS`.

Les [contrôles du frontend v8.37](validation-frontend-v8.37.json) couvrent le rendu DOM, Firefox et les installateurs. Les [résultats de la première publication](validation-releases-v8.36.json) enregistrent le workflow réussi, les huit empreintes publiques et la reconnaissance des trois archives par la recherche de mises à jour native.

Les tags frontend portent le préfixe `frontend-v` pour éviter une collision avec une version backend de même numéro. Les tags backend gardent `v`, requis par le client déjà installé. La recherche native consulte `/releases/latest` : seule une release backend peut donc recevoir « Latest ». Les noms de ses archives correspondent au client existant. Les premières installations de l’extension v8.36 conservent leurs liens vers la branche `backend-installers-v8.31`.

## Utiliser le workflow

GitHub → Actions → **Kitty releases** → **Run workflow**, sur `main`.

| Mode | Résultat |
|---|---|
| `dry-run` (par défaut) | contrôles et archives dans l’artifact `kitty-release-packages`; aucun changement aux releases |
| `draft` | brouillons GitHub, fichiers envoyés et SHA-256 vérifiés |
| `publish` | mêmes contrôles, puis publication publique |

Choisir `both`, `frontend` ou `backend`. Pour une modification de l’interface seule, choisir `frontend`; conserver la version backend. Un lancement sur une autre branche reste obligatoirement en `dry-run`.

Une modification de `.github/release-request.json` sur `main` peut aussi demander un mode et un composant. Ce fichier de commande est exclu de l’archive de sources; il ne modifie pas ses empreintes. Un commit ordinaire de l’application ne publie pas une release. Après une demande ponctuelle, remettre le fichier en `dry-run`.

## Préparer une version suivante

1. Modifier la version du composant concerné (`extension/manifest.json` ou `backend.json` et `APP_VERSION` pour le backend).
2. Exécuter les workflows Windows, macOS et publication checks sur le commit de l’application. Les trois exécutions doivent réussir.
3. Enregistrer `docs/validation-frontend-vVERSION.json` avec les deux versions, `tested_application_commit` et les URL `windows_run`, `macos_run`, `publication_checks_run`. Les sources de l’application et ses tests doivent correspondre exactement à ce commit. Les changements de documentation et d’automatisation de release sont autorisés ensuite.
4. Ajouter les notes `docs/releases/frontend-vVERSION.md` ou `backend-vVERSION.md`.
5. Préparer en `dry-run`, puis publier depuis `main` avec le composant voulu.

La préparation relit les résultats Actions et compare les blobs et modes de chaque fichier de l’application et de ses tests au commit validé. Un changement de code impose de nouvelles validations. Les nouveaux tests de l’automatisation de release sont exécutés dans le workflow lui-même.

Les fichiers sont d’abord envoyés dans un brouillon, leurs tailles et leurs digest SHA-256 GitHub sont comparés au build local, puis la release est publiée. Relancer la même exécution reprend les fichiers manquants d’un brouillon. Un fichier différent, un tag déjà occupé ou une release publique incomplète provoque un arrêt sans écrasement. Une release publique existante dont les empreintes correspondent est conservée. Les anciennes releases v8.18 et v8.16.2 restent disponibles.

Seul le job de publication reçoit `contents: write`; les contrôles disposent de lectures du dépôt et des exécutions Actions. Aucun secret personnel GitHub ou Mozilla n’est nécessaire.
