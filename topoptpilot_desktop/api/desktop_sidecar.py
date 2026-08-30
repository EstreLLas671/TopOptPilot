"""TopOptPilot authenticated sidecar entry point."""

from __future__ import annotations

import json
import multiprocessing
import os
import secrets
import socket
import threading

import uvicorn


def _exit_with_desktop_parent() -> None:
    raw_pid = os.environ.get("TOPPILOT_PARENT_PID")
    if not raw_pid or os.name != "nt":
        return
    try:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(raw_pid))
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
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
    config = uvicorn.Config("topoptpilot_desktop.api.app:app", host="127.0.0.1", port=port, log_level="warning", access_log=False)
    uvicorn.Server(config).run(sockets=[sock])
    return 0


def run_entrypoint() -> int:
    multiprocessing.freeze_support()
    return main()


if __name__ == "__main__":
    raise SystemExit(run_entrypoint())
