# Meteole v2 — Plugin QGIS Météo-France

[![QGIS](https://img.shields.io/badge/QGIS-3.16%2B-589632)](https://qgis.org)
[![Version](https://img.shields.io/badge/version-1.4.0-blue)](CHANGELOG.md)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Accès direct aux données météorologiques **Météo-France** dans QGIS — modèles
**AROME**, **ARPEGE**, **PIAF**, **AROME Outre-Mer** et **Vigilance** — via la
librairie Python [`meteole`](https://github.com/MAIF/meteole).

> **v2** : variables traduites en français, listes recentrées sur l'essentiel,
> conversion automatique des unités, découpe du raster sur une couche
> vectorielle, et détail des aléas de vigilance. Voir le [CHANGELOG](CHANGELOG.md).

Le code du plugin se trouve dans le dossier [`meteole_v2/`](meteole_v2/) ; c'est
ce dossier qui constitue l'extension installable dans QGIS.

---

## Nouveautés de la v2

| Domaine | Apport |
|---|---|
| 🇫🇷 Traduction | Variables métropole et Outre-Mer affichées en français |
| 🎯 Variables | Listes recentrées sur l'essentiel (températures, vent, humidité, précipitations, pression, nébulosité, orages : CAPE/CIN, grêle) + case « Afficher toutes les variables » |
| 🌡➡️ Unités | Conversion automatique à l'import : K → °C, Pa → hPa, m/s → km/h, kg/m² → mm, kg/kg → g/kg… |
| ✂️ Découpe | Extraction du raster sur l'**emprise** ou sur la **géométrie** réelle d'une couche vectorielle (cutline GDAL) |
| ⚠️ Vigilance | Détail des **aléas** par département (vent, orages, pluie-inondation, canicule…) : colonnes dédiées, infobulle, synthèse nationale |

---

## Installation

### Depuis le ZIP de release (recommandé)

1. Télécharger `meteole_v2.zip` depuis la page
   [Releases](https://github.com/Aleas-territoire/meteole_qgis_plugin/releases).
2. Dans QGIS : **Extensions → Installer/Gérer les extensions → Installer depuis un ZIP**.
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
installez-les manuellement (OSGeo4W Shell sous Windows) :

```bash
pip install meteole cfgrib
```

- [`meteole`](https://pypi.org/project/meteole/) — client API Météo-France
- `cfgrib` — décodage GRIB2 (nécessaire pour l'Outre-Mer)

Une **clé API Météo-France** est requise (token / api_key / application_id),
à créer sur le [portail API Météo-France](https://portail-api.meteofrance.fr/).

---

## Architecture (modules clés)

| Fichier | Rôle |
|---|---|
| `plugin.py` / `__init__.py` | Point d'entrée QGIS |
| `dialog.py` | Interface guidée (Territoire → Variable → Options) |
| `worker.py` | Récupération des données en thread (QgsTask) |
| `layer_utils.py` | Création raster GeoTIFF / points, styles, découpe |
| `arome_om.py` | Client AROME Outre-Mer (REST + GRIB2) |
| `meteo_vars.py` | **v2** — conversions d'unités, traduction, filtres de variables |
| `vigilance_utils.py` | **v2** — analyse des aléas de vigilance par département |

---

## Construire le ZIP de release

```bash
./build_zip.sh           # produit dist/meteole_v2.zip
```

Un workflow GitHub Actions ([`.github/workflows/release.yml`](.github/workflows/release.yml))
construit et publie automatiquement le ZIP lorsqu'un tag `v*` est poussé.

---

## Licence

MIT — voir [LICENSE](LICENSE). Les données restent soumises aux conditions
d'utilisation de Météo-France.
