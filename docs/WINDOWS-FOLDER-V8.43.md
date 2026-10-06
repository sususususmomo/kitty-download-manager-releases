# Backend Windows 8.43 : dossier choisi

Base : archive frontend 8.51 / backend 8.42. Frontend conservé en 8.51, backend porté à 8.43.

Le lancement Install.cmd demande un chemin absolu. Install.ps1 accepte aussi -InstallDir et -NonInteractive. L’emplacement enregistré dans la vue 64 bits du registre est proposé pour les relances. Stage, bootstrap, TEMP et TMP restent sur le disque choisi. Contrôle d’espace libre : 2 Gio avant les téléchargements.

app_paths.py déduit la racine des dossiers stage/backend et versions/VERSION-ID/backend : validation, worker, métadonnées et désinstalleur utilisent le même dossier de configuration/cache. Les scripts exécutés depuis les sources peuvent retrouver l’emplacement enregistré.

Le changement de dossier copie configuration et cache après mise en pause de l’ancienne installation. Les marqueurs de maintenance, verrous et contrôles de processus ne sont pas transférés. L’ancien dossier reste conservé. La publication du backend et du registre est transactionnelle, avec suppression des copies de données si elle échoue.

Validation exécutée sous Linux : 9 tests nouveaux réussis ; 28 contrôles portables Windows réussis, 4 tests natifs ignorés ; 3 tests de packaging réussis ; 95 contrôles de régression réussis, 5 contrôles Chromium ignorés. Journaux : validation/windows-folder/.

La CI Windows a été adaptée pour tester la validation PowerShell et une installation hors LOCALAPPDATA avec espaces et caractères spéciaux, puis la mise à jour et la désinstallation. Ces vérifications natives restent à lancer : aucune exécution Windows n’est revendiquée ici. Les téléchargements Internet des dépendances n’ont pas été exécutés dans cet environnement.

Fichiers : Install.cmd, Install.ps1, app_paths.py, windows_install.py ; métadonnées/versions backend ; README-Windows.md ; tests/test-windows-install-location.py et test-windows-installer.ps1 ; workflow Windows ; outils de packaging et installation CI.
