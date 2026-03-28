# -*- coding: utf-8 -*-
"""
Worker basé sur QgsTask (API QGIS native) — stable sur Windows.

v1.1 : création GeoTIFF + GPKG dans le thread worker
v1.2 : sélecteur de territoire AROME, passage territory= à meteole
v1.3 : client AROME-OM natif pour les territoires ultramarins.
       L\'API DPPaquetAROME-OM (https://public-api.meteofrance.fr/previnum/...)
       est une API REST distincte de l\'API WCS métropole.
       Elle retourne du GRIB2 organisé en grilles + paquets d\'indicateurs.
       Source : swagger officiel DPPaquetAROME-OM v1
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
    "2. Cliquez sur \'Générer token\' pour votre API\n"
    "3. Collez le nouveau token dans le plugin et relancez."
)

# ------------------------------------------------------------------ #
#  Configuration API AROME-OM outremer
# ------------------------------------------------------------------ #
AROME_OM_BASE = "https://public-api.meteofrance.fr/previnum/DPPaquetAROME-OM/v1"

AROME_OM_TERRITORY = {
    "ANTIL":  ("AROME-OM-ANTIL",  "productOMAN"),
    "GUYANE": ("AROME-OM-GUYANE", "productOMGU"),
    "INDIEN": ("AROME-OM-INDIEN", "productOMOI"),
    "NCALED": ("AROME-OM-NCALED", "productOMNC"),
    "POLYN":  ("AROME-OM-POLYN",  "productOMPF"),
}

AROME_METRO_TERRITORIES = {"FRANCE"}


class MeteoleTask(QgsTask):
    task_finished = pyqtSignal(dict)
    task_error    = pyqtSignal(str)

    def __init__(self, auth_key, task_name, auth_mode="token", **kwargs):
        super().__init__(f"Meteole \u2013 {task_name}", QgsTask.CanCancel)
        self.auth_key  = auth_key.strip()
        self.auth_mode = auth_mode
        self.task_name = task_name
        self.kwargs    = kwargs
        self._result   = None
        self._error    = None

    def run(self):
        try:
            territory = self.kwargs.get("territory", "FRANCE")
            is_om     = territory not in AROME_METRO_TERRITORIES
            if self.task_name == "capabilities":
                self._result = (self._get_capabilities_om()
                                if is_om else self._get_capabilities())
            elif self.task_name == "forecast":
                self._result = (self._get_forecast_om()
                                if is_om else self._get_forecast())
            elif self.task_name == "vigilance":
                self._result = self._get_vigilance()
            elif self.task_name == "probe_urls":
                self._result = self._probe_urls()
            elif self.task_name == "om_capabilities":
                self._result = self._get_om_capabilities()
            elif self.task_name == "om_forecast":
                self._result = self._get_om_forecast()
            elif self.task_name == "om_list_variables":
                self._result = self._get_om_list_variables()
            else:
                raise ValueError(f"Tâche inconnue : {self.task_name}")
            return True
        except Exception as e:
            self._error = self._format_error(e)
            return False

    def _format_error(self, e) -> str:
        import traceback
        msg = str(e)
        if "900908" in msg or "Resource forbidden" in msg:
            territory = self.kwargs.get("territory", "FRANCE") or "FRANCE"
            note = ""
            if territory != "FRANCE":
                note = (f"\n\nPour le territoire \'{territory}\', l\'API utilisée est "
                        f"DPPaquetAROME-OM. Vérifiez votre abonnement sur le portail.")
            return f"Accès refusé (erreur 900908).\n\n➡ portail-api.meteofrance.fr → \'Mes APIs\'{note}"
        if (("application_id" in msg and "unknown" in msg)
                or "401" in msg or "token" in msg.lower()):
            return TOKEN_EXPIRED_MSG
        if "Unknown `indicator`" in msg:
            ind = self.kwargs.get("indicator", "?")
            return f"Indicateur invalide : {ind}\n\nUtilisez 'Lister les indicateurs'."
        diag_url = getattr(self, "_diag_url", None)
        url_info = f"\n\nURL tentee : {diag_url}" if diag_url else ""
        return f"{type(e).__name__}: {e}{url_info}\n\n{traceback.format_exc()}"

    def finished(self, result):
        if result and self._result is not None:
            self.task_finished.emit(self._result)
        else:
            self.task_error.emit(self._error or "Tâche annulée.")

    # ================================================================== #
    #  AROME-OM outremer
    # ================================================================== #

    def _om_headers(self):
        if self.auth_mode == "api_key":
            return {"apikey": self.auth_key, "Accept": "text/json"}
        return {"Authorization": f"Bearer {self.auth_key}", "Accept": "text/json"}

    def _om_get_json(self, path, params=None):
        import requests, json
        url = AROME_OM_BASE + path
        self._diag_url = url
        r = requests.get(url, headers=self._om_headers(), params=params, timeout=30)
        if r.status_code == 401:
            raise RuntimeError(TOKEN_EXPIRED_MSG)
        if r.status_code == 403:
            raise RuntimeError(
                f"Accès refusé (HTTP 403) : {url}\n"
                "Vérifiez votre abonnement DPPaquetAROME-OM sur portail-api.meteofrance.fr.")
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} : {url}\n{r.text[:300]}")
        try:
            return json.loads(r.text)
        except Exception:
            return r.text

    def _om_model_code(self):
        territory = self.kwargs.get("territory", "ANTIL")
        entry = AROME_OM_TERRITORY.get(territory)
        if not entry:
            raise ValueError(f"Territoire \'{territory}\' non supporté. "
                             f"Valides : {list(AROME_OM_TERRITORY.keys())}")
        return entry

    def _get_capabilities_om(self):
        import json
        model_code, _ = self._om_model_code()
        grids_raw = self._om_get_json(f"/models/{model_code}/grids")
        if isinstance(grids_raw, str):
            grids_raw = json.loads(grids_raw)
        grids = grids_raw if isinstance(grids_raw, list) else [grids_raw]
        if not grids:
            raise RuntimeError(f"Aucune grille disponible pour {model_code}")
        indicators = []
        for grid in grids:
            pkgs_raw = self._om_get_json(f"/models/{model_code}/grids/{grid}/packages")
            if isinstance(pkgs_raw, str):
                pkgs_raw = json.loads(pkgs_raw)
            if isinstance(pkgs_raw, list):
                pkgs = ([p for p in pkgs_raw if isinstance(p, str)]
                        or [p.get("name", p.get("id", str(p))) for p in pkgs_raw])
            else:
                pkgs = [str(pkgs_raw)]
            indicators += [f"{grid}/{pkg}" for pkg in pkgs]
        return {"indicators": indicators, "grids": grids,
                "om_model": model_code, "territory": self.kwargs.get("territory")}

    def _get_forecast_om(self):
        import json
        model_code, product_ep = self._om_model_code()
        territory = self.kwargs.get("territory")
        indicator = self.kwargs.get("indicator", "")
        if "/" in indicator:
            grid, package = indicator.split("/", 1)
        else:
            caps = self._get_capabilities_om()
            grid, package = caps["indicators"][0].split("/", 1)
        referencetime = self.kwargs.get("run")
        pkg_raw = self._om_get_json(
            f"/models/{model_code}/grids/{grid}/packages/{package}",
            params={"referencetime": referencetime} if referencetime else None)
        if isinstance(pkg_raw, str):
            pkg_raw = json.loads(pkg_raw)
        if isinstance(pkg_raw, dict):
            if not referencetime:
                referencetime = (pkg_raw.get("referencetime")
                                 or pkg_raw.get("referenceTime")
                                 or pkg_raw.get("reference_time"))
            times_available = (pkg_raw.get("times")
                                or pkg_raw.get("timeSteps")
                                or pkg_raw.get("echeances", []))
        else:
            times_available = []
        horizons_explicit = self.kwargs.get("horizons_explicit", False)
        forecast_horizons = self.kwargs.get("forecast_horizons", [])
        if horizons_explicit and forecast_horizons:
            times_to_fetch = [f"{h:03d}H" for h in forecast_horizons]
        elif times_available:
            times_to_fetch = [t if isinstance(t, str) else f"{int(t):03d}H"
                              for t in times_available]
            if not horizons_explicit:
                times_to_fetch = times_to_fetch[:5]
        else:
            times_to_fetch = [f"{h:03d}H" for h in range(1, 5)]
        if not referencetime:
            raise RuntimeError(
                f"referencetime introuvable pour {package}.\nRéponse : {str(pkg_raw)[:300]}")
        tmp_dir    = tempfile.mkdtemp()
        layer_files = []
        for time_str in times_to_fetch:
            if self.isCanceled():
                break
            try:
                grib_path = self._om_download_grib(
                    model_code, product_ep, grid, package,
                    referencetime, time_str, tmp_dir)
                for df, var_name in self._grib_to_dataframes(grib_path):
                    label = f"{territory}_{package}_{var_name}_{time_str}"
                    info  = prepare_layer_files(df, label, var_name)
                    info["horizon_label"] = time_str
                    info["indicator"]     = f"{package}/{var_name}"
                    layer_files.append(info)
            except Exception as exc:
                import traceback as tb
                layer_files.append({
                    "layer_name": f"{package}_{time_str}", "error": str(exc),
                    "raster_path": None, "points_path": None,
                    "horizon_label": time_str, "indicator": package,
                    "value_col": "", "ind_type": "generic", "unit": ""})
        return {"layer_files": layer_files, "indicator": package}

    def _om_download_grib(self, model_code, product_ep, grid, package,
                           referencetime, time_str, tmp_dir):
        import requests
        url = f"{AROME_OM_BASE}/models/{model_code}/grids/{grid}/packages/{package}/{product_ep}"
        params  = {"referencetime": referencetime, "time": time_str, "format": "grib2"}
        headers = self._om_headers()
        headers["Accept"] = "application/octet-stream"
        self._diag_url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        r = requests.get(url, headers=headers, params=params, timeout=120)
        if r.status_code == 401:
            raise RuntimeError(TOKEN_EXPIRED_MSG)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}\n{self._diag_url}\n{r.text[:200]}")
        grib_path = os.path.join(tmp_dir, f"{package}_{time_str}.grib2")
        with open(grib_path, "wb") as f:
            f.write(r.content)
        return grib_path

    def _grib_to_dataframes(self, grib_path):
        try:
            import cfgrib
        except ImportError:
            raise RuntimeError("cfgrib requis : pip install cfgrib")
        import numpy as np, pandas as pd
        datasets = cfgrib.open_datasets(grib_path)
        result   = []
        for ds in datasets:
            lat_name = next((c for c in ds.coords if c.lower() in ("latitude","lat")), None)
            lon_name = next((c for c in ds.coords if c.lower() in ("longitude","lon")), None)
            if not lat_name or not lon_name:
                continue
            for var in ds.data_vars:
                try:
                    da   = ds[var]
                    vals = da.values
                    lats_1d = ds[lat_name].values.flatten()
                    lons_1d = ds[lon_name].values.flatten()
                    if vals.ndim == 2:
                        if len(lats_1d) == vals.shape[0] and len(lons_1d) == vals.shape[1]:
                            lon_g, lat_g = np.meshgrid(lons_1d, lats_1d)
                            lats = lat_g.flatten()
                            lons = lon_g.flatten()
                        else:
                            lats = lats_1d
                            lons = lons_1d
                        vals = vals.flatten()
                    elif vals.ndim >= 3:
                        vals = vals.reshape(-1)[: len(lats_1d)]
                        lats = lats_1d
                        lons = lons_1d
                    else:
                        lats = lats_1d
                        lons = lons_1d
                        vals = vals.flatten()
                    if len(lats) != len(vals):
                        continue
                    df = pd.DataFrame({"latitude": lats, "longitude": lons,
                                       str(var): vals}).dropna()
                    if len(df):
                        result.append((df, str(var)))
                except Exception:
                    continue
        if not result:
            raise RuntimeError(f"Aucune variable exploitable dans : {grib_path}")
        return result

    # ================================================================== #
    #  API WCS métropole (meteole)
    # ================================================================== #

    def _get_capabilities(self):
        client = self._make_client(self.kwargs["model"])
        try:
            _base = getattr(getattr(client, "_client", client),
                            "_api_base_url", "https://public-api.meteofrance.fr/public/")
            mbp = getattr(client, "_model_base_path", "?")
            ep  = getattr(client, "_entry_point", "?")
            self._diag_url = f"{_base}{mbp}/{ep}/GetCapabilities"
        except Exception:
            self._diag_url = "(URL non déterminable)"
        df_cap = client.get_capabilities()
        for col in ("indicator", "id", "coverage_id"):
            if col in df_cap.columns:
                indicators = sorted(df_cap[col].dropna().unique().tolist())
                if indicators:
                    return {"indicators": indicators}
        return {"indicators": sorted(df_cap.iloc[:, 0].dropna().unique().tolist())}

    def _get_forecast(self):
        model            = self.kwargs.get("model")
        indicator        = self.kwargs.get("indicator")
        run              = self.kwargs.get("run")
        forecast_horizons= self.kwargs.get("forecast_horizons", [1])
        lon              = self.kwargs.get("lon")
        lat              = self.kwargs.get("lat")
        heights          = self.kwargs.get("heights")
        pressures        = self.kwargs.get("pressures")
        ensemble_numbers = self.kwargs.get("ensemble_numbers")
        client = self._make_client(model)
        if model in ("arome_instantane", "piaf"):
            horizons_td = [datetime.timedelta(minutes=h*60) for h in forecast_horizons]
        else:
            horizons_td = [datetime.timedelta(hours=h) for h in forecast_horizons]
        kw = dict(indicator=indicator)
        if run:                              kw["run"]              = run
        if lon:                              kw["long"]             = lon
        if lat:                              kw["lat"]              = lat
        if heights and len(heights)>0:       kw["heights"]          = heights
        if pressures and len(pressures)>0:   kw["pressures"]        = pressures
        if ensemble_numbers is not None:     kw["ensemble_numbers"] = ensemble_numbers
        if forecast_horizons and self.kwargs.get("horizons_explicit"):
            kw["forecast_horizons"] = horizons_td
        df = client.get_coverage(**kw)
        horizon_col = next(
            (c for c in df.columns
             if "horizon" in c.lower() or c in ("time","forecast_time")), None)
        layer_files = []
        if horizon_col and df[horizon_col].nunique() > 1:
            for h_val, sub in df.groupby(horizon_col):
                h_str = str(h_val).replace(":","h").replace(" ","_").replace(",","")[:20]
                info  = prepare_layer_files(sub.reset_index(drop=True),
                                            f"{indicator[:30]}__{h_str}", indicator)
                info["horizon_label"] = h_str
                info["indicator"]     = indicator
                layer_files.append(info)
        else:
            info = prepare_layer_files(df, indicator[:40], indicator)
            info["horizon_label"] = ""
            info["indicator"]     = indicator
            layer_files.append(info)
        return {"layer_files": layer_files, "indicator": indicator}

    # ------------------------------------------------------------------ #
    #  Vigilance
    # ------------------------------------------------------------------ #

    def _get_vigilance(self):
        import threading
        vigi   = self._make_vigilance_client()
        result = {}
        if self.kwargs.get("load_phenomenon") or self.kwargs.get("load_timelaps"):
            df_phen, df_time = vigi.get_phenomenon()
            if self.kwargs.get("load_phenomenon"): result["phenomenon"] = df_phen
            if self.kwargs.get("load_timelaps"):   result["timelaps"]   = df_time
        if self.kwargs.get("load_vignette"):
            tmp = tempfile.mkdtemp()
            vignette_error = [None]
            def _dl():
                try:
                    vigi.get_vignette(output_dir=tmp)
                except TypeError:
                    try: vigi.get_vignette()
                    except Exception as e: vignette_error[0] = str(e)
                except Exception as e: vignette_error[0] = str(e)
            t = threading.Thread(target=_dl, daemon=True)
            t.start(); t.join(timeout=30)
            if t.is_alive():
                result["vignette_error"] = "Timeout : vignette non téléchargée"
            elif vignette_error[0]:
                result["vignette_error"] = vignette_error[0]
            else:
                for f in os.listdir(tmp):
                    if f.endswith(".png"):
                        result["vignette_path"] = self._georeference_png(
                            os.path.join(tmp, f), tmp)
                        break
        return result

    def _georeference_png(self, png_path, tmp_dir):
        try:
            from osgeo import gdal, osr
            WEST, EAST, SOUTH, NORTH = -5.5, 10.0, 41.0, 51.5
            src = gdal.Open(png_path)
            if not src: return png_path
            nc, nr, nb = src.RasterXSize, src.RasterYSize, src.RasterCount
            out = os.path.join(tmp_dir, "vigilance_georef.tif")
            ds  = gdal.GetDriverByName("GTiff").Create(out, nc, nr, nb, gdal.GDT_Byte)
            ds.SetGeoTransform([WEST,(EAST-WEST)/nc,0,NORTH,0,-(NORTH-SOUTH)/nr])
            srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
            ds.SetProjection(srs.ExportToWkt())
            for b in range(1, nb+1):
                ds.GetRasterBand(b).WriteArray(src.GetRasterBand(b).ReadAsArray())
            ds.FlushCache(); src = ds = None
            return out
        except Exception:
            return png_path

    # ------------------------------------------------------------------ #
    #  Probe
    # ------------------------------------------------------------------ #

    def _probe_urls(self):
        import requests as req
        territory = self.kwargs.get("territory", "ANTIL")
        if territory in AROME_OM_TERRITORY:
            model_code, _ = AROME_OM_TERRITORY[territory]
            url = f"{AROME_OM_BASE}/models/{model_code}/grids"
            try:
                r = req.get(url, headers=self._om_headers(), timeout=10)
                results = [{"url": url, "status": r.status_code,
                            "ok": r.status_code == 200, "body": r.text[:300]}]
            except Exception as e:
                results = [{"url": url, "status": -1, "ok": False, "error": str(e)}]
        else:
            results = [{"url": "N/A", "status": -1, "ok": False,
                        "error": "Territoire non outremer"}]
        return {"probe_results": results, "territory": territory}

    # ------------------------------------------------------------------ #
    #  Auth / factory métropole
    # ------------------------------------------------------------------ #

    def _auth_kwargs(self):
        return {self.auth_mode: self.auth_key}


    # ================================================================== #
    #  AROME Outre-mer — API DPPaquetAROME-OM (REST + GRIB2)
    # ================================================================== #

    def _make_om_client(self):
        """Instancie le client REST AROME-OM avec les credentials du worker."""
        from .arome_om import AromeOMClient
        return AromeOMClient(**{self.auth_mode: self.auth_key})

    def _get_om_capabilities(self):
        """
        Récupère grilles + paquets disponibles pour un territoire outremer.
        Pour chaque grille, récupère la liste de ses paquets.

        Retourne :
        {
          "territory": "ANTIL",
          "grids": [
            {"id": "0.025", "packages": ["SP1","SP2",...], "raw_pkgs": <raw>},
            ...
          ],
          "raw_grids": <raw_response>
        }
        """
        territory  = self.kwargs.get("territory", "ANTIL")
        client     = self._make_om_client()
        # Log de la réponse brute pour diagnostic
        from .arome_om import OM_TERRITORY_CONFIG, BASE_URL
        cfg      = OM_TERRITORY_CONFIG.get(territory, {})
        raw_resp = client._get_json(f"/models/{cfg.get('model_code','?')}/grids")
        # On logge la réponse brute dans le résultat pour affichage dans dialog
        raw_grids = client.list_grids(territory)

        # Fallback : si aucune grille extraite, essayer les résolutions connues
        if not raw_grids:
            from .arome_om import OM_TERRITORY_CONFIG
            fallback_grids = ["0.025", "0.01"]
            for candidate in fallback_grids:
                try:
                    test = client.list_packages(territory, candidate)
                    if test:
                        raw_grids = [candidate]
                        break
                except Exception:
                    continue

        grids_out = []
        for grid_id in raw_grids:
            if self.isCanceled():
                break
            try:
                # Log réponse brute /packages pour diagnostic
                cfg_om   = OM_TERRITORY_CONFIG.get(territory, {})
                raw_pkgs_resp = client._get_json(
                    f"/models/{cfg_om.get('model_code','?')}"
                    f"/grids/{grid_id}/packages")
                raw_pkgs = client.list_packages(territory, grid_id)
                grids_out.append({
                    "id":            grid_id,
                    "packages":      raw_pkgs,
                    "raw_pkgs":      raw_pkgs,
                    "raw_pkgs_resp": str(raw_pkgs_resp)[:1000],
                    "error":         None,
                })
            except Exception as e:
                grids_out.append({
                    "id":            grid_id,
                    "packages":      [],
                    "raw_pkgs":      [],
                    "raw_pkgs_resp": str(e),
                    "error":         str(e),
                })

        return {
            "territory":  territory,
            "grids":      grids_out,
            "raw_grids":  raw_grids,
            "raw_resp":   str(raw_resp)[:2000],
        }


    def _get_om_list_variables(self):
        """
        Télécharge un paquet AROME-OM et liste les variables qu'il contient
        sans créer de couches QGIS.
        Retourne : {territory, grid, package, variables: [{name, label, unit, type}]}
        """
        from .arome_om import (AromeOMClient, grib2_to_dataframes,
                                latest_referencetime, format_timestep,
                                grib_var_label, grib_var_type, GRIB_VAR_INFO)

        territory     = self.kwargs.get("territory", "ANTIL")
        grid          = str(self.kwargs.get("grid", "0.025"))
        package       = self.kwargs.get("package", "SP1")
        referencetime = self.kwargs.get("referencetime") or latest_referencetime()

        client    = self._make_om_client()
        # Télécharge H+1 pour avoir des données
        time_step = "001H"
        time_candidates = [time_step, "002H", "003H"]
        ref_candidates  = [referencetime]
        try:
            import datetime as _dt
            ref_dt   = _dt.datetime.strptime(referencetime, "%Y-%m-%dT%H:%M:%SZ")
            prev_ref = (ref_dt - _dt.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
            ref_candidates.append(prev_ref)
        except Exception:
            pass

        grib_bytes = None
        last_exc   = None
        for ref in ref_candidates:
            for t in time_candidates:
                try:
                    grib_bytes = client.download_product(
                        territory, grid, package, ref, t)
                    break
                except Exception as e:
                    last_exc = e
                    continue
            if grib_bytes:
                break

        if not grib_bytes:
            raise RuntimeError(
                f"Impossible de télécharger le paquet {package} "
                f"pour {territory} : {last_exc}")

        var_frames = grib2_to_dataframes(grib_bytes)
        variables = []
        for var_name, df in var_frames:
            info  = GRIB_VAR_INFO.get(var_name, ("", "", "generic"))
            label = grib_var_label(var_name)  # label enrichi avec unité
            variables.append({
                "name":  var_name,
                "label": label or info[0] or var_name,
                "unit":  info[1],
                "type":  info[2],
            })

        return {
            "territory": territory,
            "grid":      grid,
            "package":   package,
            "variables": variables,
        }

    def _get_om_forecast(self):
        """
        Télécharge un ou plusieurs paquets AROME-OM en GRIB2 et les convertit
        en couches QGIS via cfgrib + layer_utils.

        kwargs attendus :
          territory      : str  ('ANTIL', 'GUYANE', ...)
          grid           : str  identifiant grille (ex '0.025')
          package        : str  nom du paquet (ex 'SP1')
          referencetime  : str ISO-8601 UTC ou None (→ dernier run auto)
          time_horizons  : list[str] format 'hhhH' (ex ['001H','024H'])
        """
        from .arome_om import (AromeOMClient, grib2_to_dataframes,
                                latest_referencetime, format_timestep)
        from .layer_utils import prepare_layer_files

        territory      = self.kwargs.get("territory", "ANTIL")
        grid           = str(self.kwargs.get("grid", "0.025"))
        package        = self.kwargs.get("package", "SP1")
        referencetime  = self.kwargs.get("referencetime") or latest_referencetime()
        time_horizons  = self.kwargs.get("time_horizons") or ["000H"]
        # Filtre de variables : si None ou vide → toutes les variables
        selected_vars  = self.kwargs.get("selected_vars") or None

        client      = self._make_om_client()
        layer_files = []

        for time_step in time_horizons:
            if self.isCanceled():
                break

            # 1. Télécharger le GRIB2
            try:
                grib_bytes = client.download_product(
                    territory, grid, package, referencetime, time_step)
                size_kb = len(grib_bytes) // 1024
                # Stocker taille + magic bytes pour diagnostic
                magic = grib_bytes[:4] if grib_bytes else b""
                if not hasattr(self, "_grib_vars_by_pkg"):
                    self._grib_vars_by_pkg = []
                self._grib_vars_by_pkg.append(
                    f"[INFO] GRIB2 téléchargé : {size_kb} Ko | "
                    f"magic={magic!r} | {territory} {package} {time_step}")
            except Exception as e:
                raise RuntimeError(
                    f"Erreur téléchargement GRIB2\n"
                    f"  territoire : {territory}\n"
                    f"  grille     : {grid}\n"
                    f"  paquet     : {package}\n"
                    f"  réseau     : {referencetime}\n"
                    f"  échéance   : {time_step}\n"
                    f"  → {e}"
                ) from e

            # 2. Décoder GRIB2 → DataFrames
            try:
                var_frames = grib2_to_dataframes(grib_bytes)
            except Exception as e:
                raise RuntimeError(
                    f"Erreur décodage GRIB2 ({time_step}) : {e}") from e

            if not var_frames:
                if not hasattr(self, "_grib_vars_by_pkg"):
                    self._grib_vars_by_pkg = []
                self._grib_vars_by_pkg.append(
                    f"[WARN] GRIB2 {package}/{time_step} : aucune variable décodée par cfgrib (fichier vide ou format non reconnu)")
                continue

            # 3. Créer les fichiers raster/points pour chaque variable
            # Détecter une erreur cfgrib
            if var_frames and var_frames[0][0] == "_cfgrib_error_":
                err_msg = var_frames[0][1]
                if not hasattr(self, "_grib_vars_by_pkg"):
                    self._grib_vars_by_pkg = []
                self._grib_vars_by_pkg.append(
                    f"[ERR] cfgrib ne peut pas décoder {package}/{time_step} : "
                    f"{err_msg[:200]}")
                continue

            # Variables réellement disponibles dans ce GRIB2
            available = [v for v, _ in var_frames]
            # Toujours stocker + logger, même si vide
            if not hasattr(self, "_grib_vars_log"):
                self._grib_vars_log = {}
            self._grib_vars_log[f"{package}/{time_step}"] = available
            # Log immédiat dans le résultat intermédiaire
            if not hasattr(self, "_grib_vars_by_pkg"):
                self._grib_vars_by_pkg = []
            self._grib_vars_by_pkg.append(
                f"[INFO] GRIB2 {package}/{time_step} contient "
                f"{len(available)} var(s) : {available}")

            # Si filtre actif mais variable absente → log explicite
            if selected_vars:
                missing = [v for v in selected_vars if v not in available]
                if missing:
                    # Stocker le message de diagnostic dans le résultat
                    if not hasattr(self, "_grib_missing_log"):
                        self._grib_missing_log = []
                    self._grib_missing_log.append(
                        f"Paquet {package}/{time_step} : "
                        f"variable(s) {missing} absente(s). "
                        f"Variables disponibles : {available}")

            for var_name, df in var_frames:
                # Filtre : ne charge que les variables sélectionnées
                if selected_vars and var_name not in selected_vars:
                    continue
                from .arome_om import grib_var_label, grib_var_type
                var_label = grib_var_label(var_name)
                label = (f"{package}__{territory}__{time_step}"
                         f"__{var_name[:20]}")
                # Nom d'affichage enrichi avec le label français
                display_label = (f"[{territory}] {time_step} "
                                 f"{var_label or var_name}")
                try:
                    info = prepare_layer_files(
                        df, display_label,
                        var_name)  # indicator_name = shortName pour le style
                    info["horizon_label"] = time_step
                    info["indicator"]     = var_name
                    info["layer_name"]    = display_label
                    layer_files.append(info)
                except Exception as e:
                    # Variable non cartographiable → on passe
                    continue

        return {
            "layer_files":    layer_files,
            "indicator":      package,
            "territory":      territory,
            "grib_vars_log":  getattr(self, "_grib_vars_log", {}),
            "grib_missing":   getattr(self, "_grib_missing_log", []),
            "grib_vars_msgs": getattr(self, "_grib_vars_by_pkg", []),
        }

    def _make_client(self, model_key):
        from meteole import (AromeForecast, ArpegeForecast,
                              AromePEForecast, AromePIForecast, PiafForecast)
        try:
            from meteole import ArpegePEForecast
        except ImportError:
            ArpegePEForecast = None
        mapping = {
            "arome": AromeForecast, "arpege": ArpegeForecast,
            "arome_pe": AromePEForecast, "arpege_pe": ArpegePEForecast,
            "arome_instantane": AromePIForecast, "piaf": PiafForecast,
        }
        cls = mapping.get(model_key)
        if cls is None:
            raise ValueError(f"Modèle inconnu : {model_key}")
        extra = {}
        if model_key == "arome":
            extra["territory"] = "FRANCE"
            extra["precision"] = 0.01
        client = cls(**self._auth_kwargs(), **extra)
        self._patch_client(client)
        return client

    def _make_vigilance_client(self):
        from meteole import Vigilance
        client = Vigilance(**self._auth_kwargs())
        self._patch_client(client)
        return client

    @staticmethod
    def _patch_client(client):
        import types
        inner = None
        for attr in ("_client", "_api_client", "_http_client"):
            c = getattr(client, attr, None)
            if c is not None and hasattr(c, "_token_expired"):
                inner = c; break
        if inner is None and hasattr(client, "_token_expired"):
            inner = client
        if inner is None:
            return
        orig = inner.__class__.get
        def patched_get(self, path, *, params=None, max_retries=5):
            self._token_expired = False
            return orig(self, path, params=params, max_retries=max_retries)
        inner.get = types.MethodType(patched_get, inner)


MeteoleWorker = MeteoleTask
