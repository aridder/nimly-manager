import pytest

from nimly_ble_probe.cli import _validate_timeout, build_parser


def test_parser_requires_explicit_operation() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


@pytest.mark.parametrize("value", [0.49, 60.01])
def test_timeout_rejects_unbounded_values(value: float) -> None:
    with pytest.raises(ValueError):
        _validate_timeout(value, "timeout")


@pytest.mark.parametrize("value", [0.5, 8.0, 60.0])
def test_timeout_accepts_bounded_values(value: float) -> None:
    _validate_timeout(value, "timeout")
