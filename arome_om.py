# -*- coding: utf-8 -*-
"""
Client REST pour l'API AROME Outre-mer (DPPaquetAROME-OM) de Météo-France.

Cette API est DISTINCTE de l'API WCS utilisée par meteole pour la métropole.
Base URL : https://public-api.meteofrance.fr/previnum/DPPaquetAROME-OM/v1

Workflow :
  1. list_grids(territory)           → liste des grilles disponibles
  2. list_packages(territory, grid)  → liste des paquets (groupes d'indicateurs)
  3. download_product(...)           → fichier GRIB2 → DataFrame pandas via cfgrib

Références : swagger Package_AROME_Outre-mer v1
"""

from __future__ import annotations

import datetime
import json
import os
import re
import tempfile

import requests

# ------------------------------------------------------------------ #
#  Dictionnaire des variables GRIB2 connues pour AROME-OM
#  (shortName cfgrib → label français, unité, type indicateur)
# ------------------------------------------------------------------ #
GRIB_VAR_INFO: dict[str, tuple[str, str, str]] = {
    # Vent
    "u10":    ("Vent U 10m",               "m/s",    "wind"),
    "v10":    ("Vent V 10m",               "m/s",    "wind"),
    "si10":   ("Vitesse vent 10m",         "m/s",    "wind"),
    "fg10":   ("Rafale vent 10m",          "m/s",    "wind"),
    "efg10":  ("Rafale max vent 10m",      "m/s",    "wind"),
    "nfg10":  ("Rafale min vent 10m",      "m/s",    "wind"),
    "wdir10": ("Direction vent 10m",       "°",      "wind"),
    "10u":    ("Vent U 10m",               "m/s",    "wind"),
    "10v":    ("Vent V 10m",               "m/s",    "wind"),
    "10si":   ("Vitesse vent 10m",         "m/s",    "wind"),
    "10fg":   ("Rafale vent 10m",          "m/s",    "wind"),
    "10wdir": ("Direction vent 10m",       "°",      "wind"),
    # Température
    "t2m":    ("Température 2m",           "K",      "temperature"),
    "2t":     ("Température 2m",           "K",      "temperature"),
    "t":      ("Température",              "K",      "temperature"),
    "d2m":    ("Température point rosée",  "K",      "temperature"),
    "2d":     ("Température point rosée",  "K",      "temperature"),
    "skt":    ("Température surface sol",  "K",      "temperature"),
    # Humidité
    "r2":     ("Humidité relative 2m",     "%",      "humidity"),
    "2r":     ("Humidité relative 2m",     "%",      "humidity"),
    "q":      ("Humidité spécifique",      "kg/kg",  "humidity"),
    # Pression
    "prmsl":  ("Pression niveau mer",      "Pa",     "pressure"),
    "msl":    ("Pression niveau mer",      "Pa",     "pressure"),
    "sp":     ("Pression surface",         "Pa",     "pressure"),
    # Précipitations
    "tp":     ("Précipitations totales (accumulées)", "kg/m²",  "precipitation"),
    "tgrp":   ("Précipitations grêle",     "kg/m²",  "precipitation"),
    "tsnowp": ("Précipitations neige",     "kg/m²",  "precipitation"),
    "lsp":    ("Préc. grande échelle",     "kg/m²",  "precipitation"),
    "cp":     ("Préc. convectives",        "kg/m²",  "precipitation"),
    "sf":     ("Chutes de neige",          "kg/m²",  "precipitation"),
    # Nébulosité
    "tcc":    ("Nébulosité totale",        "%",      "cloud"),
    "lcc":    ("Nébulosité basse",         "%",      "cloud"),
    "mcc":    ("Nébulosité moyenne",       "%",      "cloud"),
    "hcc":    ("Nébulosité haute",         "%",      "cloud"),
    # Rayonnement / flux de chaleur
    "ssrd":   ("Rayonnement solaire surf (accumulé)", "J/m²",   "generic"),
    "slhf":   ("Flux chaleur latente surf (accumulée)","J/m²",   "generic"),
    "sshf":   ("Flux chaleur sensible surf","J/m²",  "generic"),
    "str":    ("Rayonnement thermique net","J/m²",   "generic"),
    "ssr":    ("Rayonnement solaire net",  "J/m²",   "generic"),
    "strd":   ("Rayonnement thermique",    "J/m²",   "generic"),
    "ssr":    ("Rayonnement net courte",   "J/m²",   "generic"),
    # Énergie convective
    "cape":   ("CAPE",                     "J/kg",   "convection"),
    "cin":    ("CIN",                      "J/kg",   "convection"),
    # Neige/glace
    "sde":    ("Hauteur neige",            "m",      "generic"),
    "sd":     ("Densité neige",            "kg/m²",  "generic"),
    # Rayonnement clear-sky
    "ssrc":   ("Rayonnement solaire ciel clair (accumulé)",   "J/m²",    "generic"),
    "strc":   ("Rayonnement thermique ciel clair (accumulé)", "J/m²",    "generic"),
    "tsrc":   ("Rayonnement solaire net ciel clair",          "J/m²",    "generic"),
    "ttrc":   ("Rayonnement thermique net ciel clair",        "J/m²",    "generic"),
    # Contraintes turbulentes de surface
    "iews":   ("Contrainte turbulente surface E-O",           "N/m²",    "generic"),
    "inss":   ("Contrainte turbulente surface N-S",           "N/m²",    "generic"),
    "ewss":   ("Contrainte turbulente surface E-O (acc.)",    "N/m²",    "generic"),
    "nsss":   ("Contrainte turbulente surface N-S (acc.)",    "N/m²",    "generic"),
    # Température max/min
    "mx2t":   ("Température max 2m",                          "K",       "temperature"),
    "mn2t":   ("Température min 2m",                          "K",       "temperature"),
    "mx2t6":  ("Température max 2m (6h)",                     "K",       "temperature"),
    "mn2t6":  ("Température min 2m (6h)",                     "K",       "temperature"),
    # Humidité / eau atmosphérique
    "tcwv":   ("Vapeur d'eau colonne totale",                 "kg/m²",   "humidity"),
    "tclw":   ("Eau liquide nuageuse totale",                  "kg/m²",   "cloud"),
    "tciw":   ("Glace nuageuse totale",                        "kg/m²",   "cloud"),
    # Couche limite / surface
    "blh":    ("Hauteur couche limite atmosphérique",          "m",       "generic"),
    "fsr":    ("Rugosité de surface",                          "m",       "generic"),
    "lsm":    ("Masque terre-mer",                             "",        "generic"),
    "z":      ("Orographie (géopotentiel)",                    "m²/s²",   "generic"),
    "orog":   ("Orographie",                                   "m",       "generic"),
    # Neige et sol
    "rsn":    ("Densité de la neige",                          "kg/m³",   "generic"),
    "asn":    ("Albédo de la neige",                           "",        "generic"),
    "tsn":    ("Température couche de neige",                  "K",       "temperature"),
    "stl1":   ("Température sol couche 1",                     "K",       "temperature"),
    "stl2":   ("Température sol couche 2",                     "K",       "temperature"),
    "swvl1":  ("Humidité volumique sol couche 1",              "m³/m³",   "humidity"),
    "swvl2":  ("Humidité volumique sol couche 2",              "m³/m³",   "humidity"),
    # Évaporation
    "e":      ("Évaporation (accumulée)",                      "m",       "generic"),
    "ie":     ("Évaporation instantanée",                      "kg/m²/s", "generic"),
    # Flux turbulents instantanés
    "ishf":   ("Flux de chaleur sensible instantané",          "W/m²",    "generic"),
    "ilhf":   ("Flux de chaleur latente instantané",           "W/m²",    "generic"),
    # Précipitations supplémentaires
    "crr":    ("Taux de précipitations convectives",           "kg/m²/s", "precipitation"),
    "lsrr":   ("Taux de précipitations grande échelle",        "kg/m²/s", "precipitation"),
    # Rafales supplémentaires
    "gust":   ("Rafale de vent maximale",                      "m/s",     "wind"),
    "i10fg":  ("Rafale instantanée vent 10m",                  "m/s",     "wind"),
    # Variables spécifiques AROME-OM (confirmées sur ANTIL)
    "sh2":      ("Humidité spécifique 2m",          "kg/kg",   "humidity"),
    "sh":       ("Humidité spécifique",              "kg/kg",   "humidity"),
    "sp":       ("Pression de surface",              "Pa",      "pressure"),
    "tirf":     ("Flux de pluie intégré",            "kg/m²",   "precipitation"),
    "CAPE_INS": ("CAPE instantané",                  "J/kg",    "convection"),
    "strd":     ("Rayonnement thermique descendant", "J/m²",    "generic"),
    # Inconnu
    "unknown": ("Variable GRIB non décodée (paramId inconnu)", "",        "generic"),
}




# ------------------------------------------------------------------ #
#  Contenu présumé des paquets AROME-OM
#  Source : documentation Météo-France / expérience terrain
#  Ces listes permettent de pré-peupler l'UI sans télécharger le GRIB2.
#  Les paquets inconnus restent accessibles via "Lister les variables".
# ------------------------------------------------------------------ #
# Nomenclature réelle AROME-OM (confirmée sur ANTIL) :
# SP = Surface Parameters (variables surface)
# IP = Isobaric Parameters (variables sur niveaux de pression)
# HP = Hybrid Pressure parameters (niveaux hybrides sigma)
KNOWN_PACKAGES: dict[str, list[str]] = {
    # ---- Surface ----
    "SP1": ["u10", "v10", "si10", "fg10", "efg10", "nfg10", "wdir10",
            "t2m", "r2", "prmsl", "ssrd", "tp", "tgrp", "tsnowp", "slhf"],
    # SP2 confirmé sur ANTIL :
    "SP2": ["d2m", "sh2", "mx2t", "mn2t", "t", "sp", "blh",
            "lcc", "mcc", "hcc", "tirf", "CAPE_INS"],
    # SP3 confirmé sur ANTIL (3 variables "unknown" = paramètres MF non standard) :
    "SP3": ["sshf", "slhf", "strd", "ssr", "str", "ssrc", "strc",
            "iews", "inss"],
    # ---- Isobaric (multi-niveaux de pression) ----
    # IP1 confirmé = ['z', 't', 'u', 'v', 'r']
    "IP1": ["z", "t", "u", "v", "r"],
    "IP2": ["z", "t", "u", "v", "r", "q"],
    "IP3": ["z", "t", "u", "v", "r", "w"],
    "IP4": ["z", "t", "u", "v", "r", "q", "w"],
    "IP5": ["tcc", "lcc", "mcc", "hcc"],
    # ---- Hybrid Pressure (multi-niveaux hybrides) ----
    "HP1": ["z", "t", "u", "v", "r"],
    "HP2": ["z", "t", "u", "v", "r", "q"],
    "HP3": ["z", "t", "u", "v", "r", "q", "w"],
}

# Catégories de paquets pour l'affichage UI
PACKAGE_CATEGORIES = {
    "SP1": "Surface",
    "SP2": "Surface",
    "SP3": "Surface (flux/rayonnement)",
    "IP1": "Isobare (basique)",
    "IP2": "Isobare (+ humidité spéc.)",
    "IP3": "Isobare (+ vent vertical)",
    "IP4": "Isobare (complet)",
    "IP5": "Isobare (nuages/convection)",
    "HP1": "Niveaux hybrides (basique)",
    "HP2": "Niveaux hybrides (+ humidité)",
    "HP3": "Niveaux hybrides (complet)",
}


def package_variable_entries(packages: list[str]) -> list[dict]:
    """
    Construit la liste plate des variables disponibles pour une liste de paquets.
    Chaque entrée : {display, package, var_name, label, unit}

    Pour les paquets connus, utilise KNOWN_PACKAGES.
    Pour les paquets inconnus, retourne une entrée générique.
    """
    entries = []
    seen_surface_vars = set()  # dédup pour SP uniquement

    for pkg in packages:
        vars_in_pkg = KNOWN_PACKAGES.get(pkg)
        cat = PACKAGE_CATEGORIES.get(pkg, pkg)
        is_multilevel = pkg.startswith(("IP", "HP"))

        if vars_in_pkg:
            if is_multilevel:
                # Paquets multi-niveaux : une entrée par paquet
                _ML_LABELS = {
                    "z": "Géopotentiel", "t": "Température",
                    "u": "Vent U", "v": "Vent V", "r": "Humidité rel.",
                    "q": "Humidité spéc.", "w": "Vent vertical",
                }
                var_labels = [_ML_LABELS.get(v, grib_var_label(v).split(" (")[0])
                              for v in vars_in_pkg]
                vars_summary = ", ".join(var_labels[:4])
                if len(vars_in_pkg) > 4:
                    vars_summary += "…"
                display = f"{cat} — {vars_summary}  [{pkg}]"
                entries.append({
                    "display": display,
                    "package": pkg,
                    "var_name": None,  # charger tout le paquet
                    "label":   cat,
                    "unit":    "",
                })
            else:
                # Paquets surface : déduplication par variable
                for v in vars_in_pkg:
                    if v in seen_surface_vars:
                        continue
                    seen_surface_vars.add(v)
                    label   = grib_var_label(v)
                    display = f"{label}  [{pkg}]" if label != v else f"{v}  [{pkg}]"
                    entries.append({
                        "display": display,
                        "package": pkg,
                        "var_name": v,
                        "label":   label,
                        "unit":    GRIB_VAR_INFO.get(v, ("", "", ""))[1],
                    })
        else:
            # Paquet inconnu : expose le paquet brut avec option de listage
            entries.append({
                "display": f"[Contenu inconnu — cliquer Lister]  [{pkg}]",
                "package": pkg,
                "var_name": None,  # None = charger tout le paquet
                "label":   pkg,
                "unit":    "",
            })

    return entries


def grib_var_label(short_name: str) -> str:
    """Retourne le label français d'une variable GRIB2, ou le shortName brut."""
    info = GRIB_VAR_INFO.get(short_name)
    if info:
        unit = info[1]
        return f"{info[0]} ({unit})" if unit else info[0]
    return short_name


def grib_var_type(short_name: str) -> str:
    """Retourne le type d'indicateur pour le style de couleur."""
    info = GRIB_VAR_INFO.get(short_name)
    return info[2] if info else "generic"


# ------------------------------------------------------------------ #
#  Configuration par territoire
# ------------------------------------------------------------------ #

BASE_URL = "https://public-api.meteofrance.fr/previnum/DPPaquetAROME-OM/v1"

OM_TERRITORY_CONFIG = {
    "ANTIL":  {"model_code": "AROME-OM-ANTIL",  "product_ep": "productOMAN"},
    "GUYANE": {"model_code": "AROME-OM-GUYANE", "product_ep": "productOMGU"},
    "INDIEN": {"model_code": "AROME-OM-INDIEN", "product_ep": "productOMOI"},
    "NCALED": {"model_code": "AROME-OM-NCALED", "product_ep": "productOMNC"},
    "POLYN":  {"model_code": "AROME-OM-POLYN",  "product_ep": "productOMPF"},
}


# ------------------------------------------------------------------ #
#  Helpers de parsing
# ------------------------------------------------------------------ #

def _extract_grids(data) -> list[str]:
    """
    Extrait les identifiants de grilles depuis n'importe quel format de réponse.
    Gère : JSON list, dict OGC API (avec 'links' rel=item), texte brut.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            found = re.findall(r'\b(\d+\.\d+)\b', data)
            return list(dict.fromkeys(found)) if found else []

    if isinstance(data, list):
        nums = [str(x) for x in data if isinstance(x, (int, float))]
        if nums:
            return nums
        ids = [str(x).strip() for x in data
               if isinstance(x, str)
               and re.match(r'^[\d\.\-\_]+$', x.strip())
               and len(x.strip()) < 20]
        if ids:
            return ids
        out = []
        for item in data:
            if isinstance(item, dict):
                for key in ('id', 'grid', 'value', 'name', 'code', 'title'):
                    if key in item:
                        out.append(str(item[key]))
                        break
        return out

    if isinstance(data, dict):
        # 1. Clés directes standard
        for key in ('grids', 'grid', 'items', 'features',
                    'collections', 'values', 'data'):
            if key in data and data[key]:
                result = _extract_grids(data[key])
                if result:
                    return result

        # 2. Format OGC API : liens rel OGC dans 'links'
        ogc_rels = (
            'item', 'grid', 'alternate', 'related',
            'http://www.opengis.net/def/rel/ogc/1.0/data',
            'http://www.opengis.net/def/rel/ogc/1.0/item',
        )
        links = data.get('links', [])
        item_links = [lnk for lnk in links
                      if isinstance(lnk, dict)
                      and lnk.get('rel') in ogc_rels
                      and lnk.get('rel') != 'self']
        if item_links:
            ids = []
            for lnk in item_links:
                title = str(lnk.get('title', ''))
                href  = str(lnk.get('href',  ''))
                if re.match(r'^[\d\.]+$', title.strip()):
                    ids.append(title.strip())
                else:
                    seg = href.rstrip('/').split('/')[-1]
                    if re.match(r'^[\d\.]+$', seg):
                        ids.append(seg)
            if ids:
                return ids

        # 3. Valeurs numériques dans les autres clés
        for key, val in data.items():
            if key in ('title', 'description', 'attribution', 'links'):
                continue
            if isinstance(val, list):
                nums = [str(x) for x in val
                        if isinstance(x, (int, float))
                        or (isinstance(x, str)
                            and re.match(r'^\d+\.?\d*$', x.strip()))]
                if nums:
                    return nums
            elif isinstance(val, (int, float)):
                return [str(val)]
            elif isinstance(val, str) and re.match(r'^\d+\.?\d*$', val.strip()):
                return [val.strip()]

        # 4. Dernier recours : regex sur la représentation str
        s = str(data)
        found = re.findall(r'\b(0\.\d+)\b', s)
        return list(dict.fromkeys(found)) if found else []

    return []


def _extract_packages(data) -> list[str]:
    """
    Extrait les noms de paquets depuis n'importe quel format de réponse OGC.
    Les paquets AROME-OM ont des noms courts comme SP1, SP2, HP1, HP2, HP3.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            # Texte brut : cherche des patterns de noms de paquets
            found = re.findall(r'\b([A-Z]{1,4}\d{1,2})\b', data)
            return list(dict.fromkeys(found)) if found else []

    if isinstance(data, list):
        pkgs = [str(x).strip() for x in data
                if isinstance(x, str)
                and re.match(r'^[A-Z]{1,4}\d{0,3}$', x.strip())]
        if pkgs:
            return pkgs
        short = [str(x).strip() for x in data
                 if isinstance(x, str) and 0 < len(x.strip()) < 30]
        return short

    if isinstance(data, dict):
        # 1. Clés directes
        for key in ('packages', 'package', 'items', 'features',
                    'collections', 'data', 'values'):
            if key in data and data[key]:
                result = _extract_packages(data[key])
                if result:
                    return result

        # 2. Format OGC API — liens avec rel OGC data/item
        links = data.get('links', [])
        ogc_rels = (
            'item', 'alternate', 'related',
            'http://www.opengis.net/def/rel/ogc/1.0/data',
            'http://www.opengis.net/def/rel/ogc/1.0/item',
        )
        item_links = [lnk for lnk in links
                      if isinstance(lnk, dict)
                      and lnk.get('rel') in ogc_rels
                      and lnk.get('rel') != 'self']
        if item_links:
            ids = []
            for lnk in item_links:
                title = str(lnk.get('title', ''))
                href  = str(lnk.get('href',  ''))
                # Cherche un pattern de paquet dans le titre
                found = re.findall(r'\b([A-Z]{1,4}\d{1,2})\b', title)
                if found:
                    ids.extend(found)
                else:
                    # Dernier segment de l'URL
                    seg = href.rstrip('/').split('/')[-1]
                    if re.match(r'^[A-Z]{1,4}\d{0,3}$', seg):
                        ids.append(seg)
            if ids:
                return list(dict.fromkeys(ids))

        # 3. Cherche des patterns Xnn dans toutes les valeurs
        s = str(data)
        found = re.findall(r'\b([A-Z]{1,4}\d{1,2})\b', s)
        # Filtre les faux positifs (noms propres, acronymes)
        noise = {'NO', 'OK', 'ID', 'URL', 'API', 'GET', 'OGC', 'WCS',
                 'ISO', 'UTC', 'URI', 'MF', 'FR', 'OM'}
        found = [f for f in found if f not in noise]
        return list(dict.fromkeys(found)) if found else []

    return []


# Alias rétrocompatibilité
def _parse_list(data) -> list[str]:
    return _extract_grids(data)


# ------------------------------------------------------------------ #
#  Client REST
# ------------------------------------------------------------------ #

class AromeOMClient:
    """Client pour l'API REST AROME Outre-mer de Météo-France."""

    def __init__(self, token: str = None, api_key: str = None,
                 application_id: str = None):
        self._session = requests.Session()
        self._session.headers["Accept"] = "text/json"
        if token:
            self._session.headers["Authorization"] = f"Bearer {token}"
        elif api_key:
            self._session.headers["apikey"] = api_key
        elif application_id:
            # application_id → on doit d'abord obtenir un token
            self._session.headers["Authorization"] = f"Bearer {application_id}"

    # ---- helpers ---------------------------------------------------- #

    def _get_json(self, path: str, params: dict = None):
        """GET → parse JSON (tolère text/json et application/json)."""
        url = BASE_URL + path
        r = self._session.get(url, params=params, timeout=30)
        r.raise_for_status()
        text = r.text.strip()
        if not text:
            return None
        try:
            return r.json()
        except Exception:
            try:
                return json.loads(text)
            except Exception:
                return text

    def _get_binary(self, path: str, params: dict = None) -> bytes:
        """GET → contenu binaire (GRIB2). Timeout 300s, lecture par chunks."""
        url = BASE_URL + path
        # connect_timeout=10s, read_timeout=300s
        r = self._session.get(url, params=params, timeout=(10, 300),
                              stream=True)
        r.raise_for_status()
        # Lecture par chunks pour ne pas bloquer indéfiniment
        chunks = []
        for chunk in r.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)

    # ---- capacités -------------------------------------------------- #

    def list_grids(self, territory: str) -> list[str]:
        """Retourne la liste des grilles disponibles (ex: ['0.025'])."""
        cfg = OM_TERRITORY_CONFIG[territory]
        data = self._get_json(f"/models/{cfg['model_code']}/grids")
        return _extract_grids(data)

    def list_packages(self, territory: str, grid: str) -> list[str]:
        """Retourne la liste des paquets pour un territoire+grille."""
        cfg = OM_TERRITORY_CONFIG[territory]
        data = self._get_json(
            f"/models/{cfg['model_code']}/grids/{grid}/packages")
        return _extract_packages(data)

    def get_capabilities(self, territory: str) -> dict:
        """
        Retourne la structure complète grilles + paquets pour l'UI.
        Résultat : {
            "grids":    ["0.025", ...],
            "grid":     "0.025",          ← grille par défaut (première)
            "packages": ["SP1", "SP2", ...],
            "territory": "ANTIL",
        }
        """
        grids_raw = self.list_grids(territory)
        if not grids_raw:
            return {"grids": [], "grid": None,
                    "packages": [], "territory": territory,
                    "raw_grids": grids_raw}

        grid = grids_raw[0]
        packages_raw = self.list_packages(territory, grid)

        return {
            "grids":     grids_raw,
            "grid":      grid,
            "packages":  packages_raw,
            "territory": territory,
            "raw_grids": grids_raw,
        }

    # ---- téléchargement --------------------------------------------- #

    def download_product(self, territory: str, grid: str, package: str,
                         referencetime: str, time_step: str) -> bytes:
        """
        Télécharge un paquet GRIB2.

        Args:
            territory:     code territoire ('ANTIL', …)
            grid:          identifiant grille (ex '0.025')
            package:       nom du paquet  (ex 'SP1')
            referencetime: ISO-8601 UTC   (ex '2024-03-01T00:00:00Z')
            time_step:     échéance format 'hhhH' (ex '001H', '024H')

        Returns:
            Bytes du fichier GRIB2.
        """
        cfg = OM_TERRITORY_CONFIG[territory]
        params = {
            "grid":          grid,
            "package":       package,
            "referencetime": referencetime,
            "time":          time_step,
            "format":        "grib2",
        }
        # Essaie d'abord via le REST path, puis via KVP si 404
        # Endpoint REST path (prioritaire)
        rest_path = (f"/models/{cfg['model_code']}/grids/{grid}"
                     f"/packages/{package}/{cfg['product_ep']}")
        rest_params = {"referencetime": referencetime,
                       "time": time_step, "format": "grib2"}

        # Si time=000H, l'analyse H+0 n'est pas toujours disponible → essai H+1
        time_candidates = [time_step]
        if time_step.upper() == "000H":
            time_candidates.append("001H")

        # Si le run actuel est trop récent, essayer le run précédent (−6h)
        try:
            ref_dt = datetime.datetime.strptime(
                referencetime, "%Y-%m-%dT%H:%M:%SZ")
            prev_ref = (ref_dt - datetime.timedelta(hours=6)
                        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            prev_ref = None
        ref_candidates = [referencetime]
        if prev_ref:
            ref_candidates.append(prev_ref)

        last_exc = None
        for ref in ref_candidates:
            for t in time_candidates:
                try:
                    return self._get_binary(
                        rest_path,
                        params={"referencetime": ref,
                                "time": t, "format": "grib2"})
                except requests.HTTPError as e:
                    last_exc = e
                    if e.response is None or e.response.status_code != 404:
                        raise
                    # 404 → essai suivant
                    continue

        # Tous les essais ont échoué → reraise
        if last_exc:
            raise last_exc


# ------------------------------------------------------------------ #
#  Décodage GRIB2 → DataFrame
# ------------------------------------------------------------------ #

def grib2_to_dataframes(grib_bytes: bytes) -> list[tuple[str, object]]:
    """
    Décode un fichier GRIB2 (bytes) en liste de (nom_variable, DataFrame).
    Chaque DataFrame a les colonnes : lat, lon, <variable>.

    Requiert : cfgrib, xarray (dépendances de meteole).
    """
    import cfgrib
    import pandas as pd
    import numpy as np

    tmp = tempfile.mktemp(suffix=".grib2")
    try:
        with open(tmp, "wb") as f:
            f.write(grib_bytes)

        try:
            datasets = cfgrib.open_datasets(
                tmp,
                backend_kwargs={"errors": "ignore"},
            )
        except Exception as cfgrib_err:
            # Retourner l'erreur comme variable spéciale pour diagnostic
            return [("_cfgrib_error_", str(cfgrib_err))]

        results = []
        for ds in datasets:
            for var in ds.data_vars:
                try:
                    da = ds[var]
                    # var peut être "unknown" → _flatten_dataarray tentera
                    # de récupérer le vrai nom depuis les attributs GRIB
                    df = _flatten_dataarray(da, var)
                    if df.empty:
                        continue
                    # Récupère le nom éventuellement corrigé par _flatten_dataarray
                    final_var = [c for c in df.columns
                                 if c not in ("lat", "lon")]
                    actual_var = final_var[0] if final_var else var
                    results.append((actual_var, df))
                except Exception:
                    continue

        return results

    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


def _flatten_dataarray(da, var_name: str):
    """
    Aplatit un DataArray xarray en DataFrame 2D (lat, lon, valeur).

    Gère proprement :
    - les dimensions supplémentaires (step, time, level, height...) →
      prend isel(dim=0) pour ne pas perdre les données
    - les longitudes 0-360 → -180/+180
    - les valeurs NaN/masked
    """
    import numpy as np
    import pandas as pd

    lat_dims = {"latitude", "lat", "y"}
    lon_dims = {"longitude", "lon", "x"}

    lat_dim = next((d for d in da.dims if d.lower() in lat_dims), None)
    lon_dim = next((d for d in da.dims if d.lower() in lon_dims), None)

    if lat_dim is None or lon_dim is None:
        return pd.DataFrame()

    # Tenter de récupérer le vrai nom depuis les attributs GRIB
    # (utile pour les variables "unknown" avec paramId non standard)
    attrs = da.attrs
    if var_name == "unknown":
        param_id  = attrs.get("GRIB_paramId",  attrs.get("paramId",  ""))
        short     = attrs.get("GRIB_shortName", attrs.get("shortName", ""))
        long_name = attrs.get("GRIB_name",      attrs.get("long_name",  ""))
        if short and short != "unknown":
            var_name = short
        elif param_id:
            var_name = f"param{param_id}"

    # Réduire les dimensions supplémentaires en prenant le premier indice
    extra_dims = [d for d in da.dims if d not in (lat_dim, lon_dim)]
    for dim in extra_dims:
        try:
            da = da.isel({dim: 0}, drop=True)
        except Exception:
            continue

    # Convertir en numpy pour éviter les artefacts xarray
    lats = da[lat_dim].values.astype(np.float64)
    lons = da[lon_dim].values.astype(np.float64)
    vals = da.values.astype(np.float64)

    # Normaliser les longitudes GRIB2 0-360 → -180/+180
    if lons.max() > 180:
        lons = np.where(lons > 180, lons - 360, lons)

    # Construire le DataFrame depuis la grille 2D
    if vals.ndim == 2:
        # (lat, lon) ou (lon, lat)
        if vals.shape == (len(lats), len(lons)):
            lon_grid, lat_grid = np.meshgrid(lons, lats)
        elif vals.shape == (len(lons), len(lats)):
            lat_grid, lon_grid = np.meshgrid(lats, lons)
            vals = vals.T
        else:
            return pd.DataFrame()

        flat_lat  = lat_grid.ravel()
        flat_lon  = lon_grid.ravel()
        flat_vals = vals.ravel()

    elif vals.ndim == 1:
        # Déjà aplati
        flat_lat  = lats if len(lats) == len(vals) else np.repeat(lats, len(lons))
        flat_lon  = lons if len(lons) == len(vals) else np.tile(lons, len(lats))
        flat_vals = vals
    else:
        return pd.DataFrame()

    df = pd.DataFrame({
        "lat": flat_lat,
        "lon": flat_lon,
        var_name: flat_vals,
    })

    # Supprimer NaN et valeurs manquantes GRIB (-9999, 9999, 1e20, 3.4e38...)
    df = df.dropna(subset=[var_name])
    FILL_THRESHOLD = 1e10
    df = df[df[var_name].abs() < FILL_THRESHOLD].reset_index(drop=True)

    return df



# ------------------------------------------------------------------ #
#  Helpers date/heure
# ------------------------------------------------------------------ #

def latest_referencetime() -> str:
    """
    Calcule le dernier run AROME-OM disponible :
    arrondi à 0h, 6h, 12h ou 18h UTC, avec 2h de délai de publication.
    """
    # Délai de 4h pour s'assurer que le run est publié
    now = datetime.datetime.utcnow() - datetime.timedelta(hours=4)
    run_hour = (now.hour // 6) * 6
    dt = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_timestep(hours: int) -> str:
    """Entier heures → format API 'hhhH' (ex: 1 → '001H', 24 → '024H')."""
    return f"{int(hours):03d}H"


def parse_timestep(s: str) -> int:
    """Format API 'hhhH' → entier heures (ex: '024H' → 24)."""
    return int(s.replace("H", "").replace("h", ""))
