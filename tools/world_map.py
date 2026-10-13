"""Writes images/maps/World.png and data/world_map.json: the game's own pause map, opened and seen from above, and
where the map's (x, z) land in its pixels, from the randomizer mod's dev console command worldmap.

    python tools/world_map.py <your Bug Fables install>/BepInEx

The picture is the game's art (the world map's texture, Prefabs/Objects/map), used here as the World tab's map.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from PIL import Image

PACK = Path(__file__).resolve().parent.parent


def main() -> None:
    dump = Path(sys.argv[1])
    picture = Image.open(dump / "bugfablesap-worldmap.png").convert("RGBA")
    with open(dump / "bugfablesap-worldmap.tsv", encoding="utf-8", newline="") as source:
        row = next(csv.DictReader(source, delimiter="\t"))
    # The paper only: the render's empty margin cut off.
    left, top, right, bottom = picture.getchannel("A").getbbox()
    picture.crop((left, top, right, bottom)).save(PACK / "images/maps/World.png", optimize=True)
    out = {"_about": "Where the pause map's (x, z) land in images/maps/World.png's pixels, from its top left: origin "
                     "plus x times x_step plus z times z_step. Measured by the randomizer mod's dev command worldmap "
                     "(the map opened and seen from above); written by tools/world_map.py.",
           "size": [right - left, bottom - top],
           "origin": [round(float(row["origin_x"]) - left, 2), round(float(row["origin_y"]) - top, 2)],
           "x_step": [float(row["x_step_x"]), float(row["x_step_y"])],
           "z_step": [float(row["z_step_x"]), float(row["z_step_y"])]}
    (PACK / "data/world_map.json").write_text(json.dumps(out, indent=2) + "\n", "utf-8")
    print(f"World.png {right - left}x{bottom - top}")


if __name__ == "__main__":
    main()
