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
