# Changelog – Meteole QGIS Plugin

## [1.2.1] – 2026-03-20
### Fixed
- Installation automatique de `meteole` dès le chargement du plugin (plus besoin de cliquer)
- Correction de la détection de `python.exe` sous Windows/OSGeo4W (`sys.executable` pointait vers `qgis-ltr-bin.exe`)
- Fallback `pip install --user` si les droits admin sont insuffisants
- Logs de diagnostic dans le Journal des messages QGIS (onglet "Meteole")

## [1.2.0] – 2026
### Ajouté
- Compatibilité QGIS 4.x : migration des enums Qt5 vers Qt6 (fully-qualified)
- `qgisMaximumVersion=4.99` dans metadata.txt

### Modifié
- `Qt.AlignCenter` → `Qt.AlignmentFlag.AlignCenter`
- `Qt.PointingHandCursor` → `Qt.CursorShape.PointingHandCursor`
- `Qt.Horizontal` → `Qt.Orientation.Horizontal`
- `Qt.RichText` → `Qt.TextFormat.RichText`
- `QLineEdit.Password` → `QLineEdit.EchoMode.Password`
- `QgsRasterBandStats.All` → `QgsRasterBandStats.Stats.All`

## [1.1.0]
### Ajouté
- Onglet "⏱ Horizons" : slider temporel pour basculer entre les couches raster
- Sauvegarde du modèle et de l'indicateur entre sessions

### Modifié
- `_on_forecast_done` reçoit des `file_info` au lieu de DataFrames
- Le journal ne bascule plus automatiquement vers l'onglet log