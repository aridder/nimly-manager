"""Register the Nimly Manager frontend panel."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_STATIC_URL,
    PANEL_URL_PATH,
    PANEL_WEB_COMPONENT,
)

PANEL_MODULE = "nimly-manager-panel.js"
PANEL_VERSION = "0.2.1"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve and register the admin-only manager page."""

    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_STATIC_URL, str(frontend_dir), False)]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_WEB_COMPONENT,
        sidebar_title="Nimly Manager",
        sidebar_icon="mdi:fingerprint",
        module_url=f"{PANEL_STATIC_URL}/{PANEL_MODULE}?v={PANEL_VERSION}",
        require_admin=True,
        config_panel_domain=DOMAIN,
    )
