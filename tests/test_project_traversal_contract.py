"""Architecture contracts for bounded desktop project traversal."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_listing_uses_lazy_native_enumeration_and_explicit_dfs() -> None:
    source = (ROOT / "desktop" / "src-tauri" / "src" / "project.rs").read_text(
        encoding="utf-8"
    )

    # The desktop file tree must not materialize a whole directory before it can
    # decide to prune it.  A stack of ReadDir frames makes the resource limit and
    # depth-first order explicit instead of hiding them in recursive calls.
    assert "struct ProjectDirectoryFrame" in source
    assert "entries: fs::ReadDir" in source
    assert "while let Some(frame) = stack.last_mut()" in source
    assert "MAX_PROJECT_OPEN_DIRECTORY_ENUMERATORS" in source
    assert "PROJECT_TRAVERSAL_GATE" in source
    assert "MAX_PROJECT_SCANNED_ITEMS" in source
    assert "is_non_followable_project_entry" in source
    assert "fn collect_project_entries(" not in source
    assert "let mut items = Vec::new();" not in source
