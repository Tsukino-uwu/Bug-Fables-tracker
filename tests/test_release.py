"""The release's checks and its versions.json entry (tools/release.py), the entry checked against PopTracker's own
schema for it (its packlist branch at 6cd531b).

    python -m pytest tests/test_release.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import zipfile
from pathlib import Path

import jsonschema

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))
import release  # noqa: E402

VERSIONS_SCHEMA = ("https://raw.githubusercontent.com/black-sliver/PopTracker/"
                   "6cd531b7a2075ea655b5dda0abbff8d486050325/schema/versions.schema.json")
SHA = "a" * 40
PACK_FILES = ["LICENSE", "manifest.json", "images/world.png", "items/items.json", "layouts/tracker.json",
              "locations/locations.json", "maps/maps.json", "scripts/init.lua"]


class Versions(unittest.TestCase):
    def test_the_tag_is_v_and_the_manifests_version(self):
        self.assertEqual(release.pack_version("v0.4.0", {"package_version": "0.4.0"}), "0.4.0")
        for tag in ("0.4.0", "v0.4", "v0.4.0-beta", "v0.4.1"):
            with self.assertRaises(ValueError, msg=tag):
                release.pack_version(tag, {"package_version": "0.4.0"})

    def test_the_pack_has_the_randomizers_version(self):
        release.check_same_version("0.4.0", "0.4.0")
        with self.assertRaises(ValueError):
            release.check_same_version("0.1.0", "0.4.0")

    def test_the_export_records_its_world_and_commit(self):
        world, commit = release.export_pin((PACK / "scripts/generated/logic_data.lua").read_text(encoding="utf-8"))
        self.assertRegex(world, r"^\d+\.\d+\.\d+$")
        self.assertRegex(commit, r"^[0-9a-f]{40}(\+dirty)?$")

    def test_only_the_randomizers_release_passes(self):
        release.check_pinned("0.4.0", SHA, SHA)
        for released in (None, "b" * 40):
            with self.assertRaises(ValueError):
                release.check_pinned("0.4.0", SHA, released)
        with self.assertRaises(ValueError):
            release.check_pinned("0.4.0", SHA + "+dirty", SHA)

    def test_a_tag_names_its_commit_annotated_or_not(self):
        with tempfile.TemporaryDirectory() as repo:
            def git(*args: str) -> str:
                return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.com",
                                       *args], capture_output=True, text=True, check=True).stdout.strip()
            git("init", "-q")
            git("commit", "-q", "--allow-empty", "-m", "one")
            git("tag", "v0.3.0")
            git("tag", "-a", "v0.4.0", "-m", "annotated")
            head = git("rev-parse", "HEAD")
            self.assertEqual(release.tag_commit(repo, "v0.3.0"), head)
            self.assertEqual(release.tag_commit(repo, "v0.4.0"), head)
            self.assertIsNone(release.tag_commit(repo, "v0.5.0"))


class Zip(unittest.TestCase):
    def zip_of(self, names: list[str]) -> Path:
        path = Path(tempfile.mkdtemp()) / "pack.zip"
        with zipfile.ZipFile(path, "w") as z:
            for name in names:
                z.writestr(name, "")
        return path

    def test_the_pack_at_the_root_or_in_one_folder(self):
        release.check_zip(self.zip_of(PACK_FILES))
        release.check_zip(self.zip_of([f"Bug-Fables-tracker-0.4.0/{f}" for f in PACK_FILES]))

    def test_anything_else_refused(self):
        for extra in ("tools/export.py", "PLAN.md", "README.md"):
            with self.assertRaises(ValueError, msg=extra):
                release.check_zip(self.zip_of([*PACK_FILES, extra]))
        with self.assertRaises(ValueError):
            release.check_zip(self.zip_of([f for f in PACK_FILES if not f.startswith("scripts/")]))


class Changelog(unittest.TestCase):
    def test_the_notes_bullets(self):
        notes = "### Features\n\n- Doors show where they led\n* Bosses tab\n\n### Logic\n- Fixed a gate\nText.\n"
        self.assertEqual(release.changelog(notes), ["Doors show where they led", "Bosses tab", "Fixed a gate"])
        self.assertEqual(release.changelog("No bullets."), ["See the release notes"])

    def test_newest_on_top_and_valid_for_poptracker(self):
        schema = json.loads(urllib.request.urlopen(VERSIONS_SCHEMA, timeout=30).read())
        url = "https://example.com/{}.zip"
        versions = release.add_version({"versions": []}, "0.4.0", url.format(4), "0" * 64, ["First"])
        versions = release.add_version(versions, "0.4.1", url.format(5), "1" * 64, ["Second"])
        self.assertEqual([v["package_version"] for v in versions["versions"]], ["0.4.1", "0.4.0"])
        jsonschema.validate(versions, schema)
        with self.assertRaises(ValueError):
            release.add_version(versions, "0.4.1", url.format(5), "1" * 64, ["Again"])


if __name__ == "__main__":
    unittest.main()
