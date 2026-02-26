import numpy as np
from qtpy import QtWidgets

from pymodaq_gui.utils.custom_app import CustomApp
from pymodaq_gui.utils.dock import Dock, DockArea
from pymodaq_gui.parameter import Parameter
from pymodaq_gui.managers.parameter_manager import ParameterManager
from pymodaq_gui.plotting.data_viewers.viewer1D import Viewer1D, DataToExport, DataWithAxes
from pymodaq.control_modules.daq_viewer import DAQ_Viewer, DAQ_Viewer_UI, DAQTypesEnum
from pymodaq_utils.config import Config

import datetime
import pathlib

config = Config()


def _build_param(name, title, type, value, limits=None, unit=None, **kwargs):
    params = {}
    params["name"] = name
    params["title"] = title
    params["type"] = type
    params["value"] = value
    if limits is not None:
        params["limits"] = limits
    if unit is not None:
        params["suffix"] = unit
        params["siPrefix"] = True
    for argn, argv in kwargs.items():
        params[argn] = argv
    return params


class KeithleySourcemeterApp(CustomApp):


    # Global parameters
    params = [_build_param("save_path", "Save location", "browsepath", 
                           config("data_saving", "h5file", "save_path"), filetype=False),
              _build_param("sample_name", "Sample name", "str", "SampleName"),
             ]


    def __init__(self, parent):
        super().__init__(parent)

        # Init variables
        self.daq: DAQ_Viewer = None
        self.daq_settings: QtWidgets.QWidget = None
        self.viewer: Viewer1D = None
        self.first_run = True

        # Create UI
        self.setup_ui()


    def setup_docks(self):

        # Hidden DAQ Viewer
        daq_dockarea = DockArea()
        daq_window = QtWidgets.QMainWindow()
        daq_window.setCentralWidget(daq_dockarea)
        self.daq = DAQ_Viewer(daq_dockarea, "DAQ window")
        self.daq.daq_type = DAQTypesEnum.DAQ1D
        QtWidgets.QApplication.processEvents()
        self.daq.detector = "Keithley2600"
        self.daq.init_hardware_ui(True)
        QtWidgets.QApplication.processEvents()

        # Settings for DAQ Viewer
        self.daq_settings = self.daq.ui._detector_widget
        self.daq_settings.setVisible(True)
        daq_settings_dock = self.docks["acquisition_settings"] = Dock("DAQ settings")
        daq_settings_dock.addWidget(self.daq_settings)
        daq_settings_dock.setStretch(y=0.05)
        self.dockarea.addDock(daq_settings_dock, "left")

        # Device (and sweep) settings
        params_dock = self.docks["parameters"] = Dock("Device settings")
        params_dock.addWidget(self.daq.settings_tree)
        self.dockarea.addDock(params_dock, "bottom", daq_settings_dock)

        # Save settings
        save_dock = self.docks["save"] = Dock("Save settings")
        save_dock.addWidget(self.settings_tree)
        self.dockarea.addDock(save_dock, "bottom", params_dock)

        # Visible 1D Viewer
        self.viewer = Viewer1D(QtWidgets.QWidget())
        viewer_dock = self.docks["viewer"] = Dock("I-V characteristic")
        viewer_dock.addWidget(self.viewer.parent)
        self.dockarea.addDock(viewer_dock, "right")


    def setup_actions(self):
        self.add_action("snap", "Snap Data", "snap", "Click to get one data shot")
        self.add_action("grab", "Grab Data", "run_all", "Click to continuously get data", checkable=True)


    def connect_things(self):

        # Menu actions
        self.connect_action("snap", self.daq.snap)
        self.connect_action("grab", self.daq.grab)

        # DAQ Viewer data emission
        self.daq.grab_done_signal.connect(self.show_and_save)


    def show_and_save(self, dte: DataToExport):
        self.data = dte[0].deepcopy()

        # Retrieve parameters
        sample = self.settings["sample_name"]
        path = self.settings["save_path"]

        # Save data in tab-separated text format
        if not self.first_run:
            now = datetime.datetime.now()
            now_file = now.strftime("%Y-%m-%d_%H-%M-%S")
            now_iso = now.isoformat()
            save_file = pathlib.Path(path) / f"IVcurve_{now_file}_{sample}.txt"
            x = self.data.axes[0].get_data()
            y = self.data[0]
            export_data = np.column_stack((x, y))
            header = f"{now_iso}\t{sample}\nVoltage [V]\tCurrent [A]"
            np.savetxt(save_file, export_data, fmt="%.6e", header=header, comments="#")
        self.first_run = False

        # Update viewer
        self.viewer.show_data(self.data)


    def value_changed(self, param: Parameter):
        """Apply the consequences of a change of value in the settings.

        Parameters
        ----------
        param: Parameter
            A given parameter (within detector_settings) whose value has been changed by the user
        """
        # Dispatch arguments
        name = param.name()
        val = param.value()
        unit = param.opts.get("suffix")
        qty = Q_(val, unit)

        # No parameters
        pass


def main():
    from pymodaq_gui.utils.utils import mkQApp
    from pymodaq_gui.utils.dock import DockArea
    import numpy as np

    # Create and execute app
    app = mkQApp("Keithley sourcemeter acquisition")
    area = DockArea()
    win = QtWidgets.QMainWindow()
    win.setCentralWidget(area)
    myapp = KeithleySourcemeterApp(area)
    win.show()
    app.exec()

if __name__ == '__main__':
    main()
