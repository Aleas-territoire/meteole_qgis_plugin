# -*- coding: utf-8 -*-
"""
Utilitaires pour convertir les DataFrames meteole en couches QGIS.

v1.2 :
  - _make_points_file() et add_vigilance_dept_layer() utilisent sqlite3 pur
    → aucune dépendance à QgsVectorFileWriter dans les threads worker
    → compatible toutes versions QGIS (3.16+), Windows/Linux/Mac
  - Palettes de couleurs adaptées automatiquement au type d'indicateur météo
  - Noms de champs jusqu'à 63 caractères (limite GeoPackage)
"""

import os
import re
import tempfile

import numpy as np

from qgis.core import (
    QgsVectorLayer, QgsRasterLayer, QgsGeometry,
    QgsCoordinateReferenceSystem,
    QgsGraduatedSymbolRenderer, QgsStyle,
    QgsMarkerSymbol,
    QgsSingleBandPseudoColorRenderer, QgsColorRampShader,
    QgsRasterShader, QgsRasterBandStats,
    QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsFillSymbol,
)
from qgis.PyQt.QtGui import QColor


# Colonnes à exclure des champs attributaires
SKIP_COLS = {"run", "forecast_horizon", "forecast_time",
             "reference_time", "validity_time"}


# ------------------------------------------------------------------ #
#  Détection du type d'indicateur et palettes associées
# ------------------------------------------------------------------ #

def _detect_indicator_type(indicator_name: str) -> str:
    """
    Retourne un type sémantique depuis le nom de l'indicateur.
    Les noms meteole sont de la forme : TEMPERATURE__SPECIFIC_HEIGHT_LEVEL__ABOVE_GROUND__2
    """
    name = (indicator_name or "").upper()
    if any(k in name for k in ("TEMPERATURE", "TEMP", "T2M", "T_2M", "DEW_POINT")):
        return "temperature"
    if any(k in name for k in ("WIND", "WINDSPEED", "WIND_SPEED", "FF10", "RAFALE", "GUST",
                                "U_COMPONENT", "V_COMPONENT")):
        return "wind"
    if any(k in name for k in ("RAIN", "PRECIP", "PRECIPITATION", "RR", "SNOW", "NEIGE",
                                "TOTAL_PRECIPITATION", "RAIN_FALL")):
        return "precipitation"
    if any(k in name for k in ("PRESSURE", "PRESSION", "MSLP", "PMER", "MSL",
                                "MEAN_SEA_LEVEL")):
        return "pressure"
    if any(k in name for k in ("HUMIDITY", "HUMIDITE", "RELATIVE_HUMIDITY", "HR", "HU",
                                "SPECIFIC_HUMIDITY")):
        return "humidity"
    if any(k in name for k in ("CLOUD", "NUAGE", "NEBUL", "CLOUD_COVER", "TOTAL_CLOUD")):
        return "cloud"
    if any(k in name for k in ("CAPE", "CONVECT", "LIFTED", "CIN")):
        return "convection"
    return "generic"


# Table des unités GRIB2/CF pour les indicateurs Météo-France courants
# Valeurs brutes transmises telles quelles — aucune conversion effectuée
_UNIT_MAP = {
    # Températures (Kelvin — convention WMO/GRIB2)
    "TEMPERATURE":               "K",
    "DEW_POINT_TEMPERATURE":     "K",
    "POTENTIAL_TEMPERATURE":     "K",
    "WET_BULB_TEMPERATURE":      "K",
    # Vent
    "WIND_SPEED":                "m/s",
    "WIND_SPEED_OF_GUST":        "m/s",
    "U_COMPONENT_OF_WIND":       "m/s",
    "V_COMPONENT_OF_WIND":       "m/s",
    # Précipitations
    "TOTAL_PRECIPITATION":       "kg/m²",
    "RAIN_FALL_AMOUNT":          "kg/m²",
    "TOTAL_PRECIPITATION_RATE":  "kg/m²/s",
    "TOTAL_SNOW_PRECIPITATION":  "kg/m²",
    "SNOW_DEPTH":                "m",
    # Pression
    "PRESSURE":                  "Pa",
    "MEAN_SEA_LEVEL_PRESSURE":   "Pa",
    # Humidité
    "RELATIVE_HUMIDITY":         "%",
    "SPECIFIC_HUMIDITY":         "kg/kg",
    # Nébulosité
    "TOTAL_CLOUD_COVER":         "%",
    "LOW_CLOUD_COVER":           "%",
    "MEDIUM_CLOUD_COVER":        "%",
    "HIGH_CLOUD_COVER":          "%",
    # Énergie convective
    "CAPE":                      "J/kg",
    "CIN":                       "J/kg",
}


def _detect_unit(indicator_name: str) -> str:
    """
    Retourne l'unité physique de l'indicateur (convention GRIB2/CF).
    Aucune conversion n'est effectuée sur les données.
    Retourne '' si l'unité est inconnue.
    """
    name = (indicator_name or "").upper()
    # Cherche la correspondance la plus longue en premier (évite faux positifs)
    for key in sorted(_UNIT_MAP, key=len, reverse=True):
        if key in name:
            return _UNIT_MAP[key]
    return ""


def _get_color_ramp_items(ind_type: str, vmin: float, vmax: float, unit: str = ""):
    """
    Retourne une liste de QgsColorRampShader.ColorRampItem adaptée au type d'indicateur.
    """
    def lerp(frac): return vmin + (vmax - vmin) * frac

    # (fraction, couleur_hex)
    palettes = {
        # Bleu froid → blanc → rouge chaud  (températures)
        "temperature": [
            (0.00, "#053061"), (0.20, "#2166ac"), (0.40, "#92c5de"),
            (0.50, "#f7f7f7"), (0.65, "#fddbc7"), (0.80, "#d6604d"),
            (1.00, "#67001f"),
        ],
        # Blanc calme → bleu profond (vitesse de vent)
        "wind": [
            (0.00, "#ffffff"), (0.20, "#c7e9b4"), (0.40, "#41b6c4"),
            (0.60, "#2c7fb8"), (0.80, "#253494"), (1.00, "#081d58"),
        ],
        # Blanc sec → bleu intense → violet (précipitations)
        "precipitation": [
            (0.00, "#ffffff"), (0.15, "#c6dbef"), (0.35, "#6baed6"),
            (0.55, "#2171b5"), (0.75, "#084594"), (1.00, "#4d0099"),
        ],
        # Vert bas → violet haut  (pression atmosphérique)
        "pressure": [
            (0.00, "#40004b"), (0.25, "#762a83"), (0.50, "#c2a5cf"),
            (0.75, "#a6dba0"), (1.00, "#00441b"),
        ],
        # Brun sec → vert-bleu humide  (humidité relative)
        "humidity": [
            (0.00, "#8c510a"), (0.25, "#d8b365"), (0.50, "#f6e8c3"),
            (0.75, "#5ab4ac"), (1.00, "#003c30"),
        ],
        # Bleu ciel → gris blanc  (nébulosité)
        "cloud": [
            (0.00, "#2b83ba"), (0.30, "#abdda4"), (0.60, "#ffffbf"),
            (0.80, "#d7d7d7"), (1.00, "#ffffff"),
        ],
        # Jaune → rouge vif  (énergie convective CAPE)
        "convection": [
            (0.00, "#ffffcc"), (0.25, "#fed976"), (0.50, "#fd8d3c"),
            (0.75, "#e31a1c"), (1.00, "#800026"),
        ],
        # Spectral inversé (tout autre indicateur)
        "generic": [
            (0.00, "#2b83ba"), (0.25, "#abdda4"), (0.50, "#ffffbf"),
            (0.75, "#fdae61"), (1.00, "#d7191c"),
        ],
    }

    stops = palettes.get(ind_type, palettes["generic"])
    items = []
    for i, (frac, hex_color) in enumerate(stops):
        val = lerp(frac)
        if i == 0:
            lbl = f"{val:.2f} {unit}".strip()
        elif i == len(stops) - 1:
            lbl = f"{val:.2f} {unit}".strip()
        else:
            lbl = ""
        items.append(QgsColorRampShader.ColorRampItem(val, QColor(hex_color), lbl))
    return items


# ------------------------------------------------------------------ #
#  API publique : préparer (worker) + charger (UI thread)
# ------------------------------------------------------------------ #

def prepare_layer_files(df, layer_name: str, indicator_name: str = "") -> dict:
    """
    Crée les fichiers GeoTIFF + GPKG sur disque.
    DOIT être appelé depuis le QgsTask.run() (thread worker).
    Retourne un dict de chemins — aucun objet QGIS instancié ici.
    """
    lat_col, lon_col = _find_lat_lon(df)

    # Si le DataFrame contient encore plusieurs horizons, prend le premier
    if "forecast_horizon" in df.columns and df["forecast_horizon"].nunique() > 1:
        first_h = sorted(df["forecast_horizon"].unique())[0]
        df = df[df["forecast_horizon"] == first_h].copy()

    value_col = _guess_value_col(df, lat_col, lon_col)
    ind_type  = _detect_indicator_type(indicator_name or layer_name)
    unit      = _detect_unit(indicator_name or layer_name)

    # Suffixe l'unité dans le nom de couche si connue
    display_name = f"{layer_name} [{unit}]" if unit else layer_name

    result = {
        "layer_name":   display_name,
        "value_col":    value_col,
        "ind_type":     ind_type,
        "unit":         unit,
        "raster_path":  None,
        "points_path":  None,
        "error":        None,
    }

    # --- Raster GeoTIFF ---
    try:
        result["raster_path"] = _make_raster(df, lat_col, lon_col, value_col)
    except Exception as e:
        result["error"] = f"Raster : {e}"

    # --- Points GPKG (sous-échantillonné pour les gros datasets) ---
    try:
        MAX_POINTS = 80_000
        df_pts = df
        if len(df) > MAX_POINTS:
            step = max(1, len(df) // MAX_POINTS)
            df_pts = df.iloc[::step].reset_index(drop=True)
        result["points_path"] = _make_points_file(df_pts, lat_col, lon_col,
                                                   value_col, layer_name)
    except Exception as e:
        result["error"] = (result["error"] or "") + f" | Points : {e}"

    return result


def load_layers_from_files(file_info: dict):
    """
    Instancie les couches QGIS depuis les fichiers préparés et applique les styles.
    DOIT être appelé depuis le thread principal (signal finished / _on_forecast_done).
    """
    layers = []
    layer_name = file_info["layer_name"]
    value_col  = file_info["value_col"]
    ind_type   = file_info["ind_type"]
    unit       = file_info.get("unit", "")

    if file_info.get("raster_path"):
        lyr = QgsRasterLayer(file_info["raster_path"], layer_name + " (raster)")
        if lyr.isValid():
            _style_raster(lyr, ind_type, unit)
            layers.append(lyr)

    if file_info.get("points_path"):
        lyr = QgsVectorLayer(file_info["points_path"], layer_name + " (points)", "ogr")
        if lyr.isValid():
            _style_points(lyr, value_col)
            layers.append(lyr)

    return layers


# Rétrocompatibilité
def add_dataframe_as_layer(df, layer_name: str, indicator_name: str = ""):
    """Wrapper synchrone (thread principal). Pour compatibilité ascendante."""
    info = prepare_layer_files(df, layer_name, indicator_name)
    if not info["raster_path"] and not info["points_path"]:
        raise RuntimeError(
            f"Impossible de créer les couches pour {layer_name}: {info['error']}")
    return load_layers_from_files(info)


# ------------------------------------------------------------------ #
#  Raster GeoTIFF via GDAL
# ------------------------------------------------------------------ #

def _make_raster(df, lat_col, lon_col, value_col) -> str:
    from osgeo import gdal, osr

    lats = df[lat_col].values.astype(np.float64)
    lons = df[lon_col].values.astype(np.float64)
    vals = df[value_col].values.astype(np.float64)

    lat_unique = np.unique(lats)[::-1]   # Nord en haut
    lon_unique = np.unique(lons)
    nrows, ncols = len(lat_unique), len(lon_unique)

    if nrows < 2 or ncols < 2:
        raise ValueError("Grille trop petite (< 2×2) pour créer un raster.")

    NODATA = -9999.0
    grid = np.full((nrows, ncols), NODATA, dtype=np.float32)

    lat_idx = {round(float(v), 6): i for i, v in enumerate(lat_unique)}
    lon_idx = {round(float(v), 6): i for i, v in enumerate(lon_unique)}

    for lat, lon, val in zip(lats, lons, vals):
        r = lat_idx.get(round(float(lat), 6))
        c = lon_idx.get(round(float(lon), 6))
        if r is not None and c is not None and np.isfinite(val):
            grid[r, c] = float(val)

    dx = float(lon_unique[1] - lon_unique[0]) if ncols > 1 else 0.01
    dy = float(lat_unique[0] - lat_unique[1]) if nrows > 1 else 0.01

    tmp_path = tempfile.mktemp(suffix=".tif")
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(tmp_path, ncols, nrows, 1, gdal.GDT_Float32,
                       ["COMPRESS=LZW", "TILED=YES"])
    ds.SetGeoTransform([lon_unique.min() - dx / 2, dx, 0,
                        lat_unique.max() + dy / 2, 0, -dy])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(NODATA)
    band.WriteArray(grid)
    band.FlushCache()
    ds.FlushCache()
    ds = None
    return tmp_path


def _style_raster(layer: QgsRasterLayer, ind_type: str, unit: str = ""):
    """Style pseudocouleur adapté au type d'indicateur météo."""
    try:
        provider = layer.dataProvider()
        stats    = provider.bandStatistics(1, QgsRasterBandStats.All)
        vmin, vmax = stats.minimumValue, stats.maximumValue
        if vmin == vmax:
            vmax = vmin + 1  # évite division par zéro

        ramp_items = _get_color_ramp_items(ind_type, vmin, vmax, unit)

        color_ramp = QgsColorRampShader()
        color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
        color_ramp.setColorRampItemList(ramp_items)

        shader = QgsRasterShader()
        shader.setRasterShaderFunction(color_ramp)

        renderer = QgsSingleBandPseudoColorRenderer(
            layer.dataProvider(), 1, shader)
        layer.setRenderer(renderer)
        layer.setOpacity(0.82)
        layer.triggerRepaint()
    except Exception:
        pass


# ------------------------------------------------------------------ #
#  Couche points GPKG — écriture sqlite3 pure (thread-safe, toutes versions QGIS)
# ------------------------------------------------------------------ #

def _make_points_file(df, lat_col, lon_col, value_col, layer_name: str) -> str:
    """
    Crée un GeoPackage de points avec sqlite3 pur.
    Aucune dépendance à QgsVectorFileWriter → fonctionne depuis un QgsTask
    et sur toutes les versions de QGIS (3.16+).
    """
    import sqlite3
    import struct

    def _wkb_point(x: float, y: float) -> bytes:
        """Encode un point en WKB little-endian (ISO WKB, type 1 = Point)."""
        return struct.pack("<bIdd", 1, 1, x, y)

    def _gpkg_geom(x: float, y: float) -> bytes:
        """Enveloppe WKB dans un en-tête GeoPackage (GPKG geometry blob)."""
        # Magic: 'GP', version=0, flags=1 (little-endian, enveloppe vide)
        # srs_id = 4326
        header = struct.pack("<2sBBI", b"GP", 0, 1, 4326)
        return header + _wkb_point(x, y)

    data_cols = [c for c in df.columns
                 if c not in (lat_col, lon_col) and c.lower() not in SKIP_COLS]
    # Noms de colonnes tronqués à 63 chars (limite GeoPackage)
    col_map = {c: c[:63] for c in data_cols}

    tmp_dir   = tempfile.mkdtemp()
    gpkg_path = os.path.join(tmp_dir, f"{_safe_name(layer_name)}.gpkg")

    con = sqlite3.connect(gpkg_path)
    cur = con.cursor()

    # --- Tables obligatoires du standard GeoPackage ---
    cur.executescript("""
        PRAGMA application_id = 1196444487;
        PRAGMA user_version   = 10200;

        CREATE TABLE IF NOT EXISTS gpkg_spatial_ref_sys (
            srs_name                 TEXT    NOT NULL,
            srs_id                   INTEGER NOT NULL PRIMARY KEY,
            organization             TEXT    NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition               TEXT    NOT NULL,
            description              TEXT
        );
        CREATE TABLE IF NOT EXISTS gpkg_contents (
            table_name  TEXT     NOT NULL PRIMARY KEY,
            data_type   TEXT     NOT NULL,
            identifier  TEXT,
            description TEXT     DEFAULT '',
            last_change DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x       REAL, min_y REAL, max_x REAL, max_y REAL,
            srs_id      INTEGER,
            FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
        );
        CREATE TABLE IF NOT EXISTS gpkg_geometry_columns (
            table_name         TEXT NOT NULL,
            column_name        TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id             INTEGER NOT NULL,
            z                  INTEGER NOT NULL,
            m                  INTEGER NOT NULL,
            PRIMARY KEY (table_name, column_name),
            FOREIGN KEY (table_name) REFERENCES gpkg_contents(table_name),
            FOREIGN KEY (srs_id) REFERENCES gpkg_spatial_ref_sys(srs_id)
        );
    """)

    # SRS WGS84
    cur.execute("""
        INSERT OR IGNORE INTO gpkg_spatial_ref_sys
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("WGS 84 geographic 2D", 4326, "EPSG", 4326,
          'GEOGCS["WGS 84",DATUM["WGS_1984",'
          'SPHEROID["WGS 84",6378137,298.257223563]],'
          'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
          "WGS 84"))

    # --- Table de données ---
    tbl = "points"

    # Détermine le type SQLite pour chaque colonne
    def _sqlite_type(dtype_str):
        if dtype_str.startswith("float"):  return "REAL"
        if dtype_str.startswith("int"):    return "INTEGER"
        return "TEXT"

    col_defs = ", ".join(
        f'"{col_map[c]}" {_sqlite_type(str(df[c].dtype))}'
        for c in data_cols
    )
    cur.execute(
        f'CREATE TABLE "{tbl}" (fid INTEGER PRIMARY KEY AUTOINCREMENT, '
        f'geom BLOB{", " + col_defs if col_defs else ""})'
    )

    # Métadonnées GeoPackage
    lats_arr = df[lat_col].values.astype(float)
    lons_arr = df[lon_col].values.astype(float)
    cur.execute("""
        INSERT INTO gpkg_contents VALUES (?, 'features', ?, '', NULL, ?, ?, ?, ?, 4326)
    """, (tbl, tbl,
          float(np.nanmin(lons_arr)), float(np.nanmin(lats_arr)),
          float(np.nanmax(lons_arr)), float(np.nanmax(lats_arr))))
    cur.execute("""
        INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', 'POINT', 4326, 0, 0)
    """, (tbl,))

    # --- Insertion des points en batch ---
    col_names = ", ".join(f'"{col_map[c]}"' for c in data_cols)
    placeholders = ", ".join("?" for _ in range(len(data_cols) + 1))  # +1 pour geom
    insert_sql = (
        f'INSERT INTO "{tbl}" (geom{", " + col_names if col_names else ""})'
        f' VALUES ({placeholders})'
    )

    rows = []
    for i in range(len(df)):
        geom_blob = _gpkg_geom(float(lons_arr[i]), float(lats_arr[i]))
        row = [geom_blob]
        for c in data_cols:
            val = df[c].iloc[i]
            dtype = str(df[c].dtype)
            try:
                if dtype.startswith("float"):
                    row.append(None if not np.isfinite(float(val)) else float(val))
                elif dtype.startswith("int"):
                    row.append(int(val))
                else:
                    row.append(str(val))
            except Exception:
                row.append(None)
        rows.append(row)
        # Commit par batch de 5000
        if len(rows) == 5000:
            cur.executemany(insert_sql, rows)
            rows = []

    if rows:
        cur.executemany(insert_sql, rows)

    con.commit()
    con.close()
    return gpkg_path


def _style_points(layer: QgsVectorLayer, value_col: str):
    """Points graduels (Jenks) sans contour, 55 % transparents, Ø 2 px."""
    try:
        field    = value_col[:63]
        renderer = QgsGraduatedSymbolRenderer(field)
        renderer.setClassAttribute(field)
        renderer.updateClasses(layer, QgsGraduatedSymbolRenderer.Jenks, 7)

        color_ramp = QgsStyle.defaultStyle().colorRamp("RdYlBu")
        if color_ramp:
            renderer.updateColorRamp(color_ramp)

        for i, range_item in enumerate(renderer.ranges()):
            sym = QgsMarkerSymbol.createSimple({
                "name":          "circle",
                "size":          "2.0",
                "color":         range_item.symbol().color().name(),
                "outline_style": "no",
                "outline_color": "0,0,0,0",
                "outline_width": "0",
            })
            sym.setOpacity(0.55)
            renderer.updateRangeSymbol(i, sym)

        layer.setRenderer(renderer)
        layer.triggerRepaint()
    except Exception:
        pass


# ------------------------------------------------------------------ #
#  Vigilance département
# ------------------------------------------------------------------ #

def add_vigilance_layer(df, layer_name: str):
    if df is None or len(df) == 0:
        return None
    tmp_dir  = tempfile.mkdtemp()
    csv_path = os.path.join(tmp_dir, f"{_safe_name(layer_name)}.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8")
    uri = f"file:///{csv_path}?delimiter=,&encoding=utf-8"
    lyr = QgsVectorLayer(uri, layer_name, "delimitedtext")
    return lyr if lyr.isValid() else None


def add_vigilance_dept_layer(df_time, df_phen,
                              layer_name="⚠️ Vigilance par département"):
    import json

    geojson_path = os.path.join(os.path.dirname(__file__), "departements.geojson")
    with open(geojson_path, encoding="utf-8") as f:
        geojson = json.load(f)

    df_j = (df_time[df_time["echeance"] == "J"].copy()
            if "echeance" in df_time.columns else df_time.copy())

    color_map = {}
    for _, row in df_j.iterrows():
        did = str(row["domain_id"]).zfill(2)
        cid = int(row.get("max_color_id", 1))
        color_map[did] = max(color_map.get(did, 1), cid)

    tmp_dir   = tempfile.mkdtemp()
    gpkg_path = os.path.join(tmp_dir, "vigilance_depts.gpkg")

    COLOR_NAME = {1: "Vert", 2: "Jaune", 3: "Orange", 4: "Rouge"}

    # Écriture sqlite3 pure (thread-safe, toutes versions QGIS)
    import sqlite3
    con = sqlite3.connect(gpkg_path)
    cur = con.cursor()
    cur.executescript("""
        PRAGMA application_id = 1196444487;
        PRAGMA user_version   = 10200;
        CREATE TABLE gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL, description TEXT);
        CREATE TABLE gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
            identifier TEXT, description TEXT DEFAULT '',
            last_change DATETIME DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            min_x REAL, min_y REAL, max_x REAL, max_y REAL, srs_id INTEGER);
        CREATE TABLE gpkg_geometry_columns (
            table_name TEXT NOT NULL, column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
            z INTEGER NOT NULL, m INTEGER NOT NULL,
            PRIMARY KEY (table_name, column_name));
        CREATE TABLE depts (
            fid INTEGER PRIMARY KEY AUTOINCREMENT,
            geom BLOB, code TEXT, nom TEXT, couleur_id INTEGER, couleur TEXT);
    """)
    cur.execute("""INSERT OR IGNORE INTO gpkg_spatial_ref_sys VALUES
        ('WGS 84',4326,'EPSG',4326,
        'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],
PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',NULL)""")
    cur.execute("""INSERT INTO gpkg_contents VALUES
        ('depts','features','depts','',NULL,-5.5,41.0,10.0,51.5,4326)""")
    cur.execute("""INSERT INTO gpkg_geometry_columns VALUES
        ('depts','geom','MULTIPOLYGON',4326,0,0)""")

    for feat_data in geojson["features"]:
        code = feat_data["properties"]["code"]
        nom  = feat_data["properties"]["nom"]
        cid  = color_map.get(code, 1)
        wkt  = _polygon_coords_to_wkt(feat_data["geometry"])
        if not wkt:
            continue
        # Encode la géométrie en WKB via QgsGeometry (thread principal, appelé depuis dialog)
        from qgis.core import QgsGeometry
        geom = QgsGeometry.fromWkt(wkt)
        geom_wkb = bytes(geom.asWkb())
        # En-tête GeoPackage minimal
        import struct
        gpkg_header = struct.pack("<2sBBI", b"GP", 0, 1, 4326)
        cur.execute(
            "INSERT INTO depts (geom, code, nom, couleur_id, couleur) VALUES (?,?,?,?,?)",
            (gpkg_header + geom_wkb, code, nom, cid, COLOR_NAME[cid])
        )

    con.commit()
    con.close()

    lyr = QgsVectorLayer(gpkg_path, layer_name, "ogr")
    if lyr.isValid():
        _style_vigilance_layer(lyr)
    return lyr if lyr.isValid() else None


def _polygon_coords_to_wkt(geometry):
    gtype  = geometry["type"]
    coords = geometry["coordinates"]
    if gtype == "Polygon":
        rings = ", ".join(
            "(" + ", ".join(f"{x} {y}" for x, y in ring) + ")"
            for ring in coords)
        return f"POLYGON({rings})"
    elif gtype == "MultiPolygon":
        polys = [
            "(" + ", ".join(
                "(" + ", ".join(f"{x} {y}" for x, y in ring) + ")"
                for ring in poly) + ")"
            for poly in coords]
        return f"MULTIPOLYGON({', '.join(polys)})"
    return None


def _style_vigilance_layer(layer: QgsVectorLayer):
    COLORS = {
        "Vert":   ("#1a9641", 0.5),
        "Jaune":  ("#ffff00", 0.7),
        "Orange": ("#ff7f00", 0.85),
        "Rouge":  ("#d7191c", 0.9),
    }
    categories = []
    for label, (color, opacity) in COLORS.items():
        sym = QgsFillSymbol.createSimple({
            "color":         color,
            "outline_color": "#555555",
            "outline_width": "0.3",
        })
        sym.setOpacity(opacity)
        categories.append(QgsRendererCategory(label, sym, label))

    renderer = QgsCategorizedSymbolRenderer("couleur", categories)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


# ------------------------------------------------------------------ #
#  Helpers internes
# ------------------------------------------------------------------ #

def _find_lat_lon(df):
    lat_col = lon_col = None
    for c in df.columns:
        low = c.lower()
        if low in ("latitude", "lat"):
            lat_col = c
        elif low in ("longitude", "lon", "long"):
            lon_col = c
    if not lat_col or not lon_col:
        raise RuntimeError(
            f"Colonnes lat/lon introuvables. Colonnes : {df.columns.tolist()}")
    return lat_col, lon_col


def _guess_value_col(df, lat_col, lon_col):
    skip = {lat_col.lower(), lon_col.lower()} | SKIP_COLS
    for col in df.columns:
        if col.lower() in skip:
            continue
        if str(df[col].dtype).startswith(("float", "int")):
            return col
    return df.columns[-1]


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name)[:60]
