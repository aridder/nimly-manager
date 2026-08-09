"""Config flow for Nimly Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BASE_TOPIC,
    CONF_DEVICE_NAME,
    DEFAULT_BASE_TOPIC,
    DOMAIN,
    state_topic,
)


class NimlyManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one Zigbee2MQTT-connected Nimly lock."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect the Zigbee2MQTT topic parts."""

        errors: dict[str, str] = {}
        if user_input is not None:
            base_topic = user_input[CONF_BASE_TOPIC].strip().strip("/")
            device_name = user_input[CONF_DEVICE_NAME].strip().strip("/")
            if not base_topic or not device_name:
                errors["base"] = "invalid_topic"
            elif any(
                token in base_topic or token in device_name for token in ("#", "+")
            ):
                errors["base"] = "wildcard_not_allowed"
            else:
                topic = state_topic(base_topic, device_name)
                await self.async_set_unique_id(topic)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=device_name,
                    data={
                        CONF_BASE_TOPIC: base_topic,
                        CONF_DEVICE_NAME: device_name,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BASE_TOPIC,
                    default=(
                        user_input.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC)
                        if user_input
                        else DEFAULT_BASE_TOPIC
                    ),
                ): str,
                vol.Required(
                    CONF_DEVICE_NAME,
                    default=user_input.get(CONF_DEVICE_NAME, "") if user_input else "",
                ): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
