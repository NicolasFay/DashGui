import sys
import can
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot, Qt
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget,
                             QLabel, QProgressBar, QVBoxLayout, QHBoxLayout)
from PyQt6.QtGui import QFont

CAN_INTERFACE = 'virtual'
CAN_CHANNEL = 'dashboard_test'

ID_MOTOR_STATS = 0x100
ID_BATTERY_STATS = 0x101

# Drive modes: value -> (label, color)
MODE_ECO, MODE_NORMAL, MODE_SPORT = 0, 1, 2
DRIVE_MODES = {
    MODE_ECO:    ("ECO",    "#55FF88"),
    MODE_NORMAL: ("NORMAL", "#FFFFFF"),
    MODE_SPORT:  ("SPORT",  "#FF5555"),
}

# While testing on the virtual bus, press M to cycle modes locally.
# Set to False once the real mode comes in over CAN.
LOCAL_MODE_TEST = True


class CANDashboardWorker(QThread):
    # (Speed, SOC, Temp, Throttle, Mode)
    telemetry_updated = pyqtSignal(float, int, int, int, int)
    error_raised = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.running = False

    def run(self):
        self.running = True
        bus = None
        try:
            bus = can.interface.Bus(interface=CAN_INTERFACE, channel=CAN_CHANNEL, bitrate=500000)

            current_speed = 0.0
            current_soc = 100
            current_temp = 0
            current_throttle = 0
            current_mode = MODE_NORMAL

            while self.running:
                message = bus.recv(timeout=0.05)
                if message is None:
                    continue

                if message.arbitration_id == ID_MOTOR_STATS:
                    raw_speed = (message.data[0] << 8) | message.data[1]
                    current_speed = raw_speed * 0.1
                    current_temp = message.data[2]
                    current_throttle = message.data[3]
                    current_mode = message.data[4]       #placeholder: 0=ECO, 1=NORMAL, 2=SPORT

                elif message.arbitration_id == ID_BATTERY_STATS:
                    current_soc = message.data[0]

                self.telemetry_updated.emit(current_speed, current_soc, current_temp,
                                            current_throttle, current_mode)

        except Exception as e:
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

        self.worker = CANDashboardWorker()
        self.worker.telemetry_updated.connect(self.handle_telemetry)
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

        speed_layout = QVBoxLayout()
        self.lbl_speed_val = QLabel("0")
        self.lbl_speed_val.setFont(QFont("sans-serif", 90, QFont.Weight.Bold))
        self.lbl_speed_val.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_speed_unit = QLabel("MPH")
        lbl_speed_unit.setFont(QFont("sans-serif", 16))
        lbl_speed_unit.setStyleSheet("color: #707080;")
        lbl_speed_unit.setAlignment(Qt.AlignmentFlag.AlignCenter)

        speed_layout.addWidget(self.lbl_speed_val)
        speed_layout.addWidget(lbl_speed_unit)

        mode_block = QVBoxLayout()
        mode_block.addStretch(1)
        mode_title = QLabel("MODE")
        mode_title.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
        mode_title.setStyleSheet("color: #8A8A9F;")
        mode_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.mode_value = QLabel("NORMAL")
        self.mode_value.setFont(QFont("sans-serif", 16, QFont.Weight.Bold))
        self.mode_value.setAlignment(Qt.AlignmentFlag.AlignCenter)

        mode_block.addWidget(mode_title)
        mode_block.addWidget(self.mode_value)
        mode_block.addStretch(1)

        top_row.addStretch(1)
        top_row.addLayout(speed_layout, stretch=3)
        top_row.addLayout(mode_block, stretch=1)
        main_layout.addLayout(top_row)

        main_layout.addSpacing(20)

        # ---- Bottom row: battery, temp, throttle ----
        bottom_layout = QHBoxLayout()

        battery_block = QVBoxLayout()
        lbl_bat = QLabel("BATTERY PACK STATE OF CHARGE")
        lbl_bat.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
        lbl_bat.setStyleSheet("color: #8A8A9F;")

        self.progress_soc = QProgressBar()
        self.progress_soc.setRange(0, 100)
        self.progress_soc.setValue(100)

        battery_block.addWidget(lbl_bat)
        battery_block.addWidget(self.progress_soc)
        bottom_layout.addLayout(battery_block, stretch=3)

        bottom_layout.addSpacing(50)

        thermal_block = QVBoxLayout()
        lbl_temp_title = QLabel("MOTOR TEMP")
        lbl_temp_title.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
        lbl_temp_title.setStyleSheet("color: #8A8A9F;")

        self.lbl_temp_val = QLabel("0°C")
        self.lbl_temp_val.setFont(QFont("sans-serif", 23, QFont.Weight.Bold))
        self.lbl_temp_val.setStyleSheet("color: #FF5555;")

        thermal_block.addWidget(lbl_temp_title)
        thermal_block.addWidget(self.lbl_temp_val)
        bottom_layout.addLayout(thermal_block, stretch=1)

        throttle_block = QVBoxLayout()
        throttle_title = QLabel("CURRENT THROTTLE")
        throttle_title.setFont(QFont("sans-serif", 9, QFont.Weight.Bold))
        throttle_title.setStyleSheet("color: #8A8A9F;")

        self.throttle_value = QLabel("0%")
        self.throttle_value.setFont(QFont("sans-serif", 23, QFont.Weight.Bold))
        self.throttle_value.setStyleSheet("color: #707080;")

        throttle_block.addWidget(throttle_title)
        throttle_block.addWidget(self.throttle_value)
        bottom_layout.addLayout(throttle_block, stretch=1)

        main_layout.addLayout(bottom_layout)
        self.setCentralWidget(central_widget)

    def set_mode(self, mode):
        text, color = DRIVE_MODES.get(mode, ("--", "#8A8A9F"))
        self.mode = mode
        self.mode_value.setText(text)
        self.mode_value.setStyleSheet(f"color: {color};")

    @pyqtSlot(float, int, int, int, int)
    def handle_telemetry(self, speed, soc, temp, throttle, mode):
        self.lbl_speed_val.setText(f"{speed:.0f}")
        self.progress_soc.setValue(soc)
        self.lbl_temp_val.setText(f"{temp}°C")
        self.throttle_value.setText(f"{throttle}%")
        if not LOCAL_MODE_TEST and mode != self.mode:
            self.set_mode(mode)

    @pyqtSlot(str)
    def handle_error(self, err_msg):
        print(f"[CRITICAL] {err_msg}", file=sys.stderr)

    def keyPressEvent(self, event):
        if LOCAL_MODE_TEST and event.key() == Qt.Key.Key_M:
            self.set_mode((self.mode + 1) % len(DRIVE_MODES))
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.worker.stop()
        event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    dash = DashboardWindow()
    dash.show()
    sys.exit(app.exec())