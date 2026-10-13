"""Writes images/rooms/<map>.png and data/room_pictures.json: each room as the game draws it, from the front and above
(a few straight down), cut to what the game's camera shows of it, from the randomizer mod's dev console command
roomshot all.

    python tools/room_pictures.py <your Bug Fables install>/BepInEx

Each picture covers that extent (extent()), MIN_SIDE across at least (and, seen from the front, HEADROOM over its
highest entity and DEPTH under its lowest), at the render's own scale, so a game point (x, y, z) lands at
((x - left) * x_scale, (top - z) * z_scale - y * y_scale).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from PIL import Image

PACK = Path(__file__).resolve().parent.parent
ROOM_PAD = 2.0  # as tools/export.py's
HEADROOM = 10.0
DEPTH = 6.0
MIN_SIDE = 20.0
# The game's camera (MainManager.defaultcamoffset 2.25 up and 8.25 behind its pivot, defaultcamangle 10° down, a 60°
# view at 16:9) sees this far either side of its pivot, and the floor from this far before it.
VIEW_SIDE = 8.5
VIEW_FRONT = 5.6
UNLIMITED = 900.0  # a camera limit this far out (MapControl's 999) limits nothing
OUTLIER = 30.0  # an entity this far over or under the others' middle is parked there


def extent(room: dict, shot: dict) -> tuple[float, float, float, float, float, float]:
    """What of a room the game's camera shows (left, low, right, top, floor, highest): the box its pivot may move in
    (MapControl.camlimitneg and camlimitpos) and what it sees round it, the entities' extent where it isn't limited,
    the doors always."""
    bounds = room["bounds"]
    cam = [float(shot[k]) for k in ("cam_neg_x", "cam_neg_z", "cam_pos_x", "cam_pos_z")]
    left = cam[0] - VIEW_SIDE if abs(cam[0]) < UNLIMITED else bounds[0] - ROOM_PAD
    low = cam[1] - VIEW_FRONT if abs(cam[1]) < UNLIMITED else bounds[1] - ROOM_PAD
    right = cam[2] + VIEW_SIDE if abs(cam[2]) < UNLIMITED else bounds[2] + ROOM_PAD
    inside = [e for e in room["entities"] if left <= e["at"][0] <= right and e["at"][1] >= low]
    top = max([e["at"][1] for e in inside] + ([cam[3]] if abs(cam[3]) < UNLIMITED else [])) + ROOM_PAD
    for door in room["doors"]:
        left, right = min(left, door["at"][0] - ROOM_PAD), max(right, door["at"][0] + ROOM_PAD)
        low, top = min(low, door["at"][1] - ROOM_PAD), max(top, door["at"][1] + ROOM_PAD)
    heights = sorted(e["y"] for e in inside if e["at"][1] <= top) or [0.0]
    middle = heights[len(heights) // 2]
    heights = [y for y in heights if abs(y - middle) <= OUTLIER]
    # A room whose camera stands still (a treasure room) still shows its surroundings.
    widen, deepen = max(0.0, MIN_SIDE - (right - left)) / 2, max(0.0, MIN_SIDE - (top - low)) / 2
    return left - widen, low - deepen, right + widen, top + deepen, heights[0], heights[-1]


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
        # Each axis its own scale (the picture's sides are whole pixels); height moves a point up the picture only.
        x_scale, z_scale, y_scale = float(shot["x_step_x"]), -float(shot["z_step_y"]), -float(shot["y_step_y"])
        if x_scale <= 0 or z_scale <= 0 or float(shot["x_step_y"]) or float(shot["z_step_x"]) \
                or float(shot["y_step_x"]):
            raise SystemExit(f"{name}: seen turned: {shot}")
        left, low, right, top, floor, highest = extent(rooms[name], shot)
        origin_x, origin_y = float(shot["origin_x"]), float(shot["origin_y"])
        box = (round(origin_x + left * x_scale), round(origin_y - top * z_scale - (highest + HEADROOM) * y_scale),
               round(origin_x + right * x_scale), round(origin_y - low * z_scale - (floor - DEPTH) * y_scale))
        picture = Image.open(folder / f"{name}.png")
        # Nothing drawn round it is cut away too (an entity parked far below the floor stretched the extent).
        drawn = picture.getchannel("A").getbbox()
        if drawn:
            box = (max(box[0], drawn[0]), max(box[1], drawn[1]), min(box[2], drawn[2]), min(box[3], drawn[3]))
        picture.crop(box).save(out_dir / f"{name}.png", optimize=True)
        pictures[name] = {"left": (box[0] - origin_x) / x_scale, "top": (origin_y - box[1]) / z_scale,
                          "x_scale": x_scale, "z_scale": z_scale, "y_scale": y_scale,
                          "size": [box[2] - box[0], box[3] - box[1]]}
    out = {"_about": "Each room's picture in images/rooms: the game's room seen from the front and above, or straight "
                     "down (the randomizer mod's dev command roomshot), cut to what the game's camera shows of it; "
                     "a game point (x, y, z) lands at ((x - left) * x_scale, (top - z) * z_scale - y * y_scale). "
                     "Written by tools/room_pictures.py.",
           "rooms": pictures}
    (PACK / "data/room_pictures.json").write_text(json.dumps(out, indent=1) + "\n", "utf-8", newline="\n")
    print(f"{len(pictures)} room pictures")


if __name__ == "__main__":
    main()
