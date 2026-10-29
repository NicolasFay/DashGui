import os
import socket

def sd_notify(msg: str) -> bool:
    """Send a status string to systemd. Silently does nothing outside systemd."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    if addr[0] == "@":                 # abstract socket
        addr = "\0" + addr[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(addr)
            s.sendall(msg.encode())
        return True
    except OSError:
        return False

def watchdog_interval_ms(default=500) -> int:
    """Ping at half the configured WatchdogSec, as systemd recommends."""
    usec = os.environ.get("WATCHDOG_USEC")
    return int(usec) // 2000 if usec else default