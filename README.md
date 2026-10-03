# Kitty Download Manager V8.27 — Windows x64, version de test

Cette distribution ajoute un installateur Windows à la base V8.24. Elle est
destinée à Windows 10/11 x64 et à Firefox. L’installation ne nécessite ni Python
préinstallé ni droits administrateur. Une connexion Internet est nécessaire.

## Installation

1. Extraire `kitty-download-manager-v8.27-windows-x64.zip`.
2. Ouvrir le dossier `kitty-download-manager`, puis double-cliquer sur `Install.cmd`.
3. Attendre les téléchargements et les vérifications. En cas d’erreur, le message
   reste visible dans la fenêtre; ne pas considérer l’installation comme réussie.
4. Dans Firefox, ouvrir `about:debugging#/runtime/this-firefox`, choisir
   **Charger un module complémentaire temporaire**, puis sélectionner :
   `%LOCALAPPDATA%\KittyDownloadManager\extension\manifest.json`.

Le backend, Python, yt-dlp, Mutagen, psutil, FFmpeg/ffprobe et Deno sont installés
dans **un seul dossier** : `%LOCALAPPDATA%\KittyDownloadManager`.
Les réglages et l’historique sont dans ses sous-dossiers `config` et `cache`.
Le dossier de téléchargement Windows peut avoir été déplacé : Kitty utilise
l’emplacement fourni par Windows et propose ensuite son sous-dossier
`kitty-download-manager`. Le dossier reste configurable dans la popup.

Les scripts Bash et le moteur de migration Linux présents dans les sources
servent aux tests de compatibilité du projet; l’installateur Windows ne les
exécute pas.

### Commande complète — PowerShell sur Windows

Cette commande réutilise le même dossier d’extraction dans Téléchargements.
Elle remplace les sources extraites, pas le dossier installé ni les réglages.

```powershell
$downloads = (New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path
Set-Location -LiteralPath $downloads
$zip = 'kitty-download-manager-v8.27-windows-x64.zip'
if (-not (Test-Path -LiteralPath $zip -PathType Leaf)) { throw 'Archive absente de Téléchargements.' }
if (Test-Path -LiteralPath '.\kitty-download-manager') { Remove-Item -LiteralPath '.\kitty-download-manager' -Recurse -Force }
Expand-Archive -LiteralPath $zip -DestinationPath '.' -Force
& '.\kitty-download-manager\Install.cmd'
```

## Extension Firefox permanente

Le fichier `kitty-download-manager-v8.27-unsigned.xpi` est fourni pour la
soumission à Mozilla. **Il n’est pas signé** : Firefox standard ne permet pas
son installation permanente en l’état. Le chargement temporaire ci-dessus
fonctionne pour les essais, mais doit être refait après un redémarrage de Firefox.

Pour distribuer l’extension durablement, soumettre ce XPI sur le portail
développeur Mozilla en distribution **non répertoriée**, puis utiliser le XPI
signé qu’il retourne. La signature nécessite le compte Mozilla du propriétaire;
aucun identifiant ni secret de signature n’est inclus dans ce paquet.

Avant une première soumission AMO, compléter aussi la déclaration
`browser_specific_settings.gecko.data_collection_permissions` selon le périmètre
retenu pour l’extension et son backend natif. Elle est requise pour les nouvelles
extensions. Le manifeste de cette version de test n’est donc pas présenté comme
un paquet déjà prêt à être publié sur AMO.

Procédure officielle :
https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/
https://extensionworkshop.com/documentation/develop/firefox-builtin-data-consent/

## Mise à jour et réparation

Relancer `Install.cmd` depuis une nouvelle distribution Windows. Les dépendances
sont préparées et vérifiées avant la bascule; les réglages et l’historique sont
conservés. Le worker actif reçoit une demande d’arrêt et garde ses fichiers
partiels. La file est mise en pause; la reprendre depuis Kitty après avoir
rechargé l’extension. Un backend qui ne s’arrête pas bloque la mise à jour.

Les exécutables d’une version précédente restent dans `versions` pour éviter
de supprimer une version encore utilisée par Firefox. Toutes ces versions
restent dans le même dossier Kitty. Les téléchargements terminés sont conservés.

La popup recherche les assets GitHub nommés
`kitty-download-manager-v<VERSION>-windows-x64.zip` sous Windows. Une archive
Linux portant seulement `kitty-download-manager-v<VERSION>.zip` n’est pas
sélectionnée par le backend Windows. Le bouton télécharge l’archive vérifiée;
il faut encore l’extraire et lancer l’installateur.

## Désinstallation

Utiliser **Applications installées → Kitty Download Manager → Désinstaller**,
ou `%LOCALAPPDATA%\KittyDownloadManager\Uninstall.cmd`.

La désinstallation arrête le worker, retire l’enregistrement Firefox et le
backend. **Réglages, historique et téléchargements sont conservés**. Un helper
attend la fin du processus avant d’effacer les exécutables, car Windows peut
verrouiller les fichiers d’un programme en cours d’exécution.

## Validation et limites

Les vérifications exécutées ici sont détaillées dans `tests/VALIDATION-WINDOWS.txt`.
Les tests portables et les régressions sur Linux passent. Aucun vrai système
Windows ni PowerShell n’est disponible dans cet environnement; l’installation,
les API Win32, le sélecteur de dossier et Firefox Windows restent à valider.
Cette distribution est donc une **version de test**, pas une release Windows
déclarée stable.

La validation automatisée Windows est préparée dans
`.github/workflows/windows-validation.yml`. Elle couvre les vrais verrous
interprocessus, le protocole binaire, l’annulation, l’arrêt, la survie du worker
après fermeture du job parent, puis l’installation complète, la mise à jour,
le remux audio et la désinstallation.

Le premier passage GitHub Actions de la V8.25 a réussi 26 tests Windows,
ignoré les 2 simulations POSIX, puis échoué sur le lancement des workers dans
les 2 tests d’annulation et d’arrêt (`WinError 5`). La V8.26 a préparé un Job
intermédiaire autorisant leur détachement depuis le contexte du runner.

Le passage V8.26 a atteint l’installation complète : Python privé, yt-dlp,
FFmpeg, Deno et le protocole natif direct ont été vérifiés. Le remux WebM vers
Opus a réussi. Les vérifications via le lanceur batch ont échoué car le test
suréchappait les guillemets pour CMD. La désinstallation échouait en supprimant
deux fois une clé HKCU partagée entre les vues 32 et 64 bits du registre.

La V8.27 lance le batch par son nom fixe depuis son dossier, corrige la
suppression des vues partagées et vérifie que les fichiers de runtime sont
réellement effacés après la sortie du désinstalleur. Les refus d’accès restent
bloquants et provoquent la restauration du registre. La sortie de l’installateur
est en UTF-8 et la CI affiche une trace complète sur erreur.

Le workflow V8.27 doit encore être relancé sur un vrai Windows; les résultats
Linux locaux ne valident pas à eux seuls l’installation Windows ni Firefox.

```powershell
python -m pip install psutil
python tests/test-windows-port.py
```

`tests/test-installed-windows.py` est réservé à une installation CI neuve : il
désinstalle Kitty à la fin et exige explicitement `KITTY_INSTALLED_TEST=1`.

## Références techniques vérifiées le 3 octobre 2026

- Firefox Native Messaging, registre et survie des sous-processus :
  https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_messaging
- Emplacement du manifeste Windows :
  https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests
- Python embarqué 3.13.16 et SHA-256 officiel :
  https://www.python.org/ftp/python/3.13.16/windows-3.13.16.json
- Création de processus et arrêt sous Windows :
  https://docs.python.org/3/library/subprocess.html
- Verrous Windows : https://docs.python.org/3/library/msvcrt.html
- Jobs Windows et propriété des sous-processus :
  https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- Dossier Téléchargements Windows :
  https://learn.microsoft.com/en-us/windows/win32/shell/knownfolderid
