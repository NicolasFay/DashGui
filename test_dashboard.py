import sys
import can
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

import AERO_Qt6_Testing as dashmod
from AERO_Qt6_Testing import (DashboardWindow, CAN_INTERFACE, CAN_CHANNEL,
                              ID_MOTOR_STATS, ID_BATTERY_STATS,
                              DRIVE_MODES, MODE_ECO, MODE_NORMAL, MODE_SPORT)

# Make the dashboard take its mode from CAN instead of the M-key test hook
dashmod.LOCAL_MODE_TEST = False

# (speed mph, soc %, motor temp C, throttle %, mode)
CASES = [
    (0,   100,   0,   0, MODE_NORMAL),
    (30,   72,  85,  40, MODE_ECO),
    (65,   50, 120, 100, MODE_SPORT),
    (99,    1,  25,   5, MODE_NORMAL),
    (0,     0,   0,   0, MODE_ECO),
    (10,   50,  40,  10, 7),            # invalid mode -> should show "--"
]


def send(bus, speed, soc, temp, throttle, mode):
    raw = int(round(speed * 10))
    bus.send(can.Message(arbitration_id=ID_MOTOR_STATS,
                         data=[raw >> 8, raw & 0xFF, temp, throttle, mode],
                         is_extended_id=False))
    bus.send(can.Message(arbitration_id=ID_BATTERY_STATS,
                         data=[soc], is_extended_id=False))


def tri(t, period):
    """Triangle wave 0 -> 1 -> 0 over `period` seconds."""
    x = (t % period) / period
    return 1 - abs(2 * x - 1)


def main():
    app = QApplication(sys.argv)
    dash = DashboardWindow()
    dash.show()

    bus = can.interface.Bus(interface=CAN_INTERFACE, channel=CAN_CHANNEL)
    app.aboutToQuit.connect(bus.shutdown)

    failures = []

    # ---------- Phase 1: automated checks ----------
    def check(i):
        speed, soc, temp, throttle, mode = CASES[i]
        raw = int(round(speed * 10))
        mode_text, mode_color = DRIVE_MODES.get(mode, ("--", "#8A8A9F"))
        expected = {
            "speed": f"{raw * 0.1:.0f}",
            "soc": soc,
            "temp": f"{temp}°C",
            "throttle": f"{throttle}%",
            "mode": mode_text,
            "mode_color": True,
        }
        actual = {
            "speed": dash.lbl_speed_val.text(),
            "soc": dash.progress_soc.value(),
            "temp": dash.lbl_temp_val.text(),
            "throttle": dash.throttle_value.text(),
            "mode": dash.mode_value.text(),
            "mode_color": f"color: {mode_color};" in dash.mode_value.styleSheet(),
        }
        ok = expected == actual
        print(f"[{'PASS' if ok else 'FAIL'}] case {i}: sent {CASES[i]}")
        if not ok:
            failures.append(i)
            print(f"        expected {expected}\n        got      {actual}")
        step(i + 1)

    def step(i):
        if i == len(CASES):
            print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} FAILED'}")
            print("Starting visual sweep (close the window to quit)...")
            start_sweep()
            return
        send(bus, *CASES[i])
        QTimer.singleShot(200, lambda: check(i))

    # ---------- Phase 2: continuous sweep for eyeballing ----------
    sweep_timer = QTimer()
    state = {"t": 0.0}
    MODE_ORDER = [MODE_ECO, MODE_NORMAL, MODE_SPORT]

    def tick():
        t = state["t"]
        speed = 60 * tri(t, 10)                 # 0-60 mph, 10 s cycle
        soc = int(100 - (t * 2) % 101)          # drains 100 -> 0, then wraps
        temp = int(20 + 90 * tri(t, 20))        # 20-110 C, 20 s cycle
        throttle = int(100 * tri(t, 6))         # 0-100 %, 6 s cycle
        mode = MODE_ORDER[int(t // 5) % len(MODE_ORDER)]   # new mode every 5 s
        send(bus, speed, soc, temp, throttle, mode)
        state["t"] += 0.05

    def start_sweep():
        sweep_timer.timeout.connect(tick)
        sweep_timer.start(50)

    # Give the worker thread time to open its bus before sending
    QTimer.singleShot(500, lambda: step(0))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()