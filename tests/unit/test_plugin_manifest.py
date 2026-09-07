"""Plugin manifest validation and the trust boundary around it."""

import pytest

from adaptive_agent.plugins import (
    DANGEROUS_PERMISSIONS, PluginType, Trust, blocked_reason, discover, load_manifest,
    parse_manifest,
)

VALID = {
    "schema_version": "1",
    "name": "qnn-edge-ai",
    "version": "1.0.0",
    "type": "profile",
    "description": "QNN benchmarking workflows.",
    "capabilities": ["quantization", "benchmarking"],
    "permissions": ["read_project"],
}


def test_valid_manifest_parses_without_errors():
    manifest, errors = parse_manifest(VALID)
    assert errors == []
    assert manifest.name == "qnn-edge-ai"
    assert manifest.type is PluginType.PROFILE
    assert manifest.capabilities == ["quantization", "benchmarking"]


@pytest.mark.parametrize("field", ["name", "version", "type"])
def test_missing_required_field_is_reported(field):
    _, errors = parse_manifest({key: value for key, value in VALID.items() if key != field})
    assert any(field in error for error in errors)


def test_unknown_permission_is_rejected_not_granted():
    manifest, errors = parse_manifest({**VALID, "permissions": ["read_project", "rm_rf"]})
    assert any("rm_rf" in error for error in errors)
    assert "rm_rf" not in DANGEROUS_PERMISSIONS


def test_unknown_plugin_type_is_reported():
    manifest, errors = parse_manifest({**VALID, "type": "wormhole"})
    assert manifest.type is None
    assert any("wormhole" in error for error in errors)


def test_unsupported_schema_version_is_reported():
    _, errors = parse_manifest({**VALID, "schema_version": "99"})
    assert any("schema_version" in error for error in errors)


def test_provider_plugin_must_declare_an_entrypoint():
    _, errors = parse_manifest({**VALID, "type": "provider"})
    assert any("entrypoint" in error for error in errors)
    _, ok = parse_manifest({**VALID, "type": "provider", "entrypoint": "mypkg.provider:Provider"})
    assert ok == []


def test_downloaded_plugins_are_untrusted_and_not_loadable():
    manifest, _ = parse_manifest(VALID)
    assert manifest.trust is Trust.UNTRUSTED
    assert manifest.loadable is False
    assert blocked_reason(manifest)


def test_trusted_plugin_is_loadable():
    manifest, _ = parse_manifest(VALID, trust=Trust.TRUSTED)
    assert manifest.loadable is True
    assert blocked_reason(manifest) == ""


def test_dangerous_permissions_are_named_in_the_block_reason():
    manifest, _ = parse_manifest({**VALID, "permissions": ["read_project", "run_commands",
                                                           "read_credentials"]})
    assert set(manifest.dangerous) == {"run_commands", "read_credentials"}
    reason = blocked_reason(manifest)
    assert "run_commands" in reason and "read_credentials" in reason


def test_malformed_manifest_does_not_raise(tmp_path):
    path = tmp_path / "plugin.yaml"
    path.write_text("name: [unclosed\n", encoding="utf-8")
    _, errors = load_manifest(path)
    assert errors and "YAML" in errors[0]


def test_missing_manifest_is_reported_not_raised(tmp_path):
    _, errors = load_manifest(tmp_path / "absent")
    assert errors == ["manifest not found"]


def test_discovery_reads_manifests_without_loading_code(tmp_path):
    good = tmp_path / "good"
    good.mkdir()
    (good / "plugin.yaml").write_text(
        "schema_version: '1'\nname: good\nversion: '1.0'\ntype: skill\n", encoding="utf-8")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "plugin.yaml").write_text("name: bad\n", encoding="utf-8")
    # An importable module beside the manifest must not be imported by discovery.
    (bad / "__init__.py").write_text("raise RuntimeError('plugin code executed')\n", encoding="utf-8")

    found = {item["name"] or "bad": item for item in discover(tmp_path)}
    assert found["good"]["valid"] is True
    assert found["bad"]["valid"] is False
    assert all(item["trust"] == "untrusted" for item in found.values())
    assert all(item["loadable"] is False for item in found.values())


def test_discovery_of_a_missing_directory_is_empty(tmp_path):
    assert discover(tmp_path / "nope") == []
