#!/usr/bin/env bash
#
# Construit l'archive installable du plugin : dist/meteole_v2.zip
# La racine de l'archive est le dossier « meteole_v2/ », attendu par
# l'installateur « Installer depuis un ZIP » de QGIS.
#
set -euo pipefail

PLUGIN_DIR="meteole_v2"
DIST_DIR="dist"
VERSION="$(grep -E '^version=' "${PLUGIN_DIR}/metadata.txt" | cut -d= -f2 | tr -d '[:space:]')"
OUT="${DIST_DIR}/${PLUGIN_DIR}.zip"

echo "→ Plugin : ${PLUGIN_DIR} (version ${VERSION})"

# Nettoyage des artefacts Python
find "${PLUGIN_DIR}" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "${PLUGIN_DIR}" -type f -name '*.pyc' -delete 2>/dev/null || true

mkdir -p "${DIST_DIR}"
rm -f "${OUT}"

# zip en conservant le dossier racine meteole_v2/
zip -r -q "${OUT}" "${PLUGIN_DIR}" \
    -x "*/__pycache__/*" "*.pyc" "*/.DS_Store"

echo "→ Archive créée : ${OUT}"
echo "→ Contenu (extrait) :"
unzip -l "${OUT}" | sed -n '1,12p'
