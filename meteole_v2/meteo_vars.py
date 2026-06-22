# -*- coding: utf-8 -*-
"""
Module central de sémantique des variables météo Météo-France.

Source unique de vérité pour, à la fois la métropole (indicateurs WCS meteole)
et l'Outre-Mer (shortName GRIB2). Trois responsabilités :

  1. Conversion des unités vers des unités lisibles par un public français
     (Kelvin → °C, Pa → hPa, m/s → km/h, kg/m² → mm, etc.)
  2. Traduction en français des indicateurs métropole et des variables GRIB2
  3. Filtrage : ne conserver que les variables les plus significatives / communes
     (températures, vent, humidité, précipitations, pression, nébulosité,
      variables liées aux orages : CAPE/CIN, grêle, précipitations convectives)

Aucune dépendance à QGIS : ce module peut être importé depuis le thread worker.
"""

from __future__ import annotations

# Le dictionnaire GRIB2 (shortName → label fr, unité, type) vit dans arome_om.
# arome_om n'importe que la stdlib + requests : import sûr, sans QGIS.
from .arome_om import GRIB_VAR_INFO


# ================================================================== #
#  1. Conversion des unités
# ================================================================== #
#  Clé   = unité source telle que stockée dans GRIB_VAR_INFO / _UNIT_MAP
#  Valeur = (unité cible lisible, fonction de conversion)
#  Seules les unités « peu parlantes » sont converties ; les autres
#  (%, J/kg pour la CAPE, m, W/m², N/m²…) restent inchangées.

def _k_to_c(x):      return x - 273.15      # Kelvin → Celsius
def _pa_to_hpa(x):   return x / 100.0       # Pascal → hectopascal
def _ms_to_kmh(x):   return x * 3.6         # m/s → km/h
def _x1000(x):       return x * 1000.0      # kg/kg → g/kg
def _x100(x):        return x * 100.0       # fraction m³/m³ → %
def _j_to_wh(x):     return x / 3600.0      # J/m² → Wh/m²
def _x3600(x):       return x * 3600.0      # kg/m²/s → mm/h
def _identity(x):    return x               # kg/m² ≡ mm (lame d'eau)

UNIT_CONVERSIONS = {
    "K":        ("°C",    _k_to_c),
    "Pa":       ("hPa",   _pa_to_hpa),
    "m/s":      ("km/h",  _ms_to_kmh),
    "kg/m²":    ("mm",    _identity),   # 1 kg/m² d'eau = 1 mm de lame d'eau
    "kg/m^2":   ("mm",    _identity),
    "kg/m²/s":  ("mm/h",  _x3600),
    "kg/m^2/s": ("mm/h",  _x3600),
    "kg/kg":    ("g/kg",  _x1000),
    "m³/m³":    ("%",     _x100),
    "m3/m3":    ("%",     _x100),
    "J/m²":     ("Wh/m²", _j_to_wh),
    "J/m^2":    ("Wh/m²", _j_to_wh),
}


def convert_value(value, unit):
    """Convertit un scalaire. Retourne (valeur_convertie, unité_cible)."""
    conv = UNIT_CONVERSIONS.get(unit)
    if not conv:
        return value, unit
    target, fn = conv
    try:
        return fn(value), target
    except Exception:
        return value, unit


def convert_array(arr, unit):
    """
    Convertit un tableau numpy / pandas Series.
    Retourne (tableau_converti, unité_cible). En cas d'échec, renvoie
    les valeurs et l'unité d'origine sans lever d'exception.
    """
    conv = UNIT_CONVERSIONS.get(unit)
    if not conv:
        return arr, unit
    target, fn = conv
    try:
        return fn(arr), target
    except Exception:
        return arr, unit


# ================================================================== #
#  2. Type sémantique + unité source (métropole ET outre-mer)
# ================================================================== #

# Table des unités GRIB2/CF pour les indicateurs métropole (noms WCS).
# Recherche par sous-chaîne (le nom le plus long d'abord).
_METRO_UNIT_MAP = {
    "TEMPERATURE":               "K",
    "DEW_POINT_TEMPERATURE":     "K",
    "MINIMUM_TEMPERATURE":       "K",
    "MAXIMUM_TEMPERATURE":       "K",
    "POTENTIAL_TEMPERATURE":     "K",
    "WET_BULB_TEMPERATURE":      "K",
    "WIND_SPEED":                "m/s",
    "WIND_SPEED_GUST":           "m/s",
    "WIND_SPEED_OF_GUST":        "m/s",
    "U_COMPONENT_OF_WIND":       "m/s",
    "V_COMPONENT_OF_WIND":       "m/s",
    "WIND_DIRECTION":            "°",
    "TOTAL_PRECIPITATION":       "kg/m²",
    "TOTAL_WATER_PRECIPITATION": "kg/m²",
    "RAIN_FALL_AMOUNT":          "kg/m²",
    "TOTAL_SNOW_PRECIPITATION":  "kg/m²",
    "RAINFALL_RATE":             "kg/m²/s",
    "SNOW_DEPTH":                "m",
    "PRESSURE":                  "Pa",
    "MEAN_SEA_LEVEL_PRESSURE":   "Pa",
    "RELATIVE_HUMIDITY":         "%",
    "SPECIFIC_HUMIDITY":         "kg/kg",
    "TOTAL_CLOUD_COVER":         "%",
    "LOW_CLOUD_COVER":           "%",
    "MEDIUM_CLOUD_COVER":        "%",
    "HIGH_CLOUD_COVER":          "%",
    "CONVECTIVE_AVAILABLE_POTENTIAL_ENERGY": "J/kg",
    "CONVECTIVE_INHIBITION":     "J/kg",
    "CAPE":                      "J/kg",
    "CIN":                       "J/kg",
}

# Mots-clés → type sémantique (pour le choix de la palette de couleurs)
_TYPE_KEYWORDS = {
    "temperature":   ("TEMPERATURE", "TEMP", "T2M", "T_2M", "DEW_POINT"),
    "wind":          ("WIND", "WINDSPEED", "WIND_SPEED", "FF10", "RAFALE",
                      "GUST", "U_COMPONENT", "V_COMPONENT"),
    "precipitation": ("RAIN", "PRECIP", "PRECIPITATION", "RR", "SNOW",
                      "NEIGE", "TOTAL_PRECIPITATION", "RAIN_FALL",
                      "GRAUPEL", "HAIL", "GRELE"),
    "pressure":      ("PRESSURE", "PRESSION", "MSLP", "PMER", "MSL",
                      "MEAN_SEA_LEVEL"),
    "humidity":      ("HUMIDITY", "HUMIDITE", "RELATIVE_HUMIDITY", "HR", "HU",
                      "SPECIFIC_HUMIDITY"),
    "cloud":         ("CLOUD", "NUAGE", "NEBUL", "CLOUD_COVER", "TOTAL_CLOUD"),
    "convection":    ("CAPE", "CONVECT", "LIFTED", "CIN"),
}


def indicator_type(name: str) -> str:
    """
    Retourne le type sémantique d'une variable, en privilégiant la table
    GRIB2 exacte (outre-mer) puis la détection par mots-clés (métropole).
    """
    info = GRIB_VAR_INFO.get(name)
    if info:
        return info[2]
    upper = (name or "").upper()
    for typ, kws in _TYPE_KEYWORDS.items():
        if any(k in upper for k in kws):
            return typ
    return "generic"


def source_unit(name: str) -> str:
    """
    Retourne l'unité brute (avant conversion) d'une variable.
    Cherche d'abord la table GRIB2 exacte (outre-mer), puis la table
    métropole par sous-chaîne. Retourne '' si inconnue.
    """
    info = GRIB_VAR_INFO.get(name)
    if info and info[1]:
        return info[1]
    upper = (name or "").upper()
    for key in sorted(_METRO_UNIT_MAP, key=len, reverse=True):
        if key in upper:
            return _METRO_UNIT_MAP[key]
    return ""


def display_unit(name: str) -> str:
    """Unité finale affichée à l'utilisateur (après conversion éventuelle)."""
    src = source_unit(name)
    target, _ = UNIT_CONVERSIONS.get(src, (src, None))
    return target


# ================================================================== #
#  3. Traduction française des indicateurs métropole (API WCS)
# ================================================================== #
#  Les coverage_id meteole sont de la forme :
#     <BASE>__<NIVEAU>           ex. TEMPERATURE__SPECIFIC_HEIGHT_LEVEL
#  La partie BASE (avant le 1er « __ ») porte le sens physique.

# Variable de base → libellé français
_METRO_BASE_FR = {
    "TEMPERATURE":                 "Température",
    "DEW_POINT_TEMPERATURE":       "Température du point de rosée",
    "MINIMUM_TEMPERATURE":         "Température minimale",
    "MAXIMUM_TEMPERATURE":         "Température maximale",
    "RELATIVE_HUMIDITY":           "Humidité relative",
    "SPECIFIC_HUMIDITY":           "Humidité spécifique",
    "WIND_SPEED":                  "Vitesse du vent",
    "WIND_SPEED_GUST":             "Rafales de vent",
    "WIND_SPEED_OF_GUST":          "Rafales de vent",
    "WIND_DIRECTION":              "Direction du vent",
    "U_COMPONENT_OF_WIND":         "Vent (composante U, ouest→est)",
    "V_COMPONENT_OF_WIND":         "Vent (composante V, sud→nord)",
    "TOTAL_PRECIPITATION":         "Précipitations totales",
    "TOTAL_WATER_PRECIPITATION":   "Précipitations liquides",
    "TOTAL_SNOW_PRECIPITATION":    "Précipitations neigeuses",
    "RAINFALL_RATE":               "Intensité des précipitations",
    "PRESSURE":                    "Pression",
    "TOTAL_CLOUD_COVER":           "Nébulosité totale",
    "LOW_CLOUD_COVER":             "Nébulosité basse",
    "MEDIUM_CLOUD_COVER":          "Nébulosité moyenne",
    "HIGH_CLOUD_COVER":            "Nébulosité haute",
    "CONVECTIVE_AVAILABLE_POTENTIAL_ENERGY": "Énergie convective (CAPE)",
    "CONVECTIVE_INHIBITION":       "Inhibition convective (CIN)",
}

# Niveau / surface → complément français entre parenthèses
_METRO_LEVEL_FR = [
    ("MEAN_SEA_LEVEL",               "niveau de la mer"),
    ("SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND", "au-dessus du sol"),
    ("HEIGHT_LEVEL_ABOVE_GROUND",    "au-dessus du sol"),
    ("ABOVE_GROUND",                 "au-dessus du sol"),
    ("GROUND_OR_WATER_SURFACE",      "surface"),
    ("ISOBARIC_SURFACE",             "niveau de pression"),
    ("ISOBARIC",                     "niveau de pression"),
]


def _titleize(token: str) -> str:
    """Repli : transforme TOTAL_CLOUD_COVER → « Total cloud cover »."""
    return token.replace("_", " ").capitalize()


def translate_indicator_fr(raw_name: str) -> str:
    """
    Traduit un indicateur métropole brut en libellé français lisible,
    avec, si reconnu, le niveau entre parenthèses.
    Ex. : TEMPERATURE__SPECIFIC_HEIGHT_LEVEL_ABOVE_GROUND
          → « Température (au-dessus du sol) »
    Repli gracieux si l'indicateur est inconnu.
    """
    if not raw_name:
        return raw_name
    base = raw_name.split("__")[0]
    rest = raw_name[len(base):]

    label = _METRO_BASE_FR.get(base, _titleize(base))

    level = ""
    upper_rest = rest.upper()
    for token, fr in _METRO_LEVEL_FR:
        if token in upper_rest:
            level = fr
            break

    return f"{label} ({level})" if level else label


# ================================================================== #
#  4. Filtrage : variables significatives / communes
# ================================================================== #

# --- Métropole : on conserve ces variables de base ---
METRO_KEEP_BASES = {
    "TEMPERATURE",
    "DEW_POINT_TEMPERATURE",
    "MINIMUM_TEMPERATURE",
    "MAXIMUM_TEMPERATURE",
    "RELATIVE_HUMIDITY",
    "SPECIFIC_HUMIDITY",
    "WIND_SPEED",
    "WIND_SPEED_GUST",
    "WIND_SPEED_OF_GUST",
    "WIND_DIRECTION",
    "U_COMPONENT_OF_WIND",
    "V_COMPONENT_OF_WIND",
    "TOTAL_PRECIPITATION",
    "TOTAL_WATER_PRECIPITATION",
    "TOTAL_SNOW_PRECIPITATION",
    "RAINFALL_RATE",
    "PRESSURE",
    "TOTAL_CLOUD_COVER",
    "LOW_CLOUD_COVER",
    "MEDIUM_CLOUD_COVER",
    "HIGH_CLOUD_COVER",
    "CONVECTIVE_AVAILABLE_POTENTIAL_ENERGY",  # orages
    "CONVECTIVE_INHIBITION",                  # orages
    "CAPE",
    "CIN",
}


def is_significant_metro(raw_name: str) -> bool:
    """Vrai si l'indicateur métropole fait partie des variables conservées."""
    if not raw_name:
        return False
    base = raw_name.split("__")[0]
    return base in METRO_KEEP_BASES


def filter_metro_indicators(indicators: list[str]) -> list[str]:
    """Conserve uniquement les indicateurs significatifs (ordre préservé)."""
    return [i for i in indicators if is_significant_metro(i)]


# --- Outre-Mer : shortName GRIB2 conservés (variables de surface communes) ---
OM_KEEP_SHORTNAMES = {
    # Température (surface / 2 m)
    "t2m", "2t", "t", "d2m", "2d", "skt", "mx2t", "mn2t", "mx2t6", "mn2t6",
    "stl1", "tsn",
    # Vent (10 m + rafales)
    "u10", "v10", "si10", "fg10", "efg10", "wdir10",
    "10u", "10v", "10si", "10fg", "10wdir", "gust", "i10fg",
    # Humidité
    "r2", "2r", "q", "sh2", "sh", "tcwv",
    # Pression
    "prmsl", "msl", "sp",
    # Précipitations (dont neige et grêle — orages)
    "tp", "tgrp", "tsnowp", "lsp", "cp", "sf", "tirf", "crr", "lsrr",
    # Nébulosité
    "tcc", "lcc", "mcc", "hcc",
    # Énergie convective (orages)
    "cape", "cin", "CAPE_INS",
}

# Paquets surface (gardés) vs multi-niveaux isobares/hybrides (avancés)
OM_SURFACE_PACKAGES = ("SP",)
OM_ADVANCED_PACKAGES = ("IP", "HP")


def is_significant_om(short_name: str) -> bool:
    """Vrai si la variable GRIB2 outre-mer fait partie des variables conservées."""
    return short_name in OM_KEEP_SHORTNAMES
