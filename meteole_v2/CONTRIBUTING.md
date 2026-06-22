# Contribuer au plugin Meteole QGIS

Merci de votre intérêt pour ce projet !

## Signaler un bug

Ouvrez une [Issue](https://github.com/Aleas-territoire/meteole_qgis_plugin/issues) en précisant :
- Version de QGIS
- Territoire concerné (métropole, Antilles, etc.)
- Message d'erreur complet (copier depuis l'onglet Journal du plugin)

## Proposer une amélioration

1. Forkez le dépôt
2. Créez une branche : `git checkout -b feature/ma-fonctionnalite`
3. Committez vos modifications : `git commit -m "Ajout de..."`
4. Poussez la branche : `git push origin feature/ma-fonctionnalite`
5. Ouvrez une Pull Request

## Structure du code

| Fichier | Rôle |
|---|---|
| `dialog.py` | Interface utilisateur (wizard 3 étapes) |
| `worker.py` | Tâches asynchrones QGIS (téléchargement, décodage) |
| `arome_om.py` | Client API DPPaquetAROME-OM + décodage GRIB2 |
| `layer_utils.py` | Création couches QGIS (GeoTIFF, GeoPackage) |
| `plugin.py` | Point d'entrée QGIS |

## Dépendances

```
pip install meteole cfgrib eccodes
```
