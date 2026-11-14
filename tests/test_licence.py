"""One licence for the core, the SDK, the first-party plugins and the template (D41)."""

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
COPIES = ["template/LICENSE"]


def test_the_licence_is_mit() -> None:
    assert (ROOT / "LICENSE").read_text().startswith("MIT License\n")


@pytest.mark.parametrize("copy", COPIES)
def test_each_published_package_carries_the_same_licence(copy: str) -> None:
    assert (ROOT / copy).read_text() == (ROOT / "LICENSE").read_text()
