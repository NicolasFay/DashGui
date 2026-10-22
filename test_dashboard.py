import sys
import can
import time
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QShortcut, QKeySequence

import AERO_Qt6_Testing as dashmod
from AERO_Qt6_Testing import (DashboardWindow, CAN_INTERFACE, CAN_CHANNEL,
                              ID_MOTOR_STATS, ID_BATTERY_STATS,
                              DRIVE_MODES, MODE_ECO, MODE_NORMAL, MODE_SPORT)

# Make the dashboard take its mode from CAN instead of the M-key test hook
dashmod.LOCAL_MODE_TEST = False

"""NOTE: Test the dashboard using special key presses that simulate different features/problems
M:  Toggle mode             Switches drive mode of the car (Normal, ECO, SPORT)
1:  Toggle motor silent     Speed, temp, throttle and mode go to “--” after the timeout. Battery keeps updating. Press again and everything recovers.
2:  Toggle battery silent   Only the SOC bar goes to “--”.
3:  Both silent	            Everything blanks.
4:  0.3 s motor gap	        Display does not blank (under the 0.5 s timeout).
5:  0.8 s motor gap	        Blanks, then recovers on its own.
6:  Malformed frame	        Worker thread dies, the error label appears, and the watchdog blanks everything.
7:  Restart worker	        Data resumes.
8:  Toggle_mode_source      Switches where the mode comes from (CAN vs test key)




"""
# (speed mph, soc %, motor temp C, throttle %, mode)
CASES = [
    (0,   100,   0,   0, MODE_NORMAL),
    (30,   72,  85,  40, MODE_ECO),
    (65,   50, 120, 100, MODE_SPORT),
    (99,    1,  25,   5, MODE_NORMAL),
    (0,     0,   0,   0, MODE_ECO),
    (10,   50,  40,  10, 7),            # invalid mode -> should show "--"
]


def send(bus, speed, soc, temp, throttle, mode, motor=True, battery=True):
    if motor:

        raw = int(round(speed * 10))
        bus.send(can.Message(arbitration_id=ID_MOTOR_STATS,
                         data=[raw >> 8, raw & 0xFF, temp, throttle, mode],
                         is_extended_id=False))
    if battery:
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
    #app.aboutToQuit.connect(bus.shutdown)

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

    def cleanup():
        sweep_timer.stop()
        bus.shutdown()

    def tick():
        t = state["t"]
        speed = 60 * tri(t, 10)                 # 0-60 mph, 10 s cycle
        soc = int(100 - (t * 2) % 101)          # drains 100 -> 0, then wraps
        temp = int(20 + 90 * tri(t, 20))        # 20-110 C, 20 s cycle
        throttle = int(100 * tri(t, 6))         # 0-100 %, 6 s cycle
        mode = MODE_ORDER[int(t // 5) % len(MODE_ORDER)]   # new mode every 5 s
        send(bus, speed, soc, temp, throttle, mode, 
             motor=not silent("motor_until"), 
             battery= not silent("battery_until"))
        state["t"] += 0.05

    def start_sweep():
        dashmod.LOCAL_MODE_TEST = True # allows M key to work
        sweep_timer.timeout.connect(tick)
        sweep_timer.start(50)

        # ---------- Fault injection (keys 1-7, active during the sweep) ----------
    faults = {"motor_until": 0.0, "battery_until": 0.0}

    def silent(name):
        return time.monotonic() < faults[name]

    def toggle(name):
        faults[name] = 0.0 if silent(name) else float("inf")
        print(f"[FAULT] {name}: {'SILENT' if silent(name) else 'sending again'}")

    def drop(name, seconds):
        faults[name] = time.monotonic() + seconds
        print(f"[FAULT] {name}: dropping for {seconds}s")

    def send_malformed():
        print("[FAULT] sending 2-byte motor frame (expects 5)")
        bus.send(can.Message(arbitration_id=ID_MOTOR_STATS,
                             data=[0x01, 0x02], is_extended_id=False))

    def toggle_mode_source():
        dashmod.LOCAL_MODE_TEST = not dashmod.LOCAL_MODE_TEST
        print(f"[TEST] mode source: {'M key' if dashmod.LOCAL_MODE_TEST else 'CAN'}")

    def restart_worker():
        if dash.worker.isRunning():
            print("[FAULT] worker already running")
        else:
            print("[FAULT] restarting worker thread")
            dash.worker.start()

    KEYS = {
        "1": lambda: toggle("motor_until"),          # motor goes silent / returns
        "2": lambda: toggle("battery_until"),        # battery goes silent / returns
        "3": lambda: (toggle("motor_until"), toggle("battery_until")),
        "4": lambda: drop("motor_until", 0.3),       # short gap, should NOT blank
        "5": lambda: drop("motor_until", 0.8),       # long gap, should blank, then recover
        "6": send_malformed,                         # kills the worker thread
        "7": restart_worker,
        "8": toggle_mode_source
    }
    for key, fn in KEYS.items():
        QShortcut(QKeySequence(key), dash).activated.connect(fn)

    # Give the worker thread time to open its bus before sending
    app.aboutToQuit.connect(cleanup)
    QTimer.singleShot(500, lambda: step(0))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()