"""Build the release's template archive: template.py <out.tar.gz>"""

import sys
from pathlib import Path

from release_lib import build_template

build_template(Path(sys.argv[1]).resolve())
