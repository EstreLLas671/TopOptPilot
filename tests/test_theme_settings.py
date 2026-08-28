from __future__ import annotations

from topoptpilot.schemas.models import AppSettings


def test_theme_settings_support_light_dark_system_and_custom_tokens() -> None:
    settings = AppSettings.model_validate({
        "theme": "custom",
        "custom_theme": {"accent": "#345fa8", "background": "#f4f7fb", "surface": "#ffffff", "text": "#24344d"},
    })
    assert settings.theme == "custom"
    assert settings.custom_theme.accent == "#345fa8"


def test_theme_settings_reject_non_hex_css_values() -> None:
    try:
        AppSettings.model_validate({"theme": "custom", "custom_theme": {"accent": "url(example)"}})
    except ValueError:
        return
    raise AssertionError("unsafe custom theme token was accepted")


def test_theme_settings_deep_merge_semantic_palette_and_contrast() -> None:
    settings = AppSettings.model_validate({
        "theme": "custom",
        "custom_theme": {
            "accent": "#123456",
            "chart_grid": "#334455",
            "contrast": 140,
        },
    })
    assert settings.custom_theme.accent == "#123456"
    assert settings.custom_theme.chart_grid == "#334455"
    assert settings.custom_theme.surface == "#ffffff"
    assert settings.custom_theme.volume_background == "#f1f5fa"
    assert settings.custom_theme.contrast == 140


def test_theme_settings_reject_out_of_range_contrast() -> None:
    try:
        AppSettings.model_validate({"custom_theme": {"contrast": 141}})
    except ValueError:
        return
    raise AssertionError("out-of-range contrast was accepted")