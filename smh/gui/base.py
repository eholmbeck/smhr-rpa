from __future__ import (division, print_function, absolute_import,
                        unicode_literals)
import sys
import logging
import os
from PySide import QtCore, QtGui

import mpl

DOUBLE_CLICK_INTERVAL = 0.1 # MAGIC HACK
PICKER_TOLERANCE = 10 # MAGIC HACK

## These are valid attrs of a spectral model
_allattrs = ["wavelength","expot","species","elements","loggf",
           "equivalent_width","equivalent_width_uncertainty",
           "reduced_equivalent_width",
           "abundances", "abundances_to_solar", "abundance_uncertainties",
           "is_acceptable", "is_upper_limit", "user_flag",
           "use_for_stellar_parameter_inference", "use_for_stellar_composition_inference"]
_labels = ["Wavelength $\lambda$","Excitation potential","Species","Element","log gf",
           "Equivalent width", "Equivalent width error",
           "$\log{\rm EW}/\lambda$",
           u"log ε","[X/H]", u"σ(log ε)",
           "Acceptable", "Upper Limit", "User Flag",
           "Use for Spectroscopic Stellar Parameters", "Use for Stellar Abundances"]
_short_labels = [u"λ","$\chi$","species","El.","loggf",
                 "EW", u"σ(EW)",
                 "REW",
                 "A(X)","[X/H]",u"σ(X)",
                 "", "ul", "flag",
                 "spflag", "abundflag"]
_formats = [":.1f",":.2f",":.1f","",":.2f",
            ":.1f",":.1f",
            ":.2f",
            ":.2f",":.2f",":.2f",
            "","","","",
            "",""]
_formats = ["{"+fmt+"}" for fmt in _formats]
_attr2label = dict(zip(_allattrs,_labels))
_attr2slabel = dict(zip(_allattrs,_short_labels))
_attr2format = dict(zip(_allattrs,_formats))

class SMHWidgetBase(QtGui.QWidget):
    """
    Base class for interactive widgets
    """
    def __init__(self, parent, session=None, widgets_to_update = []):
        super(SMHWidgetBase, self).__init__(parent)
        self.parent = parent
        self.widgets_to_update = widgets_to_update
        self.session = session
        ## TODO set style options here
    def reload_from_session(self):
        """
        Rewrite any internal information with session data.
        """
        raise NotImplementedError
    def send_to_session(self):
        """
        Save any internal cached information to session (if any).
        """
        raise NotImplementedError
    def update_widgets_after_selection(self, selected_models):
        """
        Call update_after_selection for all widgets_to_update
        """
        for widget in self.widgets_to_update:
            widget.update_after_selection(selected_models)
    def update_widgets_after_measurement_change(self, changed_model):
        """
        Call update_after_measurement_change for all widgets_to_update
        """
        for widget in self.widgets_to_update:
            widget.update_after_measurement_change(changed_model)

class SMHSpecDisplay(mpl.MPLWidget, SMHWidgetBase):
    """
    Refactored class to display spectrum and residual plot.
    This holds a single spectral model and draws it.
    
    INTERACTIVE PORTIONS
    * Click/shift-click to mask/antimask
    * Rightclick to zoom
    * Shift-rightclick to pan [TODO]
    
    METHODS
    update_after_selection(selected_models):
        Call after a selection is updated (to change 
    update_after_measurement_change(changed_model):
        Call after a measurement is changed in changed_model
    update_selected_model()
        Retrieve selected model from parent object.
        (Requires parent._get_selected_model())
    set_selected_model(model):
        Force selected model to be model
    update_spectrum_figure(redraw=False):
        The main workhorse of this class
        Call when you want to update the spectrum figure

    update_mask_region():
        TODO used to update just the mask

    """
    def __init__(self, parent, session=None, widgets_to_update = [], **kwargs):
        mpl.MPLWidget.__init__(self, parent=parent, **kwargs)
        SMHWidgetBase.__init__(self, parent, session, widgets_to_update)
        self.selected_model = None
        
        gs = matplotlib.gridspec.GridSpec(2, 1, height_ratios[1,2])
        #gs_top.update(hspace=0.40)

        self.ax_residual = self.figure.add_subplot(gs[0])
        self.ax_residual.axhline(0, c="#666666")
        self.ax_residual.xaxis.set_major_locator(MaxNLocator(5))
        #self.ax_residual.yaxis.set_major_locator(MaxNLocator(2))
        self.ax_residual.set_xticklabels([])
        self.ax_residual.set_ylabel("Resid")
        
        self.ax_spectrum = self.figure.add_subplot(gs[1])
        self.ax_spectrum.axhline(1, c='k', ls=':')
        self.ax_spectrum.xaxis.get_major_formatter().set_useOffset(False)
        self.ax_spectrum.xaxis.set_major_locator(MaxNLocator(5))
        self.ax_spectrum.set_xlabel(u"Wavelength (Å)")
        self.ax_spectrum.set_ylabel(r"Normalized flux")
        self.ax_spectrum.set_ylim(0, 1.2)
        self.ax_spectrum.set_yticks([0, 0.5, 1])
        
        ## MPL objects to keep track of
        self._interactive_mask_region_signal = None
        drawstyle = self.session.setting(["plot_styles","spectrum_drawstyle"],"steps-mid")
        self._lines = {
            "spectrum": self.ax_spectrum.plot([], [], c="k", drawstyle=drawstyle)[0], #None,
            "spectrum_fill": None,
            "residual_fill": None,
            "transitions_center_main": self.ax_spectrum.axvline(
                np.nan, c="#666666", linestyle=":"),
            "transitions_center_residual": self.ax_residual.axvline(
                np.nan, c="#666666", linestyle=":"),
            "model_masks": [],
            "nearby_lines": [],
            "model_fit": self.ax_spectrum.plot([], [], c="r")[0],
            "model_residual": self.ax_residual.plot(
                [], [], c="k", drawstyle="steps-mid")[0],
            "interactive_mask": [
                self.ax_spectrum.axvspan(xmin=np.nan, xmax=np.nan, ymin=np.nan,
                                         ymax=np.nan, facecolor="r", edgecolor="none", alpha=0.25,
                                         zorder=-5),
                self.ax_residual.axvspan(xmin=np.nan, xmax=np.nan, ymin=np.nan,
                                         ymax=np.nan, facecolor="r", edgecolor="none", alpha=0.25,
                                         zorder=-5)
            ]
        }
    def update_after_selection(self, selected_models):
        ## Use the last selected model as current model
        self.set_selected_model(selected_models[-1])
    def update_after_measurement_change(self, changed_model):
        ## Only do something if the changed model is the current model
        if changed_model == self.selected_model:
            raise NotImplementedError
        return None
    
    def update_selected_model(self):
        self.selected_model = self.parent._get_selected_model()
    def set_selected_model(self, model):
        self.selected_model = model
    def update_spectrum_figure(self, redraw=False):
        self.update_selected_model()
        if self.selected_model is None: return None
        
        transitions = selected_model.transitions
        window = selected_model.metadata["window"]
        limits = [
            transitions["wavelength"][0] - window,
            transitions["wavelength"][-1]+ window,
        ]
        
        ## Set axis limits, including for panning
        self.ax_spectrum.set_xlim(limits)
        self.ax_residual.set_xlim(limits)
        self.figure.reset_zoom_limits()

        ## Plot spectrum and error bars
        success = self._plot_normalized_spectrum(limits)
        if not success: return None
        
        # If this is a profile fitting line, show where the centroid is.
        x = transitions["wavelength"][0] \
            if isinstance(selected_model, ProfileFittingModel) else np.nan
        self._lines["transitions_center_main"].set_data([x, x], [0, 1.2])
        self._lines["transitions_center_residual"].set_data([x, x], [0, 1.2])
        
        ## Plot masks
        success = self._plot_masks()
        
        ## Plot model
        success = self._plot_model()

        if redraw: self.draw()
        
        return None
        
    def spectrum_left_mouse_press(self, event):
        """
        Listener for if mouse button pressed in spectrum or residual axis
        
        Masking and mask removal 
        """
        if event.button != 1: return None
        if event.inaxes not in (self.ax_residual, self.ax_spectrum):
            return None
        
        self.update_selected_model()
        selected_model = self.selected_model
        
        ## Doubleclick: remove mask, and if so refit/redraw
        if event.dblclick:
            mask_removed = self._remove_mask(selected_model, event)
            if mask_removed:
                selected_model.fit()
                self.update_spectrum_figure(True)
                ## TODO trigger other widgets
                self.update_widgets_after_measurement_change(selected_model)
            return

        ## Normal click: start drawing mask
        # Clear all masks if shift key state is not same as antimask_flag
        # Also change the antimask state
        if selected_model.metadata["antimask_flag"] != self.shift_key_pressed:
            selected_model.metadata["mask"] = []
            selected_model.metadata["antimask_flag"] = not selected_model.metadata["antimask_flag"]
            #print("Switching antimask flag to",selected_model.metadata["antimask_flag"])
            # HACK
            #self.update_fitting_options()

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
            patch.set_facecolor("g" if selected_model.metadata["antimask_flag"] else "r")

        # Set the signal and the time.
        self._interactive_mask_region_signal = (
            time.time(),
            self.mpl_connect(
                "motion_notify_event", self.update_mask_region)
        )
        
        return None
    
    def update_mask_region(self, event):
        """
        Update the visible selected masked region for the selected spectral
        model. This function is linked to a callback for when the mouse position
        moves.

        :param event:
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
            self.draw()
        return None

    def spectrum_left_mouse_release(self, event):
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
            
            spectral_model = self.selected_model

            if spectral_model is None: 
                raise RuntimeError("""Must have a spectral model selected while making mask!
                                   Must have mouseover bug?""")

            # Add mask metadata.
            minx = min(xy[0,0],xy[2,0])
            maxx = max(xy[0,0],xy[2,0])
            spectral_model.metadata["mask"].append([minx,maxx])

            # Re-fit the spectral model and send to other widgets.
            spectral_model.fit()
            self.update_widgets_after_measurement_change(spectral_model)

        # Clean up interactive mask
        xy[:, 0] = np.nan
        for patch in self._lines["interactive_mask"]:
            patch.set_xy(xy)
        self.mpl_disconnect(signal_cid)
        del self._interactive_mask_region_signal
        
        self.update_spectrum_figure()
        return None

    def _remove_mask(self, selected_model, event):
        # Called upon doubleclick
        for i, (s, e) in enumerate(spectral_model.metadata["mask"][::-1]):
            if e >= event.xdata >= s:
                mask = spectral_model.metadata["mask"]
                index = len(mask) - 1 - i
                del mask[index]
                return True
        return False

    def _plot_normalized_spectrum(self, limits, extra_disp=10):
        if self.session is None: return False
        if not hasattr(self.session, "normalized_spectrum"): return False

        spectrum = self.session.normalized_spectrum
        
        try:
            # Fix the memory leak!
            #self.ax_spectrum.lines.remove(self._lines["spectrum"])
            self._lines["spectrum"].set_data([], [])
            self.ax_spectrum.collections.remove(self._lines["spectrum_fill"])
            self.ax_residual.collections.remove(self._lines["residual_fill"])
        except Exception as e:
            # TODO fail in a better way
            # print(e)
            pass

        plot_ii = np.logical_and(spectrum.dispersion > limits[0]-extra_disp,
                                 spectrum.dispersion < limits[1]+extra_disp)
        if np.sum(plot_ii)==0: # Can't plot, no points!
            return False
        
        # Draw the spectrum.
        self._lines["spectrum"].set_data(spectrum.dispersion[plot_ii], spectrum.flux[plot_ii])
        #drawstyle = self.session.setting(["plot_styles","spectrum_drawstyle"],"steps-mid")
        #self._lines["spectrum"] = self.ax_spectrum.plot(spectrum.dispersion[plot_ii],
        #    spectrum.flux[plot_ii], c="k", drawstyle=drawstyle)[0]

        # Draw the error bars.
        sigma = 1.0/np.sqrt(spectrum.ivar[plot_ii])
        self._lines["spectrum_fill"] = \
        style_utils.fill_between_steps(self.ax_spectrum, spectrum.dispersion[plot_ii],
            spectrum.flux[plot_ii] - sigma, spectrum.flux[plot_ii] + sigma, 
            facecolor="#cccccc", edgecolor="#cccccc", alpha=1)

        # Draw the error bars.
        self._lines["residual_fill"] = \
        style_utils.fill_between_steps(self.ax_residual, spectrum.dispersion[plot_ii],
            -sigma, +sigma, facecolor="#CCCCCC", edgecolor="none", alpha=1)

        three_sigma = 3*np.median(sigma[np.isfinite(sigma)])
        self.ax_residual.set_ylim(-three_sigma, three_sigma)
        
        return True
    
    def _plot_masks(self):
        selected_model = self.selected_model
        mask_color = "g" if "antimask_flag" in selected_model.metadata and \
            selected_model.metadata["antimask_flag"] else "r"
        for i, (start, end) in enumerate(selected_model.metadata["mask"]):
            try:
                patches = self._lines["model_masks"][i]

            except IndexError:
                self._lines["model_masks"].append([
                    self.ax_spectrum.axvspan(np.nan, np.nan,
                        facecolor=mask_color, edgecolor="none", alpha=0.25),
                    self.ax_residual.axvspan(np.nan, np.nan,
                        facecolor=mask_color, edgecolor="none", alpha=0.25)
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
                patch.set_facecolor(mask_color)
                patch.set_visible(True)

        # Hide unnecessary ones.
        N = len(selected_model.metadata["mask"])
        for unused_patches in self._lines["model_masks"][N:]:
            for unused_patch in unused_patches:
                unused_patch.set_visible(False)
        
        return True
        
    def _plot_model(self):
        # Hide previous model_errs
        try:
            # Note: leaks memory, but too hard to fix
            self._lines["model_yerr"].set_visible(False)
            del self._lines["model_yerr"]
        except KeyError:
            pass
        
        selected_model = self.selected_model
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

        return True
        


class SMHScatterplot(mpl.MPLWidget, SMHWidgetBase):
    """
    Refactored class to display a single scatterplot of measurements 
    and selected points.
    """
    allattrs = _allattrs
    labels = _labels
    attr2label = _attr2label
    
    def __init__(self, parent, xval, yval, session=None, widgets_to_update = [], **kwargs):
        # These are columns that you can plot
        assert xval in self.allattrs, xval
        assert yval in self.allattrs, yval

        mpl.MPLWidget.__init__(self, parent=parent, **kwargs)
        SMHWidgetBase.__init__(self, parent, session, widgets_to_update)

        self.ax = self.add_subplot(1,1,1)
        self.ax.xaxis.get_major_formatter().set_useOffset(False)
        self.ax.yaxis.set_major_locator(MaxNLocator(5))
        self.ax.yaxis.set_major_locator(MaxNLocator(4))

        self.xval = xval
        self.yval = yval

        self.ax.set_xlabel(self.attr2label[xval])
        self.ax.set_ylabel(self.attr2label[yval])

        self._lines = {
            "selected_point": [
                self.ax.scatter([], [],
                    edgecolor="b", facecolor="none", s=150, linewidth=3, zorder=2)
            ],
            "points": [
                self.ax.scatter([], [], s=30, \
                     facecolor="k", edgecolor="k", picker=PICKER_TOLERANCE, \
                     alpha=0.5)
            ],
            "trend_lines": None
        }


        self.selected_models = None
        self._xval_cache = []
        self._yval_cache = []

    def update_after_selection(self, selected_models):
        raise NotImplementedError
    def update_after_measurement_change(self, changed_model):
        raise NotImplementedError


class SMHFittingOptions(SMHWidgetBase):
    def __init__(self, parent, session=None, widgets_to_update = []):
        super(SMHFittingOptions, self).__init__(parent, session, widgets_to_update)
    def update_after_selection(self, selected_models):
        raise NotImplementedError
    def update_after_measurement_change(self, changed_model):
        raise NotImplementedError
    

class SMHMeasurementList(SMHWidgetBase):
    def __init__(self, parent, session=None, widgets_to_update = []):
        super(SMHMeasurementList, self).__init__(parent, session, widgets_to_update)
    def update_after_selection(self, selected_models):
        raise NotImplementedError
    def update_after_measurement_change(self, changed_model):
        raise NotImplementedError
    

class MeasurementTableModelBase(QtCore.QAbstractTableModel):
    """
    A table model that accesses the properties of a list of spectral models
    (calling them "measurements" here to avoid ambiguity)
    """
    allattrs = _allattrs
    attr2slabel = _attr2slabel
    attr2format = _attr2format
    
    def __init__(self, parent, session, columns, *args):
        """
        An abstract table model for accessing spectral models from the session.
        
        :param parent:
        :param session:
        :param columns:
            List of attributes in order of columns in the table.
        """
        
        super(SpectralModelsTableModelBase, self).__init__(parent, *args)
        self.verify_columns(columns)
        self.attrs = columns
        self.header = [self.attr2label[attr] for attr in self.attrs]
        
        # Normally you should never do this, but here I know "better". See:
        #http://stackoverflow.com/questions/867938/qabstractitemmodel-parent-why
        self.parent = parent 
        self.session = session
        return None
    
    def verify_columns(self, columns):
        for col in columns:
            assert col in self.allattrs
        assert len(columns) = len(np.unique(columns))
        return True

    def data(self, index, role):
        if not index.isValid():
            return None
        if role==QtCore.Qt.FontRole:
            return _QFONT
        attr = self.attrs[index.column()]
        spectral_model = self.spectral_models[index.row()]
        
        if role != QtCore.Qt.DisplayRole: return None
        
        value = getattr(spectral_model, attr, None)
        if value is None: return ""

        ## Deal with checkboxies
        if attr in ["is_acceptable","is_upper_limit","user_flag",
                    "use_for_stellar_parameter_inference",
                    "use_for_stellar_composition_inference"] \
        and role in (QtCore.Qt.DisplayRole, QtCore.Qt.CheckStateRole):
            if role == QtCore.Qt.CheckStateRole:
                return QtCore.Qt.Checked if value else QtCore.Qt.Unchecked
            else:
                return None
        
        # any specific hacks to display attrs are put in here
        # TODO the spectral model itself should decide how its own information is displayed.
        # Make a _repr_attr for every attr?
        if attr == "wavelength":
            return spectral_model._repr_wavelength
        if attr == "elements":
            return spectral_model._repr_element

        fmt = attr2format[attr]
        mystr = fmt.format(value)
        return mystr

    @property
    def spectral_models(self):
        return self.session.metadata.get("spectral_models", [])
    
    def rowCount(self, parent):
        """ Return the number of rows in the table. """
        return len(self.spectral_models)
    
    def columnCount(self, parent):
        """ Return the number of columns in the table. """
        return len(self.header)

    def headerData(self, col, orientation, role):
        if orientation == QtCore.Qt.Horizontal \
        and role == QtCore.Qt.DisplayRole:
            return self.header[col]
        return None

    def setData(self, index, value, role=QtCore.Qt.DisplayRole):
        """
        Only allow checking/unchecking of is_acceptable and user_flag
        """
        attr = self.attrs[index.column()]
        if attr not in ["is_acceptable", "user_flag"]:
            return False
        else:
            row = index.row()
            model = self.spectral_models[row]
            # value appears to be 0 or 2. Set it to True or False
            value = (value != 0)
            setattr(model, attr, value)
            
            return value

    def flags(self, index):
        if not index.isValid(): return
        return  QtCore.Qt.ItemIsSelectable|\
                QtCore.Qt.ItemIsEnabled|\
                QtCore.Qt.ItemIsUserCheckable
    
    
