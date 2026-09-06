"""Keep all imported desktop services away from the user's LocalAppData."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path


TEST_DATA_ROOT = Path(tempfile.mkdtemp(prefix="topoptpilot-pytest-")).resolve()
os.environ["TOPOPTPILOT_DATA_DIR"] = str(TEST_DATA_ROOT)
os.environ["TOPPILOT_DATA_DIR"] = str(TEST_DATA_ROOT)


@atexit.register
def _remove_test_data() -> None:
    shutil.rmtree(TEST_DATA_ROOT, ignore_errors=True)
