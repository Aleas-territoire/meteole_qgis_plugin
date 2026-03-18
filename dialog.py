[general]
name=Meteole
qgisMinimumVersion=3.16
description=Import Météo-France weather data (AROME, ARPEGE, PIAF, Vigilance) as raster and vector layers in QGIS via the meteole library.
version=1.1.0
author=MAIF
email=contact@example.com

about=This plugin retrieves and visualizes Météo-France weather forecast data directly in QGIS. It uses the open-source Python library "meteole" to access high-resolution NWP models (AROME at 1.3 km, ARPEGE at 10 km, PIAF precipitation nowcasting) and weather alerts.

  Features:
  - Authentication via token, api_key or application_id
  - Model selection: AROME, AROME-PI, AROME-PE (ensemble), ARPEGE, PIAF
  - Automatic indicator listing from the API
  - Raster (GeoTIFF) and point (GeoPackage) layer generation
  - Smart color palettes per indicator type (temperature, wind, precipitation...)
  - Physical units displayed in layer names and legend
  - Temporal horizon slider to navigate between forecast steps
  - Weather alert map by department (Vigilance bulletins)
  - Geographic filtering: full France, canvas extent, or custom bbox

tracker=https://github.com/MAIF/meteole-qgis/issues
repository=https://github.com/MAIF/meteole-qgis

hasProcessingProvider=no
tags=weather,météo,météo-france,arome,arpege,piaf,forecast,raster,climate,vigilance,nowcasting
homepage=https://github.com/MAIF/meteole-qgis
category=Raster
icon=icon.png
experimental=False
deprecated=False
server=False
