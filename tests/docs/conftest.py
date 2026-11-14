"""The scaffold rendered for the docs is a plugin's own package, not teabot's tests, so pytest skips it."""

collect_ignore = ["scaffold"]
