"""Writes images/rooms/<map>.png and data/room_pictures.json: each room as the game draws it, seen from above, cut to its
extent in data/rooms.json, from the randomizer mod's dev console command roomshot all.

    python tools/room_pictures.py <your Bug Fables install>/BepInEx

Each picture covers its room's extent and ROOM_PAD around it, at the render's own scale, so a game point (x, z) lands
at ((x - left) * scale, (top - z) * scale).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from PIL import Image

PACK = Path(__file__).resolve().parent.parent
ROOM_PAD = 2.0  # as tools/export.py's


def main() -> None:
    folder = Path(sys.argv[1]) / "bugfablesap-rooms"
    with open(folder / "rooms.tsv", encoding="utf-8", newline="") as source:
        shots = {row["map"]: row for row in csv.DictReader(source, delimiter="\t")}
    rooms = json.loads((PACK / "data/rooms.json").read_text("utf-8"))["maps"]
    areas = json.loads((PACK / "data/map_areas.json").read_text("utf-8"))["maps"]
    out_dir = PACK / "images/rooms"
    out_dir.mkdir(parents=True, exist_ok=True)
    pictures = {}
    for name in sorted(set(rooms) & set(areas) & set(shots)):
        shot = shots[name]
        # Each axis its own scale: the picture's sides are whole pixels.
        x_scale, z_scale = float(shot["x_step_x"]), -float(shot["z_step_y"])
        if x_scale <= 0 or abs(z_scale / x_scale - 1) > 0.01 or float(shot["x_step_y"]) or float(shot["z_step_x"]):
            raise SystemExit(f"{name}: not seen straight from above: {shot}")
        left, low, right, top = rooms[name]["bounds"]
        left, low, right, top = left - ROOM_PAD, low - ROOM_PAD, right + ROOM_PAD, top + ROOM_PAD
        x0 = float(shot["origin_x"]) + left * x_scale
        y0 = float(shot["origin_y"]) - top * z_scale
        box = (round(x0), round(y0), round(x0 + (right - left) * x_scale), round(y0 + (top - low) * z_scale))
        Image.open(folder / f"{name}.png").crop(box).save(out_dir / f"{name}.png", optimize=True)
        pictures[name] = {"left": left, "top": top, "x_scale": x_scale, "z_scale": z_scale,
                          "size": [box[2] - box[0], box[3] - box[1]]}
    out = {"_about": "Each room's picture in images/rooms: the game's room seen from above (the randomizer mod's dev "
                     "command roomshot), cut to data/rooms.json's extent and ROOM_PAD; a game point (x, z) lands at "
                     "((x - left) * x_scale, (top - z) * z_scale). Written by tools/room_pictures.py.",
           "rooms": pictures}
    (PACK / "data/room_pictures.json").write_text(json.dumps(out, indent=1) + "\n", "utf-8", newline="\n")
    print(f"{len(pictures)} room pictures")


if __name__ == "__main__":
    main()
