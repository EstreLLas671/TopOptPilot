"""Authenticated loopback sidecar launched by the Tauri desktop process."""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading

import uvicorn


def _exit_with_desktop_parent() -> None:
    """Ensure a PyInstaller child cannot survive after the Tauri window exits."""
    raw_pid = os.environ.get("TOPPILOT_PARENT_PID")
    if not raw_pid or os.name != "nt":
        return
    try:
        import ctypes
        synchronize = 0x00100000
        infinite = 0xFFFFFFFF
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, int(raw_pid))
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, infinite)
            ctypes.windll.kernel32.CloseHandle(handle)
            os._exit(0)
    except (OSError, ValueError):
        return


def main() -> int:
    threading.Thread(target=_exit_with_desktop_parent, daemon=True).start()
    token = secrets.token_urlsafe(32)
    os.environ["TOPPILOT_DESKTOP_TOKEN"] = token
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    print("TOPPILOT_SIDECAR=" + json.dumps({"port": port, "token": token}), flush=True)
    config = uvicorn.Config("topoptpilot.api.fastapi_app:app", host="127.0.0.1", port=port,
                            log_level="warning", access_log=False)
    uvicorn.Server(config).run(sockets=[sock])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
