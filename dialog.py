# -*- coding: utf-8 -*-
"""
Boîte de dialogue principale du plugin Meteole.

Améliorations v1.1 :
  - _on_forecast_done reçoit des file_info (fichiers prêts) et non des DataFrames
    → seul QgsProject.addMapLayer() tourne dans le thread principal
  - Onglet "⏱ Horizons" : slider temporel pour basculer entre les couches raster
  - Le journal ne bascule plus automatiquement (on affiche un indicateur visuel discret)
  - Sauvegarde du modèle et de l'indicateur entre sessions

Améliorations v1.3 :
  - Refonte UX : interface guidée en 3 étapes
  - Connexion/paramètres déplacés dans un onglet dédié
  - Options avancées pliables

Améliorations v1.2 :
  - Sélecteur de territoire AROME pour les DROM-COM français
    (Antilles, Guyane, La Réunion/Mayotte, Nouvelle-Calédonie, Polynésie)
  - Bbox pré-rempli automatiquement selon le territoire choisi
  - Passage du paramètre territory au worker (et à la lib meteole)
  - Masquage du sélecteur territoire pour les modèles non-AROME
"""

import os
import datetime

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QComboBox, QPushButton, QTabWidget, QWidget,
    QCheckBox, QListWidget, QListWidgetItem,
    QProgressBar, QTextEdit, QSizePolicy, QMessageBox, QFileDialog,
    QScrollArea, QFrame, QSplitter, QSlider,
    QStackedWidget, QGridLayout
)
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QFont, QColor

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer,
    QgsCoordinateReferenceSystem, QgsApplication
)

from .worker import MeteoleWorker
from .layer_utils import (add_vigilance_layer, add_vigilance_dept_layer,
                           load_layers_from_files)


# ------------------------------------------------------------------ #
#  Territoires AROME disponibles
#  clé       : code meteole (passé à AromeForecast(territory=...))
#  label     : libellé affiché dans l'UI
#  bbox      : (lon_min, lon_max, lat_min, lat_max) en WGS84
# ------------------------------------------------------------------ #
# Précision par territoire :
#   FRANCE   → 0.01  (grille 1,3 km, endpoint …-001-FRANCE-WCS)
#   Outremer → 0.025 (grille 2,5 km, endpoint …-0025-<TERR>-WCS)
# L'API Météo-France renvoie HTTP 404 si on demande la mauvaise précision.
# Abonnements API Météo-France par territoire AROME :
#   FRANCE                → API "arome"                    (1.3 km, precision=0.01)
#   ANTIL + GUYANE        → API "arome-antilles-guyane"    (2.5 km, precision=0.025)
#   INDIEN (Réunion/May.) → API "arome-ocean-indien"       (2.5 km, precision=0.025)
#   NCALED                → API "arome-nouvelle-caledonie" (2.5 km, precision=0.025)
#   POLYN                 → API "arome-polynesie"          (2.5 km, precision=0.025)
# Chaque territoire outremer nécessite un abonnement DISTINCT sur le portail MF.
AROME_TERRITORIES = {
    "FRANCE": {
        "label":     "France métropolitaine",
        "bbox":      (-5.14, 9.56, 41.33, 51.09),
        "precision": 0.01,
        "grid":      "1.3 km",
        "api_name":  "arome",
    },
    "ANTIL": {
        "label":     "Antilles (Guadeloupe / Martinique)",
        "bbox":      (-63.60, -59.80, 14.20, 18.20),
        "precision": 0.025,
        "grid":      "2.5 km",
        "api_name":  "arome-antilles-guyane",
    },
    "GUYANE": {
        "label":     "Guyane",
        "bbox":      (-55.00, -51.50,  2.00,  6.00),
        "precision": 0.025,
        "grid":      "2.5 km",
        "api_name":  "arome-antilles-guyane",
    },
    "INDIEN": {
        "label":     "La Réunion / Mayotte",
        "bbox":      ( 42.00,  56.50, -23.00, -11.00),
        "precision": 0.025,
        "grid":      "2.5 km",
        "api_name":  "arome-ocean-indien",
    },
    "NCALED": {
        "label":     "Nouvelle-Calédonie",
        "bbox":      (162.50, 168.50, -22.80, -19.50),
        "precision": 0.025,
        "grid":      "2.5 km",
        "api_name":  "arome-nouvelle-caledonie",
    },
    "POLYN": {
        "label":     "Polynésie française",
        "bbox":      (-153.50, -148.00, -18.20, -15.00),
        "precision": 0.025,
        "grid":      "2.5 km",
        "api_name":  "arome-polynesie",
    },
}






class _FalseCheckBox:
    """Simule un QCheckBox toujours décoché — remplace chk_auto_horizons."""
    def isChecked(self): return False
    def setChecked(self, v): pass
    def toggled(self): pass
    def setEnabled(self, v): pass


class _FixedSpinValue:
    """Simule un QSpinBox avec valeur fixe."""
    def __init__(self, val): self._val = val
    def text(self): return str(self._val)
    def value(self): return self._val
    def setValue(self, v): self._val = v
    def setEnabled(self, v): pass


class _TerritoryAdapter:
    """
    Adaptateur pur Python pour cb_territory.
    Remplace un QComboBox caché — évite tout widget Qt et son popup bugué.
    """
    def __init__(self, territories: dict, on_changed_cb):
        self._items = [(info["label"], code)
                       for code, info in territories.items()]
        self._current = 0
        self._cb = on_changed_cb
        self._signals_blocked = False

    def currentData(self):
        if self._items:
            return self._items[self._current][1]
        return None

    def currentText(self) -> str:
        if self._items:
            return self._items[self._current][0]
        return ""

    def currentIndex(self) -> int:
        return self._current

    def count(self) -> int:
        return len(self._items)

    def itemData(self, idx):
        if 0 <= idx < len(self._items):
            return self._items[idx][1]
        return None

    def itemText(self, idx) -> str:
        if 0 <= idx < len(self._items):
            return self._items[idx][0]
        return ""

    def setCurrentIndex(self, idx: int):
        if 0 <= idx < len(self._items) and idx != self._current:
            self._current = idx
            if not self._signals_blocked:
                try:
                    self._cb(idx)
                except Exception:
                    pass

    def blockSignals(self, block: bool):
        self._signals_blocked = block

    def findText(self, text: str) -> int:
        for i, (lbl, _) in enumerate(self._items):
            if lbl == text:
                return i
        return -1

    def findData(self, data) -> int:
        for i, (_, code) in enumerate(self._items):
            if code == data:
                return i
        return -1


class _OmGridAdapter:
    """
    Adaptateur QLabel → interface QComboBox pour cb_om_grid.
    Stocke les données grille sans widget popup.
    """
    def __init__(self, label: QLabel, on_changed_cb):
        self._lbl = label
        self._items = []   # liste de (text, data)
        self._current = 0
        self._cb = on_changed_cb

    def clear(self):
        self._items = []
        self._current = 0
        self._lbl.setText("—")

    def addItem(self, text: str, data=None):
        self._items.append((text, data))
        if len(self._items) == 1:
            self._lbl.setText(text)
            self._current = 0
            try:
                self._cb(0)
            except Exception:
                pass

    def currentIndex(self) -> int:
        return self._current

    def currentText(self) -> str:
        if self._items:
            return self._items[self._current][0]
        return ""

    def itemData(self, idx):
        if 0 <= idx < len(self._items):
            return self._items[idx][1]
        return None

    def count(self) -> int:
        return len(self._items)

    def setCurrentIndex(self, idx: int):
        if 0 <= idx < len(self._items):
            self._current = idx
            self._lbl.setText(self._items[idx][0])



class _ListAdapter:
    """
    Adaptateur QListWidget → interface QComboBox générique.
    Remplace tous les QComboBox du wizard pour éviter le bug Qt5/Windows.
    """
    def __init__(self, lst: QListWidget):
        self._lst = lst

    def clear(self):
        self._lst.clear()

    def addItem(self, text: str, data=None):
        item = QListWidgetItem(text)
        if data is not None:
            item.setData(Qt.UserRole, data)
        self._lst.addItem(item)
        if self._lst.count() == 1:
            self._lst.setCurrentRow(0)

    def currentText(self) -> str:
        item = self._lst.currentItem()
        return item.text() if item else ""

    def currentData(self):
        item = self._lst.currentItem()
        return item.data(Qt.UserRole) if item else None

    def currentIndex(self) -> int:
        return self._lst.currentRow()

    def setCurrentIndex(self, idx: int):
        if 0 <= idx < self._lst.count():
            self._lst.setCurrentRow(idx)

    def setCurrentText(self, text: str):
        for i in range(self._lst.count()):
            if self._lst.item(i).text() == text:
                self._lst.setCurrentRow(i)
                return

    def count(self) -> int:
        return self._lst.count()

    def findText(self, text: str) -> int:
        for i in range(self._lst.count()):
            if self._lst.item(i).text() == text:
                return i
        return -1

    def itemText(self, idx: int) -> str:
        item = self._lst.item(idx)
        return item.text() if item else ""

    def blockSignals(self, block: bool):
        self._lst.blockSignals(block)

    def setPlaceholderText(self, text: str):
        pass  # non applicable sur QListWidget

    def update(self):
        self._lst.update()

    def repaint(self):
        self._lst.repaint()

    def setCompleter(self, _):
        pass

    def setEditable(self, _):
        pass

    def setSizePolicy(self, *args):
        self._lst.setSizePolicy(*args)


class _OmPackageAdapter:
    """
    Adaptateur QListWidget → interface QComboBox.
    Permet au code métier d'utiliser cb_om_package sans modification.
    Évite le bug Qt5/Windows où QComboBox crée un popup en fenêtre séparée.
    """
    def __init__(self, lst: QListWidget):
        self._lst = lst

    def clear(self):
        self._lst.clear()

    def addItem(self, text: str, data=None):
        item = QListWidgetItem(text)
        if data is not None:
            item.setData(Qt.UserRole, data)
        self._lst.addItem(item)
        # Sélectionner le premier item automatiquement
        if self._lst.count() == 1:
            self._lst.setCurrentRow(0)

    def currentText(self) -> str:
        item = self._lst.currentItem()
        return item.text() if item else ""

    def currentData(self):
        item = self._lst.currentItem()
        return item.data(Qt.UserRole) if item else None

    def count(self) -> int:
        return self._lst.count()

    def setCompleter(self, _):
        pass  # no-op

    def setEditable(self, _):
        pass  # no-op


class MeteoleDialog(QDialog):
    """Dialogue principal Meteole — interface guidée en 3 étapes."""

    # Indices des pages du QStackedWidget de prévision
    _PAGE_TYPE     = 0
    _PAGE_VARIABLE = 1
    _PAGE_OPTIONS  = 2

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface   = iface
        self.worker  = None
        self.thread  = None
        self.current_indicators = []
        self._horizon_layers    = []

        self.setWindowTitle("Meteole – Données Météo-France")
        self.setMinimumWidth(820)
        self.setMinimumHeight(500)
        self.resize(860, 620)
        # Fix Qt5/Windows : empêche la création de fenêtres enfants parasites
        self.setWindowFlags(
            Qt.Window |
            Qt.WindowTitleHint |
            Qt.WindowCloseButtonHint |
            Qt.WindowMinimizeButtonHint
        )
        # Non-modal : permet d'interagir avec QGIS pendant que le plugin est ouvert
        self.setWindowModality(Qt.NonModal)

        self._build_ui()
        self._load_settings()

    # ================================================================== #
    #  Construction de l'interface
    # ================================================================== #

    def closeEvent(self, event):
        self._reset_session()
        event.accept()

    def _build_ui(self):
        main = QVBoxLayout(self)
        main.setSpacing(0)
        main.setContentsMargins(0, 0, 0, 0)

        # ---- Barre de titre ----
        header = QWidget()
        header.setStyleSheet(
            "background: #2c5f8a; color: white;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)
        lbl = QLabel("🌤  Meteole – Données Météo-France")
        lbl.setStyleSheet("color:white; font-size:13px; font-weight:500;")
        hl.addWidget(lbl)

        # Bouton connexion/paramètres
        self.btn_settings = QPushButton("🔑 Connexion")
        self.btn_settings.setStyleSheet(
            "QPushButton{background:rgba(255,255,255,0.15);color:white;"
            "border:1px solid rgba(255,255,255,0.3);border-radius:4px;"
            "padding:4px 10px;font-size:12px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.25);}"
        )
        self.btn_settings.clicked.connect(self._show_settings_panel)
        hl.addWidget(self.btn_settings)
        main.addWidget(header)

        # ---- Corps principal avec onglets ----
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            "QTabBar::tab{padding:4px 10px;font-size:12px;min-width:80px;}"
        )
        main.addWidget(self.tabs, stretch=1)

        self.tabs.addTab(self._build_forecast_wizard(), "Prévisions")
        self.tabs.addTab(self._build_vigilance_tab(),   "Vigilance")
        self.tabs.addTab(self._build_horizons_tab(),    "Horizons")
        self.tabs.addTab(self._build_log_tab(),         "Journal")
        self.tabs.addTab(self._build_settings_tab(),    "Paramètres")
        # Cliquer sur l'onglet Prévisions ramène toujours à la page 1
        self.tabs.tabBarClicked.connect(
            lambda idx: self._goto_page(0) if idx == 0 else None)

        # Fix Qt5/Windows : force les popups QComboBox à rester
        # dans la fenêtre parente (évite la fenêtre QGIS3 parasite)
        self._fix_combo_popups()

        # ---- Barre de statut ----
        status_bar = QWidget()
        status_bar.setStyleSheet(
            "background:var(--color-background-secondary, #f5f5f5);"
            "border-top:1px solid #e0e0e0;"
        )
        sl = QHBoxLayout(status_bar)
        sl.setContentsMargins(12, 6, 12, 6)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.setStyleSheet(
            "QProgressBar{border:none;border-radius:3px;background:#e0e0e0;}"
            "QProgressBar::chunk{background:#2c5f8a;border-radius:3px;}"
        )
        sl.addWidget(self.progress, stretch=1)

        btn_close = QPushButton("Fermer")
        btn_close.setStyleSheet("padding:4px 14px;font-size:12px;")
        btn_close.clicked.connect(self.close)
        sl.addWidget(btn_close)
        main.addWidget(status_bar)

    # ================================================================== #
    #  Assistant de prévision (3 pages)
    # ================================================================== #

    def _build_forecast_wizard(self):
        """Conteneur du wizard à 3 pages."""
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        # --- Indicateur d'étapes ---
        steps_bar = QWidget()
        steps_bar.setStyleSheet("background:#f8f8f8;border-bottom:1px solid #e8e8e8;")
        sl = QHBoxLayout(steps_bar)
        sl.setContentsMargins(14, 8, 14, 8)
        sl.setSpacing(0)

        self._step_btns = []
        for i, (num, label) in enumerate([("1","Type & Territoire"),
                                           ("2","Variable"),
                                           ("3","Options & Chargement")]):
            btn = QPushButton(f" {num}  {label}")
            btn.setStyleSheet(self._step_style(i == 0))
            btn.setFlat(True)
            btn.clicked.connect(lambda _, p=i: self._goto_page(p))
            self._step_btns.append(btn)
            sl.addWidget(btn)
            if i < 2:
                arr = QLabel(" › ")
                arr.setStyleSheet("color:#bbb;font-size:14px;")
                sl.addWidget(arr)
        sl.addStretch()
        vl.addWidget(steps_bar)

        # Pages avec setVisible() — évite le bug Qt5/Windows du QStackedWidget
        pages_container = QWidget()
        pages_layout = QVBoxLayout(pages_container)
        pages_layout.setContentsMargins(0, 0, 0, 0)
        self._page_type     = self._build_page_type()
        self._page_variable = self._build_page_variable()
        self._page_options  = self._build_page_options()
        pages_layout.addWidget(self._page_type)
        pages_layout.addWidget(self._page_variable)
        pages_layout.addWidget(self._page_options)
        self._page_variable.setVisible(False)
        self._page_options.setVisible(False)
        vl.addWidget(pages_container, stretch=1)
        return w

    def _step_style(self, active):
        if active:
            return ("QPushButton{background:#2c5f8a;color:white;border:none;"
                    "padding:5px 14px;border-radius:4px;font-size:12px;font-weight:500;}")
        return ("QPushButton{background:transparent;color:#888;border:none;"
                "padding:5px 14px;border-radius:4px;font-size:12px;}"
                "QPushButton:hover{color:#2c5f8a;}")

    def _goto_page(self, page):
        # Ne pas forcer setCurrentIndex(0) ici — cause réorganisation fenêtres Qt5
        if self.tabs.currentIndex() != 0:
            self.tabs.setCurrentIndex(0)
        self._page_type.setVisible(page == self._PAGE_TYPE)
        self._page_variable.setVisible(page == self._PAGE_VARIABLE)
        self._page_options.setVisible(page == self._PAGE_OPTIONS)
        for i, btn in enumerate(self._step_btns):
            btn.setStyleSheet(self._step_style(i == page))
        if page in (self._PAGE_VARIABLE, self._PAGE_OPTIONS):
            self._update_om_mode()
        if page == self._PAGE_OPTIONS:
            self._update_summary()
        # Réappliquer le fix combo après chaque transition
        try:
            self._fix_combo_popups()
        except Exception:
            pass

    # ---- Page 1 : Territoire ----
    def _build_page_type(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(14)

        # Type de données
        vl.addWidget(self._section_label("Que voulez-vous visualiser ?"))
        type_row = QHBoxLayout()
        self.btn_type_forecast  = self._toggle_btn("🌡  Prévision météo", True)
        self.btn_type_vigilance = self._toggle_btn("⚠️  Vigilance Météo-France", False)
        self.btn_type_forecast.clicked.connect(lambda: self._select_type("forecast"))
        self.btn_type_vigilance.clicked.connect(lambda: self._select_type("vigilance"))
        type_row.addWidget(self.btn_type_forecast)
        type_row.addWidget(self.btn_type_vigilance)
        type_row.addStretch()
        vl.addLayout(type_row)

        # Territoire — cartes visuelles
        vl.addWidget(self._section_label("Territoire"))

        # Métropole
        self.btn_terr_metro = self._terr_card(
            "🇫🇷", "France métropolitaine",
            "AROME · ARPEGE · 1,3–10 km", True)
        self.btn_terr_metro.clicked.connect(
            lambda: self._select_territory("FRANCE"))

        # Outremer — grille 3 colonnes
        om_cards = [
            ("🏝", "Antilles",       "Guadeloupe / Martinique", "ANTIL"),
            ("🌿", "Guyane",         "Guyane française",        "GUYANE"),
            ("🌊", "Réunion/Mayotte","Océan Indien",            "INDIEN"),
            ("🗺", "Nvle-Calédonie", "Pacifique Sud",           "NCALED"),
            ("🌺", "Polynésie",      "Pacifique",               "POLYN"),
        ]
        self._terr_om_btns = {}
        metro_row = QHBoxLayout()
        metro_row.addWidget(self.btn_terr_metro)
        metro_row.addStretch()
        vl.addLayout(metro_row)

        vl.addWidget(self._section_label("Territoires d'outre-mer"))
        om_note = QLabel(
            "<i>Chaque territoire outremer nécessite un abonnement séparé "
            "sur <a href='https://portail-api.meteofrance.fr/'>portail-api.meteofrance.fr</a>.</i>")
        om_note.setOpenExternalLinks(True)
        om_note.setWordWrap(True)
        om_note.setStyleSheet("color:#666;font-size:11px;")
        vl.addWidget(om_note)

        om_grid = QGridLayout()
        om_grid.setSpacing(6)
        for i, (icon, name, sub, code) in enumerate(om_cards):
            btn = self._terr_card(icon, name, sub, False)
            btn.clicked.connect(lambda _, c=code: self._select_territory(c))
            self._terr_om_btns[code] = btn
            om_grid.addWidget(btn, i // 3, i % 3)
        vl.addLayout(om_grid)

        vl.addStretch()
        next_btn = QPushButton("Choisir la variable  →")
        next_btn.setStyleSheet(
            "QPushButton{background:#2c5f8a;color:white;border:none;"
            "padding:9px;border-radius:5px;font-size:13px;font-weight:500;}"
            "QPushButton:hover{background:#1a4a6e;}")
        next_btn.clicked.connect(self._on_next_from_territory)
        vl.addWidget(next_btn)
        scroll.setWidget(w)
        return scroll

    def _terr_card(self, icon, name, subtitle, active):
        """Crée un bouton-carte territoire."""
        btn = QPushButton(f"{icon}  {name}\n{subtitle}")
        btn.setCheckable(True)
        btn.setChecked(active)
        self._style_terr_card(btn, active)
        btn.toggled.connect(lambda c, b=btn: self._style_terr_card(b, c))
        return btn

    def _style_terr_card(self, btn, active):
        base = ("QPushButton{text-align:left;padding:8px 12px;"
                "border-radius:5px;font-size:12px;line-height:1.4;}")
        if active:
            btn.setStyleSheet(base +
                "QPushButton{background:#eef4fb;border:1.5px solid #2c5f8a;color:#1a3a5a;}")
        else:
            btn.setStyleSheet(base +
                "QPushButton{background:transparent;border:1px solid #ccc;color:#444;}"
                "QPushButton:hover{border-color:#2c5f8a;color:#2c5f8a;}")

    def _select_territory(self, code):
        """Sélectionne un territoire et met à jour les cartes."""
        # Réinitialiser les données du run précédent
        try:
            self._horizon_layers = []
            self.slider_horizon.setValue(0)
            self.slider_horizon.setMaximum(0)
            self.slider_horizon.setEnabled(False)
            self.lbl_horizon_current.setText("Aucun horizon")
            self.list_horizon_layers.clear()
            self.list_all_horizons.clear()
            self.cb_indicator.clear()
            self.cb_om_package.clear()
            self.cb_om_grid.clear()
        except Exception:
            pass
        # Désélectionner tout
        self.btn_terr_metro.setChecked(code == "FRANCE")
        self._style_terr_card(self.btn_terr_metro, code == "FRANCE")
        for c, btn in self._terr_om_btns.items():
            active = (c == code)
            btn.setChecked(active)
            self._style_terr_card(btn, active)
        # Synchroniser cb_territory
        for i in range(self.cb_territory.count()):
            if self.cb_territory.itemData(i) == code:
                self.cb_territory.setCurrentIndex(i)
                break

    def _on_next_from_territory(self):
        """Lance le chargement des indicateurs et bascule page Variable."""
        self._on_get_capabilities()
        self._goto_page(self._PAGE_VARIABLE)
    # ---- Page 2 : Variable ----
    def _build_page_variable(self):
        # Pas de QScrollArea : évite le popup QComboBox hors fenêtre sous Qt5
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(12)

        # ---- Mode métropole : choix du modèle + indicateur ----
        self.grp_metro_var = QGroupBox("Modèle et variable (métropole)")
        metro_vl = QVBoxLayout(self.grp_metro_var)

        metro_vl.addWidget(QLabel("Modèle :"))
        self._lst_model = QListWidget()
        self._lst_model.setMaximumHeight(105)
        self._lst_model.setSelectionMode(QListWidget.SingleSelection)
        for _m in [
            "AROME  (1,3 km — prévision à courte échéance)",
            "AROME-PI  (1,3 km — prévision immédiate)",
            "AROME-PE  (2,8 km — ensemble 25 scénarios)",
            "ARPEGE  (10 km — prévision globale)",
            "PIAF  (1,3 km — prévision très courte)",
        ]:
            self._lst_model.addItem(_m)
        self._lst_model.setCurrentRow(0)
        self._lst_model.currentTextChanged.connect(self._on_model_changed)
        metro_vl.addWidget(self._lst_model)
        self.cb_model = _ListAdapter(self._lst_model)

        metro_vl.addWidget(QLabel("Indicateur :"))
        self._lst_indicator = QListWidget()
        self._lst_indicator.setMaximumHeight(140)
        self._lst_indicator.setSelectionMode(QListWidget.SingleSelection)
        metro_vl.addWidget(self._lst_indicator)
        self.cb_indicator = _ListAdapter(self._lst_indicator)

        btn_reload = QPushButton("↺  Recharger la liste des indicateurs")
        btn_reload.setStyleSheet(
            "QPushButton{background:transparent;color:#2c5f8a;border:none;"
            "font-size:11px;text-align:left;padding:2px 0;}"
            "QPushButton:hover{text-decoration:underline;}")
        btn_reload.clicked.connect(self._on_get_capabilities)
        metro_vl.addWidget(btn_reload)
        vl.addWidget(self.grp_metro_var)

        # ---- Mode AROME-OM : grille + variable directe ----
        self.grp_om = QGroupBox("Variable disponible (AROME Outre-Mer)")
        om_vl = QVBoxLayout(self.grp_om)

        # cb_territory : adaptateur pur Python (pas de widget Qt)
        # évite le popup flottant Qt5/Windows
        self.cb_territory = _TerritoryAdapter(AROME_TERRITORIES,
                                               self._on_territory_changed)

        om_grid_row = QHBoxLayout()
        om_grid_row.addWidget(QLabel("Grille :"))
        self._lbl_om_grid = QLabel("—")
        self._lbl_om_grid.setStyleSheet(
            "background:var(--color-bg,#f5f5f5);border:1px solid #ccc;"
            "padding:4px 8px;border-radius:3px;font-size:12px;")
        om_grid_row.addWidget(self._lbl_om_grid, stretch=1)
        # Adaptateur pour compatibilité avec le code métier
        self.cb_om_grid = _OmGridAdapter(self._lbl_om_grid,
                                          self._on_om_grid_changed)
        om_vl.addLayout(om_grid_row)

        om_vl.addWidget(QLabel("Variable :"))
        # QListWidget au lieu de QComboBox : évite le popup flottant Qt5/Windows
        self.lst_om_package = QListWidget()
        self.lst_om_package.setMaximumHeight(180)
        self.lst_om_package.setSelectionMode(QListWidget.SingleSelection)
        om_vl.addWidget(self.lst_om_package)
        # cb_om_package : alias pour compatibilité avec le code métier
        self.cb_om_package = _OmPackageAdapter(self.lst_om_package)

        self.grp_om.setVisible(False)
        vl.addWidget(self.grp_om)

        vl.addStretch()

        # Navigation
        nav = QHBoxLayout()
        back = QPushButton("← Retour")
        back.setStyleSheet("padding:8px 14px;font-size:12px;")
        back.clicked.connect(lambda: self._goto_page(self._PAGE_TYPE))
        nav.addWidget(back)
        nav.addStretch()
        next_btn = QPushButton("Configurer et charger  →")
        next_btn.setStyleSheet(
            "QPushButton{background:#2c5f8a;color:white;border:none;"
            "padding:9px 18px;border-radius:5px;font-size:13px;font-weight:500;}"
            "QPushButton:hover{background:#1a4a6e;}")
        next_btn.clicked.connect(lambda: self._goto_page(self._PAGE_OPTIONS))
        nav.addWidget(next_btn)
        vl.addLayout(nav)

        return w
    # ---- Page 3 : Options & Chargement ----
    def _build_page_options(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(10)

        # Résumé de la sélection
        self.lbl_selection_summary = QLabel("")
        self.lbl_selection_summary.setWordWrap(True)
        self.lbl_selection_summary.setStyleSheet(
            "background:#eef4fb;border:1px solid #c5d8ee;"
            "border-radius:4px;padding:8px 12px;font-size:12px;color:#1a4a6e;")
        vl.addWidget(self.lbl_selection_summary)

        # Horizons
        grp_horiz = QGroupBox("Horizon de prévision")
        horiz_vl = QVBoxLayout(grp_horiz)
        horiz_vl.addWidget(QLabel(
            "Entrez les horizons souhaités (format HHH<b>H</b>, séparés par des virgules) :"))
        self.le_om_horizons = QLineEdit()
        self.le_om_horizons.setText("001H")
        self.le_om_horizons.setPlaceholderText("ex: 001H,024H,048H")
        horiz_vl.addWidget(self.le_om_horizons)
        horiz_vl.addWidget(QLabel(
            "<span style='color:#888;font-size:11px'>"
            "Exemple : <i>001H</i> pour H+1 uniquement, "
            "<i>001H,006H,012H,024H</i> pour 4 horizons</span>"))
        # Attributs de compatibilité avec l'ancienne logique
        self.chk_auto_horizons = _FalseCheckBox()
        self.horiz_manual_widget = self.le_om_horizons
        self.sp_h_from = _FixedSpinValue(1)
        self.sp_h_to   = _FixedSpinValue(24)
        vl.addWidget(grp_horiz)

        # Run
        grp_run = QGroupBox("Run météo")
        run_vl = QVBoxLayout(grp_run)
        self.chk_auto_run = QCheckBox("Dernier run disponible (recommandé)")
        self.chk_auto_run.setChecked(True)
        self.chk_auto_run.toggled.connect(self._toggle_run)
        run_vl.addWidget(self.chk_auto_run)
        run_row = QHBoxLayout()
        self.dte_run = QLineEdit()
        self.dte_run.setPlaceholderText("yyyy-MM-dd HH:mm  ex: 2026-03-27 06:00")
        self.dte_run.setEnabled(False)
        run_row.addWidget(self.dte_run)
        run_vl.addLayout(run_row)

        # Run OM
        self.chk_om_auto_run = QCheckBox("Dernier run OM (recommandé)")
        self.chk_om_auto_run.setChecked(True)
        self.chk_om_auto_run.toggled.connect(
            lambda v: self.dte_om_run.setEnabled(not v))
        self.dte_om_run = QLineEdit()
        self.dte_om_run.setPlaceholderText("yyyy-MM-dd HH:mm  ex: 2026-03-27 06:00")
        self.dte_om_run.setEnabled(False)
        self.om_run_widget = QWidget()
        om_run_vl = QVBoxLayout(self.om_run_widget)
        om_run_vl.setContentsMargins(0, 0, 0, 0)
        om_run_vl.addWidget(self.chk_om_auto_run)
        om_run_vl.addWidget(self.dte_om_run)
        self.om_run_widget.setVisible(False)
        run_vl.addWidget(self.om_run_widget)
        vl.addWidget(grp_run)

        # Options avancées (pliables)
        self.btn_adv_toggle = QPushButton("▸  Options avancées (zone, niveaux…)")
        self.btn_adv_toggle.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#666;"
            "text-align:left;padding:4px 0;font-size:12px;}"
            "QPushButton:hover{color:#2c5f8a;}")
        self.btn_adv_toggle.clicked.connect(self._toggle_advanced)
        vl.addWidget(self.btn_adv_toggle)

        self.adv_widget = QWidget()
        adv_vl = QVBoxLayout(self.adv_widget)
        adv_vl.setContentsMargins(0, 0, 0, 0)
        adv_vl.setSpacing(8)

        # Zone géographique
        grp_geo = QGroupBox("Zone géographique")
        geo_vl = QVBoxLayout(grp_geo)
        self.chk_full_territory = QCheckBox("Territoire entier (bbox automatique)")
        self.chk_full_territory.setChecked(True)
        self.chk_full_territory.toggled.connect(self._toggle_geo)
        geo_vl.addWidget(self.chk_full_territory)
        geo_coords = QHBoxLayout()
        for label, attr, default in [
            ("Lon min:", "sp_lon_min", -5.14),
            ("Lon max:", "sp_lon_max",  9.56),
            ("Lat min:", "sp_lat_min", 41.33),
            ("Lat max:", "sp_lat_max", 51.09),
        ]:
            geo_coords.addWidget(QLabel(label))
            le = QLineEdit(str(default))
            le.setMaximumWidth(75)
            setattr(self, attr, le)
            geo_coords.addWidget(le)
        self.geo_widget = QWidget()
        self.geo_widget.setLayout(geo_coords)
        self.geo_widget.setEnabled(False)
        geo_vl.addWidget(self.geo_widget)
        btn_canvas = QPushButton("📐 Utiliser l'emprise du canevas")
        btn_canvas.clicked.connect(self._use_canvas_extent)
        geo_vl.addWidget(btn_canvas)
        adv_vl.addWidget(grp_geo)

        # Niveaux verticaux — métropole uniquement (AROME/ARPEGE)
        self.grp_alt = QGroupBox("Niveaux verticaux (AROME métropole, ARPEGE)")
        alt_vl2 = QVBoxLayout(self.grp_alt)
        alt_row = QHBoxLayout()
        alt_row.addWidget(QLabel("Hauteur (m):"))
        self.le_heights = QLineEdit()
        self.le_heights.setPlaceholderText("ex: 2, 10")
        alt_row.addWidget(self.le_heights)
        alt_row.addWidget(QLabel("Pression (hPa):"))
        self.le_pressures = QLineEdit()
        self.le_pressures.setPlaceholderText("ex: 500, 850")
        alt_row.addWidget(self.le_pressures)
        alt_vl2.addLayout(alt_row)

        # Note outremer
        self.lbl_alt_om_note = QLabel(
            "<i>Pour AROME Outre-Mer, les niveaux sont déterminés par le paquet : "
            "SP = surface, IP = niveaux isobares, HP = niveaux hybrides. "
            "Sélectionnez le paquet adapté à l'étape 2.</i>")
        self.lbl_alt_om_note.setWordWrap(True)
        self.lbl_alt_om_note.setStyleSheet("font-size:11px;color:#666;")
        self.lbl_alt_om_note.setVisible(False)
        alt_vl2.addWidget(self.lbl_alt_om_note)
        adv_vl.addWidget(self.grp_alt)

        # Ensemble
        self.grp_ens = QGroupBox("Ensemble (AROME-PE)")
        ens_row = QHBoxLayout(self.grp_ens)
        ens_row.addWidget(QLabel("Scénarios:"))
        self.sp_ensemble = QLineEdit("3")
        self.sp_ensemble.setMaximumWidth(50)
        self.sp_ensemble.setPlaceholderText("3")
        ens_row.addWidget(self.sp_ensemble)
        ens_row.addStretch()
        self.grp_ens.setVisible(False)
        adv_vl.addWidget(self.grp_ens)

        self.adv_widget.setVisible(False)
        vl.addWidget(self.adv_widget)

        vl.addStretch()

        # Boutons d'action
        nav = QHBoxLayout()
        back = QPushButton("← Retour")
        back.setStyleSheet("padding:8px 14px;font-size:12px;")
        back.clicked.connect(lambda: self._goto_page(self._PAGE_VARIABLE))
        nav.addWidget(back)

        # Bouton lister indicateurs (métropole)
        self.btn_capabilities = QPushButton("🔍 Lister les indicateurs")
        self.btn_capabilities.setStyleSheet(
            "QPushButton{background:#4a8a4a;color:white;border:none;"
            "padding:9px 14px;border-radius:5px;font-size:12px;}"
            "QPushButton:hover{background:#2e6b2e;}")
        self.btn_capabilities.clicked.connect(self._on_get_capabilities)
        nav.addWidget(self.btn_capabilities)

        nav.addStretch()
        self.btn_load = QPushButton("⬇  Charger la couche")
        self.btn_load.setStyleSheet(
            "QPushButton{background:#2c5f8a;color:white;border:none;"
            "padding:9px 20px;border-radius:5px;font-size:13px;font-weight:500;}"
            "QPushButton:hover{background:#1a4a6e;}"
            "QPushButton:disabled{background:#aaa;}")
        self.btn_load.clicked.connect(self._on_load)
        nav.addWidget(self.btn_load)
        vl.addLayout(nav)

        # Option couche points — sur ligne séparée pour ne pas élargir la fenêtre
        self.chk_load_points = QCheckBox(
            "Charger aussi la couche points (nœuds de grille bruts)")
        self.chk_load_points.setChecked(False)
        self.chk_load_points.setStyleSheet("font-size:11px;color:#888;")
        vl.addWidget(self.chk_load_points)

        scroll.setWidget(w)
        return scroll

    # ================================================================== #
    #  Onglet Vigilance
    # ================================================================== #

    def _build_vigilance_tab(self):
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(10)

        info = QLabel(
            "<b>Bulletins de vigilance Météo-France</b><br>"
            "Carte officielle par département et tableau des phénomènes en cours.")
        info.setWordWrap(True)
        vl.addWidget(info)

        self.chk_phenomenon = QCheckBox("Tableau des phénomènes")
        self.chk_phenomenon.setChecked(True)
        vl.addWidget(self.chk_phenomenon)
        self.chk_timelaps = QCheckBox("Plages horaires par département")
        self.chk_timelaps.setChecked(True)
        vl.addWidget(self.chk_timelaps)

        btn_vigi = QPushButton("⚠️  Charger la vigilance")
        btn_vigi.setStyleSheet(
            "QPushButton{background:#b55a00;color:white;border:none;"
            "padding:9px 20px;border-radius:5px;font-size:13px;font-weight:500;}"
            "QPushButton:hover{background:#7a3c00;}")
        btn_vigi.clicked.connect(self._on_load_vigilance)
        vl.addWidget(btn_vigi)

        vl.addWidget(QLabel("<b>Synthèse :</b>"))
        self.tbl_vigilance = QTextEdit()
        self.tbl_vigilance.setReadOnly(True)
        self.tbl_vigilance.setMaximumHeight(180)
        vl.addWidget(self.tbl_vigilance)
        vl.addStretch()
        return w

    # ================================================================== #
    #  Onglet Horizons
    # ================================================================== #

    def _build_horizons_tab(self):
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(10)

        info = QLabel(
            "<b>Navigateur temporel</b><br>"
            "Après un chargement multi-horizons, naviguez entre les couches raster.")
        info.setWordWrap(True)
        vl.addWidget(info)

        slider_row = QHBoxLayout()
        lbl_prev = QLabel("◀")
        lbl_prev.setCursor(Qt.PointingHandCursor)
        lbl_prev.mousePressEvent = lambda _: self._step_horizon(-1)
        slider_row.addWidget(lbl_prev)
        self.slider_horizon = QSlider(Qt.Horizontal)
        self.slider_horizon.setMinimum(0)
        self.slider_horizon.setMaximum(0)
        self.slider_horizon.setEnabled(False)
        self.slider_horizon.valueChanged.connect(self._on_horizon_changed)
        slider_row.addWidget(self.slider_horizon, stretch=1)
        lbl_next = QLabel("▶")
        lbl_next.setCursor(Qt.PointingHandCursor)
        lbl_next.mousePressEvent = lambda _: self._step_horizon(+1)
        slider_row.addWidget(lbl_next)
        vl.addLayout(slider_row)

        self.lbl_horizon_current = QLabel("Aucun horizon")
        self.lbl_horizon_current.setAlignment(Qt.AlignCenter)
        self.lbl_horizon_current.setStyleSheet(
            "font-size:13px;font-weight:500;color:#2c5f8a;"
            "background:#eef4fb;padding:6px;border-radius:4px;")
        vl.addWidget(self.lbl_horizon_current)

        vl.addWidget(QLabel("Couches de l'horizon :"))
        self.list_horizon_layers = QListWidget()
        self.list_horizon_layers.setMaximumHeight(90)
        vl.addWidget(self.list_horizon_layers)

        ctrl = QHBoxLayout()
        for label, fn in [("👁 Tout afficher", lambda: self._set_all_horizons_visible(True)),
                           ("🙈 Masquer",       lambda: self._set_all_horizons_visible(False)),
                           ("🔍 Zoomer",        self._zoom_to_current_horizon)]:
            b = QPushButton(label)
            b.clicked.connect(fn)
            ctrl.addWidget(b)
        vl.addLayout(ctrl)

        vl.addWidget(QLabel("Tous les horizons :"))
        self.list_all_horizons = QListWidget()
        vl.addWidget(self.list_all_horizons)
        vl.addStretch()
        return w

    # ================================================================== #
    #  Onglet Journal
    # ================================================================== #

    def _build_log_tab(self):
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(10, 10, 10, 10)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 9))
        vl.addWidget(self.log_view)
        b = QPushButton("Effacer")
        b.clicked.connect(self.log_view.clear)
        vl.addWidget(b)
        return w

    # ================================================================== #
    #  Onglet Paramètres (connexion + diagnostic)
    # ================================================================== #

    def _build_settings_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 14, 16, 14)
        vl.setSpacing(12)

        # Auth
        grp = QGroupBox("Authentification Météo-France")
        gl = QVBoxLayout(grp)

        auth_row = QHBoxLayout()
        auth_row.addWidget(QLabel("Type :"))
        self.cb_auth_type = QComboBox()
        self.cb_auth_type.addItems([
            "token  (Générer token sur le portail)",
            "api_key  (Clé API directe)",
            "application_id  (OAuth)",
        ])
        self.cb_auth_type.currentIndexChanged.connect(self._on_auth_type_changed)
        auth_row.addWidget(self.cb_auth_type)
        gl.addLayout(auth_row)

        key_row = QHBoxLayout()
        self.lbl_auth_key = QLabel("Token :")
        self.lbl_auth_key.setMinimumWidth(80)
        key_row.addWidget(self.lbl_auth_key)
        self.le_appid = QLineEdit()
        self.le_appid.setEchoMode(QLineEdit.Password)
        self.le_appid.setPlaceholderText("Collez votre clé ici…")
        key_row.addWidget(self.le_appid)
        chk_show = QCheckBox("Afficher")
        chk_show.toggled.connect(
            lambda v: self.le_appid.setEchoMode(
                QLineEdit.Normal if v else QLineEdit.Password))
        key_row.addWidget(chk_show)
        gl.addLayout(key_row)

        btn_portail = QPushButton("🔗 Ouvrir portail-api.meteofrance.fr")
        btn_portail.setStyleSheet("color:#2c5f8a;border:none;text-align:left;")
        btn_portail.clicked.connect(
            lambda: __import__("webbrowser").open(
                "https://portail-api.meteofrance.fr/"))
        gl.addWidget(btn_portail)

        gl.addWidget(QLabel(
            "<span style='color:#888;font-size:11px'>"
            "⚠️ Le token expire après 1 heure.</span>"))
        vl.addWidget(grp)

        # Diagnostic URLs outremer
        grp_probe = QGroupBox("Diagnostic URLs AROME Outre-Mer")
        probe_vl = QVBoxLayout(grp_probe)
        probe_row = QHBoxLayout()
        probe_row.addWidget(QLabel("Territoire :"))
        self.cb_probe_territory = QComboBox()
        for code, info in AROME_TERRITORIES.items():
            if code != "FRANCE":
                self.cb_probe_territory.addItem(
                    f"{info['label']} ({code})", code)
        probe_row.addWidget(self.cb_probe_territory)
        btn_probe = QPushButton("🔍 Tester les URLs")
        btn_probe.setStyleSheet(
            "QPushButton{background:#6a4a9a;color:white;border:none;"
            "padding:5px 10px;border-radius:4px;}"
            "QPushButton:hover{background:#4a2a7a;}")
        btn_probe.clicked.connect(self._on_probe_urls)
        probe_row.addWidget(btn_probe)
        probe_vl.addLayout(probe_row)
        self.probe_results_view = QTextEdit()
        self.probe_results_view.setReadOnly(True)
        self.probe_results_view.setMaximumHeight(100)
        self.probe_results_view.setFont(QFont("Courier New", 9))
        probe_vl.addWidget(self.probe_results_view)
        vl.addWidget(grp_probe)

        vl.addStretch()
        scroll.setWidget(w)
        return scroll

    # ================================================================== #
    #  Helpers UI
    # ================================================================== #

    def _fix_combo_popups(self):
        """Fix Qt5/Windows : les QComboBox dans QStackedWidget créent
        un popup en fenêtre séparée. On force Qt.Tool sur leur view.
        À appeler après construction complète de l'UI.
        """
        for combo in self.findChildren(QComboBox):
            try:
                combo.setEditable(False)
                combo.setCompleter(None)
                view = combo.view()
                if view:
                    win = view.window()
                    if win and win is not self:
                        win.setWindowFlags(
                            win.windowFlags() | Qt.Tool)
            except Exception:
                pass


    def _reset_session(self):
        """Remet à zéro l'état du wizard et de l'onglet Horizons."""
        # Horizons
        self._horizon_layers = []
        try:
            self.slider_horizon.setValue(0)
            self.slider_horizon.setMaximum(0)
            self.slider_horizon.setEnabled(False)
            self.lbl_horizon_current.setText("Aucun horizon")
            self.list_horizon_layers.clear()
            self.list_all_horizons.clear()
        except Exception:
            pass

        # Champ horizons
        try:
            self.le_om_horizons.setText("001H")
        except Exception:
            pass

        # Listes variables / indicateurs
        try:
            self.cb_indicator.clear()
        except Exception:
            pass
        try:
            self.cb_om_package.clear()
        except Exception:
            pass
        try:
            self.cb_om_grid.clear()
        except Exception:
            pass

        # Journal
        try:
            self.log_view.clear()
        except Exception:
            pass

        # Revenir à la page 1
        try:
            self._goto_page(self._PAGE_TYPE)
        except Exception:
            pass

    def _section_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "font-size:11px;font-weight:500;color:#888;"
            "text-transform:uppercase;letter-spacing:0.05em;")
        return lbl

    def _toggle_btn(self, text, active):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(active)
        self._style_toggle_btn(btn, active)
        btn.toggled.connect(lambda c, b=btn: self._style_toggle_btn(b, c))
        return btn

    def _style_toggle_btn(self, btn, active):
        if active:
            btn.setStyleSheet(
                "QPushButton{background:#2c5f8a;color:white;border:none;"
                "padding:8px 16px;border-radius:5px;font-size:13px;}")
        else:
            btn.setStyleSheet(
                "QPushButton{background:transparent;color:#555;"
                "border:1px solid #ccc;padding:8px 16px;"
                "border-radius:5px;font-size:13px;}"
                "QPushButton:hover{border-color:#2c5f8a;color:#2c5f8a;}")

    def _select_type(self, type_):
        is_f = (type_ == "forecast")
        self.btn_type_forecast.setChecked(is_f)
        self.btn_type_vigilance.setChecked(not is_f)
        self._style_toggle_btn(self.btn_type_forecast, is_f)
        self._style_toggle_btn(self.btn_type_vigilance, not is_f)
        if not is_f:
            # Basculer vers l'onglet vigilance
            self.tabs.setCurrentIndex(1)

    def _toggle_advanced(self):
        visible = self.adv_widget.isVisible()
        self.adv_widget.setVisible(not visible)
        self.btn_adv_toggle.setText(
            ("▾" if not visible else "▸") +
            "  Options avancées (zone, niveaux…)")

    def _show_settings_panel(self):
        self.tabs.setCurrentIndex(4)

    # ---- Compat avec business logic ----
    _TAB_FORECAST  = 0
    _TAB_VIGILANCE = 1
    _TAB_HORIZONS  = 2
    _TAB_LOG       = 3

    def _on_tab_changed(self, idx):
        pass  # plus de logique de bouton par onglet

    def _log(self, msg, switch_tab=False):
        self.log_view.append(msg)
        if switch_tab or msg.startswith("[ERR]"):
            self.tabs.setCurrentIndex(self._TAB_LOG)

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        self.btn_load.setEnabled(not busy)
        self.btn_capabilities.setEnabled(not busy)

    def _update_summary(self):
        """Met à jour le résumé affiché en haut de la page Options."""
        try:
            is_om = self._is_om_territory()
            if is_om:
                entry = self.cb_om_package.currentData()
                var   = entry.get("display", "?") if entry else "?"
                terr  = AROME_TERRITORIES.get(
                    self.cb_territory.currentData(), {}).get("label", "?")
                txt = f"<b>{var}</b><br>Territoire : {terr}"
            else:
                ind  = self.cb_indicator.currentText() or "—"
                model = self.cb_model.currentText().split("  ")[0]
                txt  = f"<b>{ind}</b><br>Modèle : {model}"
            self.lbl_selection_summary.setText(txt)
        except Exception:
            pass

    def _update_om_mode(self):
        """Bascule l'UI selon territoire métropole/outremer."""
        try:
            is_om = self._is_om_territory()
        except Exception:
            is_om = False
        self.grp_om.setVisible(is_om)
        self.grp_metro_var.setVisible(not is_om)
        try:
            self.om_horizons_widget.setVisible(is_om)
            self.om_run_widget.setVisible(is_om)
        except Exception:
            pass
        try:
            if is_om:
                self.grp_alt.setVisible(True)
                self.le_heights.setVisible(False)
                self.le_pressures.setVisible(False)
                self.lbl_alt_om_note.setVisible(True)
                self.grp_ens.setVisible(False)
            else:
                model = self.cb_model.currentText()
                has_levels = any(m in model for m in
                                 ("AROME  ", "AROME-PE", "ARPEGE"))
                self.grp_alt.setVisible(has_levels)
                self.le_heights.setVisible(True)
                self.le_pressures.setVisible(True)
                self.lbl_alt_om_note.setVisible(False)
                self.grp_ens.setVisible(
                    "PE" in model or "ensemble" in model)
        except Exception:
            pass

    def _on_model_changed(self, text):
        self._update_om_mode()
        self.cb_indicator.clear()

    def _is_om_territory(self):
        code = self.cb_territory.currentData()
        return code not in ("FRANCE", None, "")


    def _toggle_run(self, auto):
        self.dte_run.setEnabled(not auto)

    def _toggle_horizons(self, auto):
        self.horiz_manual_widget.setEnabled(not auto)

    def _toggle_geo(self, full):
        self.geo_widget.setEnabled(not full)

    # Index des onglets (ordre défini dans _build_ui)
    # _TAB_* définis dans le bloc UI (nouvelles valeurs)

    def _on_load_current_tab(self):
        """Dispatch du bouton principal selon l'onglet actif."""
        idx = self.tabs.currentIndex()
        if idx == self._TAB_FORECAST:
            self._on_load()
        elif idx == self._TAB_VIGILANCE:
            self._on_load_vigilance()

    def _on_territory_changed(self, _):
        """Met à jour la bbox et remet 'territoire entier' quand on change de territoire."""
        code = self.cb_territory.currentData()
        info = AROME_TERRITORIES.get(code, AROME_TERRITORIES["FRANCE"])
        lon_min, lon_max, lat_min, lat_max = info["bbox"]
        self.sp_lon_min.setText(str(lon_min))
        self.sp_lon_max.setText(str(lon_max))
        self.sp_lat_min.setText(str(lat_min))
        self.sp_lat_max.setText(str(lat_max))
        # Remet la case "territoire entier" cochée (bbox auto = pas de filtre lon/lat)
        self.chk_full_territory.setChecked(True)
        # Affiche/masque le panneau OM selon le territoire
        is_om = code != "FRANCE"
        self.grp_om.setVisible(is_om)
        if is_om:
            self.grp_alt.setVisible(False)
            self.grp_ens.setVisible(False)
            # Réinitialise les combos OM
            self.cb_om_grid.clear()
            self.cb_om_package.clear()
            self.cb_indicator.clear()
            self.cb_indicator.setPlaceholderText(
                "Cliquez 'Lister' pour charger les paquets AROME-OM…")
        else:
            self.grp_om.setVisible(False)
        grid      = info.get('grid', '?')
        precision = info.get('precision', 0.025)
        api_name  = info.get('api_name', 'arome')
        self._log(
            f"[INFO] Territoire AROME → {info['label']} ({code}) "
            f"| API: {api_name} | résolution {grid} (precision={precision}) "
            f"| bbox lon [{lon_min}, {lon_max}] lat [{lat_min}, {lat_max}]"
        )

    def _use_canvas_extent(self):
        extent = self.iface.mapCanvas().extent()
        crs    = self.iface.mapCanvas().mapSettings().destinationCrs()
        from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem
        wgs84     = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(crs, wgs84, QgsProject.instance())
        ext_wgs   = transform.transformBoundingBox(extent)
        self.sp_lon_min.setText(str(ext_wgs.xMinimum()))
        self.sp_lon_max.setText(str(ext_wgs.xMaximum()))
        self.sp_lat_min.setText(str(ext_wgs.yMinimum()))
        self.sp_lat_max.setText(str(ext_wgs.yMaximum()))
        self.chk_full_territory.setChecked(False)

    def _register_horizon_layers(self, layers_by_horizon: list):
        self._horizon_layers = layers_by_horizon
        n = len(layers_by_horizon)
        self.slider_horizon.setMinimum(0)
        self.slider_horizon.setMaximum(max(0, n - 1))
        self.slider_horizon.setValue(0)
        self.slider_horizon.setEnabled(n > 1)

        self.list_all_horizons.clear()
        for item in layers_by_horizon:
            self.list_all_horizons.addItem(f"H {item['horizon_label']}")

        if n > 0:
            self._on_horizon_changed(0)
            if n > 1:
                self.tabs.setCurrentIndex(self._TAB_HORIZONS)

    def _on_horizon_changed(self, idx):
        if not self._horizon_layers:
            return
        idx = max(0, min(idx, len(self._horizon_layers) - 1))
        for i, item in enumerate(self._horizon_layers):
            visible = (i == idx)
            for lyr in item.get("layers", []):
                if isinstance(lyr, QgsRasterLayer):
                    root = QgsProject.instance().layerTreeRoot()
                    node = root.findLayer(lyr.id())
                    if node:
                        node.setItemVisibilityChecked(visible)
        h_item  = self._horizon_layers[idx]
        h_label = h_item.get("horizon_label", "")
        self.lbl_horizon_current.setText(
            f"Horizon : {h_label}" if h_label else "Horizon unique")
        self.list_horizon_layers.clear()
        for lyr in h_item.get("layers", []):
            self.list_horizon_layers.addItem(f"  {lyr.name()}")

    def _step_horizon(self, delta):
        new_val = self.slider_horizon.value() + delta
        new_val = max(self.slider_horizon.minimum(),
                      min(self.slider_horizon.maximum(), new_val))
        self.slider_horizon.setValue(new_val)

    def _set_all_horizons_visible(self, visible: bool):
        root = QgsProject.instance().layerTreeRoot()
        for item in self._horizon_layers:
            for lyr in item.get("layers", []):
                node = root.findLayer(lyr.id())
                if node:
                    node.setItemVisibilityChecked(visible)

    def _zoom_to_current_horizon(self):
        idx = self.slider_horizon.value()
        if not self._horizon_layers or idx >= len(self._horizon_layers):
            return
        for lyr in self._horizon_layers[idx].get("layers", []):
            if isinstance(lyr, QgsRasterLayer) and lyr.isValid():
                self.iface.setActiveLayer(lyr)
                self.iface.zoomToActiveLayer()
                break

    # ------------------------------------------------------------------ #
    #  Paramètres
    # ------------------------------------------------------------------ #

    def _on_auth_type_changed(self, idx):
        labels       = ["Token :", "API Key :", "Application ID :"]
        placeholders = [
            "Collez votre token ici…",
            "Collez votre api_key ici…",
            "Collez votre Application ID ici…",
        ]
        self.lbl_auth_key.setText(labels[idx])
        self.le_appid.setPlaceholderText(placeholders[idx])

    def _auth_mode(self):
        return ["token", "api_key", "application_id"][
            self.cb_auth_type.currentIndex()]

    def _use_token(self):
        return self.cb_auth_type.currentIndex() == 0

    def _load_settings(self):
        s = QSettings()
        self.le_appid.setText(s.value("meteole/auth_key", ""))
        self.cb_auth_type.setCurrentIndex(int(s.value("meteole/auth_type", 0)))

        saved_model = s.value("meteole/last_model", "")
        # Recherche par préfixe pour compatibilité avec anciens libellés
        idx = self.cb_model.findText(saved_model)
        if idx < 0:
            # Essai par correspondance de préfixe
            short = saved_model.split("  ")[0].split(" (")[0]
            for i in range(self.cb_model.count()):
                if self.cb_model.itemText(i).startswith(short):
                    idx = i
                    break
        if idx >= 0:
            self.cb_model.blockSignals(True)
            self.cb_model.setCurrentIndex(idx)
            self.cb_model.blockSignals(False)

        saved_model_for_ind = s.value("meteole/last_model_for_indicator", "")
        last_ind = s.value("meteole/last_indicator", "")
        if last_ind and saved_model_for_ind == saved_model:
            self.cb_indicator.blockSignals(True)
            self.cb_indicator.addItem(last_ind)
            self.cb_indicator.setCurrentText(last_ind)
            self.cb_indicator.blockSignals(False)
        else:
            self.cb_indicator.setPlaceholderText(
                f"Cliquez sur 'Lister les indicateurs' pour {saved_model}…"
            )

        # Restaure le territoire AROME sans déclencher de log
        saved_territory = s.value("meteole/last_territory", "FRANCE")
        for i in range(self.cb_territory.count()):
            if self.cb_territory.itemData(i) == saved_territory:
                self.cb_territory.blockSignals(True)
                self.cb_territory.setCurrentIndex(i)
                self.cb_territory.blockSignals(False)
        # Synchroniser les cartes territoire visuelles
        try:
            self._select_territory(saved_territory)
        except Exception:
            pass
        # Appliquer la bbox du territoire restauré
        info = AROME_TERRITORIES.get(saved_territory,
                                     AROME_TERRITORIES["FRANCE"])
        lon_min, lon_max, lat_min, lat_max = info["bbox"]
        self.sp_lon_min.setText(str(lon_min))
        self.sp_lon_max.setText(str(lon_max))
        self.sp_lat_min.setText(str(lat_min))
        self.sp_lat_max.setText(str(lat_max))

    def _save_settings(self):
        s = QSettings()
        s.setValue("meteole/auth_key",                 self.le_appid.text())
        s.setValue("meteole/auth_type",                self.cb_auth_type.currentIndex())
        s.setValue("meteole/last_model",               self.cb_model.currentText())
        s.setValue("meteole/last_indicator",           self.cb_indicator.currentText())
        s.setValue("meteole/last_model_for_indicator", self.cb_model.currentText())
        s.setValue("meteole/last_territory",           self.cb_territory.currentData())

    def _get_appid(self):
        key = self.le_appid.text().strip()
        if not key:
            label = "token" if self._use_token() else "Application ID"
            QMessageBox.warning(self, "Clé manquante",
                                f"Veuillez saisir votre {label} dans l'onglet Connexion.")
            return None
        self._save_settings()
        return key

    def _get_forecast_params(self):
        model_map = {
            "AROME  (1,3 km — prévision à courte échéance)": "arome",
            "AROME-PI  (1,3 km — prévision immédiate)":       "arome_instantane",
            "AROME-PE  (2,8 km — ensemble 25 scénarios)":     "arome_pe",
            "ARPEGE  (10 km — prévision globale)":             "arpege",
            "PIAF  (1,3 km — prévision très courte)":          "piaf",
        }
        horizons_explicit = not self.chk_auto_horizons.isChecked()
        _raw = self.cb_model.currentText()
        model_key = model_map.get(_raw) or next(
            (v for k, v in model_map.items() if _raw.startswith(k.split("  ")[0])),
            "arome")

        # Territoire : pertinent uniquement pour AROME déterministe
        territory = "FRANCE"
        if model_key == "arome":
            territory = self.cb_territory.currentData() or "FRANCE"

        params = {
            "model":             model_key,
            "indicator":         self.cb_indicator.currentText().strip() or None,
            "territory":         territory,
            "run":               None,
            "forecast_horizons": ([int(h.strip().rstrip("H"))
                                   for h in self.le_om_horizons.text().split(",")
                                   if h.strip()]
                                  if horizons_explicit else []),
            "horizons_explicit": horizons_explicit,
            "lon":               None,
            "lat":               None,
            "heights":           None,
            "pressures":         None,
            "ensemble_numbers":  None,
        }

        if not self.chk_auto_run.isChecked():
            try:
                import datetime as _dt
                dt = _dt.datetime.strptime(
                    self.dte_run.text().strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                dt = _dt.datetime.utcnow() - _dt.timedelta(hours=6)
            params["run"] = dt.strftime("%Y-%m-%dT%H.00.00Z")

        # Bbox : uniquement si la case "territoire entier" est décochée
        if not self.chk_full_territory.isChecked():
            params["lon"] = (float(self.sp_lon_min.text() or 0), float(self.sp_lon_max.text() or 0))
            params["lat"] = (float(self.sp_lat_min.text() or 0), float(self.sp_lat_max.text() or 0))

        h_text = self.le_heights.text().strip()
        if h_text:
            try:
                params["heights"] = [int(x.strip()) for x in h_text.split(",")]
            except ValueError:
                pass

        p_text = self.le_pressures.text().strip()
        if p_text:
            try:
                params["pressures"] = [int(x.strip()) for x in p_text.split(",")]
            except ValueError:
                pass

        if self.sp_ensemble.isEnabled():
            params["ensemble_numbers"] = range(int(self.sp_ensemble.text() or 3))

        return params

    # ------------------------------------------------------------------ #
    #  Lancement des tâches
    # ------------------------------------------------------------------ #

    def _run_task(self, task):
        self._current_task = task
        task.task_finished.connect(self._dispatch_finished)
        task.task_error.connect(self._on_worker_error)
        QgsApplication.taskManager().addTask(task)

    def _dispatch_finished(self, result):
        task_name = getattr(self._current_task, "task_name", "")
        if task_name == "capabilities":
            self._on_capabilities_done(result)
        elif task_name == "forecast":
            self._on_forecast_done(result)
        elif task_name == "vigilance":
            self._on_vigilance_done(result)
        elif task_name == "probe_urls":
            self._on_probe_done(result)
        elif task_name == "om_capabilities":
            self._on_om_capabilities_done(result)
        elif task_name == "om_forecast":
            self._on_om_forecast_done(result)

    _listing_model_text = ""

    def _on_get_capabilities(self):
        appid = self._get_appid()
        if not appid:
            return
        model_map = {
            "AROME  (1,3 km — prévision à courte échéance)": "arome",
            "AROME-PI  (1,3 km — prévision immédiate)":       "arome_instantane",
            "AROME-PE  (2,8 km — ensemble 25 scénarios)":     "arome_pe",
            "ARPEGE  (10 km — prévision globale)":             "arpege",
            "PIAF  (1,3 km — prévision très courte)":          "piaf",
        }
        model_text = self.cb_model.currentText()
        model      = model_map[model_text]
        self._listing_model_text = model_text

        territory  = "FRANCE"
        if model == "arome":
            territory = self.cb_territory.currentData() or "FRANCE"
        is_om      = (model == "arome" and territory != "FRANCE")
        terr_label = AROME_TERRITORIES.get(territory, {}).get("label", territory)

        if is_om:
            # Mode AROME-OM : appelle l'API DPPaquetAROME-OM
            self.cb_om_grid.clear()
            self.cb_om_package.clear()
            self._set_busy(True)
            self._log(f"[INFO] Récupération grilles/paquets AROME-OM "
                      f"({terr_label})…")
            task = MeteoleWorker(appid, "om_capabilities",
                                 auth_mode=self._auth_mode(),
                                 territory=territory)
        else:
            # Mode WCS métropole
            self.cb_indicator.blockSignals(True)
            self.cb_indicator.clear()
            self.cb_indicator.setPlaceholderText(
                f"Chargement des indicateurs {model_text}…")
            self.cb_indicator.blockSignals(False)
            self._set_busy(True)
            self._log(f"[INFO] Récupération des indicateurs pour {model_text} "
                      f"(territoire : {terr_label})…")
            task = MeteoleWorker(appid, "capabilities",
                                 auth_mode=self._auth_mode(),
                                 model=model,
                                 territory=territory)
        self._run_task(task)

    def _on_capabilities_done(self, result):
        self._set_busy(False)
        indicators = result.get("indicators", [])
        model_text = self._listing_model_text or self.cb_model.currentText()

        self.cb_indicator.blockSignals(True)
        self.cb_indicator.clear()
        for ind in indicators:
            self.cb_indicator.addItem(ind)
        self.cb_indicator.setPlaceholderText(
            f"{len(indicators)} indicateurs disponibles pour {model_text}")
        self.cb_indicator.blockSignals(False)
        self.cb_indicator.update()
        self.cb_indicator.repaint()
        # Basculer vers la page Variable du wizard
        self._goto_page(self._PAGE_VARIABLE)
        self._log(f"[OK] {len(indicators)} indicateurs chargés pour {model_text}.")

    def _on_load(self):
        appid = self._get_appid()
        if not appid:
            return

        # Détermine si on est en mode AROME-OM outremer
        is_om = self._is_om_territory()
        territory = self.cb_territory.currentData()

        # Log de diagnostic
        self._log(f"[DEBUG] is_om={is_om} | territory={territory} "
                  f"| model={self.cb_model.currentText()[:30]}")

        if is_om:
            # Mode AROME-OM : utilise les paramètres du panneau grp_om
            om_params = self._get_om_forecast_params()
            self._log(f"[DEBUG] om_params={om_params}")
            if not om_params.get("package"):
                QMessageBox.warning(self, "Paquet manquant",
                                    "Veuillez sélectionner un paquet AROME-OM.")
                return
            terr_label = AROME_TERRITORIES.get(territory, {}).get("label", territory)
            self._set_busy(True)
            sel = om_params.get("selected_vars")
            sel_str = (f" | vars={sel}" if sel else " | toutes les variables")
            self._log(
                f"[INFO] Téléchargement AROME-OM [{terr_label}] "
                f"paquet={om_params['package']} "
                f"grille={om_params['grid_id']} "
                f"horizons={om_params['time_horizons']}{sel_str}…"
            )
            task = MeteoleWorker(
                appid, "om_forecast",
                auth_mode=self._auth_mode(),
                territory=om_params["territory"],
                grid=str(om_params["grid_id"]),
                package=om_params["package"],
                referencetime=om_params["referencetime"],
                time_horizons=om_params["time_horizons"],
                selected_vars=om_params.get("selected_vars"),
            )
        else:
            # Mode WCS métropole
            params = self._get_forecast_params()
            if not params.get("indicator"):
                QMessageBox.warning(self, "Indicateur manquant",
                                    "Veuillez sélectionner un indicateur.")
                return
            terr_label    = AROME_TERRITORIES.get(territory, {}).get("label", "")
            territory_str = (f" [{terr_label}]"
                              if terr_label and territory != "FRANCE" else "")
            self._set_busy(True)
            self._log(
                f"[INFO] Récupération + création des couches "
                f"({params['model']}{territory_str} – {params['indicator']})…"
            )
            task = MeteoleWorker(appid, "forecast",
                                 auth_mode=self._auth_mode(), **params)
        self._run_task(task)

    def _on_forecast_done(self, result):
        self._set_busy(False)
        layer_files = result.get("layer_files", [])
        # Afficher les diagnostics GRIB2 EN PREMIER (même si pas de données)
        for msg in result.get("grib_vars_msgs", []):
            self._log(msg)
        for msg in result.get("grib_missing", []):
            self._log(f"[WARN] {msg}")

        if not layer_files:
            self._log(
                "[WARN] Aucune donnée retournée. "
                "La variable demandée est peut-être absente du paquet téléchargé. "
                "Voir les lignes [INFO] GRIB2 ci-dessus pour les variables disponibles.")
            return

        layers_by_horizon = []
        file_info = {}
        for file_info in layer_files:
            h_label = file_info.get("horizon_label", "")
            self._log(f"[INFO] Chargement couche : {file_info['layer_name']}…")
            try:
                _pts = getattr(self, "chk_load_points", None)
                layers = load_layers_from_files(
                    file_info,
                    load_points=_pts.isChecked() if _pts else False)
                loaded = []
                for lyr in layers:
                    if lyr and lyr.isValid():
                        QgsProject.instance().addMapLayer(lyr)
                        self._log(f"[OK] Couche ajoutée : {lyr.name()}")
                        loaded.append(lyr)
                    else:
                        self._log("[WARN] Couche invalide ignorée.")
                if loaded:
                    layers_by_horizon.append({
                        "horizon_label": h_label,
                        "layers":        loaded,
                    })
            except Exception as e:
                self._log(f"[ERR] {file_info['layer_name']} : {e}")

        if layers_by_horizon:
            self._register_horizon_layers(layers_by_horizon)

        if file_info.get("error"):
            self._log(f"[WARN] Avertissements : {file_info['error']}")


    # ------------------------------------------------------------------ #
    #  Vigilance
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    #  AROME Outre-Mer — capabilities et forecast
    # ------------------------------------------------------------------ #

    def _on_om_grid_changed(self, _):
        """Met à jour les variables quand la grille change."""
        from .arome_om import package_variable_entries
        grid_idx = self.cb_om_grid.currentIndex()
        if grid_idx < 0:
            return
        data = self.cb_om_grid.itemData(grid_idx) or {}
        packages = data.get("packages", [])
        self.cb_om_package.clear()
        entries = package_variable_entries(packages)
        for e in entries:
            self.cb_om_package.addItem(e["display"], e)

    def _on_om_capabilities_done(self, result):
        """Reçoit les grilles+paquets outremer et peuple l'UI."""
        self._set_busy(False)
        territory = result.get("territory", "")
        grids     = result.get("grids", [])      # list of {id, packages, error}
        raw_grids = result.get("raw_grids", [])

        raw_resp = result.get("raw_resp", "")
        self._log(f"[INFO] Réponse brute /grids : {raw_resp[:600]}")
        self._log(f"[INFO] Grilles extraites pour {territory} : "
                  f"{[g['id'] for g in grids]}")

        self.cb_om_grid.clear()
        self.cb_om_package.clear()

        if not grids:
            self._log(f"[WARN] Aucune grille trouvée pour {territory}. "
                      f"Réponse brute : {str(raw_grids)[:300]}")
            QMessageBox.warning(
                self, "AROME-OM",
                f"Aucune grille disponible pour {territory}.\n"
                f"Vérifiez votre abonnement sur portail-api.meteofrance.fr.")
            return

        from .arome_om import package_variable_entries

        all_packages     = []
        selected_grid_id = None

        for g in grids:
            gid      = g.get("id", "?")
            packages = g.get("packages", [])
            err      = g.get("error")
            label    = f"Grille {gid}"
            if err:
                label += f"  ⚠️ {str(err)[:40]}"
                self._log(f"[WARN] Grille {gid} : {err}")
            else:
                self._log(f"[OK] Grille {gid} → paquets : {packages}")
            self.cb_om_grid.addItem(label, {"id": gid, "packages": packages})
            if selected_grid_id is None:
                selected_grid_id = gid
                all_packages = packages

        # Peupler cb_om_package avec les variables individualisées
        self.cb_om_package.clear()
        entries = package_variable_entries(all_packages)
        for e in entries:
            self.cb_om_package.addItem(e["display"], e)

        n_vars = self.cb_om_package.count()
        self._log(f"[OK] {n_vars} variable(s) disponible(s) pour {territory} "
                  f"(paquets : {all_packages}).")
        self.tabs.setCurrentIndex(self._TAB_FORECAST)

    def _get_om_forecast_params(self):
        """Collecte les paramètres pour une requête AROME-OM."""
        territory = self.cb_territory.currentData()
        grid_idx  = self.cb_om_grid.currentIndex()
        grid_data = self.cb_om_grid.itemData(grid_idx) if grid_idx >= 0 else []

        # Récupère l'ID numérique de la grille depuis le label
        grid_label = self.cb_om_grid.currentText()
        try:
            grid_id = float(grid_label.replace("Grille", "").split("⚠️")[0].strip())
        except ValueError:
            grid_id = grid_label.strip()

        # cb_om_package stocke {display, package, var_name, label, unit}
        entry   = self.cb_om_package.currentData()
        package = entry["package"] if entry else self.cb_om_package.currentText().strip()
        # var_name None = charger tout le paquet
        sel_var = entry.get("var_name") if entry else None

        # Referencetime
        if self.chk_om_auto_run.isChecked():
            referencetime = None  # worker déterminera le dernier run
        else:
            try:
                import datetime as _dt
                dt = _dt.datetime.strptime(
                    self.dte_om_run.text().strip(), "%Y-%m-%d %H:%M")
            except ValueError:
                dt = _dt.datetime.utcnow() - _dt.timedelta(hours=6)
            referencetime = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Horizons — lire le champ texte le_om_horizons
        raw = self.le_om_horizons.text().strip()
        if raw:
            time_horizons = [h.strip().upper() for h in raw.split(",")
                             if h.strip()]
        else:
            time_horizons = ["001H"]
        if not time_horizons:
            time_horizons = ["001H"]

        # Variable sélectionnée dans le combo
        selected_vars = [sel_var] if sel_var else None

        return {
            "territory":     territory,
            "grid_id":       grid_id,
            "package":       package,
            "referencetime": referencetime,
            "time_horizons": time_horizons,
            "selected_vars": selected_vars,
        }

    def _on_om_forecast_done(self, result):
        """Reçoit les layer_files de la tâche om_forecast."""
        # Même logique que _on_forecast_done (réutilise le code existant)
        self._on_forecast_done(result)

    # ------------------------------------------------------------------ #
    #  Diagnostic URLs outremer
    # ------------------------------------------------------------------ #

    def _on_probe_urls(self):
        appid = self._get_appid()
        if not appid:
            return
        territory = self.cb_probe_territory.currentData()
        terr_label = AROME_TERRITORIES.get(territory, {}).get('label', territory)
        self.probe_results_view.setPlainText(f"Test en cours pour {terr_label}…")
        self._set_busy(True)
        self._log(f"[INFO] Diagnostic URLs outremer → {terr_label} ({territory})…")
        task = MeteoleWorker(appid, "probe_urls",
                             auth_mode=self._auth_mode(),
                             territory=territory)
        self._run_task(task)

    def _on_probe_done(self, result):
        self._set_busy(False)
        territory = result.get('territory', '?')
        probe_results = result.get('probe_results', [])

        lines = [f"Résultats pour territoire {territory}:\n"]
        winning = []
        for r in probe_results:
            status = r['status']
            ok     = r['ok']
            icon   = '✅' if ok else ('⚠️' if status == 403 else '❌')
            url    = r['url']
            lines.append(f"{icon} HTTP {status}\n   {url}")
            if ok:
                winning.append(url)

        if winning:
            lines.append(f"\n🎯 URL valide trouvée !\n→ {winning[0]}")
            self._log(f"[OK] URL valide pour {territory} : {winning[0]}")
        elif any(r['status'] == 403 for r in probe_results):
            lines.append(
                "\n⚠️ HTTP 403 détecté : l'URL est correcte mais votre abonnement "
                "n'inclut pas ce territoire.\n"
                "Abonnez-vous sur portail-api.meteofrance.fr."
            )
            self._log(f"[WARN] Territoire {territory} : URL correcte, abonnement manquant (403).")
        else:
            lines.append("\n❌ Aucune URL valide trouvée. Copiez ces résultats et ouvrez un ticket.")
            self._log(f"[WARN] Territoire {territory} : aucune URL valide parmi les candidats.")

        self.probe_results_view.setPlainText('\n'.join(lines))
        self.tabs.setCurrentIndex(self._TAB_CONNEXION)

    def _on_load_vigilance(self):
        appid = self._get_appid()
        if not appid:
            return
        self._set_busy(True)
        self._log("[INFO] Récupération des bulletins de vigilance…")
        task = MeteoleWorker(
            appid, "vigilance",
            auth_mode=self._auth_mode(),
            load_phenomenon=self.chk_phenomenon.isChecked(),
            load_timelaps=self.chk_timelaps.isChecked(),
            load_vignette=False,
        )
        self._run_task(task)

    def _on_vigilance_done(self, result):
        self._set_busy(False)

        PHENOM_FR = {
            "wind": "Vent violent", "rain": "Pluie-inondation",
            "flood": "Crues", "snow": "Neige-verglas",
            "thunder": "Orages", "storm": "Tempête",
            "avalanches": "Avalanches", "heat": "Canicule",
            "cold": "Grand froid", "fog": "Brouillard",
        }
        COLOR      = {1: ("#00aa00","white"), 2: ("#ffdd00","black"),
                      3: ("#ff8800","white"), 4: ("#dd0000","white")}
        COLOR_NAME = {1: "Vert", 2: "Jaune", 3: "Orange", 4: "Rouge"}

        df_phen = result.get("phenomenon")
        if df_phen is not None:
            html = ("<table border='1' cellpadding='3' cellspacing='0' "
                    "style='border-collapse:collapse;font-size:11px;'>")
            html += ("<tr style='background:#dde;'>"
                     "<th>Phénomène</th><th>Échéance</th>"
                     "<th>Couleur max</th><th>Nb depts</th></tr>")
            for _, row in df_phen.iterrows():
                phenom    = str(row.get("phenomenon_libelle", "?"))
                phenom_fr = PHENOM_FR.get(phenom, phenom)
                ech       = str(row.get("echeance", ""))
                counts    = row.get("phenomenon_counts", [])
                max_color_id = 1
                max_count    = 0
                try:
                    if isinstance(counts, str):
                        import json
                        counts = json.loads(counts.replace("'", '"'))
                    for item in counts:
                        cid = int(item.get("color_id", 1))
                        cnt = int(item.get("count", 0))
                        if cid > max_color_id and cnt > 0:
                            max_color_id = cid
                        if cid == max_color_id:
                            max_count = cnt
                except Exception:
                    max_count = int(row.get("any_color_count", 0))
                bg, fg      = COLOR.get(max_color_id, ("#fff","black"))
                color_label = COLOR_NAME.get(max_color_id, "?")
                html += (f"<tr><td>{phenom_fr}</td><td>{ech}</td>"
                         f"<td style='background:{bg};color:{fg};"
                         f"text-align:center;'><b>{color_label}</b></td>"
                         f"<td style='text-align:center;'>{max_count}</td></tr>")
            html += "</table>"
            self.tbl_vigilance.setHtml(html)
            self._log("[OK] Tableau de vigilance chargé.")

        df_time = result.get("timelaps")
        if df_time is not None and "max_color_id" in df_time.columns:
            try:
                lyr = add_vigilance_dept_layer(df_time, df_phen)
                if lyr and lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
                    self._log("[OK] Couche vigilance par département ajoutée.")
            except Exception as e:
                self._log(f"[WARN] Couche départements : {e}")

        vignette_path  = result.get("vignette_path")
        vignette_error = result.get("vignette_error")
        if vignette_error:
            self._log(f"[WARN] Vignette non disponible : {vignette_error}")
        if vignette_path:
            lyr = QgsRasterLayer(vignette_path, "⚠️ Vigilance Météo-France")
            if lyr.isValid():
                lyr.setOpacity(0.85)
                QgsProject.instance().addMapLayer(lyr)
                self._log("[OK] Vignette vigilance ajoutée.")
            else:
                self._log(f"[WARN] Vignette invalide : {vignette_path}")

    def _on_worker_error(self, msg):
        self._set_busy(False)
        self._log(f"[ERR] {msg}", switch_tab=True)
        QMessageBox.critical(self, "Erreur Meteole", msg)
