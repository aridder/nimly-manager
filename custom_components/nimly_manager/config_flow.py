"""Config flow for Nimly Manager."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
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

from .const import (
    CONF_BASE_TOPIC,
    CONF_BLE_ADDRESS,
    CONF_DEVICE_NAME,
    CONF_OWNER_RECORD,
    DATA_OWNER_STORE,
    DEFAULT_BASE_TOPIC,
    DOMAIN,
    OPTION_OWNER_KEY_IMPORTED,
    OPTION_OWNER_NAME,
    state_topic,
)
from .nimly_ble.constants import NIMLY_ADVERTISING_UUID
from .nimly_ble.keystore import KeyStoreError, owner_record_from_json

CONF_REMOVE_OWNER_KEY = "remove_owner_key"
MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


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
            address = _normalize_mac(user_input.get(CONF_BLE_ADDRESS, ""))
            if address is None:
                errors[CONF_BLE_ADDRESS] = "invalid_ble_address"
            record = None
            pasted = (user_input.get(CONF_OWNER_RECORD) or "").strip()
            if pasted:
                try:
                    record = owner_record_from_json(pasted)
                except KeyStoreError:
                    errors[CONF_OWNER_RECORD] = "invalid_owner_record"
            if not errors:
                if user_input.get(CONF_REMOVE_OWNER_KEY):
                    await store.async_remove(entry.entry_id)
                    options.pop(OPTION_OWNER_NAME, None)
                elif record is not None:
                    await store.async_save_record(entry.entry_id, record)
                    options[OPTION_OWNER_NAME] = record.name or None
                options[CONF_BLE_ADDRESS] = address
                options[OPTION_OWNER_KEY_IMPORTED] = store.has(entry.entry_id)
                return self.async_create_entry(title="", data=options)

        current = options.get(CONF_BLE_ADDRESS) or ""
        candidates = _discovered_nimly_addresses(self.hass)
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


def _normalize_mac(value: str) -> str | None:
    cleaned = value.strip().upper().replace("-", ":")
    if len(cleaned) == 12 and ":" not in cleaned:
        cleaned = ":".join(cleaned[i : i + 2] for i in range(0, 12, 2))
    return cleaned if MAC_RE.match(cleaned) else None


def _discovered_nimly_addresses(hass) -> list[SelectOptionDict]:
    """Connectable advertisements carrying Nimly's 0xFD00 service data."""

    candidates: list[SelectOptionDict] = []
    for info in bluetooth.async_discovered_service_info(hass, connectable=True):
        if NIMLY_ADVERTISING_UUID not in info.service_data:
            continue
        seed = bytes(info.service_data[NIMLY_ADVERTISING_UUID])[:2]
        enrolled = "enrollet" if seed and seed != b"\x00\x00" else "factory"
        candidates.append(
            {
                "value": info.address,
                "label": f"{info.name or 'Nimly'} {info.address} · {info.rssi} dBm "
                f"via {info.source} · {enrolled}",
            }
        )
    return candidates
