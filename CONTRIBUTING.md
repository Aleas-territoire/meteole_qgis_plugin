# Guide de contribution — meteole_qgis_plugin

Merci de l'intérêt porté à ce plugin ! Ce document explique comment contribuer efficacement.

---

## Prérequis

- **QGIS** ≥ 3.16
- **Python** ≥ 3.9 (inclus dans QGIS)
- La librairie [`meteole`](https://github.com/MAIF/meteole) (v0.2.x)
- Un compte sur [portail-api.meteofrance.fr](https://portail-api.meteofrance.fr) avec au moins un abonnement actif (AROME ou ARPEGE)

---

## Installation pour le développement

1. Clonez ce dépôt dans le dossier de plugins QGIS :
```
   # Windows
   %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\

   # Linux
   ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/

   # macOS
   ~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/
```

2. Installez `meteole` dans l'interpréteur Python de QGIS :
```
   python -m pip install meteole==0.2.*
```

3. Rechargez QGIS ou utilisez le plugin **Plugin Reloader** pour recharger sans redémarrer.

---

## Signaler un bug

Avant d'ouvrir une issue, vérifiez :
- que votre token n'est pas expiré (durée de vie : 1 heure — le régénérer sur le portail)
- que votre compte est bien abonné à l'API concernée (chaque modèle requiert un abonnement séparé)
- que vous utilisez une version de `meteole` compatible (v0.2.x)

Dans votre issue, précisez :
- la version de QGIS (`À propos de QGIS`)
- la version de `meteole` (`pip show meteole`)
- le modèle et l'indicateur utilisés
- le message d'erreur complet (journal des messages QGIS)

---

## Proposer une modification

1. Ouvrez d'abord une **issue** pour discuter de la modification envisagée
2. Forkez le dépôt et créez une branche dédiée (`fix/nom-du-bug` ou `feat/nom-feature`)
3. Faites des commits atomiques avec des messages clairs
4. Ouvrez une **Pull Request** en référençant l'issue correspondante

---

## Conventions de code

- Python 3, compatible avec l'interpréteur QGIS embarqué
- Commentaires et messages utilisateur en **français**
- Noms de variables et fonctions en **anglais**
- Pas de dépendances supplémentaires sans discussion préalable (`gdal`, `numpy`, `sqlite3` sont déjà disponibles dans QGIS)
- Toute modification de `worker.py` doit rester **thread-safe** : ce fichier s'exécute dans un `QgsTask`, jamais dans le thread principal
- Les fichiers GeoPackage sont écrits avec **sqlite3 pur** (sans `QgsVectorFileWriter`) — ne pas modifier ce choix sans test sur Windows, Linux et macOS

---

## Structure du projet
```
meteole_qgis/
├── __init__.py          # Point d'entrée QGIS
├── plugin.py            # Classe principale du plugin
├── dialog.py            # Interface graphique (QDialog)
├── worker.py            # Tâches asynchrones (QgsTask)
├── layer_utils.py       # Création des couches QGIS
├── departements.geojson # Géométries des départements français
├── metadata.txt         # Métadonnées QGIS
└── docs/screenshots/    # Captures d'écran
```

---

## Compatibilité meteole

`meteole` est une bibliothèque en développement actif. En cas de changement d'API :
- Documentez la version de `meteole` concernée dans votre PR
- Consultez le `CHANGELOG.md` pour le suivi des adaptations déjà réalisées
- Le patch `_patch_client()` dans `worker.py` gère les incompatibilités de renouvellement de token — signalez toute régression

---

## Ressources utiles

- Documentation de l'API Météo-France : [portail-api.meteofrance.fr](https://portail-api.meteofrance.fr)
- Librairie meteole : [github.com/MAIF/meteole](https://github.com/MAIF/meteole)
- Documentation QGIS pour les plugins : [docs.qgis.org](https://docs.qgis.org/latest/fr/docs/pyqgis_developer_cookbook/)

---

## Licence

En contribuant, vous acceptez que votre code soit distribué sous la licence **MIT** du projet (voir `LICENSE`).
