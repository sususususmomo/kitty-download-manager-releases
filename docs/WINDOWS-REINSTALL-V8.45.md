# Backend 8.45 — réinstallation Windows et WinError 5

L’erreur fournie survient après la vérification du protocole Firefox, au renommage du dossier `stage-…` vers `versions/8.44-…`. Le journal ne permet pas d’identifier le processus ou la règle de permissions responsable du refus. Il confirme l’opération qui échoue.

Le nouvel installeur prépare Python, ses paquets, FFmpeg, Deno et le backend dans un dossier de version unique, à son emplacement définitif sur le disque choisi. Ce dossier reste inactif tant que le protocole Firefox n’est pas validé. Le lancement du backend bascule ensuite par la transaction existante. Aucun renommage du dossier contenant les exécutables n’est nécessaire.

Les anciens appelants utilisant `stage-…` restent compatibles : le contenu est copié vers une nouvelle version, puis validé, sans déplacement du dossier source. Le point d’entrée PowerShell prépare directement le dossier définitif et évite cette copie supplémentaire. Après réussite, son nettoyage conserve explicitement le nouveau dossier actif. Sur échec de validation ou d’enregistrement, le lanceur, l’extension et le registre précédents sont restaurés. Les anciennes versions restent disponibles ; réglages, historique, cookies et médias sont conservés. La file reste en pause après maintenance.

Une version déjà active ne peut pas être utilisée comme dossier de préparation. Les chemins de version doivent rester sous le dossier Kitty, correspondre à la version source et ne contenir ni lien ni jonction.

## Validation locale

| Suite | Résultat |
| --- | --- |
| Dossier choisi, migration, activation différée et rollback | 12 réussis |
| Installation/processus portables | 30 réussis, 5 natifs Windows ignorés |
| Packaging et installation Linux | 3 réussis |

Les nouveaux cas vérifient la publication sans déplacement du dossier, la conservation de l’ancienne installation jusqu’à validation, le refus de préparer dans le runtime actif et le nettoyage d’une copie partielle. La suite native Windows ajoute un fichier ouvert avec partage de lecture/écriture sans partage de suppression, vérifie que Windows refuse le renommage et vérifie la publication avec ce verrou. Le smoke test d’installation Windows effectue désormais la mise à jour depuis un dossier de version définitif.

PowerShell 5.1, les handles Win32 et l’installation réelle Windows ne peuvent pas être exécutés depuis l’environnement Linux courant. Ces tests sont intégrés au workflow Windows, sans prétendre qu’il a été exécuté ici.

Référence Microsoft : [CreateFileW, règles de partage et accès de renommage](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew). L’absence de partage de suppression peut empêcher un renommage ; ceci explique la classe de problème, sans identifier le verrou exact du poste signalé.

## Installation

Extraire la nouvelle archive dans un dossier distinct, fermer Firefox, puis lancer `Install.cmd`. Conserver le dossier proposé `E:\download\Kitty-Download-Manager`. Après le message de réussite, rouvrir Firefox et vérifier la connexion dans Kitty. L’extension reste en version 8.52 et conserve les corrections de sélection des sites et des titres introduites avec le backend 8.44.
