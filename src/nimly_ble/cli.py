"""``nimly-ble-owner``: preflight, enroll and fingerprint-scan from a laptop.

Run next to the door. Until the module is enrolled it only advertises for a
few minutes after a battery pull, so pull the battery first. ``enroll`` is
the irreversible step and refuses to run without a recent passing preflight,
a factory seed, and the explicit at-the-lock flag.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from nimly_ble_probe.firmware import FirmwareVersion
from nimly_ble_probe.probe import BleUnavailableError, discover_nimly

from . import enrollment
from .keystore import KeyStoreError, OwnerKeyStore
from .session import CommandFailed, Session, SessionError
from .transport_bleak import BleakTransport

MIN_FIRMWARE = FirmwareVersion(4, 6, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nimly-ble-owner",
        description="Local BLE owner tooling for a Nimly lock (writes to the lock).",
    )
    parser.add_argument("--scan-timeout", type=float, default=20.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true", dest="as_json")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="Handshake, model og default eier-auth; endrer ingenting")

    enroll = sub.add_parser("enroll", help="Engangs lokal eier-enrollment (irreversibel)")
    enroll.add_argument("--name", required=True, help="Låsens navn, maks 8 ASCII-tegn")
    enroll.add_argument(
        "--at-the-lock",
        action="store_true",
        help="Bekreft at du står ved låsen og har gjort preflight nå",
    )

    scan = sub.add_parser("fingerprint-scan", help="Start fingeravtrykk-registrering i én BLE-slot")
    scan.add_argument("--slot", type=int, required=True, help="BLE-slot 150–199")
    scan.add_argument("--at-the-lock", action="store_true")
    return parser


async def _find_lock(scan_timeout: float):
    found = await discover_nimly(scan_timeout)
    if not found:
        raise SessionError("fant ingen Nimly-annonsering — ta ut og inn batteriet og prøv igjen")
    if len(found) > 1:
        raise SessionError("flere Nimly-enheter funnet; flytt deg nærmere din egen")
    return found[0]


async def _run(args: argparse.Namespace) -> int:
    # Refuse cheap things before a 20 s scan: the flag, then the record state.
    if args.command in ("enroll", "fingerprint-scan") and not args.at_the_lock:
        raise enrollment.EnrollmentRefused("legg til --at-the-lock for å bekrefte")
    if args.command == "enroll" and len(args.name.encode("ascii", "ignore")) > 8:
        raise enrollment.EnrollmentRefused("--name er maks 8 ASCII-tegn")
    discovered = await _find_lock(args.scan_timeout)
    adv = discovered.advertisement
    address = adv.address
    store = OwnerKeyStore()

    async with BleakTransport(discovered.device, timeout=args.timeout) as transport:
        firmware_text = await transport.read_software_revision()
        firmware = FirmwareVersion.parse(firmware_text)
        if firmware is None or firmware < MIN_FIRMWARE:
            raise SessionError(f"firmware {firmware_text!r} under dokumentert minimum 4.6.0")
        fw = (firmware.major, firmware.minor, firmware.patch)
        session = Session(transport, firmware=fw, timeout=args.timeout)

        if args.command == "preflight":
            report = await enrollment.preflight(session, lock_address=address, firmware=fw)
            report["enrollment_state"] = adv.enrollment_state
            report["rssi"] = adv.rssi
            marker = store.mark_preflight(address, report)
            report["preflight_marker"] = str(marker)
            _emit(report, args.as_json)
            return 0

        if args.command == "enroll":
            if adv.enrollment_state != "factory":
                raise enrollment.EnrollmentRefused(
                    f"seed er ikke 00 00 (state={adv.enrollment_state}); ikke en factory-lås"
                )
            record = await enrollment.enroll(session, store, lock_address=address, name=args.name)
            _emit(
                {
                    "stage": record.stage,
                    "name": record.name,
                    "owner_record": str(store.path_for(address)),
                    "note": "Eiernøkkel lagret lokalt. Ikke del fila. Test nå: scan uten batteriuttak.",
                },
                args.as_json,
            )
            return 0

        if args.command == "fingerprint-scan":
            result = await enrollment.fingerprint_scan(
                session, store, lock_address=address, slot=args.slot
            )
            _emit(result, args.as_json)
            return 0
    return 1


def _emit(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except BleUnavailableError as error:
        parser.error(str(error))
    except (enrollment.EnrollmentRefused, KeyStoreError) as error:
        print(f"Nektet: {error}", file=sys.stderr)
        return 3
    except CommandFailed as error:
        print(f"Låsen avviste: {error}", file=sys.stderr)
        return 4
    except (SessionError, OSError, RuntimeError, ValueError) as error:
        print(f"BLE-feil: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
