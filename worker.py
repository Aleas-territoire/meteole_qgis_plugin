# -*- coding: utf-8 -*-
"""
Worker basé sur QgsTask (API QGIS native) — stable sur Windows.

Améliorations v1.1 :
  - La création des fichiers GeoTIFF + GPKG se fait dans run() (thread worker)
    → plus de freeze de l'interface lors du chargement de gros datasets
  - Le résultat contient des "file_info" (chemins disque) et non des DataFrames
  - Retourne l'indicateur et l'horizon pour chaque couche (utile pour le slider)

Gestion du token Météo-France :
  Le token généré sur portail-api.meteofrance.fr dure 1 heure.
  meteole tente de le renouveler via application_id ; si absent, on intercepte
  l'erreur et on demande à l'utilisateur de régénérer un token.
"""

import datetime
import tempfile
import os

from qgis.core import QgsTask, QgsApplication
from qgis.PyQt.QtCore import pyqtSignal

from .layer_utils import prepare_layer_files

TOKEN_EXPIRED_MSG = (
    "Votre token Météo-France a expiré (durée de vie : 1 heure).\n\n"
    "Pour continuer :\n"
    "1. Allez sur portail-api.meteofrance.fr\n"
    "2. Cliquez sur 'Générer token' pour votre API\n"
    "3. Collez le nouveau token dans le plugin et relancez."
)


class MeteoleTask(QgsTask):
    """Tâche QGIS native pour les appels API meteole."""

    task_finished = pyqtSignal(dict)
    task_error    = pyqtSignal(str)

    def __init__(self, auth_key, task_name, auth_mode="token", **kwargs):
        super().__init__(f"Meteole – {task_name}", QgsTask.CanCancel)
        self.auth_key  = auth_key.strip()
        self.auth_mode = auth_mode
        self.task_name = task_name
        self.kwargs    = kwargs
        self._result   = None
        self._error    = None

    # ------------------------------------------------------------------ #
    #  QgsTask interface
    # ------------------------------------------------------------------ #

    def run(self):
        try:
            if self.task_name == "capabilities":
                self._result = self._get_capabilities()
            elif self.task_name == "forecast":
                self._result = self._get_forecast()
            elif self.task_name == "vigilance":
                self._result = self._get_vigilance()
            else:
                raise ValueError(f"Tâche inconnue : {self.task_name}")
            return True
        except Exception as e:
            self._error = self._format_error(e)
            return False

    def _format_error(self, e) -> str:
        """Traduit les erreurs API courantes en messages lisibles."""
        import traceback
        msg = str(e)

        # Erreur 900908 : abonnement manquant pour ce modèle
        if "900908" in msg or "Resource forbidden" in msg:
            model = self.kwargs.get("model", "ce modèle")
            return (
                f"Accès refusé à l'API « {model} » (erreur 900908).\n\n"
                f"Votre compte n'est pas abonné à cette API sur le portail Météo-France.\n\n"
                f"➡ Connectez-vous sur portail-api.meteofrance.fr\n"
                f"  → 'Mes APIs' → vérifiez que « {model.upper()} » est bien souscrit.\n\n"
                f"Note : AROME et AROME-PE sont deux APIs distinctes nécessitant "
                f"des abonnements séparés."
            )

        # Token expiré
        if ("application_id" in msg and "unknown" in msg) or "401" in msg or "token" in msg.lower():
            return TOKEN_EXPIRED_MSG

        # Indicateur invalide
        if "Unknown `indicator`" in msg:
            indicator = self.kwargs.get("indicator", "?")
            model = self.kwargs.get("model", "?")
            return (
                f"Indicateur invalide : « {indicator} » n'existe pas pour le modèle {model}.\n\n"
                f"Utilisez 'Lister les indicateurs' pour voir la liste disponible."
            )

        # Erreur générique avec traceback complet dans le journal
        return f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"

    def finished(self, result):
        if result and self._result is not None:
            self.task_finished.emit(self._result)
        else:
            self.task_error.emit(self._error or "Tâche annulée.")

    # ------------------------------------------------------------------ #
    #  Capacités
    # ------------------------------------------------------------------ #

    def _get_capabilities(self):
        client = self._make_client(self.kwargs["model"])
        df_cap = client.get_capabilities()
        # Colonnes retournées par meteole v0.2.x :
        # ['title', 'id', 'subtype', 'indicator', 'run', 'interval']
        for col in ("indicator", "id", "coverage_id"):
            if col in df_cap.columns:
                indicators = sorted(df_cap[col].dropna().unique().tolist())
                if indicators:
                    return {"indicators": indicators}
        return {"indicators": sorted(df_cap.iloc[:, 0].dropna().unique().tolist())}

    # ------------------------------------------------------------------ #
    #  Prévisions — création des fichiers dans le thread
    # ------------------------------------------------------------------ #

    def _get_forecast(self):
        model             = self.kwargs.get("model")
        indicator         = self.kwargs.get("indicator")
        run               = self.kwargs.get("run")
        forecast_horizons = self.kwargs.get("forecast_horizons", [1])
        lon               = self.kwargs.get("lon")
        lat               = self.kwargs.get("lat")
        heights           = self.kwargs.get("heights")
        pressures         = self.kwargs.get("pressures")
        ensemble_numbers  = self.kwargs.get("ensemble_numbers")

        client = self._make_client(model)

        if model in ("arome_instantane", "piaf"):
            horizons_td = [datetime.timedelta(minutes=h * 60)
                           for h in forecast_horizons]
        else:
            horizons_td = [datetime.timedelta(hours=h)
                           for h in forecast_horizons]

        kw = dict(indicator=indicator)
        if run:                              kw["run"]              = run
        if lon:                              kw["long"]             = lon   # meteole: 'long' pas 'lon'
        if lat:                              kw["lat"]              = lat
        if heights and len(heights) > 0:     kw["heights"]          = heights
        if pressures and len(pressures) > 0: kw["pressures"]        = pressures
        if ensemble_numbers is not None:     kw["ensemble_numbers"] = ensemble_numbers
        if forecast_horizons and self.kwargs.get("horizons_explicit"):
            kw["forecast_horizons"] = horizons_td

        df = client.get_coverage(**kw)

        # Détecte la colonne horizon (nom variable selon version meteole)
        horizon_col = next(
            (c for c in df.columns
             if "horizon" in c.lower() or c in ("time", "forecast_time")),
            None
        )

        # Décompose par horizon → un file_info par horizon
        layer_files = []

        if horizon_col and df[horizon_col].nunique() > 1:
            for h_val, sub in df.groupby(horizon_col):
                h_str = (str(h_val)
                         .replace(":", "h")
                         .replace(" ", "_")
                         .replace(",", "")[:20])
                label = f"{indicator[:30]}__{h_str}"
                info  = prepare_layer_files(
                    sub.reset_index(drop=True), label, indicator)
                info["horizon_label"] = h_str
                info["indicator"]     = indicator
                layer_files.append(info)
        else:
            label = f"{indicator[:40]}"
            info  = prepare_layer_files(df, label, indicator)
            info["horizon_label"] = ""
            info["indicator"]     = indicator
            layer_files.append(info)

        return {"layer_files": layer_files, "indicator": indicator}

    # ------------------------------------------------------------------ #
    #  Vigilance
    # ------------------------------------------------------------------ #

    def _get_vigilance(self):
        vigi   = self._make_vigilance_client()
        result = {}

        if self.kwargs.get("load_phenomenon") or self.kwargs.get("load_timelaps"):
            df_phen, df_time = vigi.get_phenomenon()
            if self.kwargs.get("load_phenomenon"): result["phenomenon"] = df_phen
            if self.kwargs.get("load_timelaps"):   result["timelaps"]   = df_time

        if self.kwargs.get("load_vignette"):
            tmp = tempfile.mkdtemp()
            try:
                import threading
                vignette_error = [None]

                def _download():
                    try:
                        vigi.get_vignette(output_dir=tmp)
                    except TypeError:
                        try:
                            vigi.get_vignette()
                        except Exception as e:
                            vignette_error[0] = str(e)
                    except Exception as e:
                        vignette_error[0] = str(e)

                t = threading.Thread(target=_download, daemon=True)
                t.start()
                t.join(timeout=30)

                if t.is_alive():
                    result["vignette_error"] = (
                        "Timeout : la vignette n'a pas pu être téléchargée en 30 s")
                elif vignette_error[0]:
                    result["vignette_error"] = vignette_error[0]
                else:
                    for f in os.listdir(tmp):
                        if f.endswith(".png"):
                            png_path  = os.path.join(tmp, f)
                            georef    = self._georeference_png(png_path, tmp)
                            result["vignette_path"] = georef
                            break
            except Exception as e:
                result["vignette_error"] = str(e)

        return result

    def _georeference_png(self, png_path, tmp_dir):
        try:
            from osgeo import gdal, osr
            WEST, EAST, SOUTH, NORTH = -5.5, 10.0, 41.0, 51.5
            src_ds = gdal.Open(png_path)
            if src_ds is None:
                return png_path
            ncols, nrows, nbands = (src_ds.RasterXSize,
                                     src_ds.RasterYSize,
                                     src_ds.RasterCount)
            out_path = os.path.join(tmp_dir, "vigilance_georef.tif")
            driver   = gdal.GetDriverByName("GTiff")
            out_ds   = driver.Create(out_path, ncols, nrows, nbands,
                                     gdal.GDT_Byte)
            dx = (EAST - WEST)  / ncols
            dy = (NORTH - SOUTH) / nrows
            out_ds.SetGeoTransform([WEST, dx, 0, NORTH, 0, -dy])
            srs = osr.SpatialReference()
            srs.ImportFromEPSG(4326)
            out_ds.SetProjection(srs.ExportToWkt())
            for b in range(1, nbands + 1):
                out_ds.GetRasterBand(b).WriteArray(
                    src_ds.GetRasterBand(b).ReadAsArray())
            out_ds.FlushCache()
            src_ds = out_ds = None
            return out_path
        except Exception:
            return png_path

    # ------------------------------------------------------------------ #
    #  Auth / factory
    # ------------------------------------------------------------------ #

    def _auth_kwargs(self):
        return {self.auth_mode: self.auth_key}

    def _make_client(self, model_key):
        from meteole import (AromeForecast, ArpegeForecast,
                              AromePEForecast, AromePIForecast, PiafForecast)
        try:
            from meteole import ArpegePEForecast
        except ImportError:
            ArpegePEForecast = None

        mapping = {
            "arome":            AromeForecast,
            "arpege":           ArpegeForecast,
            "arome_pe":         AromePEForecast,
            "arpege_pe":        ArpegePEForecast,
            "arome_instantane": AromePIForecast,
            "piaf":             PiafForecast,
        }
        cls = mapping.get(model_key)
        if cls is None:
            raise ValueError(
                f"Modèle non disponible dans cette version de meteole : {model_key}")
        client = cls(**self._auth_kwargs())
        self._patch_client(client)
        return client

    def _make_vigilance_client(self):
        from meteole import Vigilance
        client = Vigilance(**self._auth_kwargs())
        self._patch_client(client)
        return client

    @staticmethod
    def _patch_client(client):
        """
        Patch meteole v0.2.x : empêche le renouvellement automatique du token.
        """
        import types
        inner = None
        for attr in ("_client", "_api_client", "_http_client"):
            candidate = getattr(client, attr, None)
            if candidate is not None and hasattr(candidate, "_token_expired"):
                inner = candidate
                break
        if inner is None and hasattr(client, "_token_expired"):
            inner = client
        if inner is None:
            return
        original_get = inner.__class__.get

        def patched_get(self, path, *, params=None, max_retries=5):
            self._token_expired = False
            return original_get(self, path, params=params, max_retries=max_retries)

        inner.get = types.MethodType(patched_get, inner)


# Alias pour dialog.py
MeteoleWorker = MeteoleTask
