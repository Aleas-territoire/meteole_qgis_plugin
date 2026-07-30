# Changelog — Meteole QGIS Plugin

## [1.3.0] — 2026-06

### Nouvelles fonctionnalités
- **Traduction française des variables** : les indicateurs métropole (noms WCS
  bruts comme `TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND`) sont désormais
  affichés en français (« Température (au-dessus du sol) »). Le nom brut est
  conservé en interne pour l'appel API.
- **Listes de variables recentrées** : par défaut, seules les variables les plus
  utiles sont proposées (températures de surface et au-dessus du sol, vent,
  humidité, précipitations, pression, nébulosité, variables d'orages CAPE/CIN,
  grêle). Une case **« Afficher toutes les variables »** rétablit la liste
  complète (niveaux de pression isobares IP/HP, flux, rayonnements…).
- **Conversion automatique des unités à l'import** vers des unités lisibles par
  un public français :
  - Kelvin → °C
  - Pascal → hectopascal (hPa)
  - m/s → km/h
  - kg/m² → mm (lame d'eau), kg/m²/s → mm/h
  - kg/kg → g/kg, fraction m³/m³ → %, J/m² → Wh/m²
  L'unité affichée dans le nom de couche et la légende suit la conversion.
- **Extraction / recadrage selon l'emprise d'une couche vectorielle** : nouveau
  sélecteur de couche vecteur dans « Zone géographique », en complément de
  l'emprise du canevas. Le raster est restreint à l'emprise choisie
  (sous-échantillonnage serveur côté métropole, recadrage côté client en
  Outre-Mer).

### Architecture
- Nouveau module `meteo_vars.py` : source unique de vérité pour la sémantique
  des variables (conversions d'unités, traduction française, filtres de
  variables significatives), partagé par la métropole et l'Outre-Mer.

---

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

## [1.3.1] — 2026-06

### Améliorations
- **Découpe du raster sur la géométrie réelle de la couche vectorielle** (et non
  plus seulement sur son emprise rectangulaire), via une cutline GDAL
  (`gdal.Warp` avec `cropToCutline`). Les pixels hors des polygones deviennent
  transparents (NODATA). Case « Découper le raster sur la géométrie de la
  couche » (activée par défaut) pour basculer entre découpe géométrique et
  recadrage rectangulaire.

## [1.4.0] — 2026-06

### Améliorations — Vigilance
- **Détail des aléas** : la fonction Vigilance indique désormais quel(s)
  phénomène(s) explique(nt) la vigilance de chaque département (vent violent,
  pluie-inondation, orages, inondation, neige-verglas, canicule, grand froid,
  avalanches, vagues-submersion) avec leur couleur respective.
- La couche « Vigilance par département » porte une colonne par aléa, l'aléa
  dominant (« alea_max ») et un résumé textuel (« aleas ») ; une infobulle au
  survol et un champ d'affichage exposent ces aléas directement sur la carte.
- Le panneau Vigilance affiche une synthèse nationale par aléa (niveau max,
  nombre de départements concernés) et la liste des départements en vigilance
  orange / rouge avec leurs aléas.

### Architecture
- Nouveau module `vigilance_utils.py` (sans dépendance QGIS) : analyse de la
  carte de vigilance par département et par aléa.

## [1.4.1] — 2026-07

### Améliorations — Précipitations & pas de temps
- **Sélection de la période de cumul** pour les variables cumulées, peuplée
  dynamiquement depuis l'API, avec **défaut PT1H** (cumul horaire) au lieu du
  cumul 24 h imposé. Résout l'impossibilité d'obtenir des échéances < 24 h.
- **Menu déroulant des échéances** au pas de temps réel du modèle (15 min pour
  AROME-PI, 5 min pour PIAF, horaire pour AROME/ARPEGE) ; multi-sélection.
- Aide dynamique expliquant le lien période de cumul ↔ échéance.
- Fenêtre de cumul inscrite dans le nom de couche (« … — cumul 1 h »).
- Suppression de la saisie d'horizons en métropole (remplacée par le menu) ;
  options avancées dépliées par défaut.

### Corrections & robustesse
- Chargement des couches par `coverage_id` (corrige « Indicateur invalide » sur
  AROME-PI ; garantit la cohérence run/cumul/échéance).
- Lecture des échéances sans re-télécharger le GetCapabilities (~1,7 Mo pour
  AROME) → nettement plus rapide.
- Cache de session des listings : rebasculer entre modèles est instantané.
- Retry automatique si le GetCapabilities est tronqué (corrige le cas « une
  seule variable affichée ») ; résultat partiel non mis en cache.
- Variables PIAF/AROME-PI (intensité, précip. solides/convectives) désormais
  incluses dans le filtre ; filet de sécurité si aucune variable « significative ».
- Retour systématique au modèle AROME à l'ouverture / au retour à l'étape 1 ;
  résolution de modèle robuste (AROME-PI / AROME-PE ne sont plus confondus).
- Message explicite en cas d'erreur d'abonnement (900908).

## [1.4.2] — 2026-07

### Ergonomie
- Après un chargement, un panneau propose des actions claires : « Modèle / variable » (retour étape 2) et « Recommencer » (retour étape 1), pour enchaîner sans manipulations hasardeuses.
- En-têtes d'étapes cliquables mis en évidence (curseur main, infobulle) ; étape 2 renommée « Modèle & variable ».

### Corrections — stabilité de la sélection
- **PIAF nettement plus rapide** : le garde-fou anti-troncature se basait sur le nombre d'indicateurs (< 3) et se déclenchait à tort pour PIAF, qui n'a qu'une seule variable, provoquant deux re-téléchargements inutiles à chaque listing. Il se base désormais sur le nombre de lignes brutes ; PIAF se liste en un seul appel.
- **Run expiré (PIAF/AROME-PI)** : ces modèles se rafraîchissant toutes les 15 min, le coverage capté au listing pouvait ne plus exister au chargement (« NoSuchCoverage »). Le dernier run est désormais ré-résolu automatiquement en cas d'expiration, de façon transparente.
- **Ensemble (AROME-PE)** : le paramètre `ensemble_numbers` n'est plus transmis qu'au modèle AROME-PE (ENSEMBLE). Les modèles déterministes (AROME, AROME-PI, ARPEGE, PIAF) ne le reçoivent plus, ce qui évite tout risque de données dupliquées ou d'erreur de fusion. Nombre de membres borné (1 à 25).
- **Emprise du canevas hors domaine** : si l'emprise (canevas ou couche) débordait du domaine du modèle (par exemple au sud de 37,5°N pour AROME), le chargement échouait (« latitude out of bounds »). L'emprise est désormais rognée automatiquement au domaine du modèle.
- **Multi-échéances corrigé** : sélectionner plusieurs pas de temps ne produisait qu'un seul raster. La lecture de la sélection (cumul et échéances) dépendait de la visibilité du widget, or l'étape 2 est masquée au moment du chargement (on est sur l'étape 3) : les choix étaient donc ignorés et l'API retombait sur un seul horizon par défaut. La lecture ne dépend plus de la visibilité ; une couche par échéance sélectionnée est de nouveau produite, et le cumul choisi est bien appliqué.
- Correction d'une désynchronisation : après un listing ou un rechargement, la
  première variable était « sélectionnée » sans que les menus Période de cumul
  et Échéances ne se mettent à jour (le handler ne se déclenchait pas). Résultat,
  le plugin semblait « s'emmêler les pinceaux » quand on changeait de paramètre.
  Désormais aucune variable n'est présélectionnée : l'utilisateur choisit, ce qui
  synchronise proprement les menus.
- Garde de cohérence au chargement : si le modèle a changé depuis le dernier
  listing, ou si la variable n'est plus reconnue, un message invite à recliquer
  sur « Lister les indicateurs » au lieu de charger avec un état incohérent.
- Réinitialisation systématique des menus cumul/échéances à chaque (re)listing.
