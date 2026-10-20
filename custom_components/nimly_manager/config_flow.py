"""Config flow for Nimly Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .ble_setup import (
    BleSetupError,
    async_apply_ble_setup,
    discovered_nimly_locks,
    normalize_mac,
    parse_owner_record,
)
from .const import (
    CONF_BASE_TOPIC,
    CONF_BLE_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_OWNER_RECORD,
    DATA_OWNER_STORE,
    DEFAULT_BASE_TOPIC,
    DOMAIN,
    state_topic,
)

CONF_REMOVE_OWNER_KEY = "remove_owner_key"


class NimlyManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure one Zigbee2MQTT-connected Nimly lock."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NimlyManagerOptionsFlow:
        return NimlyManagerOptionsFlow()

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


class NimlyManagerOptionsFlow(config_entries.OptionsFlow):
    """BLE address and the one-time owner-key import.

    The pasted record goes straight into the private owner store and never
    into ``entry.options``; the options only remember the address, the lock's
    BLE name and that a key exists.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        store = self.hass.data[DOMAIN][DATA_OWNER_STORE]
        entry = self.config_entry
        options = dict(entry.options)

        if user_input is not None:
            try:
                record = parse_owner_record(user_input.get(CONF_OWNER_RECORD))
            except BleSetupError:
                errors[CONF_OWNER_RECORD] = "invalid_owner_record"
                record = None
            if normalize_mac(user_input.get(CONF_BLE_ADDRESS, "")) is None:
                errors[CONF_BLE_ADDRESS] = "invalid_ble_address"
            if not errors:
                options = await async_apply_ble_setup(
                    self.hass,
                    entry,
                    address=user_input[CONF_BLE_ADDRESS],
                    record=record,
                    remove_owner_key=bool(user_input.get(CONF_REMOVE_OWNER_KEY)),
                )
                return self.async_create_entry(title="", data=options)

        current = options.get(CONF_BLE_ADDRESS) or ""
        candidates: list[SelectOptionDict] = [
            {
                "value": str(lock["address"]),
                "label": f"{lock['name']} {lock['address']} · {lock['rssi']} dBm "
                f"via {lock['source']} · {lock['enrollment_state']}",
            }
            for lock in discovered_nimly_locks(self.hass)
        ]
        if current and current not in {c["value"] for c in candidates}:
            candidates.insert(0, {"value": current, "label": f"{current} (lagret)"})
        schema: dict[Any, Any] = {
            vol.Required(CONF_BLE_ADDRESS, default=current): SelectSelector(
                SelectSelectorConfig(
                    options=candidates,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_OWNER_RECORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD, multiline=False)
            ),
        }
        if store.has(entry.entry_id):
            schema[vol.Optional(CONF_REMOVE_OWNER_KEY, default=False)] = (
                BooleanSelector()
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "owner_key_state": (
                    "importert" if store.has(entry.entry_id) else "ikke importert"
                ),
            },
        )
