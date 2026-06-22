# -*- coding: utf-8 -*-
"""
Analyse des aléas (phénomènes) de la vigilance Météo-France.

La carte de vigilance (`cartevigilance/encours`) fournit, pour chaque
département (« domain »), le détail PAR ALÉA : vent, pluie-inondation, orages,
inondation, neige-verglas, canicule, grand froid, avalanches,
vagues-submersion — chacun avec sa propre couleur (vert/jaune/orange/rouge).

Le plugin n'exploitait jusqu'ici que la couleur maximale par département.
Ce module extrait le détail par aléa afin de répondre à la question
« quel(s) aléa(s) explique(nt) la vigilance ? ».

Aucune dépendance QGIS : importable depuis le thread worker et testable seul.
"""

from __future__ import annotations

# Identifiants officiels Météo-France des phénomènes (aléas)
PHENOMENON_FR = {
    "1": "Vent violent",
    "2": "Pluie-inondation",
    "3": "Orages",
    "4": "Inondation",
    "5": "Neige-verglas",
    "6": "Canicule",
    "7": "Grand froid",
    "8": "Avalanches",
    "9": "Vagues-submersion",
}

# Nom de colonne (sans accent/espace) pour la couche départements
PHENOMENON_COL = {
    "1": "vent",
    "2": "pluie_inondation",
    "3": "orages",
    "4": "inondation",
    "5": "neige_verglas",
    "6": "canicule",
    "7": "grand_froid",
    "8": "avalanches",
    "9": "vagues_submersion",
}

PHENOMENON_ORDER = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]

COLOR_FR = {0: "—", 1: "Vert", 2: "Jaune", 3: "Orange", 4: "Rouge"}


def parse_hazards(map_json: dict) -> list[dict]:
    """
    Transforme la réponse brute de `Vigilance.get_map()` en une liste plate :
        {echeance, domain_id, phenomenon_id, phenomenon_fr, color_id, color_fr}

    Tolérant aux variations de structure (clés absentes, listes vides).
    """
    out: list[dict] = []
    if not isinstance(map_json, dict):
        return out

    product = map_json.get("product", map_json) or {}
    periods = product.get("periods", []) or []

    for period in periods:
        if not isinstance(period, dict):
            continue
        ech = period.get("echeance", "")
        timelaps = period.get("timelaps", {}) or {}
        domains  = timelaps.get("domain_ids", []) or []
        for dom in domains:
            if not isinstance(dom, dict):
                continue
            code = str(dom.get("domain_id", "")).strip()
            items = dom.get("phenomenon_items", []) or []
            for ph in items:
                if not isinstance(ph, dict):
                    continue
                pid = str(ph.get("phenomenon_id", "")).strip()
                cid = ph.get("phenomenon_max_color_id",
                             ph.get("max_color_id", 1))
                try:
                    cid = int(cid)
                except (TypeError, ValueError):
                    cid = 1
                out.append({
                    "echeance":       ech,
                    "domain_id":      code,
                    "phenomenon_id":  pid,
                    "phenomenon_fr":  PHENOMENON_FR.get(pid, pid),
                    "color_id":       cid,
                    "color_fr":       COLOR_FR.get(cid, str(cid)),
                })
    return out


def hazards_by_department(hazards: list[dict], echeance: str = "J") -> dict:
    """
    Agrège les aléas par département (code à 2 caractères) pour une échéance.
    Retourne : {code_dept: {phenomenon_id: color_id_max}}.
    Les zones côtières (codes à 3 caractères) sont rattachées à leur
    département parent (2 premiers caractères), en prenant la couleur max.
    """
    res: dict[str, dict] = {}
    for h in hazards:
        if echeance and h.get("echeance") != echeance:
            continue
        raw = str(h.get("domain_id", ""))
        code = raw[:2].zfill(2) if raw else ""
        if not code:
            continue
        pid = h.get("phenomenon_id", "")
        cid = int(h.get("color_id", 1))
        dept = res.setdefault(code, {})
        dept[pid] = max(dept.get(pid, 0), cid)
    return res


def summarize_department(dept_map: dict, min_color: int = 2) -> str:
    """
    Résumé lisible des aléas actifs d'un département (couleur ≥ jaune).
    Ex. : « Orages (Orange), Pluie-inondation (Jaune) ». '' si rien (vert).
    """
    active = [(pid, c) for pid, c in dept_map.items() if c >= min_color]
    active.sort(key=lambda x: (-x[1], PHENOMENON_ORDER.index(x[0])
                               if x[0] in PHENOMENON_ORDER else 99))
    return ", ".join(f"{PHENOMENON_FR.get(pid, pid)} ({COLOR_FR.get(c, c)})"
                     for pid, c in active)


def dominant_hazard(dept_map: dict) -> str:
    """Aléa dominant (couleur la plus élevée) d'un département, en français."""
    if not dept_map:
        return ""
    pid = max(dept_map, key=lambda p: dept_map[p])
    if dept_map[pid] < 2:
        return ""
    return PHENOMENON_FR.get(pid, pid)


def national_summary(hazards: list[dict], echeance: str = "J") -> list[dict]:
    """
    Synthèse nationale par aléa pour une échéance :
        [{phenomenon_id, phenomenon_fr, color_id_max, color_fr, nb_departements}]
    nb_departements = nombre de départements en vigilance ≥ jaune pour cet aléa.
    Trié par couleur décroissante.
    """
    by_dept = hazards_by_department(hazards, echeance)
    agg: dict[str, dict] = {}
    for dept_map in by_dept.values():
        for pid, cid in dept_map.items():
            a = agg.setdefault(pid, {"max": 0, "count": 0})
            a["max"] = max(a["max"], cid)
            if cid >= 2:
                a["count"] += 1
    rows = []
    for pid in PHENOMENON_ORDER:
        if pid not in agg:
            continue
        a = agg[pid]
        rows.append({
            "phenomenon_id":   pid,
            "phenomenon_fr":   PHENOMENON_FR.get(pid, pid),
            "color_id_max":    a["max"],
            "color_fr":        COLOR_FR.get(a["max"], str(a["max"])),
            "nb_departements": a["count"],
        })
    rows.sort(key=lambda r: -r["color_id_max"])
    return rows
