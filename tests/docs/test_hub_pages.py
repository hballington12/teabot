"""The plugin hub's pages in the docs: built from the catalogue's fields, with every author's words escaped."""

import importlib.util
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).parents[2] / "scripts/docs/hub.py"
spec = importlib.util.spec_from_file_location("hub_pages", SCRIPT)
assert spec is not None and spec.loader is not None
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)

COMMIT = "a" * 40


def catalogue(**plugin: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "wom",
        "package": "teabot-wom",
        "description": "Wise Old Man lookups",
        "repository": "https://github.com/someone/teabot-wom",
        "licence": "MIT License",
        "versions": [
            {
                "commit": COMMIT,
                "version": "1.0.0",
                "teabot": ">=1.4,<2",
                "external_connections": "api.wiseoldman.net",
                "dependencies": [],
            }
        ],
    }
    return {"plugins": [{**base, **plugin}]}


def test_each_plugin_gets_a_card_and_a_page(tmp_path: Path) -> None:
    assert hub.write(catalogue(), tmp_path) == ["wom"]
    index = (tmp_path / "index.md").read_text()
    assert "[wom](wom.md)" in index and "Wise Old Man lookups" in index
    page = (tmp_path / "wom.md").read_text()
    assert (
        "uv run teabot hub add wom" in page and f"https://github.com/someone/teabot-wom/tree/{COMMIT}" in page
    )
    assert "api.wiseoldman.net" in page


def test_an_authors_words_cannot_add_html_or_links(tmp_path: Path) -> None:
    hub.write(catalogue(description="<script>x</script> [click](https://evil.example) it's *fine*"), tmp_path)
    page = (tmp_path / "wom.md").read_text()
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "[click](https" not in page and "\\[click\\]" in page
    assert "it's" in page


def test_a_listing_with_a_bad_id_or_source_gets_no_page(tmp_path: Path) -> None:
    assert hub.write(catalogue(id="../etc"), tmp_path) == []
    assert hub.write(catalogue(repository="javascript:alert(1)"), tmp_path) == []


def test_without_the_catalogue_the_section_says_so(tmp_path: Path) -> None:
    assert hub.write(None, tmp_path) == []
    assert "could not be read" in (tmp_path / "index.md").read_text()
