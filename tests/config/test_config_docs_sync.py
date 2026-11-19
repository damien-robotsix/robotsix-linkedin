"""Cross-file sync checks for the duplicated config-field key list.

The settings-key set must stay identical across several files: the JSON
Schema (``config/config.schema.json``, generated from ``Settings``), the
shipped template (``config/config.json``), the README "Config fields" table,
the DEPLOY.md config template, and the ``_ConfigUpdate`` model behind
``PUT /config``. Historically nothing failed when these drifted apart (adding
or renaming a setting meant editing every copy by hand). These tests make any
divergence fail CI: ``config/config.schema.json`` is the single reference the
other copies are verified against.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from linkedin_service.app import _ConfigUpdate

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "config" / "config.schema.json"
TEMPLATE_CONFIG = REPO_ROOT / "config" / "config.json"
README = REPO_ROOT / "README.md"
DEPLOY = REPO_ROOT / "DEPLOY.md"

_FIELD_CELL = re.compile(r"^\|\s*`([^`]+)`")
_JSON_FENCE = re.compile(r"^```json\n(.*?)\n```$", re.MULTILINE | re.DOTALL)


def _schema_field_keys() -> list[str]:
    """Return the canonical config field names from the JSON Schema."""
    schema: dict[str, Any] = json.loads(SCHEMA.read_text(encoding="utf-8"))
    properties: dict[str, Any] = schema["properties"]
    return sorted(properties)


def _table_field_keys(markdown: Path, heading: str) -> list[str]:
    """Return the first-column field names of the table under ``heading``."""
    keys: list[str] = []
    collecting = False
    for line in markdown.read_text(encoding="utf-8").splitlines():
        if line.startswith(heading):
            collecting = True
        elif not collecting:
            continue
        elif line.startswith("|"):
            match = _FIELD_CELL.match(line)
            if match is not None:
                keys.append(match.group(1))
        elif line.strip():
            break
    return sorted(keys)


def _first_json_block_keys(markdown: Path) -> list[str]:
    """Return the top-level keys of the first ```json code block."""
    match = _JSON_FENCE.search(markdown.read_text(encoding="utf-8"))
    assert match is not None, f"{markdown}: no ```json code block found"
    document: dict[str, Any] = json.loads(match.group(1))
    return sorted(document)


def _diff_message(document: str, actual: list[str], expected: list[str]) -> str:
    """Describe how ``document``'s keys diverge from the schema."""
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    return (
        f"{document} config-field keys diverge from config.schema.json — "
        f"missing: {missing}, extra: {extra}"
    )


def test_schema_has_config_fields() -> None:
    """Guard against a vacuous schema making the sync checks pass trivially."""
    assert len(_schema_field_keys()) > 0


def test_readme_config_fields_table_matches_schema() -> None:
    expected = _schema_field_keys()
    actual = _table_field_keys(README, "### Config fields")
    assert actual == expected, _diff_message("README 'Config fields' table", actual, expected)


def test_deploy_config_template_matches_schema() -> None:
    expected = _schema_field_keys()
    actual = _first_json_block_keys(DEPLOY)
    assert actual == expected, _diff_message("DEPLOY.md config template", actual, expected)


def test_shipped_config_template_matches_schema() -> None:
    expected = _schema_field_keys()
    data: dict[str, Any] = json.loads(TEMPLATE_CONFIG.read_text(encoding="utf-8"))
    actual = sorted(data)
    assert actual == expected, _diff_message("config/config.json", actual, expected)


def test_config_update_model_matches_schema() -> None:
    expected = _schema_field_keys()
    actual = sorted(_ConfigUpdate.model_fields)
    assert actual == expected, _diff_message("app._ConfigUpdate", actual, expected)
