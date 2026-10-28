"""The PII rules in .gitleaks.toml catch real-looking data and allow obviously fake fixtures.

Sample values are assembled at runtime so this file itself never trips the scanner.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.sometimes

CONFIG = Path(__file__).parent.parent / ".gitleaks.toml"


def scan(tmp_path: Path, text: str) -> set[str]:
    if shutil.which("gitleaks") is None:
        pytest.skip("gitleaks not installed (CI installs it; locally: brew install gitleaks)")
    (tmp_path / "sample.md").write_text(text)
    report = tmp_path / "report.json"
    subprocess.run(
        [
            "gitleaks",
            "dir",
            str(tmp_path / "sample.md"),
            "--config",
            str(CONFIG),
            "--no-banner",
            "--redact",
            "--report-format",
            "json",
            "--report-path",
            str(report),
            "--exit-code",
            "0",
        ],
        check=True,
        capture_output=True,
    )
    return {finding["RuleID"] for finding in json.loads(report.read_text())}


@pytest.mark.parametrize(
    ("rule", "text"),
    [
        ("us-routing-number", "Routing number: " + "1210" + "00358"),
        ("bank-account-number", "Account # " + "4837" + "29105562"),
        ("micr-line", "⑆" + "111" + "000025" + "⑆"),
        ("us-ssn", "SSN " + "219" + "-09-" + "9999"),
        ("usb-serial-device-path", "port /dev/cu." + "usbserial-" + "Q7RZK2M9"),
    ],
)
def test_real_looking_data_is_caught(tmp_path, rule, text):
    assert rule in scan(tmp_path, text)


@pytest.mark.parametrize(
    "text",
    [
        "Routing number: 000000000",
        "Account # 000123456789",
        "SSN 000-00-0000",
        "port /dev/cu.usbserial-TEST01",
        "Pay to Jane Example 1234.56 on 2026-10-28, check 1001",
    ],
)
def test_fake_fixture_data_is_allowed(tmp_path, text):
    assert scan(tmp_path, text) == set()
