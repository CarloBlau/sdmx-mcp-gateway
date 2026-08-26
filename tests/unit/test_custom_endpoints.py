"""Custom endpoint registration: config.py's SDMX_CUSTOM_ENDPOINTS_FILE loader.
Uses pytest's built-in tmp_path fixture for temporary custom endpoint files."""

import json

import pytest

from config import SDMX_ENDPOINTS, load_custom_endpoints, add_custom_endpoints
from models.schemas import CustomEndpointConstraints, CustomEndpointAuth

pytestmark = pytest.mark.unit


def _write(tmp_path, entries):
    path = tmp_path / "custom_endpoints.json"
    path.write_text(json.dumps(entries))
    return str(path)


def _valid_entry(**overrides):
    entry = {
        "key": "ACME",
        "name": "Acme Statistics",
        "base_url": "https://sdmx.acme.example/rest",
        "agency_id": "ACME",
        "description": "Acme's internal SDMX endpoint",
        "constraints": {"single_flow": "availableconstraint", "bulk": None},
        "references_support": ["none", "children"],
        "version_tag": "omit",
        "auth": {"header": "X-Api-Key", "env": "SDMX_ACME_KEY"},
    }
    entry.update(overrides)
    return entry


def test_unset_path_returns_empty_list():
    assert load_custom_endpoints(None) == []
    assert load_custom_endpoints("") == []


def test_valid_entry_is_loaded(tmp_path):
    path = _write(tmp_path, [_valid_entry()])
    loaded = load_custom_endpoints(path)

    assert [ep.key for ep in loaded] == ["ACME"]
    entry = loaded[0]
    assert entry.name == "Acme Statistics"
    assert entry.base_url == "https://sdmx.acme.example/rest"
    assert entry.agency_id == "ACME"
    assert entry.constraints == CustomEndpointConstraints(single_flow="availableconstraint", bulk=None)
    assert entry.references_support == ["none", "children"]
    assert entry.version_tag == "omit"
    assert entry.auth == CustomEndpointAuth(header="X-Api-Key", env="SDMX_ACME_KEY")


def test_multiple_entries_all_load(tmp_path):
    path = _write(
        tmp_path,
        [_valid_entry(key="ACME", agency_id="ACME"), _valid_entry(key="BETA", agency_id="BETA")],
    )
    loaded = load_custom_endpoints(path)
    assert {ep.key for ep in loaded} == {"ACME", "BETA"}


def test_missing_required_field_rejects_the_whole_file(tmp_path):
    entry = _valid_entry()
    del entry["base_url"]
    path = _write(tmp_path, [entry])
    with pytest.raises(ValueError):
        load_custom_endpoints(path)


def test_extra_field_rejects_the_whole_file(tmp_path):
    path = _write(tmp_path, [_valid_entry(unexpected_field="nope")])
    with pytest.raises(ValueError):
        load_custom_endpoints(path)


@pytest.mark.parametrize(
    "bad_url",
    ["ftp://sdmx.acme.example/rest", "not-a-url", "javascript:alert(1)", "sdmx.acme.example/rest"],
)
def test_bad_base_url_scheme_is_rejected(tmp_path, bad_url):
    path = _write(tmp_path, [_valid_entry(base_url=bad_url)])
    with pytest.raises(ValueError):
        load_custom_endpoints(path)


@pytest.mark.parametrize("bad_key", ["acme", "1ACME", "ACME-1", "ACME KEY", ""])
def test_bad_key_is_rejected(tmp_path, bad_key):
    path = _write(tmp_path, [_valid_entry(key=bad_key)])
    with pytest.raises(ValueError):
        load_custom_endpoints(path)


@pytest.mark.parametrize("bad_agency", ["", "1ACME", "ACME KEY", "ACME/../etc"])
def test_bad_agency_id_is_rejected(tmp_path, bad_agency):
    path = _write(tmp_path, [_valid_entry(agency_id=bad_agency)])
    with pytest.raises(ValueError):
        load_custom_endpoints(path)


def test_adding_a_new_endpoint_is_accepted(tmp_path):
    key = "ZZTESTORG"
    assert key not in SDMX_ENDPOINTS
    path = _write(tmp_path, [_valid_entry(key=key, agency_id=key, name="ZZ Test Org Statistics")])
    loaded = load_custom_endpoints(path)
    try:
        add_custom_endpoints(loaded)
        assert SDMX_ENDPOINTS[key]["name"] == "ZZ Test Org Statistics"
        assert SDMX_ENDPOINTS[key]["base_url"] == "https://sdmx.acme.example/rest"
    finally:
        del SDMX_ENDPOINTS[key]

def test_adding_a_builtin_endpoint_key_does_nothing(tmp_path):
    key = "ECB"
    assert key in SDMX_ENDPOINTS
    path = _write(tmp_path, [_valid_entry(key=key, agency_id=key)])
    loaded = load_custom_endpoints(path)
    add_custom_endpoints(loaded)
    assert SDMX_ENDPOINTS[key]["name"] == "European Central Bank"


def test_key_colliding_within_the_same_file_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        [_valid_entry(key="ACME", agency_id="ACME"), _valid_entry(key="ACME", agency_id="ACME")],
    )
    with pytest.raises(ValueError):
        load_custom_endpoints(path)


@pytest.mark.parametrize("bad_env", ["sdmx_acme_key", "1KEY", "SDMX ACME KEY", "SDMX-ACME-KEY"])
def test_bad_auth_env_name_is_rejected(tmp_path, bad_env):
    path = _write(tmp_path, [_valid_entry(auth={"header": "X-Api-Key", "env": bad_env})])
    with pytest.raises(ValueError):
        load_custom_endpoints(path)


@pytest.mark.parametrize("bad_version_tag", ["a/b", "1.0 ", " 1.0", "\t"])
def test_bad_version_tag_is_rejected(tmp_path, bad_version_tag):
    path = _write(tmp_path, [_valid_entry(version_tag=bad_version_tag)])
    with pytest.raises(ValueError):
        load_custom_endpoints(path)


def test_pinned_version_tag_is_accepted(tmp_path):
    path = _write(tmp_path, [_valid_entry(version_tag="1.0.0")])
    loaded = load_custom_endpoints(path)
    assert loaded[0].version_tag == "1.0.0"


def test_no_version_tag_defaults_to_none(tmp_path):
    entry = _valid_entry()
    del entry["version_tag"]
    path = _write(tmp_path, [entry])
    loaded = load_custom_endpoints(path)
    assert loaded[0].version_tag is None
