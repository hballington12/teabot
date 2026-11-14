"""Print the changelog's section for a release, as its GitHub release notes: notes.py v1.2.3"""

import sys

from release_lib import ROOT, changelog_section, version_of

print(changelog_section(ROOT / "CHANGELOG.md", version_of(sys.argv[1])))
