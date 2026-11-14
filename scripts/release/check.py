"""Refuse a release whose versions, changelog or template do not match its tag: check.py v1.2.3"""

import sys

from release_lib import problems

found = problems(sys.argv[1])
for problem in found:
    print(f"error: {problem}", file=sys.stderr)
sys.exit(1 if found else 0)
