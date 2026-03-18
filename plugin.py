# -*- coding: utf-8 -*-
"""
Meteole QGIS Plugin
Génération de cartes météo depuis les données Météo-France via la librairie meteole.
"""


def classFactory(iface):
    from .plugin import MeteolePlugin
    return MeteolePlugin(iface)
