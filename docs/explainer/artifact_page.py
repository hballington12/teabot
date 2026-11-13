"""Write out/artifact/index.html: ManimGX's presenter page, ready to publish as an Artifact.

The publish step wraps the page in its own doctype and head, so this drops the page's own
doctype and meta lines and gives it a readable title. Run it after `manimgx present`.
"""

from pathlib import Path

OUT = Path(__file__).parent / "out"
SOURCE = OUT / "teapot-walkthrough.html"
TARGET = OUT / "artifact" / "index.html"
TITLE = "teapot walkthrough"


def main() -> None:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not line.startswith(("<!doctype", "<meta charset", '<meta name="viewport"'))]
    page = "\n".join(kept).replace("<title>TeapotWalkthrough</title>", f"<title>{TITLE}</title>")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(page + "\n", encoding="utf-8")
    print(TARGET)


if __name__ == "__main__":
    main()
