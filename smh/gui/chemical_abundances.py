#!/usr/bin/env python
# -*- coding: utf-8 -*-

""" The stellar parameters tab in Spectroscopy Made Hard """

from __future__ import (division, print_function, absolute_import,
                        unicode_literals)

__all__ = ["ChemicalAbundancesTab"]

import logging
import matplotlib.gridspec
import numpy as np
import sys
from PySide import QtCore, QtGui
import time

from smh import utils
import mpl, style_utils
from matplotlib.ticker import MaxNLocator
#from smh.photospheres import available as available_photospheres
import smh.radiative_transfer as rt
from smh.spectral_models import (ProfileFittingModel, SpectralSynthesisModel)
from abund_tree import AbundTreeView, AbundTreeModel, AbundTreeMeasurementItem, AbundTreeElementSummaryItem
from spectral_models_table import SpectralModelsTableView, SpectralModelsFilterProxyModel, SpectralModelsTableModelBase
from linelist_manager import TransitionsDialog

logger = logging.getLogger(__name__)

if sys.platform == "darwin":
        
    # See http://successfulsoftware.net/2013/10/23/fixing-qt-4-for-mac-os-x-10-9-mavericks/
    substitutes = [
        (".Lucida Grande UI", "Lucida Grande"),
        (".Helvetica Neue DeskInterface", "Helvetica Neue")
    ]
    for substitute in substitutes:
        QtGui.QFont.insertSubstitution(*substitute)


DOUBLE_CLICK_INTERVAL = 0.1 # MAGIC HACK
PICKER_TOLERANCE = 10 # MAGIC HACK


class ChemicalAbundancesTab(QtGui.QWidget):
    
    def __init__(self, parent):
        super(ChemicalAbundancesTab, self).__init__(parent)
        self.parent = parent
        self.parent_splitter = QtGui.QSplitter(self)
        self.parent_layout = QtGui.QHBoxLayout(self)
        self.parent_splitter.setContentsMargins(20, 20, 20, 0)
        self.parent_layout.addWidget(self.parent_splitter)
        
        ################
        # LEFT HAND SIDE
        ################
        lhs_widget = QtGui.QWidget(self)
        lhs_layout = QtGui.QVBoxLayout()
        
        hbox = QtGui.QHBoxLayout()
        self.filter_combo_box = QtGui.QComboBox(self)
        self.filter_combo_box.setSizeAdjustPolicy(QtGui.QComboBox.AdjustToContents)
        self.filter_combo_box.addItem("All")
        self.element_summary_text = QtGui.QLabel(self)
        self.element_summary_text.setText("Please load spectral models")
        sp = QtGui.QSizePolicy(QtGui.QSizePolicy.MinimumExpanding, 
                               QtGui.QSizePolicy.MinimumExpanding)
        self.element_summary_text.setSizePolicy(sp)
        hbox.addWidget(self.filter_combo_box)
        hbox.addWidget(self.element_summary_text)
        lhs_layout.addLayout(hbox)

        self.table_view = SpectralModelsTableView(self)
        # Set up a proxymodel.
        self.proxy_spectral_models = SpectralModelsFilterProxyModel(self)
        self.proxy_spectral_models.add_filter_function(
            "use_for_stellar_composition_inference",
            lambda model: model.use_for_stellar_composition_inference)

        self.proxy_spectral_models.setDynamicSortFilter(True)
        header = ["", u"λ\n(Å)", "log ε\n(dex)", u"E. W.\n(mÅ)",
                  "REW", "Element\n"]
        attrs = ("is_acceptable", "_repr_wavelength", "abundance", "equivalent_width", 
                 "reduced_equivalent_width", "_repr_element")
        self.all_spectral_models = SpectralModelsTableModel(self, header, attrs)
        self.proxy_spectral_models.setSourceModel(self.all_spectral_models)

        self.table_view.setModel(self.proxy_spectral_models)
        self.table_view.setSelectionBehavior(
            QtGui.QAbstractItemView.SelectRows)

        # TODO: Re-enable sorting.
        self.table_view.setSortingEnabled(False)
        self.table_view.resizeColumnsToContents()
        self.table_view.setColumnWidth(0, 30) # MAGIC
        self.table_view.setColumnWidth(1, 70) # MAGIC
        self.table_view.setColumnWidth(2, 70) # MAGIC
        self.table_view.setColumnWidth(3, 70) # MAGIC
        self.table_view.setColumnWidth(4, 70) # MAGIC
        self.table_view.setMinimumSize(QtCore.QSize(240, 0))
        self.table_view.horizontalHeader().setStretchLastSection(True)
        sp = QtGui.QSizePolicy(
            QtGui.QSizePolicy.MinimumExpanding, 
            QtGui.QSizePolicy.MinimumExpanding)
        sp.setHeightForWidth(self.table_view.sizePolicy().hasHeightForWidth())
        self.table_view.setSizePolicy(sp)
        lhs_layout.addWidget(self.table_view)

        # Buttons
        hbox = QtGui.QHBoxLayout()
        self.btn_fit_all = QtGui.QPushButton(self)
        self.btn_fit_all.setText("Fit all acceptable")
        self.btn_fit_one = QtGui.QPushButton(self)
        self.btn_fit_one.setText("Fit one")
        hbox.addWidget(self.btn_fit_all)
        hbox.addWidget(self.btn_fit_one)
        lhs_layout.addLayout(hbox)

        hbox = QtGui.QHBoxLayout()
        self.btn_measure_all = QtGui.QPushButton(self)
        self.btn_measure_all.setText("Measure all acceptable")
        self.btn_measure_one = QtGui.QPushButton(self)
        self.btn_measure_one.setText("Measure one")
        hbox.addWidget(self.btn_measure_all)
        hbox.addWidget(self.btn_measure_one)
        lhs_layout.addLayout(hbox)

        hbox = QtGui.QHBoxLayout()
        self.btn_refresh = QtGui.QPushButton(self)
        self.btn_refresh.setText("Refresh from session")
        self.btn_replot  = QtGui.QPushButton(self)
        self.btn_replot.setText("Refresh plots")
        hbox.addWidget(self.btn_refresh)
        hbox.addWidget(self.btn_replot)
        lhs_layout.addLayout(hbox)

        lhs_layout.addLayout(hbox)
        
        # Model fitting options
        self._create_fitting_options_widget()
        lhs_layout.addWidget(self.fitting_options)

        lhs_widget.setLayout(lhs_layout)
        self.parent_splitter.addWidget(lhs_widget)

        #############################
        # RIGHT HAND SIDE: MPL WIDGET
        #############################
        rhs_layout = QtGui.QVBoxLayout()
        self.figure = mpl.MPLWidget(None, tight_layout=True, autofocus=True)
        self.figure.setMinimumSize(QtCore.QSize(800, 300))
        
        gs_top = matplotlib.gridspec.GridSpec(3,1,height_ratios=[1,2,1])
        gs_top.update(top=.95,bottom=.05,hspace=0)
        gs_bot = matplotlib.gridspec.GridSpec(3,1,height_ratios=[1,2,1])
        gs_bot.update(top=.95,bottom=.05,hspace=.3)
        
        self.ax_residual = self.figure.figure.add_subplot(gs_top[0])
        self.ax_residual.axhline(0, c="#666666")
        self.ax_residual.xaxis.set_major_locator(MaxNLocator(5))
        #self.ax_residual.yaxis.set_major_locator(MaxNLocator(2))
        self.ax_residual.set_xticklabels([])
        self.ax_residual.set_ylabel("Residual")
        
        self.ax_spectrum = self.figure.figure.add_subplot(gs_top[1])
        self.ax_spectrum.xaxis.get_major_formatter().set_useOffset(False)
        self.ax_spectrum.xaxis.set_major_locator(MaxNLocator(5))
        self.ax_spectrum.set_xlabel(u"Wavelength (Å)")
        self.ax_spectrum.set_ylabel(r"Normalized flux")
        
        self.ax_line_strength = self.figure.figure.add_subplot(gs_bot[2])
        self.ax_line_strength.xaxis.get_major_formatter().set_useOffset(False)
        self.ax_line_strength.yaxis.set_major_locator(MaxNLocator(5))
        self.ax_line_strength.yaxis.set_major_locator(MaxNLocator(4))
        self.ax_line_strength.set_xlabel(r"$\log({\rm EW}/\lambda)$")
        self.ax_line_strength.set_ylabel("A(X)")
        
        self._points = [self.ax_line_strength.scatter([], [], s=30, \
             facecolor="k", edgecolor="k", picker=PICKER_TOLERANCE, \
             alpha=0.5)]
        self._trend_lines = None
        
        # Some empty figure objects that we will use later.
        self._lines = {
            "selected_point": [
                self.ax_line_strength.scatter([], [],
                    edgecolor="b", facecolor="none", s=150, linewidth=3, zorder=2)
            ],
            "spectrum": None,
            "transitions_center_main": self.ax_spectrum.axvline(
                np.nan, c="#666666", linestyle=":"),
            "transitions_center_residual": self.ax_residual.axvline(
                np.nan, c="#666666", linestyle=":"),
            "model_masks": [],
            "nearby_lines": [],
            "model_fit": self.ax_spectrum.plot([], [], c="r")[0],
            "model_residual": self.ax_residual.plot([], [], c="k")[0],
            "interactive_mask": [
                self.ax_spectrum.axvspan(xmin=np.nan, xmax=np.nan, ymin=np.nan,
                    ymax=np.nan, facecolor="r", edgecolor="none", alpha=0.25,
                    zorder=-5),
                self.ax_residual.axvspan(xmin=np.nan, xmax=np.nan, ymin=np.nan,
                    ymax=np.nan, facecolor="r", edgecolor="none", alpha=0.25,
                    zorder=-5)
            ]
        }
        
        self.parent_splitter.addWidget(self.figure)

        # Connect filter combo box
        self.filter_combo_box.currentIndexChanged.connect(self.filter_combo_box_changed)
        
        # Connect selection model
        _ = self.table_view.selectionModel()
        _.selectionChanged.connect(self.selected_model_changed)

        # Connect buttons
        self.btn_fit_all.clicked.connect(self.fit_all)
        self.btn_fit_one.clicked.connect(self.fit_one)
        self.btn_measure_all.clicked.connect(self.measure_all)
        self.btn_measure_one.clicked.connect(self.measure_one)
        self.btn_refresh.clicked.connect(self.refresh_table)
        self.btn_replot.clicked.connect(self.refresh_plots)

        # Connect matplotlib.
        self.figure.mpl_connect("button_press_event", self.figure_mouse_press)
        self.figure.mpl_connect("button_release_event", self.figure_mouse_release)
        self.figure.figure.canvas.callbacks.connect(
            "pick_event", self.figure_mouse_pick)
        
        self._currently_plotted_element = None
        self._rew_cache = []
        self._abund_cache = []
        self.populate_widgets()

    def _create_fitting_options_widget(self):
        group_box = QtGui.QGroupBox(self)
        group_box.setTitle("Fitting options")
        opt_layout = QtGui.QVBoxLayout(group_box)
        opt_layout.setContentsMargins(6, 12, 6, 6)
        self.opt_tabs = QtGui.QTabWidget(group_box)
        self.opt_tab_common = QtGui.QWidget()
        
        # Common options
        self.tab_common = QtGui.QWidget()
        vbox_common = QtGui.QVBoxLayout(self.tab_common)
        grid_common = QtGui.QGridLayout()
        grid_common.addItem(
            QtGui.QSpacerItem(40, 20, 
                QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum),
            1, 2, 1, 1)

        label = QtGui.QLabel(self.tab_common)
        label.setText("Data fitting window")
        grid_common.addWidget(label, 0, 1, 1, 1)
        self.edit_window = QtGui.QLineEdit(self.tab_common)
        self.edit_window.setMinimumSize(QtCore.QSize(60, 0))
        self.edit_window.setMaximumSize(QtCore.QSize(60, 16777215))
        self.edit_window.setValidator(
            QtGui.QDoubleValidator(0, 1000, 1, self.edit_window))
        grid_common.addWidget(self.edit_window, 0, 3, 1, 1)

        self.checkbox_continuum = QtGui.QCheckBox(self.tab_common)
        self.checkbox_continuum.setText("")
        grid_common.addWidget(self.checkbox_continuum, 1, 0, 1, 1)
        label = QtGui.QLabel(self.tab_common)
        label.setText("Model continuum with polynomial order")
        grid_common.addWidget(label, 1, 1, 1, 1)
        self.combo_continuum = QtGui.QComboBox(self.tab_common)
        self.combo_continuum.setMinimumSize(QtCore.QSize(60, 0))
        self.combo_continuum.setMaximumSize(QtCore.QSize(60, 16777215))
        grid_common.addWidget(self.combo_continuum, 1, 3, 1, 1)

        for i in range(10):
            self.combo_continuum.addItem("{:.0f}".format(i))

        self.checkbox_vrad_tolerance = QtGui.QCheckBox(self.tab_common)
        self.checkbox_vrad_tolerance.setText("")
        grid_common.addWidget(self.checkbox_vrad_tolerance, 2, 0, 1, 1)
        label = QtGui.QLabel(self.tab_common)
        label.setText("Set tolerance on residual radial velocity")
        grid_common.addWidget(label, 2, 1, 1, 1)
        self.edit_vrad_tolerance = QtGui.QLineEdit(self.tab_common)
        self.edit_vrad_tolerance.setMinimumSize(QtCore.QSize(60, 0))
        self.edit_vrad_tolerance.setMaximumSize(QtCore.QSize(60, 16777215))
        self.edit_vrad_tolerance.setValidator(
            QtGui.QDoubleValidator(0, 100, 2, self.edit_vrad_tolerance))
        grid_common.addWidget(self.edit_vrad_tolerance, 2, 3, 1, 1)

        grid_common.addItem(QtGui.QSpacerItem(40, 20, 
            QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum), 2, 2, 1, 1)
        vbox_common.addLayout(grid_common)
        vbox_common.addItem(QtGui.QSpacerItem(20, 40, 
            QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Expanding))
        self.opt_tabs.addTab(self.tab_common, "Common")
        
        # Profile model options.
        self.tab_profile = QtGui.QWidget()
        grid_profile = QtGui.QGridLayout(self.tab_profile)


        label = QtGui.QLabel(self.tab_profile)
        label.setText("Profile type")
        grid_profile.addWidget(label, 0, 1, 1, 1)
        grid_profile.addItem(
            QtGui.QSpacerItem(40, 20, 
                QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum),
            0, 2, 1, 1)
        self.combo_profile = QtGui.QComboBox(self.tab_profile)
        grid_profile.addWidget(self.combo_profile, 0, 3, 1, 1)

        for each in ("Gaussian", "Lorentzian", "Voigt"):
            self.combo_profile.addItem(each)

        label = QtGui.QLabel(self.tab_profile)
        label.setText("Detection sigma for nearby absorption lines")
        grid_profile.addWidget(label, 1, 1, 1, 1)
        hbox = QtGui.QHBoxLayout()
        hbox.addItem(QtGui.QSpacerItem(40, 20, 
            QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum))
        self.edit_detection_sigma = QtGui.QLineEdit(self.tab_profile)
        self.edit_detection_sigma.setMinimumSize(QtCore.QSize(60, 0))
        self.edit_detection_sigma.setMaximumSize(QtCore.QSize(60, 16777215))
        self.edit_detection_sigma.setValidator(
            QtGui.QDoubleValidator(0, 100, 1, self.edit_detection_sigma))
        hbox.addWidget(self.edit_detection_sigma)
        grid_profile.addLayout(hbox, 1, 3, 1, 1)


        label = QtGui.QLabel(self.tab_profile)
        label.setText("Neighbouring pixels required to detect nearby lines")
        grid_profile.addWidget(label, 2, 1, 1, 1)
        hbox = QtGui.QHBoxLayout()
        hbox.addItem(QtGui.QSpacerItem(40, 20, 
            QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum))
        self.edit_detection_pixels = QtGui.QLineEdit(self.tab_profile)
        self.edit_detection_pixels.setMinimumSize(QtCore.QSize(60, 0))
        self.edit_detection_pixels.setMaximumSize(QtCore.QSize(60, 16777215))
        self.edit_detection_pixels.setValidator(
            QtGui.QIntValidator(0, 100, self.edit_detection_pixels))
        hbox.addWidget(self.edit_detection_pixels)
        grid_profile.addLayout(hbox, 2, 3, 1, 1)


        label = QtGui.QLabel(self.tab_profile)
        label.setText("Use central pixel weighting")
        grid_profile.addWidget(label, 4, 1, 1, 1)
        self.checkbox_use_central_weighting = QtGui.QCheckBox(self.tab_profile)
        self.checkbox_use_central_weighting.setText("")
        grid_profile.addWidget(self.checkbox_use_central_weighting, 4, 0, 1, 1)

    
        label = QtGui.QLabel(self.tab_profile)
        label.setText("Tolerance in wavelength position")
        grid_profile.addWidget(label, 3, 1, 1, 1)
        self.checkbox_wavelength_tolerance = QtGui.QCheckBox(self.tab_profile)
        self.checkbox_wavelength_tolerance.setText("")
        grid_profile.addWidget(self.checkbox_wavelength_tolerance, 3, 0, 1, 1)
        hbox = QtGui.QHBoxLayout()
        hbox.addItem(QtGui.QSpacerItem(40, 20, QtGui.QSizePolicy.Expanding,
            QtGui.QSizePolicy.Minimum))
        self.edit_wavelength_tolerance = QtGui.QLineEdit(self.tab_profile)
        self.edit_wavelength_tolerance.setMinimumSize(QtCore.QSize(50, 0))
        self.edit_wavelength_tolerance.setMaximumSize(QtCore.QSize(60, 16777215))
        self.edit_wavelength_tolerance.setValidator(
            QtGui.QDoubleValidator(0, 10, 2, self.edit_wavelength_tolerance))
        hbox.addWidget(self.edit_wavelength_tolerance)
        grid_profile.addLayout(hbox, 3, 3, 1, 1)

        self.opt_tabs.addTab(self.tab_profile, "Profile options")
        
        # Synthesis model options.
        self.tab_synthesis = QtGui.QWidget()
        vbox_synthesis = QtGui.QVBoxLayout(self.tab_synthesis)
        grid_synthesis = QtGui.QGridLayout()

        label = QtGui.QLabel(self.tab_synthesis)
        label.setText("Initial abundance boundary")
        grid_synthesis.addWidget(label, 0, 1, 1, 1)
        self.edit_initial_abundance_bound = QtGui.QLineEdit(self.tab_synthesis)
        self.edit_initial_abundance_bound.setMinimumSize(QtCore.QSize(60, 0))
        self.edit_initial_abundance_bound.setMaximumSize(QtCore.QSize(60, 16777215))
        self.edit_initial_abundance_bound.setValidator(
            QtGui.QDoubleValidator(0, 2, 1, self.edit_initial_abundance_bound))
        grid_synthesis.addWidget(self.edit_initial_abundance_bound, 0, 3, 1, 1)

        self.checkbox_model_smoothing = QtGui.QCheckBox(self.tab_synthesis)
        self.checkbox_model_smoothing.setText("")
        grid_synthesis.addWidget(self.checkbox_model_smoothing, 1, 0, 1, 1)
        label = QtGui.QLabel(self.tab_synthesis)
        label.setText("Model observed resolution by smoothing")
        grid_synthesis.addWidget(label, 1, 1, 1, 1)

        label = QtGui.QLabel(self.tab_synthesis)
        label.setText("Constrain smoothing to less than:")
        grid_synthesis.addWidget(label, 2, 1, 1, 1)
        self.edit_smoothing_bound = QtGui.QLineEdit(self.tab_synthesis)
        self.edit_smoothing_bound.setMinimumSize(QtCore.QSize(60, 0))
        self.edit_smoothing_bound.setMaximumSize(QtCore.QSize(60, 16777215))
        self.edit_smoothing_bound.setValidator(
            QtGui.QDoubleValidator(0, 10, 1, self.edit_smoothing_bound))
        grid_synthesis.addWidget(self.edit_smoothing_bound, 2, 3, 1, 1)

        self.btn_specify_abundances = QtGui.QPushButton(self.tab_synthesis)
        self.btn_specify_abundances.setText("Specify explicit abundance table TODO")
        grid_synthesis.addWidget(self.btn_specify_abundances, 3, 1, 1, 1)

        grid_synthesis.addItem(QtGui.QSpacerItem(40, 20, 
            QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Minimum), 0, 2, 1, 1)
        vbox_synthesis.addLayout(grid_synthesis)
        vbox_synthesis.addItem(QtGui.QSpacerItem(20, 40, 
            QtGui.QSizePolicy.Minimum, QtGui.QSizePolicy.Expanding))
        self.opt_tabs.addTab(self.tab_synthesis, "Synthesis options")


        # Buttons.
        hbox_btns = QtGui.QHBoxLayout()
        self.auto_fit_checkbox = QtGui.QCheckBox(group_box)
        self.auto_fit_checkbox.setText("Autofit")
        hbox_btns.addWidget(self.auto_fit_checkbox)

        # Final layout placement.
        opt_layout.addWidget(self.opt_tabs)
        opt_layout.addLayout(hbox_btns)
        self.opt_tabs.raise_()
        self.fitting_options = group_box

        # Connect Signals
        # Common options.
        self.edit_window.textChanged.connect(
            self.update_edit_window)
        self.edit_window.textChanged.connect(
            self.autofit)
        self.checkbox_continuum.stateChanged.connect(
            self.clicked_checkbox_continuum)
        self.checkbox_continuum.stateChanged.connect(
            self.autofit)
        self.combo_continuum.currentIndexChanged.connect(
            self.update_continuum_order)
        self.combo_continuum.currentIndexChanged.connect(
            self.autofit)
        self.checkbox_vrad_tolerance.stateChanged.connect(
            self.clicked_checkbox_vrad_tolerance)
        self.checkbox_vrad_tolerance.stateChanged.connect(
            self.autofit)
        self.edit_vrad_tolerance.textChanged.connect(
            self.update_vrad_tolerance)
        self.edit_vrad_tolerance.textChanged.connect(
            self.autofit)

        # Profile options.
        self.combo_profile.currentIndexChanged.connect(
            self.update_combo_profile)
        self.combo_profile.currentIndexChanged.connect(
            self.autofit)
        self.edit_detection_sigma.textChanged.connect(
            self.update_detection_sigma)
        self.edit_detection_sigma.textChanged.connect(
            self.autofit)
        self.edit_detection_pixels.textChanged.connect(
            self.update_detection_pixels)
        self.edit_detection_pixels.textChanged.connect(
            self.autofit)
        self.checkbox_use_central_weighting.stateChanged.connect(
            self.clicked_checkbox_use_central_weighting)
        self.checkbox_use_central_weighting.stateChanged.connect(
            self.autofit)
        self.checkbox_wavelength_tolerance.stateChanged.connect(
            self.clicked_checkbox_wavelength_tolerance)
        self.checkbox_wavelength_tolerance.stateChanged.connect(
            self.autofit)
        self.edit_wavelength_tolerance.textChanged.connect(
            self.update_wavelength_tolerance)
        self.edit_wavelength_tolerance.textChanged.connect(
            self.autofit)

        # Synthesis options.
        self.edit_initial_abundance_bound.textChanged.connect(
            self.update_initial_abundance_bound)
        self.edit_initial_abundance_bound.textChanged.connect(
            self.autofit)
        self.checkbox_model_smoothing.stateChanged.connect(
            self.clicked_checkbox_model_smoothing)
        self.checkbox_model_smoothing.stateChanged.connect(
            self.autofit)
        self.edit_smoothing_bound.textChanged.connect(
            self.update_smoothing_bound)
        self.edit_smoothing_bound.textChanged.connect(
            self.autofit)
        self.btn_specify_abundances.clicked.connect(
            self.clicked_btn_specify_abundances)
        self.btn_specify_abundances.clicked.connect(
            self.autofit)

    def populate_widgets(self):
        """
        Refresh widgets from session.
        Call whenever a session is loaded or spectral models changed
        TODO
        """
        self.refresh_table()
        return None

    def populate_filter_combo_box(self):
        if self.parent.session is None: return None
        box = self.filter_combo_box
        box.clear()
        box.addItem("All")

        all_species = set([])
        for spectral_model in self.all_spectral_models.spectral_models:
            all_species.update(set(spectral_model.species))
        if len(all_species)==0: return None
        all_species = np.sort(list(all_species))
        for species in all_species:
            elem = utils.species_to_element(species)
            assert species == utils.element_to_species(elem)
            box.addItem(elem)

    def filter_combo_box_changed(self):
        elem = self.filter_combo_box.currentText()
        table_model = self.proxy_spectral_models
        table_model.delete_all_filter_functions()
        table_model.reset()
        if elem is None or elem == "" or elem == "All":
            self.element_summary_text.setText("")
        else:
            species = utils.element_to_species(elem)
            filter_function = lambda model: species in model.species
            table_model.beginResetModel()
            table_model.add_filter_function(elem, filter_function)
            table_model.endResetModel()
        self.summarize_current_table()
        self.refresh_cache()
        self.refresh_plots()
        return None

    def summarize_current_table(self):
        elem = self.filter_combo_box.currentText()
        if elem is None or elem == "" or elem == "All":
            self.element_summary_text.setText("")
            return None
        table_model = self.proxy_spectral_models
        # TODO loop through proxy table to compute N, mean A(X), error?
        # That seems very slow...
        self.element_summary_text.setText(elem)
        return None

    def refresh_table(self):
        if self.parent.session is None: return None
        self._check_for_spectral_models()
        self.proxy_spectral_models.reset()
        self.populate_filter_combo_box()
        return None

    def refresh_plots(self):
        print("Refreshing plots"); start = time.time()
        model, proxy_index, index = self._get_selected_model(True)
        print(model, proxy_index, index)
        self.update_spectrum_figure(redraw=False)
        self.update_selected_points_plot(redraw=False)
        self.update_line_strength_figure(redraw=True)
        print ("Time: {:.1f}s".format(time.time()-start))
        return None

    def fit_all(self):
        self._check_for_spectral_models()

        # Fit all acceptable
        num_unacceptable = 0
        for i,m in enumerate(self.all_spectral_models.spectral_models):
            if not m.is_acceptable:
                num_unacceptable += 1
                continue
            if isinstance(m, SpectralSynthesisModel):
                try:
                    res = m.fit()
                except (ValueError, RuntimeError) as e:
                    logger.debug("Fitting error",m)
                    logger.debug(e)
            if isinstance(m, ProfileFittingModel):
                try:
                    res = m.fit()
                except (ValueError, RuntimeError) as e:
                    logger.debug("Fitting error",m)
                    logger.debug(e)
        # If none are acceptable, then fit all
        if num_unacceptable == self.all_spectral_models.rowCount(None):
            print("Found no acceptable spectral models, fitting all!")
            for i,m in enumerate(self.all_spectral_models.spectral_models):
                if isinstance(m, SpectralSynthesisModel):
                    try:
                        res = m.fit()
                    except (ValueError, RuntimeError) as e:
                        logger.debug("Fitting error",m)
                        logger.debug(e)
                if isinstance(m, ProfileFittingModel):
                    try:
                        res = m.fit()
                    except (ValueError, RuntimeError) as e:
                        logger.debug("Fitting error",m)
                        logger.debug(e)
        self.proxy_spectral_models.reset()
        self.refresh_cache()
        self.refresh_plots()
        return None

    def measure_all(self):
        i_profile = 0
        i_synth = 0
        equivalent_widths = []
        transition_indices = []
        spectral_model_indices = []
        for i,m in enumerate(self.parent.session.metadata["spectral_models"]):
            if isinstance(m, ProfileFittingModel):
                spectral_model_indices.append(i)
                transition_indices.extend(m._transition_indices)
                if m.is_acceptable:
                    equivalent_widths.append(1000.* \
                        m.metadata["fitted_result"][-1]["equivalent_width"][0])
                else:
                    equivalent_widths.append(np.nan)
                i_profile += 1
            elif isinstance(m, SpectralSynthesisModel):
                print("Ignoring synthesis",m)
                i_synth += 1

        if len(equivalent_widths) == 0 \
        or np.isfinite(equivalent_widths).sum() == 0:
            raise ValueError("no measured transitions to calculate abundances")
        
        transition_indices = np.array(transition_indices)
        spectral_model_indices = np.array(spectral_model_indices)
        transitions = self.parent.session.metadata["line_list"][transition_indices].copy()
        transitions["equivalent_width"] = equivalent_widths
        finite = np.isfinite(transitions["equivalent_width"])
            
        # Store COG abundances straight into session
        abundances = self.parent.session.rt.abundance_cog(
            self.parent.session.stellar_photosphere, transitions[finite])
        for index, abundance in zip(spectral_model_indices[finite], abundances):
            self.parent.session.metadata["spectral_models"][index]\
                .metadata["fitted_result"][-1]["abundances"] = [abundance]


        self.proxy_spectral_models.reset()
        self.refresh_cache()
        self.refresh_plots()
        return None

    def fit_one(self):
        spectral_model, proxy_index, index = self._get_selected_model(True)
        if spectral_model is None: return None
        try:
            res = spectral_model.fit()
        except (ValueError, RuntimeError) as e:
            logger.debug("Fitting error",spectral_model)
            logger.debug(e)
            return None
        self.update_table_data(proxy_index, index)
        self.update_cache(proxy_index)
        self.selected_model_changed()
        return None

    def measure_one(self):
        spectral_model, proxy_index, index = self._get_selected_model(True)
        if spectral_model is None: return None
        try:
            ab = spectral_model.abundances
        except rt.RTError as e:
            logger.debug("Abundance error",spectral_model)
            logger.debug(e)
            return None
        except KeyError as e:
            print("Fit a model first!")
            return None
        self.update_table_data(proxy_index, index)
        self.update_cache(proxy_index)
        self.selected_model_changed()
        return None

    def _check_for_spectral_models(self):
        for sm in self.parent.session.metadata.get("spectral_models", []):
            if sm.use_for_stellar_composition_inference: break
        else:
            reply = QtGui.QMessageBox.information(self,
                "No spectral models found",
                "No spectral models are currently associated with the "
                "determination of chemical abundances.\n\n"
                "Click 'OK' to load the transitions manager.")
            if reply == QtGui.QMessageBox.Ok:
                # Load line list manager.
                dialog = TransitionsDialog(self.parent.session,
                    callbacks=[self.proxy_spectral_models.reset, 
                               self.populate_widgets])
                dialog.exec_()

                # Do we even have any spectral models now?
                for sm in self.parent.session.metadata.get("spectral_models", []):
                    if sm.use_for_stellar_composition_inference: break
                else:
                    return False
            else:
                return False
        return True


    def figure_mouse_pick(self, event):
        """
        Trigger for when the mouse is used to select an item in the figure.

        :param event:
            The matplotlib event.
        """
        self.table_view.selectRow(event.ind[0])
        return None

    def figure_mouse_press(self, event):
        """
        Trigger for when the mouse button is pressed in the figure.

        :param event:
            The matplotlib event.
        """
        logger.debug("Mouse pressed"+str(event))

        if event.inaxes in (self.ax_residual, self.ax_spectrum):
            self.spectrum_axis_mouse_press(event)
        return None


    def figure_mouse_release(self, event):
        """
        Trigger for when the mouse button is released in the figure.

        :param event:
            The matplotlib event.
        """
        logger.debug("Mouse released"+str(event))

        if event.inaxes in (self.ax_residual, self.ax_spectrum):
            self.spectrum_axis_mouse_release(event)
        return None

    def spectrum_axis_mouse_press(self, event):
        """
        The mouse button was pressed in the spectrum axis.

        :param event:
            The matplotlib event.
        """

        if event.dblclick:

            # Double click.
            spectral_model, proxy_index, index = self._get_selected_model(True)

            for i, (s, e) in enumerate(spectral_model.metadata["mask"][::-1]):
                if e >= event.xdata >= s:
                    # Remove a mask
                    print("Removing mask")
                    # TODO this doesn't seem to work?
                    mask = spectral_model.metadata["mask"]
                    index = len(mask) - 1 - i
                    del mask[index]

                    # Re-fit the current spectral_model.
                    spectral_model.fit()

                    # Update the view for this row.
                    self.update_table_data(proxy_index, index)

                    # Update the view of the current model.
                    self.update_spectrum_figure(True)
                    break

            else:
                # No match with a masked region. 
                # TODO: Add a point that will be used for the continuum?
                # For the moment just refit the model.
                spectral_model.fit()

                # Update the view for this row.
                self.update_table_data(proxy_index, index)

                # Update the view of the current model.
                self.update_spectrum_figure(True)
                return None

        else:
            # Single click.
            xmin, xmax, ymin, ymax = (event.xdata, np.nan, -1e8, +1e8)
            for patch in self._lines["interactive_mask"]:
                patch.set_xy([
                    [xmin, ymin],
                    [xmin, ymax],
                    [xmax, ymax],
                    [xmax, ymin],
                    [xmin, ymin]
                ])

            # Set the signal and the time.
            self._interactive_mask_region_signal = (
                time.time(),
                self.figure.mpl_connect(
                    "motion_notify_event", self.update_mask_region)
            )

        return None


    def update_mask_region(self, event):
        """
        Update the visible selected masked region for the selected spectral
        model. This function is linked to a callback for when the mouse position
        moves.

        :para event:
            The matplotlib motion event to show the current mouse position.
        """

        if event.xdata is None: return

        signal_time, signal_cid = self._interactive_mask_region_signal
        if time.time() - signal_time > DOUBLE_CLICK_INTERVAL:

            data = self._lines["interactive_mask"][0].get_xy()

            # Update xmax.
            data[2:4, 0] = event.xdata
            for patch in self._lines["interactive_mask"]:
                patch.set_xy(data)

            self.figure.draw()

        return None



    def spectrum_axis_mouse_release(self, event):
        """
        Mouse button was released from the spectrum axis.

        :param event:
            The matplotlib event.
        """

        try:
            signal_time, signal_cid = self._interactive_mask_region_signal

        except AttributeError:
            return None

        xy = self._lines["interactive_mask"][0].get_xy()

        if event.xdata is None:
            # Out of axis; exclude based on the closest axis limit
            xdata = xy[2, 0]
        else:
            xdata = event.xdata


        # If the two mouse events were within some time interval,
        # then we should not add a mask because those signals were probably
        # part of a double-click event.
        if  time.time() - signal_time > DOUBLE_CLICK_INTERVAL \
        and np.abs(xy[0,0] - xdata) > 0:
            
            # Get current spectral model.
            spectral_model, proxy_index, index = self._get_selected_model(True)
            if spectral_model is None: 
                raise RuntimeError("""Must have a spectral model selected while making mask!
                                   Must have mouseover bug?""")

            # Add mask metadata.
            spectral_model.metadata["mask"].append([xy[0,0], xy[2, 0]])

            # Re-fit the spectral model.
            spectral_model.fit()

            # Update the table view for this row.
            self.update_table_data(proxy_index, index)

            # Update the view of the spectral model.
            self.update_spectrum_figure()

        xy[:, 0] = np.nan
        for patch in self._lines["interactive_mask"]:
            patch.set_xy(xy)

        self.figure.mpl_disconnect(signal_cid)
        self.figure.draw()
        del self._interactive_mask_region_signal
        return None

    def _get_selected_model(self, full_output=False):
        try:
            proxy_index = self.table_view.selectionModel().selectedIndexes()[0]
        except IndexError:
            return (None, None, None) if full_output else None
        index = self.proxy_spectral_models.mapToSource(proxy_index).row()
        model = self.parent.session.metadata["spectral_models"][index]
        return (model, proxy_index, index) if full_output else model

    def selected_model_changed(self):
        #model, proxy_index, index = self._get_selected_model(True)
        self.update_fitting_options()
        self.refresh_plots()
        return None

    def update_spectrum_figure(self, redraw=False):
        """
        TODO refactor all this plotting?
        Currently copied straight from stellar_parameters.py with minor changes
        """
        if self._lines["spectrum"] is None \
        and hasattr(self.parent, "session") \
        and hasattr(self.parent.session, "normalized_spectrum"):
            # Draw the spectrum.
            spectrum = self.parent.session.normalized_spectrum
            self._lines["spectrum"] = self.ax_spectrum.plot(spectrum.dispersion,
                spectrum.flux, c="k", drawstyle="steps-mid")

            sigma = 1.0/np.sqrt(spectrum.ivar)
            style_utils.fill_between_steps(self.ax_spectrum, spectrum.dispersion,
                spectrum.flux - sigma, spectrum.flux + sigma, 
                facecolor="#cccccc", edgecolor="#cccccc", alpha=1)

            style_utils.fill_between_steps(self.ax_residual, spectrum.dispersion,
                -sigma, +sigma, facecolor="#CCCCCC", edgecolor="none", alpha=1)

            self.ax_spectrum.set_xlim(
                spectrum.dispersion[0], spectrum.dispersion[-1])
            self.ax_residual.set_xlim(self.ax_spectrum.get_xlim())
            self.ax_spectrum.set_ylim(0, 1.2)
            self.ax_spectrum.set_yticks([0, 0.5, 1])
            three_sigma = 3*np.median(sigma[np.isfinite(sigma)])
            self.ax_residual.set_ylim(-three_sigma, three_sigma)

            if redraw: self.figure.draw()
        
        selected_model = self._get_selected_model()
        if selected_model is None:
            print("No model selected")
            return None
        transitions = selected_model.transitions
        window = selected_model.metadata["window"]
        limits = [
            transitions["wavelength"][0] - window,
            transitions["wavelength"][-1] + window,
        ]

        # Zoom to region.
        self.ax_spectrum.set_xlim(limits)
        self.ax_residual.set_xlim(limits)
            
        # If this is a profile fitting line, show where the centroid is.
        x = transitions["wavelength"][0] \
            if isinstance(selected_model, ProfileFittingModel) else np.nan
        self._lines["transitions_center_main"].set_data([x, x], [0, 1.2])
        self._lines["transitions_center_residual"].set_data([x, x], [0, 1.2])
        # Model masks specified by the user.
        # (These should be shown regardless of whether there is a fit or not.)
        for i, (start, end) in enumerate(selected_model.metadata["mask"]):
            try:
                patches = self._lines["model_masks"][i]

            except IndexError:
                self._lines["model_masks"].append([
                    self.ax_spectrum.axvspan(np.nan, np.nan,
                        facecolor="r", edgecolor="none", alpha=0.25),
                    self.ax_residual.axvspan(np.nan, np.nan,
                        facecolor="r", edgecolor="none", alpha=0.25)
                ])
                patches = self._lines["model_masks"][-1]

            for patch in patches:
                patch.set_xy([
                    [start, -1e8],
                    [start, +1e8],
                    [end,   +1e8],
                    [end,   -1e8],
                    [start, -1e8]
                ])
                patch.set_visible(True)

        # Hide unnecessary ones.
        N = len(selected_model.metadata["mask"])
        for unused_patches in self._lines["model_masks"][N:]:
            for unused_patch in unused_patches:
                unused_patch.set_visible(False)

        # Hide previous model_errs
        try:
            self._lines["model_yerr"].set_visible(False)
            del self._lines["model_yerr"]
            # TODO: This is wrong. It doesn't actually delete them so if
            #       you ran this forever then you would get a real bad 
            #       memory leak in Python. But for now, re-calculating
            #       the PolyCollection is in the too hard basket.

        except KeyError:
            None

        # Things to show if there is a fitted result.
        try:
            (named_p_opt, cov, meta) = selected_model.metadata["fitted_result"]

            # Test for some requirements.
            _ = (meta["model_x"], meta["model_y"], meta["residual"])

        except KeyError:
            meta = {}
            self._lines["model_fit"].set_data([], [])
            self._lines["model_residual"].set_data([], [])

        else:
            assert len(meta["model_x"]) == len(meta["model_y"])
            assert len(meta["model_x"]) == len(meta["residual"])
            assert len(meta["model_x"]) == len(meta["model_yerr"])

            self._lines["model_fit"].set_data(meta["model_x"], meta["model_y"])
            self._lines["model_residual"].set_data(meta["model_x"], 
                meta["residual"])

            # Model yerr.
            if np.any(np.isfinite(meta["model_yerr"])):
                self._lines["model_yerr"] = self.ax_spectrum.fill_between(
                    meta["model_x"],
                    meta["model_y"] + meta["model_yerr"],
                    meta["model_y"] - meta["model_yerr"],
                    facecolor="r", edgecolor="none", alpha=0.5)

            # Model masks due to nearby lines.
            if "nearby_lines" in meta:
                for i, (_, (start, end)) in enumerate(meta["nearby_lines"]):
                    try:
                        patches = self._lines["nearby_lines"][i]
                
                    except IndexError:
                        self._lines["nearby_lines"].append([
                            self.ax_spectrum.axvspan(np.nan, np.nan,
                                facecolor="b", edgecolor="none", alpha=0.25),
                            self.ax_residual.axvspan(np.nan, np.nan,
                                facecolor="b", edgecolor="none", alpha=0.25)
                        ])
                        patches = self._lines["nearby_lines"][-1]

                    for patch in patches:                            
                        patch.set_xy([
                            [start, -1e8],
                            [start, +1e8],
                            [end,   +1e8],
                            [end,   -1e8],
                            [start, -1e8]
                        ])
                        patch.set_visible(True)
                    
        # Hide any masked model regions due to nearby lines.
        N = len(meta.get("nearby_lines", []))
        for unused_patches in self._lines["nearby_lines"][N:]:
            for unused_patch in unused_patches:
                unused_patch.set_visible(False)

        if redraw: self.figure.draw()

        return None

    def update_cache(self, proxy_index):
        """
        Update the point plotting cache
        """
        proxy_row = proxy_index.row()
        table_model = self.proxy_spectral_models
        try:
            if not table_model.data(table_model.createIndex(proxy_row, 0, None)):
                raise ValueError #to put in nan
            rew = float(table_model.data(table_model.createIndex(proxy_row, 4, None)))
            abund = float(table_model.data(table_model.createIndex(proxy_row, 2, None)))
        except ValueError:
            self._rew_cache[proxy_row] = np.nan
            self._abund_cache[proxy_row] = np.nan
        else:
            self._rew_cache[proxy_row] = rew
            self._abund_cache[proxy_row] = abund
        
    def refresh_cache(self):
        # Compute cache of REW and abundance from spectral model table model
        # Wow this is the worst naming ever
        # Note that we should use np.nan for REW for synthesis models to keep indices ok
        # I believe that is correctly done in the table model
        current_element =  self.filter_combo_box.currentText()
        self._currently_plotted_element = current_element
        table_model = self.proxy_spectral_models
        rew_list = []
        abund_list = []
        for row in range(table_model.rowCount()):
            try:
                rew = float(table_model.data(table_model.createIndex(row, 4, None)))
                abund = float(table_model.data(table_model.createIndex(row, 2, None)))
            except ValueError:
                rew_list.append(np.nan); abund_list.append(np.nan)
            else:
                rew_list.append(rew); abund_list.append(abund)
        self._rew_cache = np.array(rew_list)
        self._abund_cache = np.array(abund_list)
        
    def update_selected_points_plot(self, redraw=False):
        """
        Plot selected points
        """
        if self.filter_combo_box.currentText() == "All":
            if redraw: self.figure.draw()
            return None
        # These are the proxy model indices
        indices = np.unique(np.array([index.row() for index in \
            self.table_view.selectionModel().selectedIndexes()]))
        if len(indices) == 0:
            self._lines["selected_point"][0].set_offsets(np.array([np.nan,np.nan]).T)
            if redraw: self.figure.draw()
            return None
        print("Selecting points: {} {} {}".format(indices, \
              self._rew_cache[indices],self._abund_cache[indices]))
        
        self._lines["selected_point"][0].set_offsets(\
            np.array([self._rew_cache[indices],self._abund_cache[indices]]).T)
        if redraw: self.figure.draw()
        return None

    def update_line_strength_figure(self, redraw=False, use_cache=True):
        current_element =  self.filter_combo_box.currentText()
        if current_element == "All":
            if redraw: self.figure.draw()
            return None
        if current_element == self._currently_plotted_element and use_cache:
            self._points[0].set_offsets(np.array([self._rew_cache, self._abund_cache]).T)
            style_utils.relim_axes(self.ax_line_strength)
            if redraw: self.figure.draw()
            return None
        self.refresh_cache()
        
        collections = self._points
        collections[0].set_offsets(np.array([self._rew_cache,self._abund_cache]).T)
        style_utils.relim_axes(self.ax_line_strength)
        
        # TODO trend lines

        if redraw: self.figure.draw()
        return None

    def update_fitting_options(self):
        try:
            selected_model = self._get_selected_model()
        except IndexError:
            return None
        if selected_model is None: return None
    
        # Common model.
        self.edit_window.setText("{}".format(selected_model.metadata["window"]))

        # Continuum order.
        continuum_order = selected_model.metadata["continuum_order"]
        if continuum_order < 0:
            self.checkbox_continuum.setChecked(False)
            self.combo_continuum.setEnabled(False)
        else:
            self.checkbox_continuum.setChecked(True)
            self.combo_continuum.setEnabled(True)
            self.combo_continuum.setCurrentIndex(continuum_order)

        # Radial velocity tolerance.
        vrad_tolerance = selected_model.metadata.get("velocity_tolerance", None)
        if vrad_tolerance is None:
            self.checkbox_vrad_tolerance.setChecked(False)
            self.edit_vrad_tolerance.setEnabled(False)
        else:
            self.checkbox_vrad_tolerance.setChecked(True)
            self.edit_vrad_tolerance.setEnabled(True)
            self.edit_vrad_tolerance.setText("{}".format(vrad_tolerance))

        # Profile options.
        if isinstance(selected_model, ProfileFittingModel):
            self.tab_profile.setEnabled(True)

            self.combo_profile.setCurrentIndex(
                ["gaussian", "lorentzian", "voight"].index(
                    selected_model.metadata["profile"]))

            self.edit_detection_sigma.setText("{}".format(
                selected_model.metadata["detection_sigma"]))
            self.edit_detection_pixels.setText("{}".format(
                selected_model.metadata["detection_pixels"]))

            self.checkbox_use_central_weighting.setEnabled(
                selected_model.metadata["central_weighting"])

            tolerance = selected_model.metadata.get("wavelength_tolerance", None)
            if tolerance is None:
                self.checkbox_wavelength_tolerance.setEnabled(False)
            else:
                self.checkbox_wavelength_tolerance.setEnabled(True)
                self.edit_wavelength_tolerance.setText(
                    "{}".format(tolerance))

        else:
            self.tab_profile.setEnabled(False)

        # Synthesis options.
        if isinstance(selected_model, SpectralSynthesisModel):
            self.tab_synthesis.setEnabled(True)

            # Update widgets.
            self.edit_initial_abundance_bound.setText(
                "{}".format(selected_model.metadata["initial_abundance_bounds"]))
            
            self.checkbox_model_smoothing.setEnabled(
                selected_model.metadata["smoothing_kernel"])

            # TODO sigma smooth tolerance needs implementing.
        else:
            self.tab_synthesis.setEnabled(False)

        return None

    def update_table_data(self, proxy_index, index):
        data_model = self.proxy_spectral_models.sourceModel()
        data_model.dataChanged.emit(
            data_model.createIndex(proxy_index.row(), 0),
            data_model.createIndex(proxy_index.row(),
                 data_model.columnCount(QtCore.QModelIndex())))
        self.table_view.rowMoved(
            proxy_index.row(), proxy_index.row(), proxy_index.row())
        return None

    ###############################
    # FITTING OPTION UPDATE METHODS
    ###############################

    def update_edit_window(self):
        """ The wavelength window was updated """
        model = self._get_selected_model()
        try:
            window = float(self.edit_window.text())
        except:
            return None
        else:
            model.metadata["window"] = window
            # Just update the axis limits.
            transitions = model.transitions
            # TODO synth wavelength
            xlim = (transitions["wavelength"][0] - window,
                    transitions["wavelength"][-1] + window)
            self.ax_spectrum.set_xlim(xlim)
            self.ax_line_strength.set_xlim(xlim)
            self.figure.draw()
        return None

    def clicked_checkbox_continuum(self):
        """ The checkbox for modeling the continuum was clicked. """
        if self.checkbox_continuum.isChecked():
            self.combo_continuum.setEnabled(True)
            self.update_continuum_order()
        else:
            self._get_selected_model().metadata["continuum_order"] = -1
            self.combo_continuum.setEnabled(False)
        return None

    def update_continuum_order(self):
        """ The continuum order to use in model fitting was changed. """
        self._get_selected_model().metadata["continuum_order"] \
            = int(self.combo_continuum.currentText())
        return None

    def clicked_checkbox_vrad_tolerance(self):
        """ The checkbox for velocity tolerance was clicked. """
        if self.checkbox_vrad_tolerance.isChecked():
            self.edit_vrad_tolerance.setEnabled(True)
            self.update_vrad_tolerance()
        else:
            self.edit_vrad_tolerance.setEnabled(False)
            self._get_selected_model().metadata["velocity_tolerance"] = None
        return None

    def update_vrad_tolerance(self):
        """ The tolerance on radial velocity was updated. """
        try:
            value = float(self.edit_vrad_tolerance.text())
        except:
            value = None
        self._get_selected_model().metadata["velocity_tolerance"] = value
        return None

    def update_combo_profile(self):
        """ Update the profile that is used for fitting atomic transitions. """
        self._get_selected_model().metadata["profile"] \
            = self.combo_profile.currentText().lower()
        return None

    def update_detection_sigma(self):
        """ The detection sigma for nearby lines has been updated. """
        self._get_selected_model().metadata["detection_sigma"] \
            = float(self.edit_detection_sigma.text())
        return None

    def update_detection_pixels(self):
        """ The number of pixels to qualify a detection has been updated. """
        self._get_selected_model().metadata["detection_pixels"] \
            = int(self.edit_detection_pixels.text())
        return None
    def clicked_checkbox_use_central_weighting(self):
        """ The checkbox to use central weighting has been clicked. """
        self._get_selected_model().metadata["central_weighting"] \
            = self.checkbox_use_central_weighting.isChecked()
        return None
    def clicked_checkbox_wavelength_tolerance(self):
        """ The checkbox to set a wavelength tolerance has been clicked. """
        if self.checkbox_wavelength_tolerance.isChecked():
            self.edit_wavelength_tolerance.setEnabled(True)
            self.update_wavelength_tolerance()
        else:
            self.edit_wavelength_tolerance.setEnabled(False)
            self._get_selected_model().metadata["wavelength_tolerance"] = None
        return None
    def update_wavelength_tolerance(self):
        """ The wavelength tolerance for a profile centroid has been updated. """
        self._get_selected_model().metadata["wavelength_tolerance"] \
            = float(self.edit_wavelength_tolerance.text())
        return None
    def update_initial_abundance_bound(self):
        """ The initial abundance bound has been updated. """
        self._get_selected_model().metadata["initial_abundance_bounds"] \
            = float(self.edit_initial_abundance_bound.text())
        return None
    def clicked_checkbox_model_smoothing(self):
        """ The checkbox to smooth the model spectrum has been clicked. """
        if self.checkbox_model_smoothing.isChecked():
            self._get_selected_model().metadata["smoothing_kernel"] = True
            self.edit_smoothing_bound.setEnabled(True)
            self.update_smoothing_bound()
        else:
            self._get_selected_model().metadata["smoothing_kernel"] = False
            self.edit_smoothing_bound.setEnabled(False)
        return None
    def update_smoothing_bound(self):
        """ The limits on the smoothing kernel have been updated. """
        value = float(self.edit_smoothing_bound.text())
        self._get_selected_model().metadata["sigma_smooth"] = (-value, value)
        if self.auto_fit_checkbox.isChecked(): self._get_selected_model().fit()
        return None
    def clicked_btn_specify_abundances(self):
        raise NotImplementedError

    def autofit(self):
        if self.auto_fit_checkbox.isChecked():
            m, pix, ix = self._get_selected_model(True)
            m.fit()
            self.update_table_data(ix)
            self.update_spectrum_figure(True)


class SpectralModelsTableModel(SpectralModelsTableModelBase):
    def data(self, index, role):
        """
        Display the data.

        :param index:
            The table index.

        :param role:
            The display role.
        """

        if not index.isValid():
            return None

        column = index.column()
        spectral_model = self.spectral_models[index.row()]

        if  column == 0 \
        and role in (QtCore.Qt.DisplayRole, QtCore.Qt.CheckStateRole):
            value = spectral_model.is_acceptable
            if role == QtCore.Qt.CheckStateRole:
                return QtCore.Qt.Checked if value else QtCore.Qt.Unchecked
            else:
                return None
        elif column == 1:
            value = spectral_model._repr_wavelength

        elif column == 2:
            try:
                abundances \
                    = spectral_model.metadata["fitted_result"][2]["abundances"]

            except (IndexError, KeyError):
                value = ""

            else:
                # TODO need to get current element from session to pick which one
                # How many elements were measured?
                value = "; ".join(["{0:.2f}".format(abundance) \
                    for abundance in abundances])

        elif column == 3 or column == 4:
            try:
                result = spectral_model.metadata["fitted_result"][2]
                equivalent_width = result["equivalent_width"][0]
            except:
                equivalent_width = np.nan

            if column == 3:
                value = "{0:.1f}".format(1000 * equivalent_width) \
                    if np.isfinite(equivalent_width) else ""
            if column == 4:
                value = "{:.2f}".format(np.log10(equivalent_width/float(spectral_model._repr_wavelength))) \
                    if np.isfinite(equivalent_width) else ""
                
        elif column == 5:
            # TODO need to get current element from session to pick which one
            value = "; ".join(["{}".format(element) \
                      for element in spectral_model.elements])

        return value if role == QtCore.Qt.DisplayRole else None

    def setData(self, index, value, role=QtCore.Qt.DisplayRole):
        start = time.time()
        value = super(SpectralModelsTableModel, self).setData(index, value, role)
        print("setData: superclass: {:.1f}s".format(time.time()-start))
        if index.column() != 0: return False
        
        # It ought to be enough just to emit the dataChanged signal, but
        # there is a bug when using proxy models where the data table is
        # updated but the view is not, so we do this hack to make it
        # work:

        # TODO: This means when this model is used in a tab, that tab
        #       (or whatever the parent is)
        #       should have a .table_view widget and an .update_spectrum_figure
        #       method.

        proxy_index = self.parent.table_view.model().mapFromSource(index)
        proxy_row = proxy_index.row()
        self.parent.table_view.rowMoved(proxy_row, proxy_row, proxy_row)

        print(proxy_index,proxy_row)
        self.parent.update_cache(proxy_index)
        print("Time to setData: {:.1f}s".format(time.time()-start))
        self.parent.refresh_plots()

        return value