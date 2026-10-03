"""Writes data/map_areas.json, each map's area (MapControl.areaid), from the randomizer mod's map dump.

    python tools/map_areas.py <your Bug Fables install>/BepInEx/bugfablesap-mapdump.tsv

The dump comes from the mod's MapDump debug setting (the randomizer's development.md), which reads every map prefab.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent


def main() -> None:
    areas = [entry["area"] for entry in json.loads((PACK / "data/area_pips.json").read_text("utf-8"))["areas"]]
    with open(sys.argv[1], encoding="utf-8", newline="") as dump:
        rows = list(csv.DictReader(dump, delimiter="\t"))
    maps = {row["map"]: areas[int(row["area"])] for row in rows if row["area"] != ""}
    out = {"_about": "Each map's area (MapControl.areaid, by MainManager.Areas), from the randomizer mod's map dump; "
                     "written by tools/map_areas.py.", "maps": dict(sorted(maps.items()))}
    (PACK / "data/map_areas.json").write_text(json.dumps(out, indent=2) + "\n", "utf-8")
    print(f"{len(maps)} maps")


if __name__ == "__main__":
    main()
