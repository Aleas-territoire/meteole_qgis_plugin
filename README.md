# Meteole v2 : plugin QGIS Météo-France

[![QGIS](https://img.shields.io/badge/QGIS-3.16%2B-589632)](https://qgis.org)
[![Version](https://img.shields.io/badge/version-1.4.1-blue)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Accès direct aux données météorologiques **Météo-France** dans QGIS : modèles
**AROME**, **AROME-PI**, **AROME-PE**, **ARPEGE**, **PIAF**, **AROME Outre-Mer**
et **Vigilance**, via la bibliothèque Python
[`meteole`](https://github.com/MAIF/meteole).

Le code du plugin se trouve dans le dossier [`meteole_v2/`](meteole_v2/) : c'est
ce dossier qui constitue l'extension installable dans QGIS.

---

## Nouveautés

### v1.4.1 (précipitations et pas de temps)

| Domaine | Apport |
|---|---|
| Période de cumul | Menu déroulant pour les variables cumulées (précipitations, neige), alimenté dynamiquement par l'API, avec défaut PT1H (cumul horaire) au lieu du cumul 24 h imposé. Résout l'impossibilité d'obtenir des échéances inférieures à 24 h. |
| Échéances | Menu déroulant au pas de temps réel de chaque modèle : 15 min pour AROME-PI, 5 min pour PIAF, horaire pour AROME et ARPEGE. Multi-sélection (une couche par échéance). |
| Lisibilité | Aide dynamique expliquant le lien période de cumul / échéance ; fenêtre de cumul inscrite dans le nom de couche (par exemple « ... cumul 1 h »). |
| Robustesse | Chargement par `coverage_id` (fin de l'erreur « Indicateur invalide » sur AROME-PI), lecture des échéances sans re-télécharger le GetCapabilities, cache de session, et nouvelle tentative automatique si le GetCapabilities est tronqué. |

### v2 (base)

| Domaine | Apport |
|---|---|
| Traduction | Variables métropole et Outre-Mer affichées en français |
| Variables | Listes recentrées sur l'essentiel (températures, vent, humidité, précipitations, pression, nébulosité, variables d'orages CAPE/CIN, grêle), avec une case « Afficher toutes les variables » |
| Unités | Conversion automatique à l'import : K vers °C, Pa vers hPa, m/s vers km/h, kg/m² vers mm, kg/kg vers g/kg |
| Découpe | Extraction du raster sur l'emprise ou sur la géométrie réelle d'une couche vectorielle (cutline GDAL) |
| Vigilance | Détail des aléas par département (vent, orages, pluie-inondation, canicule), avec colonnes dédiées, infobulle et synthèse nationale |

Historique complet dans le [CHANGELOG](CHANGELOG.md).

---

## Installation

### Depuis le ZIP de release (recommandé)

1. Télécharger `meteole_v2.zip` depuis la page
   [Releases](https://github.com/Aleas-territoire/meteole_qgis_plugin/releases).
2. Dans QGIS : Extensions, puis Installer/Gérer les extensions, puis
   Installer depuis un ZIP.
3. Sélectionner le fichier, puis activer « Meteole v2 ».

### Depuis les sources (développement)

```bash
git clone https://github.com/Aleas-territoire/meteole_qgis_plugin.git
cd meteole_qgis_plugin
# Lien symbolique du dossier plugin vers le profil QGIS (Linux/macOS)
ln -s "$(pwd)/meteole_v2" \
  ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/meteole_v2
```

Sous Windows, copier le dossier `meteole_v2` dans :
`%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`

---

## Dépendances Python

Le plugin s'appuie sur des paquets installés dans l'environnement Python de QGIS.
Il tente de les installer automatiquement au premier lancement ; en cas d'échec,
installez-les manuellement (OSGeo4W Shell sous Windows, Terminal sous macOS avec
le Python embarqué de QGIS) :

```bash
pip install meteole cfgrib
```

* [`meteole`](https://pypi.org/project/meteole/) : client de l'API Météo-France
* `cfgrib` : décodage GRIB2, nécessaire uniquement pour l'Outre-Mer

Une **clé API Météo-France** est requise (mode api_key, token ou application_id),
à créer sur le [portail API Météo-France](https://portail-api.meteofrance.fr/).
Une même clé fonctionne pour tous les modèles auxquels l'application est abonnée.

---

## Utilisation

Le plugin guide la saisie en trois étapes.

1. **Type et territoire.** Choisir la France métropolitaine ou un territoire
   d'Outre-Mer (Antilles, Guyane, Réunion/Mayotte, Nouvelle-Calédonie,
   Polynésie).
2. **Variable.** Sélectionner un modèle (AROME par défaut), cliquer sur
   « Lister les indicateurs », puis choisir une variable. Pour les variables
   cumulées (précipitations), choisir la période de cumul, puis une ou
   plusieurs échéances. Pour les variables instantanées (température, vent,
   pression), seules les échéances sont proposées.
3. **Options et chargement.** Régler éventuellement l'emprise (canevas ou
   géométrie d'une couche vectorielle) et les niveaux, puis lancer le
   chargement. Le raster GeoTIFF (et, en option, une couche de points) est
   ajouté au projet, avec conversion des unités et découpe éventuelle.

Deux notions à distinguer pour les précipitations :

* la **période de cumul** est la largeur de la fenêtre d'accumulation (par
  exemple 1 h) ;
* l'**échéance** est l'instant de fin de cette fenêtre. Une fenêtre de 3 h ne
  peut donc pas se terminer avant l'échéance 3 h.

L'onglet **Vigilance** ajoute la carte des départements colorée par niveau, avec
le détail des aléas. L'onglet **Horizons** permet de naviguer entre les
échéances chargées.

---

## Architecture (modules clés)

| Fichier | Rôle |
|---|---|
| `plugin.py`, `__init__.py` | Point d'entrée QGIS |
| `dialog.py` | Interface guidée (Territoire, Variable, Options) |
| `worker.py` | Récupération des données en tâche de fond (QgsTask) |
| `layer_utils.py` | Création des couches raster/points, styles, découpe |
| `arome_om.py` | Client AROME Outre-Mer (REST et GRIB2) |
| `meteo_vars.py` | Conversions d'unités, traduction, filtres de variables |
| `vigilance_utils.py` | Analyse des aléas de vigilance par département |

---

## Construire le ZIP de release

```bash
./build_zip.sh           # produit dist/meteole_v2.zip
```

Un workflow GitHub Actions
([`.github/workflows/release.yml`](.github/workflows/release.yml)) construit et
publie automatiquement le ZIP lorsqu'un tag `v*` est poussé.

---

## Licence

MIT : voir [LICENSE](LICENSE). Les données restent soumises aux conditions
d'utilisation de Météo-France.
