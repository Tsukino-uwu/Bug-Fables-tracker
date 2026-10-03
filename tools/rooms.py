"""Writes data/rooms.json: each map's extent and its doors (where each sits in the map, the map it leads to, and where
it lands there), from the randomizer mod's entity dump. Door targets are map indexes, named from the decompiled game's
MainManager.Maps (read for the names only; it never enters this repo).

    python tools/rooms.py <your Bug Fables install>/BepInEx/bugfablesap-entitydump.tsv [<decompiled folder>]

The decompiled folder defaults to the randomizer checkout's (../bug_fables_ap/decompiled).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
PARKED = 90.0  # the game parks unused objects this high and above, out of reach


def point(field: str) -> tuple[float, float, float]:
    x, y, z = (float(v) for v in field.split(":"))
    return x, y, z


def map_names(decompiled: Path) -> list[str]:
    source = (decompiled / "MainManager.cs").read_text(encoding="utf-8", errors="ignore")
    body = re.search(r"public enum Maps\s*\{(.*?)\}", source, re.S).group(1)
    return [x.strip().split("=")[0].strip() for x in body.split(",") if x.strip()]


def main() -> None:
    dump = Path(sys.argv[1])
    decompiled = Path(sys.argv[2]) if len(sys.argv) > 2 else PACK.parent / "bug_fables_ap" / "decompiled"
    names = map_names(decompiled)
    rooms: dict[str, dict] = {}
    with dump.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            if not row["position"]:
                continue
            x, y, z = point(row["position"])
            if y >= PARKED:
                continue
            room = rooms.setdefault(row["map"], {"points": [], "doors": []})
            room["points"].append((x, z))
            data = row["data"].split()
            vectors = (row["vectordata"] or "").split()
            if row["objecttype"] == "DoorOtherMap" and data and len(vectors) >= 2:
                target = int(data[0])
                arrive = point(vectors[1])
                room["doors"].append({"index": int(row["index"]), "name": row["name"],
                                      "to": names[target] if 0 <= target < len(names) else None,
                                      "at": [round(x, 2), round(z, 2)], "arrive": [round(arrive[0], 2),
                                                                                   round(arrive[2], 2)]})
    out = {"_about": "Each map's extent (the corners of its entities' positions, x and z) and its doors: where each "
                     "sits, the map it leads to and where it lands there, from the randomizer mod's entity dump; "
                     "written by tools/rooms.py.",
           "maps": {}}
    for name in sorted(rooms):
        xs = [p[0] for p in rooms[name]["points"]]
        zs = [p[1] for p in rooms[name]["points"]]
        out["maps"][name] = {"bounds": [round(min(xs), 2), round(min(zs), 2), round(max(xs), 2), round(max(zs), 2)],
                             "doors": rooms[name]["doors"]}
    (PACK / "data/rooms.json").write_text(json.dumps(out, indent=1) + "\n", "utf-8")
    doors = sum(len(r["doors"]) for r in out["maps"].values())
    print(f"{len(out['maps'])} maps, {doors} doors")


if __name__ == "__main__":
    main()
