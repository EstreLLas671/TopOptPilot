"""Canonical 2.1 names and narrow compatibility adapters."""
from __future__ import annotations
from typing import Any

LEGACY_STAGE_TO_STEP = {"F0": "STEP1", "F1": "STEP2", "F2": "STEP3", "F3": "STEP4"}
STEP_TO_LEGACY_STAGE = {value: key for key, value in LEGACY_STAGE_TO_STEP.items()}
STEP_LABELS = {
    "STEP1": "Step1",
    "STEP2": "Step2",
    "STEP3": "Step3",
    "STEP4": "Step4",
}
LEGACY_MODE_TO_NEW = {"AUTONOMOUS": "DEEP_OPTIMIZATION", "COPILOT": "DEEP_OPTIMIZATION", "RESEARCH": "DEEP_OPTIMIZATION", "ENGINEERING": "BASIC_IMPLEMENTATION"}

def normalize_stage(value: Any, default: str = "STEP1") -> str:
    parts = str(value or "").split()
    if not parts:
        return default
    token = parts[0].upper()
    token = LEGACY_STAGE_TO_STEP.get(token, token)
    return token if token in STEP_LABELS else default

def stage_label(value: Any) -> str:
    return STEP_LABELS[normalize_stage(value)]

def normalize_mode(value: Any) -> str:
    token = str(value or "DEEP_OPTIMIZATION").upper()
    return LEGACY_MODE_TO_NEW.get(token, token)

def migrate_public_names(value: Any) -> Any:
    if isinstance(value, dict): return {key: migrate_public_names(item) for key, item in value.items()}
    if isinstance(value, list): return [migrate_public_names(item) for item in value]
    if isinstance(value, str):
        head = value.split()[0].upper() if value else ""
        if head in LEGACY_STAGE_TO_STEP: return LEGACY_STAGE_TO_STEP[head] + value[len(value.split()[0]):]
        return LEGACY_MODE_TO_NEW.get(value.upper(), value)
    return value
