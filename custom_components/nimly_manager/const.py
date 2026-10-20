"""Constants for Nimly Manager."""

DOMAIN = "nimly_manager"

CONF_BASE_TOPIC = "base_topic"
CONF_DEVICE_NAME = "device_name"
DEFAULT_BASE_TOPIC = "zigbee2mqtt"

DATA_RUNTIMES = "runtimes"
DATA_SERVICES_REGISTERED = "services_registered"
DATA_SLOT_STORAGE = "slot_storage"
DATA_WEBSOCKET_REGISTERED = "websocket_registered"

PANEL_URL_PATH = "nimly-manager"
PANEL_STATIC_URL = "/nimly_manager_static"
PANEL_WEB_COMPONENT = "nimly-manager-panel"

SERVICE_START_FINGERPRINT_ENROLLMENT = "start_fingerprint_enrollment"
SERVICE_CONFIRM_FINGERPRINT_ENROLLMENT = "confirm_fingerprint_enrollment"
SERVICE_CANCEL_FINGERPRINT_ENROLLMENT = "cancel_fingerprint_enrollment"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PERSON_ID = "person_id"
ATTR_PERSON_NAME = "person_name"
ATTR_SESSION_ID = "session_id"
ATTR_SLOT = "slot"

EVENT_FINGERPRINT_ENROLLMENT_STATE = "nimly_fingerprint_enrollment_state"
EVENT_FINGERPRINT_ENROLLMENT_VERIFIED = "nimly_fingerprint_enrollment_verified"


def state_topic(base_topic: str, device_name: str) -> str:
    """Build the state topic from a friendly name or an already-prefixed topic."""

    base_topic = base_topic.strip().strip("/")
    device_name = device_name.strip().strip("/")
    if device_name == base_topic or device_name.startswith(f"{base_topic}/"):
        return device_name
    return f"{base_topic}/{device_name}"


# BLE (steg 5): one explicit scan action over Home Assistant's bluetooth stack.
CONF_BLE_ADDRESS = "ble_address"
CONF_OWNER_RECORD = "owner_record"
OPTION_OWNER_KEY_IMPORTED = "owner_key_imported"
OPTION_OWNER_NAME = "owner_name"

DATA_OWNER_STORE = "owner_store"
DATA_SCAN_COORDINATOR = "scan_coordinator"

SERVICE_START_FINGERPRINT_SCAN = "start_fingerprint_scan"
SERVICE_CANCEL_FINGERPRINT_SCAN = "cancel_fingerprint_scan"

ATTR_BLE_SLOT = "ble_slot"
ATTR_AT_THE_LOCK = "at_the_lock"

EVENT_FINGERPRINT_SCAN_STATE = "nimly_fingerprint_scan_state"
