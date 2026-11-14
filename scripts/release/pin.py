"""Pin teabot-announcements to the core it is released with: pin.py v1.2.3"""

import sys

from release_lib import PLUGIN_PYPROJECT, ROOT, pin_plugin, version_of

pin_plugin(ROOT / PLUGIN_PYPROJECT, version_of(sys.argv[1]))
