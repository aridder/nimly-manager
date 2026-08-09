"""Read-only BLE discovery for supported Nimly locks."""

from .advertisement import NimlyAdvertisement, inspect_advertisement

__all__ = ["NimlyAdvertisement", "inspect_advertisement"]
