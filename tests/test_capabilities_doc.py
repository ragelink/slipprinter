"""docs/capabilities.md must list every command in the profile, supported or not."""

import re
from pathlib import Path

import pytest

from slipprinter.profile import COMMANDS, UNSUPPORTED

pytestmark = pytest.mark.always

DOC = (Path(__file__).parent.parent / "docs" / "capabilities.md").read_text()
SUPPORTED, UNSUPPORTED_SECTION = DOC.split("## Not supported", 1)


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.mnemonic)
def test_supported_command_is_documented(command):
    assert re.search(rf"^\| `{re.escape(command.mnemonic)}` \|", SUPPORTED, re.MULTILINE)


@pytest.mark.parametrize("mnemonic", [m for m, _ in UNSUPPORTED.values()])
def test_unsupported_command_is_documented(mnemonic):
    assert f"`{mnemonic}`" in UNSUPPORTED_SECTION
