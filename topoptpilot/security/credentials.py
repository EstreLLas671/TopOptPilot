"""Secret storage backed by Windows Credential Manager.

Secrets never enter AppSettings, SQLite, logs, reports, or reproduction bundles.
The process environment remains the highest-priority one-shot override.
"""
from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes

TARGET = "TopOptPilot/QwenOpenAICompatible"
_LOCAL_TARGET_RE = re.compile(r"^TopOptPilot/[A-Za-z0-9_./-]{1,220}$")


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _advapi():
    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is only available on Windows")
    dll = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    dll.CredWriteW.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(_CredentialW))]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    return dll


def _validate_local_target(target: str) -> str:
    """Limit generic Credential Manager use to TopOptPilot-owned names."""
    value = str(target).strip()
    if not _LOCAL_TARGET_RE.fullmatch(value):
        raise ValueError("Credential target is not a valid TopOptPilot local target")
    return value


def _write_credential(target: str, value: str, *, username: str) -> None:
    value = value.strip()
    if not value or len(value) > 2048:
        raise ValueError("Credential value must contain 1–2048 characters")
    blob = value.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(blob)
    credential = _CredentialW(Type=1, TargetName=target, Comment="TopOptPilot local credential",
                              CredentialBlobSize=len(blob),
                              CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
                              Persist=2, UserName=username)
    dll = _advapi()
    if not dll.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def _read_credential(target: str = TARGET) -> str | None:
    if os.name != "nt":
        return None
    dll = _advapi()
    pointer = ctypes.POINTER(_CredentialW)()
    if not dll.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == 1168:  # ERROR_NOT_FOUND
            return None
        raise ctypes.WinError(error)
    try:
        item = pointer.contents
        raw = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        dll.CredFree(pointer)


def _delete_credential(target: str) -> bool:
    if os.name != "nt":
        return False
    dll = _advapi()
    if dll.CredDeleteW(target, 1, 0):
        return True
    error = ctypes.get_last_error()
    if error == 1168:
        return False
    raise ctypes.WinError(error)


def set_local_secret(target: str, value: str, *, username: str = "TopOptPilot") -> None:
    """Store a non-exportable local secret under a scoped product target.

    This is intentionally not a general credential API.  It exists so a
    loopback-only headless daemon can keep its session token out of files,
    command arguments, reports and terminal output.
    """
    _write_credential(_validate_local_target(target), value, username=username)


def get_local_secret(target: str) -> str | None:
    return _read_credential(_validate_local_target(target))


def delete_local_secret(target: str) -> bool:
    return _delete_credential(_validate_local_target(target))


def set_qwen_api_key(value: str) -> None:
    _write_credential(TARGET, value, username="DASHSCOPE_API_KEY")


def get_qwen_api_key() -> str:
    return os.environ.get("DASHSCOPE_API_KEY") or _read_credential() or ""


def qwen_api_key_source() -> str:
    if os.environ.get("DASHSCOPE_API_KEY"):
        return "environment"
    return "credential_manager" if _read_credential() else "not_configured"


def delete_qwen_api_key() -> bool:
    return _delete_credential(TARGET)
