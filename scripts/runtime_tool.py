"""Helpers for scripts/build-runtime.sh (#63).

Runs with the standalone runtime's own Python during the build, so it uses the
standard library only.

  relocate-scripts BIN_DIR
      Console scripts written by pip start with the absolute path of the
      interpreter they were installed with (the CI build directory). Replace
      that shebang with a /bin/sh trampoline that runs the python3 next to the
      script, so the runtime keeps working wherever install.sh unpacks it.

  check-macos-tags SITE_PACKAGES --max 13.0
      Fail if any installed wheel only runs on a macOS newer than --max or on
      something other than arm64. The runtime is built on a newer runner than
      the oldest macOS the app supports.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# A shell line that Python reads as a string literal: sh runs the exec, Python
# skips it. The same trick pip uses for interpreter paths that are too long.
TRAMPOLINE = (
    "#!/bin/sh\n"
    "'''exec' \"$(dirname -- \"$0\")/python3\" \"$0\" \"$@\"\n"
    "' '''\n"
)

_PYTHON_SHEBANG = re.compile(rb"^#![ \t]*/\S*/python3?(\.\d+)?[ \t]*\r?$")
_MACOS_PLATFORM = re.compile(r"^macosx_(\d+)_(\d+)_(\w+)$")
_ARM64_ARCHES = {"arm64", "universal2"}


def relocate_scripts(bin_dir: Path) -> list[str]:
    """Rewrites absolute python shebangs in bin_dir; returns the changed names."""
    changed = []
    for path in sorted(bin_dir.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        first, newline, rest = data.partition(b"\n")
        if not newline or not _PYTHON_SHEBANG.match(first):
            continue
        # Write in place so the file keeps its mode.
        path.write_bytes(TRAMPOLINE.encode() + rest)
        changed.append(path.name)
    return changed


def parse_version(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)", text)
    if not match:
        raise ValueError(f"expected MAJOR.MINOR, got {text!r}")
    return int(match.group(1)), int(match.group(2))


def platform_fits(platform: str, max_version: tuple[int, int]) -> bool:
    """True if a wheel platform tag runs on arm64 macOS max_version."""
    if platform == "any":
        return True
    match = _MACOS_PLATFORM.match(platform)
    if not match:
        return False
    version = (int(match.group(1)), int(match.group(2)))
    return version <= max_version and match.group(3) in _ARM64_ARCHES


def wheel_tags(wheel_file: Path) -> list[str]:
    tags = []
    for line in wheel_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "Tag":
            tags.append(value.strip())
    return tags


def macos_tag_violations(site_packages: Path, max_version: tuple[int, int]) -> list[str]:
    """Returns one line per installed wheel that has no tag fitting max_version."""
    violations = []
    for wheel_file in sorted(site_packages.glob("*.dist-info/WHEEL")):
        tags = wheel_tags(wheel_file)
        platforms = [tag.rsplit("-", 1)[-1] for tag in tags]
        if not any(platform_fits(p, max_version) for p in platforms):
            name = wheel_file.parent.name
            violations.append(f"{name}: {', '.join(tags) or 'no Tag lines'}")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    relocate = sub.add_parser("relocate-scripts")
    relocate.add_argument("bin_dir", type=Path)
    check = sub.add_parser("check-macos-tags")
    check.add_argument("site_packages", type=Path)
    check.add_argument("--max", dest="max_version", required=True)
    args = parser.parse_args(argv)

    if args.command == "relocate-scripts":
        for name in relocate_scripts(args.bin_dir):
            print(f"relocatable: {name}")
        return 0

    if not args.site_packages.is_dir():
        print(f"ERROR: {args.site_packages} is not a directory", file=sys.stderr)
        return 1
    max_version = parse_version(args.max_version)
    if not list(args.site_packages.glob("*.dist-info/WHEEL")):
        print(f"ERROR: no installed wheels in {args.site_packages}", file=sys.stderr)
        return 1
    violations = macos_tag_violations(args.site_packages, max_version)
    for line in violations:
        print(f"ERROR: needs newer macOS or another arch than {args.max_version}: {line}",
              file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
