#!/usr/bin/env python3
"""Enforce source and release hygiene for Home Assistant integration repos."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_EXACT_NAMES = {
    ".DS_Store",
    ".env",
    "secrets.yaml",
}
FORBIDDEN_SUFFIXES = {
    ".bak",
    ".db",
    ".har",
    ".pcap",
    ".pcapng",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".swp",
    ".trace",
}
FORBIDDEN_PARTS = {
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}


def tracked_paths() -> list[PurePosixPath]:
    """Return all tracked paths using Git's NUL-safe format."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable not found")
    output = subprocess.check_output(  # noqa: S603 - fixed Git executable
        [git, "ls-files", "-z"],
        cwd=ROOT,
    )
    return [
        PurePosixPath(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    ]


def artifact_findings(paths: list[PurePosixPath]) -> list[str]:
    """Return tracked paths that cannot be production source."""
    findings: list[str] = []
    for path in paths:
        name = path.name
        lowered = name.casefold()
        if (
            name in FORBIDDEN_EXACT_NAMES
            or name.startswith("._")
            or name.startswith("__tmp")
            or name.startswith("zz_")
            or lowered.endswith("~")
            or any(part in FORBIDDEN_PARTS for part in path.parts)
            or any(lowered.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
            or ".bak-" in lowered
        ):
            findings.append(str(path))
    return findings


def manifest_versions() -> list[str]:
    """Validate integration manifests and return their versions."""
    manifests = sorted((ROOT / "custom_components").glob("*/manifest.json"))
    if not manifests:
        raise ValueError("no custom_components/*/manifest.json found")
    versions: list[str] = []
    for manifest in manifests:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        version = data.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"{manifest.relative_to(ROOT)} has no version")
        versions.append(version)
    return versions


def validate_tag(versions: list[str]) -> None:
    """Require release tags to equal v<manifest version>."""
    ref = os.environ.get("GITHUB_REF", "")
    prefix = "refs/tags/"
    if not ref.startswith(prefix):
        return
    tag = ref.removeprefix(prefix)
    expected = {
        version if version.startswith("v") else f"v{version}"
        for version in versions
    }
    if tag not in expected:
        raise ValueError(
            f"release tag {tag!r} does not match manifest tag(s) "
            f"{sorted(expected)}"
        )


def main() -> int:
    """Run all repository-policy checks."""
    try:
        findings = artifact_findings(tracked_paths())
        if findings:
            print("Forbidden tracked artifacts:", file=sys.stderr)
            for finding in findings:
                print(f"- {finding}", file=sys.stderr)
            return 1
        versions = manifest_versions()
        validate_tag(versions)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Repository hygiene failed: {error}", file=sys.stderr)
        return 1
    print("Repository hygiene passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
