"""Constants for Nimly Manager."""

DOMAIN = "nimly_manager"

CONF_BASE_TOPIC = "base_topic"
CONF_DEVICE_NAME = "device_name"
DEFAULT_BASE_TOPIC = "zigbee2mqtt"

DATA_RUNTIMES = "runtimes"
DATA_SERVICES_REGISTERED = "services_registered"

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
    """Build the Zigbee2MQTT state topic without accepting wildcards."""

    return f"{base_topic.strip().strip('/')}/{device_name.strip().strip('/')}"
