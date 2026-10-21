import sys
import can
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget,
                             QLabel, QProgressBar, QVBoxLayout, QHBoxLayout)
from PyQt6.QtGui import QFont
import time

# CAN bus configuration
# 'virtual' is python-can's in-process test bus; swap for 'socketcan' (and a
# real channel like 'can0') when running on the vehicle hardware.
CAN_INTERFACE = 'virtual'
CAN_CHANNEL = 'dashboard_test'

'''
TODO: Find out how often the motor controller and BMS actually send 0x100 and 0x101. 
values are placeholders, and the timeout should be roughly 
3-5x the real period so one dropped frame doesnt blank the display.
'''

# Arbitration IDs of the messages this dashboard listens for
ID_MOTOR_STATS = 0x100
ID_BATTERY_STATS = 0x101

MOTOR_TIMEOUT_S = 0.5     # placeholder
BATTERY_TIMEOUT_S = 2.0   # placeholder

# Drive modes: value -> (label, color)
# The numeric values are what arrives on the bus; the tuple is what we display.
MODE_ECO, MODE_NORMAL, MODE_SPORT = 0, 1, 2
DRIVE_MODES = {
    MODE_ECO:    ("ECO",    "#55FF88"),
    MODE_NORMAL: ("NORMAL", "#FFFFFF"),
    MODE_SPORT:  ("SPORT",  "#FF5555"),
}

COLOR_TITLE = "#8A8A9F"
COLOR_MUTED = "#707080"
COLOR_THERMAL = "#FF5555"


# While testing on the virtual bus, press M to cycle modes locally.
# Set to False once the real mode comes in over CAN.
LOCAL_MODE_TEST = True


class CANDashboardWorker(QThread):
    """Background thread that reads CAN frames and forwards decoded values.
 
    CAN reads block, so they run off the GUI thread. The worker never touches
    widgets directly; it only emits signals, which Qt delivers safely to the
    GUI thread.
    """

    motor_updated = pyqtSignal(float, int, int, int)   # speed, temp, throttle, mode
    battery_updated = pyqtSignal(int)                  # soc
    error_raised = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = False

    def run(self):
        self.running = True
        bus = None
        try:
            bus = can.interface.Bus(interface=CAN_INTERFACE, channel=CAN_CHANNEL, bitrate=500000)

            while self.running:
                # Short timeout so the loop can notice running=False quickly
                message = bus.recv(timeout=0.05)
                if message is None:
                    continue

                # Process the received CAN message based on its arbitration ID
                if message.arbitration_id == ID_MOTOR_STATS:
                    # speed is two bytes combined into one 16-bit number and scaled by 0.1
                    speed = ((message.data[0] << 8) | message.data[1]) * 0.1
                    self.motor_updated.emit(speed, message.data[2], message.data[3], message.data[4])
                elif message.arbitration_id == ID_BATTERY_STATS:
                    self.battery_updated.emit(message.data[0])

        except Exception as e:
            # Any failure (bus won't open, bad frame, etc.) ends the thread
            # and is reported to the GUI as a string.
            self.error_raised.emit(f"CAN Interface Error: {str(e)}")
        finally:
            if bus:
                bus.shutdown()

    def stop(self):
        self.running = False
        self.wait()


class DashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.mode = MODE_NORMAL
        self.init_ui()
        self.set_mode(self.mode)
        self.show_motor_no_data()
        self.show_battery_no_data()

        self.last_motor_rx = None # None being no message has been received yet, good for startup
        self.last_battery_rx = None
        self.motor_stale = True # flags to indicate if the last message is stale
        self.battery_stale = True

        self.watchdog_timer = QTimer(self) # timer to check for stale messages
        self.watchdog_timer.timeout.connect(self.check_staleness)
        self.watchdog_timer.start(100)    # check 10x per second

        self.worker = CANDashboardWorker() # Worker Thread
        self.worker.motor_updated.connect(self.handle_motor)
        self.worker.battery_updated.connect(self.handle_battery)
        self.worker.error_raised.connect(self.handle_error)
        self.worker.start()

    def init_ui(self):
        self.setWindowTitle("EV Digital Instrument Cluster")
        self.setFixedSize(480, 320)

        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(40, 20, 40, 30)

        # ---- Top row: speedometer (center) + drive mode (right) ----
        top_row = QHBoxLayout()

        # build individual blocks
        speed_layout = self.build_speed_block()
        mode_block = self.build_mode_block()

        # add them to the top row with stretch factors to control sizing
        top_row.addStretch(1)
        top_row.addLayout(speed_layout, stretch=3)
        top_row.addLayout(mode_block, stretch=1)

        # add top row to main layout
        main_layout.addLayout(top_row)
        main_layout.addSpacing(20)

        # ---- Bottom row: battery, temp, throttle ----
        bottom_layout = QHBoxLayout()

        # Build individual blocks
        thermal_block = self.build_thermal_block()
        battery_block = self.build_battery_block()
        throttle_block = self.build_throttle_block()

        # add them all to bottom_layout with style
        bottom_layout.addLayout(battery_block, stretch=3)
        bottom_layout.addSpacing(50)
        bottom_layout.addLayout(thermal_block, stretch=1)
        bottom_layout.addLayout(throttle_block, stretch=1)

        # add bottom row to main layout
        main_layout.addLayout(bottom_layout)
        self.setCentralWidget(central_widget)

    def set_mode(self, mode):
        """Show the given drive mode; unknown values display as a grey '--'."""
        text, color = DRIVE_MODES.get(mode, ("--", "#8A8A9F"))
        self.mode = mode
        self.mode_value.setText(text)
        self.mode_value.setStyleSheet(f"color: {color};")

    @pyqtSlot(float, int, int, int)
    def handle_motor(self, speed, temp, throttle, mode):
        """Runs in the GUI thread whenever the worker emits new motor telemetry."""
        # Watchdog Flags
        self.last_motor_rx = time.monotonic() # update the last received time for motor stats
        self.motor_stale = False # reset the stale flag since we just received a message
        # Updating GUI
        self.lbl_speed_val.setText(f"{speed:.0f}")
        self.lbl_temp_val.setText(f"{temp}°C")
        self.lbl_temp_val.setStyleSheet("color: " + COLOR_THERMAL + ";")
        self.throttle_value.setText(f"{throttle}%")
        # In local test mode the M key owns the mode display, so ignore CAN's
        if not LOCAL_MODE_TEST and mode != self.mode:
            self.set_mode(mode)

    @pyqtSlot(int)
    def handle_battery(self, soc):
        """Runs in the GUI thread whenever the worker emits new battery telemetry."""
        # Watchdog Flags
        self.last_battery_rx = time.monotonic() # update the last received time for battery stats
        self.battery_stale = False # reset the stale flag since we just received a message
        # Updating GUI
        self.progress_soc.setFormat("%p%") # resets the format to percentage
        self.progress_soc.setValue(soc)

    @pyqtSlot(str)
    def handle_error(self, err_msg):
        """Worker reported a failure; for now just log it to stderr."""
        print(f"[CRITICAL] {err_msg}", file=sys.stderr)

    def keyPressEvent(self, event):
        """Test hook: M cycles ECO -> NORMAL -> SPORT while LOCAL_MODE_TEST is on."""
        if LOCAL_MODE_TEST and event.key() == Qt.Key.Key_M:
            self.set_mode((self.mode + 1) % len(DRIVE_MODES))
        else:
            super().keyPressEvent(event) # let Qt handle all other keys

    def closeEvent(self, event):
        """Stop the CAN thread cleanly before the window closes."""
        self.worker.stop()
        event.accept()

    def check_staleness(self):
        now = time.monotonic()

        # motor_stale is True if the last motor message was received more than MOTOR_TIMEOUT_S seconds ago
        motor_timed_out = (self.last_motor_rx is None or
                    now - self.last_motor_rx > MOTOR_TIMEOUT_S)
        if motor_timed_out and not self.motor_stale:
            self.motor_stale = True
            self.show_motor_no_data()

        # same for battery_stale
        battery_timed_out = (self.last_battery_rx is None or
                            now - self.last_battery_rx > BATTERY_TIMEOUT_S)
        if battery_timed_out and not self.battery_stale:
            self.battery_stale = True
            self.show_battery_no_data()

    #----------------- UI Block Builders -----------------
    def build_speed_block(self):
        speed_layout = QVBoxLayout()
        self.lbl_speed_val = QLabel("0")
        self.lbl_speed_val.setFont(QFont("sans-serif", 90, QFont.Weight.Bold))
        self.lbl_speed_val.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_speed_unit = QLabel("MPH")
        lbl_speed_unit.setFont(QFont("sans-serif", 16))
        lbl_speed_unit.setStyleSheet("color: " + COLOR_MUTED + ";")
        lbl_speed_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)

        speed_layout.addWidget(self.lbl_speed_val)
        speed_layout.addWidget(lbl_speed_unit)
        return speed_layout

    def build_mode_block(self):
        mode_block = QVBoxLayout()
        mode_block.addStretch(1)
        mode_title = QLabel("MODE")
        mode_title.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
        mode_title.setStyleSheet("color: " + COLOR_TITLE + ";")
        mode_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.mode_value = QLabel("NORMAL")
        self.mode_value.setFont(QFont("sans-serif", 16, QFont.Weight.Bold))
        self.mode_value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mode_block.addWidget(mode_title)
        mode_block.addWidget(self.mode_value)
        mode_block.addStretch(1)
        return mode_block

    def build_battery_block(self):
        battery_block = QVBoxLayout()
        lbl_bat = QLabel("BATTERY PACK STATE OF CHARGE")
        lbl_bat.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
        lbl_bat.setStyleSheet("color: " + COLOR_TITLE + ";")

        self.progress_soc = QProgressBar()
        self.progress_soc.setRange(0, 100)
        self.progress_soc.setValue(100)

        battery_block.addWidget(lbl_bat)
        battery_block.addWidget(self.progress_soc)
        return battery_block

    def build_thermal_block(self):
        thermal_block = QVBoxLayout()
        lbl_temp_title = QLabel("MOTOR TEMP")
        lbl_temp_title.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
        lbl_temp_title.setStyleSheet("color: " + COLOR_TITLE + ";")

        self.lbl_temp_val = QLabel("0°C")
        self.lbl_temp_val.setFont(QFont("sans-serif", 23, QFont.Weight.Bold))
        self.lbl_temp_val.setStyleSheet("color: " + COLOR_THERMAL + ";")

        thermal_block.addWidget(lbl_temp_title)
        thermal_block.addWidget(self.lbl_temp_val)
        return thermal_block

    def build_throttle_block(self):
        throttle_block = QVBoxLayout()
        throttle_title = QLabel("CURRENT THROTTLE")
        throttle_title.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
        throttle_title.setStyleSheet("color: " + COLOR_TITLE + ";")

        self.throttle_value = QLabel("0%")
        self.throttle_value.setFont(QFont("sans-serif", 23, QFont.Weight.Bold))
        self.throttle_value.setStyleSheet("color: " + COLOR_MUTED + ";")

        throttle_block.addWidget(throttle_title)
        throttle_block.addWidget(self.throttle_value)
        return throttle_block
    
    #----------------- No Data Handlers -----------------
    def show_motor_no_data(self):
        self.lbl_speed_val.setText("--")
        self.lbl_temp_val.setText("--°C")
        self.lbl_temp_val.setStyleSheet("color: " + COLOR_MUTED + ";")
        self.throttle_value.setText("--%")
        self.set_mode(-1) # unknown mode, shows "--" in grey

    def show_battery_no_data(self):
        self.progress_soc.setValue(0)
        self.progress_soc.setFormat("--")
        #self.progress_soc.setTextVisible(True)
        #self.progress_soc.setStyleSheet("color: " + COLOR_MUTED + ";")
        



if __name__ == '__main__':
    app = QApplication(sys.argv)
    dash = DashboardWindow()
    dash.show()
    sys.exit(app.exec())
