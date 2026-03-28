# Changelog — Meteole QGIS Plugin

## [1.2.0] — 2026-03-28

### Nouvelles fonctionnalités
- **Interface guidée en 3 étapes** : Territoire → Variable → Options & Chargement
- **Sélection visuelle du territoire** par cartes cliquables (France métropole + 5 territoires OM)
- **Support complet AROME Outre-Mer** via l'API DPPaquetAROME-OM :
  - Antilles (Guadeloupe / Martinique)
  - Guyane française
  - Réunion / Mayotte (Océan Indien)
  - Nouvelle-Calédonie
  - Polynésie française
- **Variables individualisées** : chaque variable GRIB2 exposée avec son nom français complet (ex. "Température 2m (K)", "Précipitations totales (accumulées)")
- **Dictionnaire GRIB_VAR_INFO** : 80+ variables AROME-OM reconnues et labellisées
- **Décodage GRIB2 robuste** via cfgrib avec normalisation longitude 0-360 → -180/+180
- **Onglet Horizons** : navigateur temporel slider pour basculer entre les horizons chargés
- **Option couche points** : désactivée par défaut, activable pour interroger des valeurs exactes
- **Reset automatique** : remise à zéro à la fermeture et au changement de territoire
- **Dialog non-modal** : QGIS reste utilisable pendant les téléchargements

### Corrections
- Fix normalisation longitude GRIB2 (données correctement positionnées en outremer)
- Fix décodage cfgrib multi-dimensions (step, time, level) sans perte de données
- Fix variables "unknown" : tentative d'identification via attributs GRIB (paramId)
- Fix timeout téléchargement GRIB2 : lecture par chunks 64Ko, timeout (10, 300)s
- Fix fallback run précédent (−6h) si H+0 non disponible sur l'API OM
- Fix fenêtre popup Qt5/Windows parasite (remplacement QComboBox/QSpinBox/QDateTimeEdit par widgets sans popup)

### Améliorations UX
- Labels onglets raccourcis pour éviter la troncature
- Options avancées (zone géographique, niveaux) pliables par défaut
- Note explicative sur les niveaux verticaux en mode outremer (SP/IP/HP)
- Journal plugin enrichi : contenu GRIB2, variables disponibles, variables manquantes
- Résumé de la sélection affiché en haut de la page Options

---

## [1.1.0] — 2025-12

### Nouvelles fonctionnalités
- Support initial AROME Outre-Mer (Antilles, Guyane, Réunion, Nouvelle-Calédonie, Polynésie)
- Sélecteur de territoire avec bbox automatique
- Navigateur temporel multi-horizons
- Onglet Vigilance Météo-France avec tableau des phénomènes

### Corrections
- Précision bbox par territoire (0.01 métropole, 0.025 outremer)
- Fix MODEL_NAME par territoire OM

---

## [1.0.0] — 2025

- Version initiale
- Support AROME, AROME-PI, AROME-PE, ARPEGE, PIAF (métropole)
- Authentification token / api_key / application_id
- Couches raster GeoTIFF et points GeoPackage
- Bulletins de vigilance
