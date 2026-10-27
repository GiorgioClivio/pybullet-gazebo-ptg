"""PTG snapshot id: <yy>w<ww><letter> = ISO year (2 digits), ISO week, then a, b, c... for each release that week.

Set only by `python3 tools/package.py --release`, which also records the release fingerprint (SHA-256 of the
repository's SHA256SUMS manifest) in RELEASES.md.
"""
SNAPSHOT = "26w44d"
