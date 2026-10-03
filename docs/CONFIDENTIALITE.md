# Confidentialité — Kitty Download Manager

Kitty Download Manager est une extension Firefox reliée à un backend installé sur votre ordinateur.

L’extension recherche les médias dans les pages affichées pour son bouton flottant. Quand vous demandez un téléchargement depuis la popup, le bouton flottant ou le menu contextuel, elle transmet l’URL choisie, le format et l’action demandée au backend local par Native Messaging. Le backend contacte ensuite les sites concernés pour obtenir les métadonnées et télécharger les médias. Les URLs peuvent contenir des informations personnelles que vous avez incluses dans l’adresse.

Les préférences de l’interface sont conservées dans le stockage local de Firefox. Le backend conserve ses réglages, sa file, son historique, ses fichiers temporaires et ses journaux sur votre ordinateur. L’historique contient les informations des téléchargements Kitty : notamment URLs, titres, états et chemins des fichiers. Kitty ne lit pas l’historique général de navigation de Firefox et n’envoie pas d’analyses d’usage ou de télémétrie à son développeur.

Le bouton Télécharger du backend ouvre un téléchargement public sur GitHub. L’installation Windows/macOS récupère les dépendances nécessaires auprès de leurs fournisseurs. Les fonctions de vérification des mises à jour interrogent les fournisseurs concernés. Ces services et les sites de médias reçoivent les informations habituelles d’une requête réseau, dont l’adresse IP, et appliquent leurs propres politiques de confidentialité.

La connexion YouTube est facultative et utilise un profil Firefox distinct destiné à Kitty. Si vous la configurez et l’activez, les informations de session sont conservées localement et utilisées par le backend pour les téléchargements YouTube demandés. Kitty ne lit pas les cookies de votre profil Firefox habituel. Vous pouvez désactiver ou supprimer cette session dans les réglages.

La copie du diagnostic dans le presse-papiers est déclenchée par votre action. Le diagnostic peut inclure les chemins et les détails de votre installation; vous choisissez ensuite où le partager.

L’historique peut être effacé depuis Kitty. La suppression du backend conserve les données locales par défaut, afin de permettre une réinstallation sans perdre les réglages ou l’historique.
