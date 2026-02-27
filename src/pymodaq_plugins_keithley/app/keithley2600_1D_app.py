import numpy as np
from qtpy import QtWidgets

from pymodaq_gui.utils.custom_app import CustomApp
from pymodaq_gui.utils.dock import Dock, DockArea
from pymodaq_gui.utils.widgets import SpinBox
from pymodaq_gui.parameter import Parameter
from pymodaq_gui.managers.parameter_manager import ParameterManager
from pymodaq_gui.plotting.data_viewers.viewer1D import Viewer1D, DataToExport, DataWithAxes
from pymodaq.control_modules.daq_viewer import DAQ_Viewer, DAQ_Viewer_UI, DAQTypesEnum
from pymodaq.control_modules.daq_move import DAQ_Move
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


class KeithleySourcemeter1DApp(CustomApp):

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

        # Set initial device properties
        controller_ID = 1
        move_settings = self.move.settings.child("move_settings")
        move_settings.child("multiaxes")["multi_status"] = "Slave"
        move_settings.child("multiaxes")["controller_ID"] = controller_ID
        move_settings["channel"] = "B"
        daq_settings = self.daq.settings.child("detector_settings")
        daq_settings["controller_status"] = "Master"
        daq_settings["controller_ID"] = controller_ID
        daq_settings["channel"] = "A"

        # Initialize DAQ Viewer (master)
        self.daq.init_hardware_ui(True)
        QtWidgets.QApplication.processEvents()

        # Dirty patch to retrieve controller and apply it to DAQ move
        while not self.daq.controller:
            QtWidgets.QApplication.processEvents()
        self.move.controller = self.daq.controller 

        # Initialize DAQ Move (slave)
        self.move.init_hardware_ui(True)
        QtWidgets.QApplication.processEvents()


    def setup_docks(self):

        # Hidden area with DAQ move and DAQ viewer
        daq_dockarea = DockArea()
        daq_window = QtWidgets.QMainWindow()
        daq_window.setCentralWidget(daq_dockarea)

        # Hidden DAQ viewer
        self.daq = DAQ_Viewer(daq_dockarea, "DAQ window")
        self.daq.daq_type = DAQTypesEnum.DAQ1D
        QtWidgets.QApplication.processEvents()
        self.daq.detector = "Keithley2600"

        # Hidden DAQ move
        self.move = DAQ_Move(self, "DAQ move")
        QtWidgets.QApplication.processEvents()
        self.move.actuator = "Keithley2600"

        # Controls for DAQ Move
        self.move_controls = self.move.ui.move_toolbar
        self.move_controls.setVisible(True)
        move_controls_dock = self.docks["move_settings"] = Dock("Source settings")
        move_controls_dock.addWidget(self.move_controls)
        move_controls_dock.setStretch(x=2, y=1)
        self.dockarea.addDock(move_controls_dock, "left")

        # Controls for DAQ Viewer
        self.daq_controls = self.daq.ui._detector_widget
        self.daq_controls.setVisible(True)
        daq_controls_dock = self.docks["acquisition_settings"] = Dock("DAQ settings")
        daq_controls_dock.addWidget(self.daq_controls)
        daq_controls_dock.setStretch(x=2, y=2)
        self.dockarea.addDock(daq_controls_dock, "bottom", move_controls_dock)

        # Device (and sweep) settings
        params_dock = self.docks["parameters"] = Dock("Device settings")
        params_dock.addWidget(self.daq.settings_tree)
        params_dock.setStretch(x=2, y=10)
        self.dockarea.addDock(params_dock, "bottom", daq_controls_dock)

        # Save settings
        save_dock = self.docks["save"] = Dock("Save settings")
        save_dock.addWidget(self.settings_tree)
        save_dock.setStretch(x=2, y=4)
        self.dockarea.addDock(save_dock, "bottom", params_dock)

        # Visible 1D Viewer
        self.viewer = Viewer1D(QtWidgets.QWidget())
        viewer_dock = self.docks["viewer"] = Dock("I-V characteristic")
        viewer_dock.addWidget(self.viewer.parent)
        viewer_dock.setStretch(x=10)
        self.dockarea.addDock(viewer_dock, "right")


    def setup_actions(self):

        # Snap button
        self.add_action("snap", "Snap Data", "snap", "Click to get one data shot")

        # Waiting time spinbox
        wait_time_param = self.daq.settings.child("main_settings").child("wait_time")
        wait_time_widget = SpinBox()
        wait_time_widget.setValue(wait_time_param.value())
        wait_time_widget.valueChanged.connect(lambda new_val: wait_time_param.setValue(new_val))
        wait_time_widget.setMaximumWidth(100)
        self.add_widget("wait_label", QtWidgets.QLabel("Wait time [ms]:"))
        self.add_widget("wait_time", wait_time_widget, tip="Waiting time between subsequent measurements")

        # Grab button
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

        # Save data in tab-separated text format (except when initializing)
        if not self.first_run:

            # Retrieve detector settings
            daq_settings = self.daq.settings.child("detector_settings") 

            # Retrieve measurement start and end timestamps from detector settings
            meas_start = daq_settings["meas_start"].toPython()
            meas_end = daq_settings["meas_end"].toPython()

            # Retrieve idle polarization voltage from detector settings
            idle_pol_on = daq_settings["idle_pol_on"]
            idle_pol_v = daq_settings["idle_pol_v"] if idle_pol_on else 0

            # Set header: measurement start/end, sample name, column names, polarization voltage
            header = ""
            header += f"Start\t{meas_start.isoformat()}\n"
            header += f"End\t{meas_end.isoformat()}\n"
            header += f"Sample\t{sample}\n"
            header += f"Polarization voltage after scan [V]\t{idle_pol_v}\n"
            header += f"\n"
            header += f"Voltage [V]\tCurrent [A]"

            # Set filename
            dt_file = meas_end.strftime("%Y-%m-%d_%H-%M-%S")
            save_file = pathlib.Path(path) / f"IVcurve_{dt_file}_{sample}.txt"

            # Set data
            x = self.data.axes[0].get_data()
            y = self.data[0]
            export_data = np.column_stack((x, y))

            # Write file
            np.savetxt(save_file, export_data, fmt="%.6e", header=header, comments="#")

        # Reset first run flag
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
    myapp = KeithleySourcemeter1DApp(area)
    win.show()
    app.exec()

if __name__ == '__main__':
    main()
