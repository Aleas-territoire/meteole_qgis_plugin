# -*- coding: utf-8 -*-
"""
Boîte de dialogue principale du plugin Meteole.

Améliorations v1.1 :
  - _on_forecast_done reçoit des file_info (fichiers prêts) et non des DataFrames
    → seul QgsProject.addMapLayer() tourne dans le thread principal
  - Onglet "⏱ Horizons" : slider temporel pour basculer entre les couches raster
  - Le journal ne bascule plus automatiquement (on affiche un indicateur visuel discret)
  - Sauvegarde du modèle et de l'indicateur entre sessions
"""

import os
import datetime

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QLineEdit, QComboBox, QPushButton, QTabWidget, QWidget,
    QDoubleSpinBox, QSpinBox, QCheckBox, QListWidget, QListWidgetItem,
    QProgressBar, QTextEdit, QSizePolicy, QMessageBox, QFileDialog,
    QScrollArea, QFrame, QSplitter, QSlider, QDateTimeEdit
)
from qgis.PyQt.QtCore import Qt, QSettings, QDateTime
from qgis.PyQt.QtGui import QFont, QColor

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer,
    QgsCoordinateReferenceSystem, QgsApplication
)

from .worker import MeteoleWorker
from .layer_utils import (add_vigilance_layer, add_vigilance_dept_layer,
                           load_layers_from_files)


class MeteoleDialog(QDialog):
    """Dialogue principal pour récupérer et charger des données Météo-France."""

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface   = iface
        self.worker  = None
        self.thread  = None
        self.current_indicators = []

        # Stockage pour le slider temporel :
        # [ {"horizon_label": str, "raster_layer": QgsRasterLayer, ...}, ... ]
        self._horizon_layers = []

        self.setWindowTitle("Meteole – Données Météo-France")
        self.setMinimumWidth(700)
        self.setMinimumHeight(720)

        self._build_ui()
        self._load_settings()
        # Initialise la visibilité des sections selon le modèle par défaut
        self._on_model_changed(self.cb_model.currentText())

    # ------------------------------------------------------------------ #
    #  Construction de l'interface
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)

        # En-tête
        header = QLabel("🌤  Meteole – Accès aux données Météo-France")
        font = QFont()
        font.setPointSize(13)
        font.setBold(True)
        header.setFont(font)
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("color: #2c5f8a; padding: 6px;")
        main_layout.addWidget(header)

        # Onglets
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_connexion_tab(), "🔑 Connexion")
        self.tabs.addTab(self._build_forecast_tab(), "📡 Prévisions")
        self.tabs.addTab(self._build_vigilance_tab(), "⚠️ Vigilance")
        self.tabs.addTab(self._build_horizons_tab(), "⏱ Horizons")
        self.tabs.addTab(self._build_log_tab(), "📋 Journal")

        # Met à jour les boutons quand on change d'onglet
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Barre de progression
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        main_layout.addWidget(self.progress)

        # Boutons bas de page
        btn_layout = QHBoxLayout()

        self.btn_capabilities = QPushButton("🔍 Lister les indicateurs")
        self.btn_capabilities.setStyleSheet(
            "QPushButton { background:#4a8a4a; color:white; padding:8px 14px; "
            "border-radius:4px; }"
            "QPushButton:hover { background:#2e6b2e; }"
        )
        self.btn_capabilities.clicked.connect(self._on_get_capabilities)

        self.btn_load = QPushButton("⬇  Charger la couche")
        self.btn_load.setStyleSheet(
            "QPushButton { background:#2c5f8a; color:white; padding:8px 18px; "
            "border-radius:4px; font-weight:bold; }"
            "QPushButton:hover { background:#1a4a6e; }"
            "QPushButton:disabled { background:#aaa; }"
        )
        self.btn_load.clicked.connect(self._on_load_current_tab)

        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.close)

        btn_layout.addWidget(self.btn_capabilities)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_load)
        btn_layout.addWidget(btn_close)
        main_layout.addLayout(btn_layout)

    # ------------------------------------------------------------------ #
    #  Onglet Connexion
    # ------------------------------------------------------------------ #

    def _build_connexion_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(12)

        grp = QGroupBox("Authentification Météo-France")
        grp_layout = QVBoxLayout(grp)

        lbl = QLabel(
            "Créez un compte sur <a href='https://portail-api.meteofrance.fr/'>"
            "portail-api.meteofrance.fr</a>, abonnez-vous aux APIs souhaitées "
            "(AROME, ARPEGE…) puis récupérez votre clé d'accès."
        )
        lbl.setOpenExternalLinks(True)
        lbl.setWordWrap(True)
        grp_layout.addWidget(lbl)

        try:
            import meteole
            ver_str = meteole.__version__
            grp_layout.addWidget(
                QLabel(f"<i>✅ Version meteole installée : <b>{ver_str}</b></i>"))
        except Exception:
            pass

        auth_row = QHBoxLayout()
        auth_row.addWidget(QLabel("Type de clé :"))
        self.cb_auth_type = QComboBox()
        self.cb_auth_type.addItems([
            "token        (récupéré via 'Générer token')",
            "api_key      (clé API directe)",
            "application_id  (Application ID OAuth)",
        ])
        self.cb_auth_type.currentIndexChanged.connect(self._on_auth_type_changed)
        auth_row.addWidget(self.cb_auth_type)
        grp_layout.addLayout(auth_row)

        grp_layout.addWidget(QLabel(
            "<i>💡 Dans 'Mes APIs' sur le portail, cliquez <b>Générer token</b> → "
            "utilisez <b>token</b>.</i>"
        ))

        self.lbl_auth_key = QLabel("Token :")
        row = QHBoxLayout()
        row.addWidget(self.lbl_auth_key)
        self.le_appid = QLineEdit()
        self.le_appid.setPlaceholderText("Collez votre token ici…")
        self.le_appid.setEchoMode(QLineEdit.Password)
        self.chk_show = QCheckBox("Afficher")
        self.chk_show.toggled.connect(
            lambda v: self.le_appid.setEchoMode(
                QLineEdit.Normal if v else QLineEdit.Password))
        row.addWidget(self.le_appid)
        row.addWidget(self.chk_show)
        grp_layout.addLayout(row)

        grp_layout.addWidget(QLabel(
            "<i>La clé est sauvegardée localement dans les paramètres QGIS.</i>"))

        btn_portail = QPushButton("🔗  Ouvrir le portail Météo-France (générer un token)")
        btn_portail.setStyleSheet(
            "color: #2c5f8a; text-decoration: underline; border: none; text-align: left;")
        btn_portail.setCursor(Qt.PointingHandCursor)
        btn_portail.clicked.connect(
            lambda: __import__("webbrowser").open(
                "https://portail-api.meteofrance.fr/"))
        grp_layout.addWidget(btn_portail)

        grp_layout.addWidget(QLabel(
            "<b>⚠️ Attention :</b> le token expire après <b>1 heure</b>. "
            "Si une erreur 'token expiré' apparaît, régénérez-en un nouveau."))

        layout.addWidget(grp)

        # Tableau des modèles
        info = QGroupBox("Modèles disponibles")
        info_layout = QVBoxLayout(info)
        models_text = (
            "<table border='1' cellpadding='4' cellspacing='0' "
            "style='border-collapse:collapse;'>"
            "<tr style='background:#dde;'><th>Modèle</th><th>Résolution</th>"
            "<th>Fréquence MAJ</th><th>Horizon</th></tr>"
            "<tr><td>AROME</td><td>1.3 km</td><td>3 h</td><td>51 h</td></tr>"
            "<tr><td>AROME-PI</td><td>1.3 km</td><td>1 h</td><td>360 min</td></tr>"
            "<tr><td>AROME-PE (ensemble)</td><td>2.8 km</td><td>6 h</td>"
            "<td>51 h / 25 scénarios</td></tr>"
            "<tr><td>ARPEGE</td><td>10 km</td><td>6 h</td><td>114 h</td></tr>"
            "<tr><td>PIAF</td><td>1.3 km</td><td>10 min</td><td>195 min</td></tr>"
            "</table>"
        )
        lbl_models = QLabel(models_text)
        lbl_models.setTextFormat(Qt.RichText)
        info_layout.addWidget(lbl_models)
        layout.addWidget(info)
        layout.addStretch()
        return w

    # ------------------------------------------------------------------ #
    #  Onglet Prévisions
    # ------------------------------------------------------------------ #

    def _build_forecast_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(10)

        # Modèle
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Modèle :"))
        self.cb_model = QComboBox()
        self.cb_model.addItems([
            "AROME",
            "AROME-PI (Prévision Immédiate)",
            "AROME-PE (ensemble)",
            "ARPEGE",
            "PIAF",
        ])
        self.cb_model.currentTextChanged.connect(self._on_model_changed)
        row1.addWidget(self.cb_model)
        layout.addLayout(row1)

        # Indicateur
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Indicateur :"))
        self.cb_indicator = QComboBox()
        self.cb_indicator.setEditable(True)
        self.cb_indicator.setPlaceholderText(
            "Cliquez sur 'Lister les indicateurs' d'abord…")
        self.cb_indicator.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row2.addWidget(self.cb_indicator)
        layout.addLayout(row2)

        # Run
        grp_run = QGroupBox("Date et heure du run (optionnel)")
        run_layout = QHBoxLayout(grp_run)
        self.chk_auto_run = QCheckBox("Run automatique (dernier disponible)")
        self.chk_auto_run.setChecked(True)
        self.chk_auto_run.toggled.connect(self._toggle_run)
        run_layout.addWidget(self.chk_auto_run)
        self.dte_run = QDateTimeEdit(QDateTime.currentDateTimeUtc().addDays(-1))
        self.dte_run.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dte_run.setEnabled(False)
        run_layout.addWidget(self.dte_run)
        layout.addWidget(grp_run)

        # Horizons
        grp_horiz = QGroupBox("Horizons de prévision")
        horiz_layout = QVBoxLayout(grp_horiz)
        self.chk_auto_horizons = QCheckBox(
            "Automatique (utiliser les horizons disponibles par défaut)")
        self.chk_auto_horizons.setChecked(True)
        self.chk_auto_horizons.toggled.connect(self._toggle_horizons)
        horiz_layout.addWidget(self.chk_auto_horizons)

        horiz_row = QHBoxLayout()
        horiz_row.addWidget(QLabel("De H+"))
        self.sp_h_from = QSpinBox()
        self.sp_h_from.setRange(0, 500)
        self.sp_h_from.setValue(24)
        horiz_row.addWidget(self.sp_h_from)
        horiz_row.addWidget(QLabel("à H+"))
        self.sp_h_to = QSpinBox()
        self.sp_h_to.setRange(1, 500)
        self.sp_h_to.setValue(30)
        horiz_row.addWidget(self.sp_h_to)
        horiz_row.addWidget(QLabel("heures"))
        horiz_row.addStretch()
        self.horiz_manual_widget = QWidget()
        self.horiz_manual_widget.setLayout(horiz_row)
        self.horiz_manual_widget.setEnabled(False)
        horiz_layout.addWidget(self.horiz_manual_widget)
        layout.addWidget(grp_horiz)

        # Niveaux verticaux (masqué pour PIAF et AROME-PI)
        self.grp_alt = QGroupBox("Niveaux verticaux (optionnel)")
        alt_layout = QHBoxLayout(self.grp_alt)
        alt_layout.addWidget(QLabel("Hauteur (m) :"))
        self.le_heights = QLineEdit()
        self.le_heights.setPlaceholderText("ex: 2, 10 (vide = auto)")
        alt_layout.addWidget(self.le_heights)
        alt_layout.addWidget(QLabel("Pression (hPa) :"))
        self.le_pressures = QLineEdit()
        self.le_pressures.setPlaceholderText("ex: 500, 850")
        alt_layout.addWidget(self.le_pressures)
        layout.addWidget(self.grp_alt)

        # Zone géographique
        grp_geo = QGroupBox("Zone géographique (France métropolitaine par défaut)")
        geo_layout = QVBoxLayout(grp_geo)
        self.chk_full_france = QCheckBox("France métropolitaine entière")
        self.chk_full_france.setChecked(True)
        self.chk_full_france.toggled.connect(self._toggle_geo)
        geo_layout.addWidget(self.chk_full_france)

        geo_coords = QHBoxLayout()
        for label, attr, default in [
            ("Lon min :", "sp_lon_min", -5.14),
            ("Lon max :", "sp_lon_max",  9.56),
            ("Lat min :", "sp_lat_min", 41.33),
            ("Lat max :", "sp_lat_max", 51.09),
        ]:
            geo_coords.addWidget(QLabel(label))
            sb = QDoubleSpinBox()
            sb.setRange(-180 if "Lon" in label else -90,
                         180 if "Lon" in label else  90)
            sb.setValue(default)
            sb.setDecimals(4)
            setattr(self, attr, sb)
            geo_coords.addWidget(sb)

        self.geo_widget = QWidget()
        self.geo_widget.setLayout(geo_coords)
        self.geo_widget.setEnabled(False)
        geo_layout.addWidget(self.geo_widget)

        btn_from_canvas = QPushButton("📐 Utiliser l'emprise du canevas")
        btn_from_canvas.clicked.connect(self._use_canvas_extent)
        geo_layout.addWidget(btn_from_canvas)
        layout.addWidget(grp_geo)

        # Ensemble (masqué sauf AROME-PE)
        self.grp_ens = QGroupBox("Options ensemble (AROME-PE / ARPEGE-PE)")
        ens_layout = QHBoxLayout(self.grp_ens)
        ens_layout.addWidget(QLabel("Nombre de scénarios :"))
        self.sp_ensemble = QSpinBox()
        self.sp_ensemble.setRange(1, 35)
        self.sp_ensemble.setValue(3)
        self.sp_ensemble.setEnabled(False)
        ens_layout.addWidget(self.sp_ensemble)
        ens_layout.addStretch()
        layout.addWidget(self.grp_ens)

        layout.addStretch()
        return w

    # ------------------------------------------------------------------ #
    #  Onglet Vigilance
    # ------------------------------------------------------------------ #

    def _build_vigilance_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel(
            "<b>Bulletins de vigilance Météo-France</b><br>"
            "Affiche la vignette officielle (carte par département) "
            "et le tableau de synthèse des phénomènes."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.chk_phenomenon = QCheckBox("Tableau de synthèse des phénomènes")
        self.chk_phenomenon.setChecked(True)
        layout.addWidget(self.chk_phenomenon)

        self.chk_timelaps = QCheckBox(
            "Plages horaires par département (nécessaire pour la carte)")
        self.chk_timelaps.setChecked(True)
        layout.addWidget(self.chk_timelaps)

        note = QLabel("<i>👇 Utilisez le bouton <b>⚠️ Charger la vigilance</b> en bas de fenêtre.</i>")
        note.setStyleSheet("color: #666; padding: 4px;")
        layout.addWidget(note)

        layout.addWidget(QLabel("<b>Synthèse :</b>"))
        self.tbl_vigilance = QTextEdit()
        self.tbl_vigilance.setReadOnly(True)
        self.tbl_vigilance.setMaximumHeight(200)
        self.tbl_vigilance.setPlaceholderText(
            "Le tableau de vigilance s'affichera ici…")
        layout.addWidget(self.tbl_vigilance)
        layout.addStretch()
        return w

    # ------------------------------------------------------------------ #
    #  Onglet Horizons (slider temporel)
    # ------------------------------------------------------------------ #

    def _build_horizons_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setSpacing(10)

        info = QLabel(
            "<b>Navigateur d'horizons temporels</b><br>"
            "Après un chargement avec plusieurs horizons, utilisez le slider "
            "pour basculer entre les couches raster."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Ligne slider + label horizon courant
        slider_row = QHBoxLayout()
        self.lbl_horizon_prev = QLabel("◀")
        self.lbl_horizon_prev.setCursor(Qt.PointingHandCursor)
        self.lbl_horizon_prev.mousePressEvent = lambda _: self._step_horizon(-1)
        slider_row.addWidget(self.lbl_horizon_prev)

        self.slider_horizon = QSlider(Qt.Horizontal)
        self.slider_horizon.setMinimum(0)
        self.slider_horizon.setMaximum(0)
        self.slider_horizon.setValue(0)
        self.slider_horizon.setEnabled(False)
        self.slider_horizon.valueChanged.connect(self._on_horizon_changed)
        slider_row.addWidget(self.slider_horizon, stretch=1)

        self.lbl_horizon_next = QLabel("▶")
        self.lbl_horizon_next.setCursor(Qt.PointingHandCursor)
        self.lbl_horizon_next.mousePressEvent = lambda _: self._step_horizon(+1)
        slider_row.addWidget(self.lbl_horizon_next)

        layout.addLayout(slider_row)

        # Horizon courant
        self.lbl_horizon_current = QLabel("Aucun horizon disponible")
        self.lbl_horizon_current.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self.lbl_horizon_current.setFont(font)
        self.lbl_horizon_current.setStyleSheet(
            "color: #2c5f8a; padding: 4px; background: #eef4fb; "
            "border-radius: 4px;")
        layout.addWidget(self.lbl_horizon_current)

        # Liste des couches de l'horizon courant
        layout.addWidget(QLabel("Couches de l'horizon sélectionné :"))
        self.list_horizon_layers = QListWidget()
        self.list_horizon_layers.setMaximumHeight(120)
        layout.addWidget(self.list_horizon_layers)

        # Boutons de contrôle
        ctrl_row = QHBoxLayout()
        btn_show_all = QPushButton("👁 Tout afficher")
        btn_show_all.clicked.connect(lambda: self._set_all_horizons_visible(True))
        btn_hide_all = QPushButton("🙈 Tout masquer")
        btn_hide_all.clicked.connect(lambda: self._set_all_horizons_visible(False))
        btn_zoom = QPushButton("🔍 Zoomer sur la couche")
        btn_zoom.clicked.connect(self._zoom_to_current_horizon)
        ctrl_row.addWidget(btn_show_all)
        ctrl_row.addWidget(btn_hide_all)
        ctrl_row.addWidget(btn_zoom)
        layout.addLayout(ctrl_row)

        # Résumé de tous les horizons chargés
        layout.addWidget(QLabel("Tous les horizons chargés :"))
        self.list_all_horizons = QListWidget()
        layout.addWidget(self.list_all_horizons)

        layout.addStretch()
        return w

    # ------------------------------------------------------------------ #
    #  Onglet Journal
    # ------------------------------------------------------------------ #

    def _build_log_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Courier New", 9))
        layout.addWidget(self.log_view)
        btn_clear = QPushButton("Effacer le journal")
        btn_clear.clicked.connect(self.log_view.clear)
        layout.addWidget(btn_clear)
        return w

    # ------------------------------------------------------------------ #
    #  Helpers UI
    # ------------------------------------------------------------------ #

    def _toggle_run(self, auto):
        self.dte_run.setEnabled(not auto)

    def _toggle_horizons(self, auto):
        self.horiz_manual_widget.setEnabled(not auto)

    def _toggle_geo(self, full):
        self.geo_widget.setEnabled(not full)

    # Index des onglets (ordre défini dans _build_ui)
    _TAB_CONNEXION  = 0
    _TAB_FORECAST   = 1
    _TAB_VIGILANCE  = 2
    _TAB_HORIZONS   = 3
    _TAB_LOG        = 4

    def _on_tab_changed(self, idx):
        """Adapte le libellé et le comportement du bouton principal selon l'onglet."""
        if idx == self._TAB_FORECAST:
            self.btn_load.setText("⬇  Charger la couche")
            self.btn_load.setStyleSheet(
                "QPushButton { background:#2c5f8a; color:white; padding:8px 18px; "
                "border-radius:4px; font-weight:bold; }"
                "QPushButton:hover { background:#1a4a6e; }"
                "QPushButton:disabled { background:#aaa; }"
            )
            self.btn_load.setEnabled(True)
            self.btn_capabilities.setVisible(True)
        elif idx == self._TAB_VIGILANCE:
            self.btn_load.setText("⚠️  Charger la vigilance")
            self.btn_load.setStyleSheet(
                "QPushButton { background:#b55a00; color:white; padding:8px 18px; "
                "border-radius:4px; font-weight:bold; }"
                "QPushButton:hover { background:#7a3c00; }"
                "QPushButton:disabled { background:#aaa; }"
            )
            self.btn_load.setEnabled(True)
            self.btn_capabilities.setVisible(False)
        else:
            self.btn_load.setText("⬇  Charger la couche")
            self.btn_load.setStyleSheet(
                "QPushButton { background:#aaa; color:white; padding:8px 18px; "
                "border-radius:4px; font-weight:bold; }"
            )
            self.btn_load.setEnabled(False)
            self.btn_capabilities.setVisible(idx == self._TAB_CONNEXION or
                                              idx == self._TAB_HORIZONS or
                                              idx == self._TAB_LOG)

    def _on_load_current_tab(self):
        """Dispatch du bouton principal selon l'onglet actif."""
        idx = self.tabs.currentIndex()
        if idx == self._TAB_FORECAST:
            self._on_load()
        elif idx == self._TAB_VIGILANCE:
            self._on_load_vigilance()

    def _on_model_changed(self, text):
        # Capacités par modèle
        # heights/pressures : seulement AROME, AROME-PE, ARPEGE (indicateurs multi-niveaux)
        # ensemble          : seulement AROME-PE
        HAS_LEVELS    = text in ("AROME", "AROME-PE (ensemble)", "ARPEGE")
        IS_ENSEMBLE   = "PE" in text or "ensemble" in text

        # Sections niveaux verticaux et ensemble
        self.grp_alt.setVisible(HAS_LEVELS)
        self.grp_ens.setVisible(IS_ENSEMBLE)
        self.sp_ensemble.setEnabled(IS_ENSEMBLE)

        # Vide la liste des indicateurs : elle est propre à chaque modèle
        self.cb_indicator.blockSignals(True)
        self.cb_indicator.clear()
        self.cb_indicator.blockSignals(False)
        self.cb_indicator.setPlaceholderText(
            f"Modèle changé → cliquez sur 'Lister les indicateurs' pour {text}…"
        )

    def _use_canvas_extent(self):
        extent = self.iface.mapCanvas().extent()
        crs    = self.iface.mapCanvas().mapSettings().destinationCrs()
        from qgis.core import QgsCoordinateTransform, QgsCoordinateReferenceSystem
        wgs84     = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(crs, wgs84, QgsProject.instance())
        ext_wgs   = transform.transformBoundingBox(extent)
        self.sp_lon_min.setValue(ext_wgs.xMinimum())
        self.sp_lon_max.setValue(ext_wgs.xMaximum())
        self.sp_lat_min.setValue(ext_wgs.yMinimum())
        self.sp_lat_max.setValue(ext_wgs.yMaximum())
        self.chk_full_france.setChecked(False)

    def _log(self, msg, switch_tab=False):
        """Ajoute un message au journal. Ne bascule vers l'onglet journal
        que si switch_tab=True ou si le message est une erreur."""
        self.log_view.append(msg)
        # Indicateur visuel discret sur l'onglet journal (sans changer l'onglet actif)
        journal_idx = 4  # index de l'onglet Journal
        if switch_tab or msg.startswith("[ERR]"):
            self.tabs.setCurrentIndex(journal_idx)

    def _set_busy(self, busy):
        self.progress.setVisible(busy)
        self.btn_capabilities.setEnabled(not busy)
        if busy:
            self.btn_load.setEnabled(False)
        else:
            # Restaure l'état contextuel selon l'onglet actif
            self._on_tab_changed(self.tabs.currentIndex())

    # ------------------------------------------------------------------ #
    #  Slider temporel
    # ------------------------------------------------------------------ #

    def _register_horizon_layers(self, layers_by_horizon: list):
        """
        Enregistre les couches groupées par horizon dans le navigateur.
        layers_by_horizon : liste de dicts {horizon_label, layers:[QgsMapLayer]}
        """
        self._horizon_layers = layers_by_horizon

        n = len(layers_by_horizon)
        self.slider_horizon.setMinimum(0)
        self.slider_horizon.setMaximum(max(0, n - 1))
        self.slider_horizon.setValue(0)
        self.slider_horizon.setEnabled(n > 1)

        # Populate la liste globale
        self.list_all_horizons.clear()
        for item in layers_by_horizon:
            self.list_all_horizons.addItem(f"H {item['horizon_label']}")

        if n > 0:
            self._on_horizon_changed(0)
            # Bascule vers l'onglet Horizons si plusieurs horizons
            if n > 1:
                self.tabs.setCurrentIndex(3)

    def _on_horizon_changed(self, idx):
        if not self._horizon_layers:
            return
        idx = max(0, min(idx, len(self._horizon_layers) - 1))

        # Masque toutes les couches raster sauf l'horizon courant
        for i, item in enumerate(self._horizon_layers):
            visible = (i == idx)
            for lyr in item.get("layers", []):
                if isinstance(lyr, QgsRasterLayer):
                    root = QgsProject.instance().layerTreeRoot()
                    node = root.findLayer(lyr.id())
                    if node:
                        node.setItemVisibilityChecked(visible)

        h_item = self._horizon_layers[idx]
        h_label = h_item.get("horizon_label", "")
        self.lbl_horizon_current.setText(
            f"Horizon : {h_label}" if h_label else "Horizon unique")

        # Met à jour la liste de couches de l'horizon courant
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
        labels = ["Token :", "API Key :", "Application ID :"]
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

        # Restaure le modèle (signal bloqué pour restaurer l'indicateur d'abord)
        saved_model = s.value("meteole/last_model", "AROME")
        idx = self.cb_model.findText(saved_model)
        if idx >= 0:
            self.cb_model.blockSignals(True)
            self.cb_model.setCurrentIndex(idx)
            self.cb_model.blockSignals(False)
            # _on_model_changed sera appelé depuis __init__ après _load_settings

        # Restaure l'indicateur SEULEMENT si le modèle sauvegardé est identique
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

    def _save_settings(self):
        s = QSettings()
        s.setValue("meteole/auth_key",                self.le_appid.text())
        s.setValue("meteole/auth_type",               self.cb_auth_type.currentIndex())
        s.setValue("meteole/last_model",              self.cb_model.currentText())
        s.setValue("meteole/last_indicator",          self.cb_indicator.currentText())
        # Mémorise le modèle associé à l'indicateur sauvegardé
        s.setValue("meteole/last_model_for_indicator", self.cb_model.currentText())

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
            "AROME":                          "arome",
            "AROME-PI (Prévision Immédiate)":  "arome_instantane",
            "AROME-PE (ensemble)":             "arome_pe",
            "ARPEGE":                          "arpege",
            "PIAF":                            "piaf",
        }
        horizons_explicit = not self.chk_auto_horizons.isChecked()
        params = {
            "model":             model_map[self.cb_model.currentText()],
            "indicator":         self.cb_indicator.currentText().strip() or None,
            "run":               None,
            "forecast_horizons": (list(range(self.sp_h_from.value(),
                                             self.sp_h_to.value() + 1))
                                  if horizons_explicit else []),
            "horizons_explicit": horizons_explicit,
            "lon":               None,
            "lat":               None,
            "heights":           None,
            "pressures":         None,
            "ensemble_numbers":  None,
        }

        if not self.chk_auto_run.isChecked():
            dt = self.dte_run.dateTime().toPyDateTime()
            params["run"] = dt.strftime("%Y-%m-%dT%H.00.00Z")

        if not self.chk_full_france.isChecked():
            params["lon"] = (self.sp_lon_min.value(), self.sp_lon_max.value())
            params["lat"] = (self.sp_lat_min.value(), self.sp_lat_max.value())

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
            params["ensemble_numbers"] = range(self.sp_ensemble.value())

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

    # Nom du modèle UI actuellement listé (pour _on_capabilities_done)
    _listing_model_text = ""

    def _on_get_capabilities(self):
        appid = self._get_appid()
        if not appid:
            return
        model_map = {
            "AROME":                          "arome",
            "AROME-PI (Prévision Immédiate)":  "arome_instantane",
            "AROME-PE (ensemble)":             "arome_pe",
            "ARPEGE":                          "arpege",
            "PIAF":                            "piaf",
        }
        model_text = self.cb_model.currentText()
        model = model_map[model_text]
        self._listing_model_text = model_text  # mémorise pour _on_capabilities_done

        # Vide et désactive le combo pendant le chargement
        self.cb_indicator.blockSignals(True)
        self.cb_indicator.clear()
        self.cb_indicator.setPlaceholderText(f"Chargement des indicateurs {model_text}…")
        self.cb_indicator.blockSignals(False)

        self._set_busy(True)
        self._log(f"[INFO] Récupération des indicateurs pour {model_text}…")
        task = MeteoleWorker(appid, "capabilities",
                             auth_mode=self._auth_mode(), model=model)
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
        self.tabs.setCurrentIndex(1)  # Onglet Prévisions
        self._log(f"[OK] {len(indicators)} indicateurs chargés pour {model_text}.")

    def _on_load(self):
        appid = self._get_appid()
        if not appid:
            return
        params = self._get_forecast_params()
        if not params.get("indicator"):
            QMessageBox.warning(self, "Indicateur manquant",
                                "Veuillez sélectionner un indicateur.")
            return
        self._set_busy(True)
        self._log(
            f"[INFO] Récupération + création des couches "
            f"({params['model']} – {params['indicator']})…"
        )
        task = MeteoleWorker(appid, "forecast",
                             auth_mode=self._auth_mode(), **params)
        self._run_task(task)

    def _on_forecast_done(self, result):
        """
        Reçoit les file_info (fichiers déjà créés dans le worker).
        Seul addMapLayer() s'exécute ici → thread principal léger.
        """
        self._set_busy(False)
        layer_files = result.get("layer_files", [])
        indicator   = result.get("indicator", "")

        if not layer_files:
            self._log("[WARN] Aucune donnée retournée.")
            return

        # Réinitialise le navigateur d'horizons
        layers_by_horizon = []

        for file_info in layer_files:
            h_label = file_info.get("horizon_label", "")
            self._log(f"[INFO] Chargement couche : {file_info['layer_name']}…")
            try:
                layers = load_layers_from_files(file_info)
                loaded = []
                for lyr in layers:
                    if lyr and lyr.isValid():
                        QgsProject.instance().addMapLayer(lyr)
                        self._log(f"[OK] Couche ajoutée : {lyr.name()}")
                        loaded.append(lyr)
                    else:
                        self._log(f"[WARN] Couche invalide ignorée.")

                if loaded:
                    layers_by_horizon.append({
                        "horizon_label": h_label,
                        "layers":        loaded,
                    })
            except Exception as e:
                self._log(f"[ERR] {file_info['layer_name']} : {e}")

        # Enregistre dans le navigateur d'horizons
        if layers_by_horizon:
            self._register_horizon_layers(layers_by_horizon)

        if file_info.get("error"):
            self._log(f"[WARN] Avertissements : {file_info['error']}")

    # ------------------------------------------------------------------ #
    #  Vigilance
    # ------------------------------------------------------------------ #

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

                bg, fg     = COLOR.get(max_color_id, ("#fff","black"))
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
