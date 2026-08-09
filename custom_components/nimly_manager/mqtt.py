"""Home Assistant MQTT subscription for Nimly Manager."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import EVENT_FINGERPRINT_ENROLLMENT_VERIFIED
from .runtime import NimlyLockRuntime

_LOGGER = logging.getLogger(__name__)


async def async_subscribe_state(
    hass: HomeAssistant,
    entry: ConfigEntry,
    runtime: NimlyLockRuntime,
) -> None:
    """Subscribe through Home Assistant's configured MQTT integration."""

    @callback
    def receive_message(message: Any) -> None:
        try:
            payload: Any = json.loads(message.payload)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Ignorerer ugyldig JSON på Nimly state-topic %s", runtime.topic
            )
            return
        if not isinstance(payload, dict):
            _LOGGER.warning(
                "Ignorerer ikke-objekt på Nimly state-topic %s", runtime.topic
            )
            return

        verification = runtime.observe_mqtt_state(
            payload,
            now=datetime.now(UTC),
        )
        if verification is None:
            return
        hass.bus.async_fire(
            EVENT_FINGERPRINT_ENROLLMENT_VERIFIED,
            {
                "config_entry_id": entry.entry_id,
                **verification.as_event_data(),
            },
        )

    unsubscribe = await mqtt.async_subscribe(
        hass,
        runtime.topic,
        receive_message,
        qos=0,
        encoding="utf-8",
    )
    entry.async_on_unload(unsubscribe)
