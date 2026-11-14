"""Build the release's template archive, locked against the published packages: template.py v1.2.3 <out.tar.gz>"""

import sys
from pathlib import Path

from release_lib import build_template, version_of

build_template(version_of(sys.argv[1]), Path(sys.argv[2]).resolve())
