"""Command-line interface for the read-only Nimly BLE probe."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from .firmware import compatibility_for
from .probe import BleUnavailableError, discover_nimly, read_software_revision


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nimly-ble-probe",
        description="Read-only discovery and firmware inspection for Nimly BLE locks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Skann etter Nimly-annonseringer")
    scan.add_argument("--timeout", type=float, default=8.0)
    scan.add_argument("--json", action="store_true", dest="as_json")
    scan.add_argument(
        "--reveal-identifiers",
        action="store_true",
        help="Vis BLE-adresse og rå service-data",
    )

    inspect = subparsers.add_parser(
        "inspect", help="Les standard firmwarefelt fra én funnet Nimly-enhet"
    )
    inspect.add_argument("probe_id", help="probe_id fra scan")
    inspect.add_argument("--timeout", type=float, default=10.0)
    inspect.add_argument("--scan-timeout", type=float, default=8.0)
    inspect.add_argument("--json", action="store_true", dest="as_json")
    inspect.add_argument(
        "--reveal-identifiers",
        action="store_true",
        help="Vis BLE-adresse og rå service-data",
    )
    return parser


def _validate_timeout(value: float, label: str) -> None:
    if not 0.5 <= value <= 60:
        raise ValueError(f"{label} må være mellom 0,5 og 60 sekunder")


def _print_scan(items: list[object], as_json: bool) -> None:
    if as_json:
        print(json.dumps({"devices": items}, ensure_ascii=False, indent=2))
        return
    if not items:
        print("Ingen Nimly BLE-enheter funnet.")
        return
    for item in items:
        assert isinstance(item, dict)
        print(
            f"{item['probe_id']}  name={item['name'] or '-'}  "
            f"rssi={item['rssi'] if item['rssi'] is not None else '-'}  "
            f"service_data={item['service_data_kind']}"
        )


async def _run(args: argparse.Namespace) -> int:
    _validate_timeout(args.timeout, "timeout")
    if args.command == "inspect":
        _validate_timeout(args.scan_timeout, "scan-timeout")
        discovered = await discover_nimly(args.scan_timeout)
        selected = next(
            (
                item
                for item in discovered
                if item.advertisement.probe_id == args.probe_id
            ),
            None,
        )
        if selected is None:
            print(f"Fant ikke {args.probe_id} i en ny BLE-skanning.", file=sys.stderr)
            return 2

        firmware = await read_software_revision(selected.device, args.timeout)
        payload = selected.advertisement.as_dict(
            reveal_identifiers=args.reveal_identifiers
        )
        payload["software_revision"] = firmware
        payload["compatibility"] = compatibility_for(firmware)
        payload["operations"] = ["scan", "gatt_read_software_revision"]
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"{payload['probe_id']}  software_revision={firmware or '-'}")
        return 0

    discovered = await discover_nimly(args.timeout)
    payloads = [
        item.advertisement.as_dict(reveal_identifiers=args.reveal_identifiers)
        for item in discovered
    ]
    _print_scan(payloads, args.as_json)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except (BleUnavailableError, ValueError) as error:
        parser.error(str(error))
    except (OSError, RuntimeError) as error:
        print(f"BLE-feil: {error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
