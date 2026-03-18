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

    def unload(self):
        """Supprime le plugin de l'interface QGIS."""
        for action in self.actions:
            self.iface.removePluginRasterMenu(self.menu, action)
        if self.toolbar:
            del self.toolbar

    def run(self):
        """Ouvre la boîte de dialogue principale du plugin."""
        # Vérifier que meteole est installé
        try:
            import meteole  # noqa: F401
        except ImportError:
            reply = QMessageBox.question(
                self.iface.mainWindow(),
                "Dépendance manquante",
                "La librairie Python 'meteole' n'est pas installée.\n\n"
                "Voulez-vous l'installer maintenant via pip ?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._install_meteole()
            else:
                return

        if self.dialog is None:
            self.dialog = MeteoleDialog(self.iface)

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _install_meteole(self):
        """Installe la librairie meteole via pip dans l'environnement QGIS."""
        import subprocess
        import sys

        python_exe = sys.executable
        try:
            result = subprocess.run(
                [python_exe, "-m", "pip", "install", "meteole"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                QMessageBox.information(
                    self.iface.mainWindow(),
                    "Installation réussie",
                    "La librairie 'meteole' a été installée avec succès.\n"
                    "Veuillez relancer le plugin.",
                )
            else:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Erreur d'installation",
                    f"L'installation a échoué :\n{result.stderr}",
                )
        except Exception as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Erreur",
                f"Impossible d'installer meteole :\n{str(e)}",
            )
