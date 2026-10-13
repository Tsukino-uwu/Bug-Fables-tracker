"""A release's checks and its entry in versions.json, the file the manifest's versions_url points PopTracker at.
Run by .github/workflows/release.yml when a release is published, and by hand before one:

    python tools/release.py check v0.4.0 --randomizer <the randomizer's checkout or git URL>
    python tools/release.py check-zip <a zip of the pack>
    python tools/release.py add v0.4.0 --zip <the zip> --url <its download URL> --notes <the release notes>
        --versions <versions.json>

The format is PopTracker's (its packlist branch: README.md, schema/versions.schema.json, at 6cd531b).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
# What the zip holds at its top level (or inside its one folder, as GitHub's archive has it; PopTracker's
# src/core/pack.cpp opens either): the pack, everything else export-ignore in .gitattributes.
SHIPPED = {"LICENSE", "images", "items", "layouts", "locations", "manifest.json", "maps", "scripts"}


def pack_version(tag: str, manifest: dict) -> str:
    """The version a tag releases: the tag is v and the manifest's package_version."""
    version = manifest["package_version"]
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"the tag must look like v0.1.0, got {tag!r}")
    if tag != f"v{version}":
        raise ValueError(f"the tag is {tag} but manifest.json's package_version is {version}")
    return version


def export_pin(logic_data: str) -> tuple[str, str]:
    """The world_version and randomizer_commit tools/export.py recorded."""
    found = dict(re.findall(r'\["(world_version|randomizer_commit)"\] = "([^"]*)"', logic_data))
    return found["world_version"], found["randomizer_commit"]


def tag_commit(randomizer: str, tag: str) -> str | None:
    """The commit a tag of the randomizer's repo names (an annotated tag peeled), or None without that tag."""
    # Every tag, not a pattern: some git builds leave out an annotated tag's ^{} line when given one.
    out = subprocess.run(["git", "ls-remote", "--tags", randomizer], capture_output=True, text=True,
                         check=True).stdout
    refs = {ref: sha for sha, ref in (line.split("\t") for line in out.splitlines())}
    return refs.get(f"refs/tags/{tag}^{{}}") or refs.get(f"refs/tags/{tag}")


def check_pinned(world_version: str, commit: str, released: str | None) -> None:
    """The logic is the randomizer's release of that world_version, so a seed's world_version check means it."""
    tag = f"v{world_version}"
    if released is None:
        raise ValueError(f"the export says world {world_version}, but the randomizer has no tag {tag}")
    if commit != released:
        raise ValueError(f"the export is from the randomizer's {commit}, not its release {tag} ({released}): "
                         f"export again from {tag}")


def zip_top_level(path: Path) -> set[str]:
    """The zip's top-level names, inside its one folder when it has only that."""
    parts = [n.strip("/").split("/") for n in zipfile.ZipFile(path).namelist() if n.strip("/")]
    if len({p[0] for p in parts}) == 1 and any(len(p) > 1 for p in parts):
        parts = [p[1:] for p in parts if len(p) > 1]
    return {p[0] for p in parts}


def check_zip(path: Path) -> None:
    top = zip_top_level(path)
    if top != SHIPPED:
        extra, missing = sorted(top - SHIPPED), sorted(SHIPPED - top)
        raise ValueError(f"the zip holds {extra or 'nothing'} it shouldn't, and lacks {missing or 'nothing'}")


def changelog(notes: str) -> list[str]:
    """The release notes' bullets, which PopTracker shows with the update; the notes' own link when they have none."""
    lines = [re.sub(r"^\s*[-*]\s+", "", line).strip() for line in notes.splitlines() if re.match(r"\s*[-*]\s", line)]
    return lines or ["See the release notes"]


def add_version(versions: dict, version: str, url: str, sha256: str, changes: list[str]) -> dict:
    """versions.json with this version on top, PopTracker taking the top entry as the latest."""
    if any(v["package_version"] == version for v in versions["versions"]):
        raise ValueError(f"versions.json already lists {version}")
    entry = {"package_version": version, "download_url": url, "sha256": sha256, "changelog": changes}
    return {"versions": [entry, *versions["versions"]]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="the tag, the manifest and the export agree")
    check.add_argument("tag")
    check.add_argument("--randomizer", required=True, help="the randomizer's checkout or git URL")
    zip_check = sub.add_parser("check-zip", help="the zip holds the pack and only the pack")
    zip_check.add_argument("zip", type=Path)
    add = sub.add_parser("add", help="add the release to versions.json")
    add.add_argument("tag")
    add.add_argument("--zip", required=True, type=Path)
    add.add_argument("--url", required=True)
    add.add_argument("--notes", required=True, type=Path)
    add.add_argument("--versions", required=True, type=Path, help="versions.json, started when missing")
    args = parser.parse_args()

    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    try:
        if args.command == "check":
            pack_version(args.tag, manifest)
            world, commit = export_pin((PACK / "scripts/generated/logic_data.lua").read_text(encoding="utf-8"))
            check_pinned(world, commit, tag_commit(args.randomizer, f"v{world}"))
            print(f"{args.tag}: the manifest agrees, the logic is the randomizer's v{world}")
        elif args.command == "check-zip":
            check_zip(args.zip)
            print(f"{args.zip.name}: the pack and only the pack")
        else:
            version = pack_version(args.tag, manifest)
            versions = (json.loads(args.versions.read_text(encoding="utf-8")) if args.versions.exists()
                        else {"versions": []})
            sha256 = hashlib.sha256(args.zip.read_bytes()).hexdigest()
            versions = add_version(versions, version, args.url, sha256,
                                   changelog(args.notes.read_text(encoding="utf-8")))
            args.versions.write_text(json.dumps(versions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                     newline="\n")
            print(f"versions.json: {version} on top, sha256 {sha256}")
    except ValueError as error:
        sys.exit(f"release: {error}")


if __name__ == "__main__":
    main()
