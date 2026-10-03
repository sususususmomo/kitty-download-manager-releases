L’interface Firefox de Kitty, compatible avec le **backend v8.31 / protocole natif 1**. Ses versions évoluent indépendamment du backend; cette release ne remplace pas la release backend « Latest ».

- Ouverture optimisée : l’état de la file et la compatibilité du backend sont demandés en parallèle, tout en conservant la restauration des préférences et la protection contre les flashs d’affichage.
- Réglages repliables : Langue, Dossier de destination, Pill flottant, Backend Kitty, Cookies, Dépendances, Diagnostic, Maintenance.
- Parcours d’installation du backend adapté à Linux, Windows et macOS, avec détection automatique après installation.
- Actions backend adaptées à l’état de la connexion et aux mises à jour, sans doublon avec Dépendances ou Diagnostic.
- Icônes de langue et de dossier, statut backend vert après vérification réussie de la connexion et de la version.

Fichiers :

- `kitty-download-manager-v8.36-unsigned.xpi` : extension seule, destinée à la soumission Mozilla. **Non signé**; une installation permanente dans Firefox standard attend la signature Mozilla.
- `kitty-download-manager-v8.36.zip` : sources complètes, extension, XPI et scripts d’installation, dans un seul dossier `kitty-download-manager`.
- `validation-frontend-v8.36.json` : versions, résultats et liens des contrôles effectués.
- `SHA256SUMS` : empreintes des trois fichiers précédents.

Test temporaire : Firefox → `about:debugging` → Ce Firefox → Charger un module temporaire → `extension/manifest.json`.

Commande fish complète pour l’archive de sources, dans le dossier habituel :

```fish
cd ~/Downloads
and unzip -o kitty-download-manager-v8.36.zip
and cd kitty-download-manager
and chmod +x install.sh
and ./install.sh
```

Recharger ensuite l’extension temporaire dans `about:debugging`. La décompression conserve les médias déjà présents.

Validation : [Windows](https://github.com/sususususmomo/kitty-download-manager-releases/actions/runs/37160431577), [Mac Intel et Apple Silicon](https://github.com/sususususmomo/kitty-download-manager-releases/actions/runs/37160431505), [liens des installateurs et validateur Mozilla](https://github.com/sususususmomo/kitty-download-manager-releases/actions/runs/37160431683). Dix-neuf captures de la popup Firefox sur chacun de ces trois environnements; régression Linux réussie. Mozilla lint : 0 erreur, 0 notice, 13 avertissements documentés pour la revue. Les tests ne couvrent pas les téléchargements de médias en ligne ni l’authentification YouTube. La publication sur Mozilla Add-ons et la signature restent à effectuer.
