import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "nimly_manager"


def test_manifest_declares_panel_dependencies_and_config_flow() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())

    assert manifest["domain"] == "nimly_manager"
    assert manifest["config_flow"] is True
    assert set(manifest["dependencies"]) >= {
        "frontend",
        "http",
        "mqtt",
        "panel_custom",
        "websocket_api",
    }
    assert manifest["iot_class"] == "local_push"
    assert manifest["documentation"].startswith("https://github.com/")
    assert manifest["issue_tracker"].endswith("/issues")


def test_translation_files_are_valid_json() -> None:
    source = json.loads((COMPONENT / "strings.json").read_text())

    for language in ("en", "nb"):
        translated = json.loads(
            (COMPONENT / "translations" / f"{language}.json").read_text()
        )
        assert translated["config"]["step"]["user"]["data"]
    assert source["config"]["error"]["wildcard_not_allowed"]


def test_service_descriptions_exist_for_all_enrollment_actions() -> None:
    services = (COMPONENT / "services.yaml").read_text()

    assert "start_fingerprint_enrollment:" in services
    assert "confirm_fingerprint_enrollment:" in services
    assert "cancel_fingerprint_enrollment:" in services


def test_hacs_metadata_and_brand_asset_exist() -> None:
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs["name"] == "Nimly Manager"
    assert hacs["country"] == "NO"
    assert (COMPONENT / "brand" / "icon.png").stat().st_size > 0


def test_release_versions_match() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert f'version = "{manifest["version"]}"' in pyproject
    assert f"## {manifest['version']}" in (ROOT / "CHANGELOG.md").read_text()


def test_admin_panel_asset_contains_enrollment_flow() -> None:
    panel = COMPONENT / "frontend" / "nimly-manager-panel.js"
    source = panel.read_text()

    assert panel.stat().st_size > 0
    assert 'customElements.define("nimly-manager-panel"' in source
    assert '"nimly_manager/enrollment/start"' in source
    assert '"nimly_manager/enrollment/confirm"' in source
    assert '"nimly_manager/enrollment/cancel"' in source
