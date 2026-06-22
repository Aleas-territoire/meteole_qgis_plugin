# -*- coding: utf-8 -*-
"""
Plugin principal Meteole pour QGIS.
"""

import os
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.core import QgsApplication

from .dialog import MeteoleDialog


class MeteolePlugin:
    """Plugin QGIS pour accéder aux données Météo-France via meteole."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = "Meteole"
        self.toolbar = None
        self.dialog = None

    def add_action(self, icon_path, text, callback, enabled_flag=True,
                   add_to_menu=True, add_to_toolbar=True, status_tip=None,
                   whats_this=None, parent=None):
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)
        if whats_this is not None:
            action.setWhatsThis(whats_this)
        if add_to_toolbar and self.toolbar:
            self.toolbar.addAction(action)
        if add_to_menu:
            self.iface.addPluginToRasterMenu(self.menu, action)

        self.actions.append(action)
        return action

    def initGui(self):
        """Initialise l'interface graphique du plugin."""
        icon_path = os.path.join(self.plugin_dir, "icon.png")

        self.toolbar = self.iface.addToolBar("Meteole")
        self.toolbar.setObjectName("MeteoleToolbar")

        self.add_action(
            icon_path,
            text="Meteole – Données Météo-France",
            callback=self.run,
            parent=self.iface.mainWindow(),
            status_tip="Récupérer et visualiser des données météo Météo-France",
        )

        # Installation automatique silencieuse de la dépendance au chargement
        self._ensure_meteole_installed()

    def _ensure_meteole_installed(self):
        """Vérifie et installe silencieusement meteole si absent."""
        try:
            import meteole  # noqa: F401
            return  # Déjà installé, rien à faire
        except ImportError:
            pass

        import subprocess
        import sys

        python_exe = self._find_python_exe()

        try:
            result = subprocess.run(
                [python_exe, "-m", "pip", "install", "meteole"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                # Tentative avec --user si le premier essai échoue (droits insuffisants)
                result = subprocess.run(
                    [python_exe, "-m", "pip", "install", "--user", "meteole"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            if result.returncode == 0:
                QMessageBox.information(
                    self.iface.mainWindow(),
                    "Meteole – Installation réussie",
                    "La librairie 'meteole' a été installée automatiquement.\n"
                    "Veuillez redémarrer QGIS pour finaliser l'initialisation.",
                )
            else:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Meteole – Échec de l'installation automatique",
                    f"Impossible d'installer 'meteole' automatiquement.\n\n"
                    f"Installez-la manuellement en ouvrant OSGeo4W Shell et en tapant :\n"
                    f"    pip install meteole\n\n"
                    f"Détail de l'erreur :\n{result.stderr[:500]}",
                )
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Meteole – Erreur",
                f"Erreur lors de l'installation automatique de 'meteole' :\n{str(e)}\n\n"
                f"Installez-la manuellement via OSGeo4W Shell :\n    pip install meteole",
            )

    def _find_python_exe(self):
        """Trouve le python.exe réel de l'environnement QGIS/OSGeo4W."""
        import sys
        import os

        # Cas 1 : python.exe dans le même dossier que l'exécutable courant
        candidate = os.path.join(os.path.dirname(sys.executable), "python.exe")
        if os.path.isfile(candidate):
            return candidate

        # Cas 2 : parcourir sys.path pour trouver un python.exe valide
        for path in sys.path:
            candidate = os.path.join(path, "python.exe")
            if os.path.isfile(candidate):
                return candidate

        # Cas 3 : fallback sur sys.executable (Linux/macOS ou cas edge)
        return sys.executable

    def unload(self):
        """Supprime le plugin de l'interface QGIS."""
        for action in self.actions:
            self.iface.removePluginRasterMenu(self.menu, action)
        if self.toolbar:
            del self.toolbar

    def run(self):
        """Ouvre la boîte de dialogue principale du plugin."""
        # Vérifier que meteole est bien disponible (au cas où l'install aurait échoué)
        try:
            import meteole  # noqa: F401
        except ImportError:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Dépendance manquante",
                "La librairie 'meteole' n'est pas installée.\n\n"
                "Installez-la via OSGeo4W Shell :\n    pip install meteole\n\n"
                "Puis redémarrez QGIS.",
            )
            return

        if self.dialog is None:
            self.dialog = MeteoleDialog(self.iface)

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
