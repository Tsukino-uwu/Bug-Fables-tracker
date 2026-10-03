"""Writes the pack's generated files from the Bug Fables apworld: its logic as Rule Builder's to_dict writes each rule
(scripts/generated/logic_data.lua), the items, the locations, and the placeholder map and icons, drawn by code.

    python tools/export.py --archipelago <your Archipelago checkout>

The checkout has the randomizer's apworld linked in as worlds/bug_fables (the randomizer's development.md).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

PACK = Path(__file__).resolve().parent.parent
# Rules the pack's Lua evaluates (scripts/logic.lua): Archipelago's and the apworld's own (its custom_rules.py).
SUPPORTED_RULES = {"And", "Or", "Has", "HasAllCounts", "True_", "False_", "Filtered",
                   "CanUse", "Member", "MoveItem", "Boat", "WayBack"}
WORLD_MAP = "World"
WORLD_SCALE = 70  # pixels per unit of the pause map's coordinates
WORLD_MARGIN = 40
PIN = 28
AREA_SIZE = 1600  # an area map's longer side, in pixels
ROOM_PAD = 2.0  # game units around a room's entities
ROOM_GAP = 3.0
FREE_STEP = 6.0
GROUP_GAP = 30.0
EDGE = 3.0  # a door this far inside its room's extent is inside it, not at its edge
INSIDE_PX = 24  # an inside room's box on the map
# Matching ring pairs for doors whose rooms can't sit side by side, told apart by colour.
WRAP_COLOURS = [(90, 190, 220, 255), (230, 200, 80, 255), (120, 210, 130, 255), (240, 140, 170, 255),
                (160, 150, 240, 255), (240, 160, 90, 255), (200, 230, 230, 255), (150, 200, 90, 255)]
PANEL_SHAPE = 16 / 9  # PopTracker's map panel, wide


def display_name(area: str) -> str:
    """For now the area's enum name in words; the game's own names (its AreaNames text) are still to be read."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", area)


def load_world(archipelago: Path) -> dict[str, Any]:
    """Everything the export reads from the apworld, imported from the checkout without writing into it."""
    sys.dont_write_bytecode = True
    os.chdir(archipelago)
    sys.path.insert(0, str(archipelago))
    import worlds.bug_fables as package
    from worlds.bug_fables import abilities, custom_rules, data_tables, items, logic, options, regions, rules, slot_data
    return {"package": package, "abilities": abilities, "custom_rules": custom_rules, "data": data_tables,
            "items": items, "logic": logic, "options": options, "regions": regions, "rules": rules,
            "slot_data": slot_data}


def randomizer_commit(package_dir: Path) -> str:
    """The randomizer checkout's commit the apworld came from, marked when it had uncommitted changes."""
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(package_dir), *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    commit = git("rev-parse", "HEAD")
    return commit + ("+dirty" if git("status", "--porcelain", "--", ".") else "")


def code_of(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def walk(rule: dict[str, Any]):
    yield rule
    for child in rule.get("children", ()):
        yield from walk(child)
    if "child" in rule:
        yield from walk(rule["child"])


def rule_dict(rule: Any) -> dict[str, Any] | None:
    return None if rule is None else rule.to_dict()


def build(w: dict[str, Any]) -> dict[str, Any]:
    data, regions, rules = w["data"], w["regions"], w["rules"]
    abilities, custom_rules, options = w["abilities"], w["custom_rules"], w["options"]
    option_fields = options.BugFablesOptions.type_hints
    option_names = {f"{cls.__module__}.{cls.__name__}": name for name, cls in option_fields.items()}
    sent = set(w["slot_data"].SLOT_OPTIONS)

    door_of = {data.door_name(end.map, end.door): {"map": end.map, "door": end.door}
               for c in data.DOORS.connections for end in (c.a, c.b)}
    one_way_of = {data.door_name(d.map, d.door): {"map": d.map, "door": d.door} for d in data.ONE_WAYS}
    entrances = []
    for e in regions.logic_entrances():
        entrance = {"name": e.name, "from": e.from_map, "to": e.to_map, "rule": rule_dict(e.rule)}
        if e.name in door_of:
            entrance["door"] = door_of[e.name]
        elif e.name in one_way_of:
            entrance["one_way"] = one_way_of[e.name]
        entrances.append(entrance)
    partners = {}
    for c in data.DOORS.connections:
        partners[f"{c.a.map}|{c.a.door}"] = c.b.map
        partners[f"{c.b.map}|{c.b.door}"] = c.a.map

    locations = [{"id": data.LOCATION_NAME_TO_ID[loc.name], "name": loc.name, "region": loc.region,
                  "category": loc.category, "rule": rule_dict(rules.spot_rule(loc))} for loc in data.LOCATIONS]
    events = [{"name": e.name, "item": e.item, "region": e.region, "category": e.category,
               "rule": rule_dict(rules.spot_rule(e))} for e in data.STORY_EVENTS]
    events += [{"name": a.name, "item": "Artifact", "region": a.region, "rule": rule_dict(rules.spot_rule(a))}
               for a in data.ARTIFACTS]
    event_items = {e["item"] for e in events}

    # Every item a rule can need, and the most copies one asks for.
    needed: dict[str, int] = {}
    for spot in (*entrances, *locations, *events):
        for part in walk(spot["rule"]) if spot["rule"] else ():
            if part["rule"] not in SUPPORTED_RULES:
                raise SystemExit(f"{spot['name']}: the pack's Lua has no rule {part['rule']!r}")
            for f in part.get("options", ()):
                if option_names.get(f["option"]) not in sent:
                    raise SystemExit(f"{spot['name']}: {f['option']} isn't in slot_data's options")
            args = part.get("args", {})
            if part["rule"] == "Has":
                needed[args["item_name"]] = max(needed.get(args["item_name"], 0), args["count"])
            elif part["rule"] == "HasAllCounts":
                for name, count in args["item_counts"].items():
                    needed[name] = max(needed.get(name, 0), count)
    for name, ability in abilities.ABILITIES.items():
        needed[ability.item] = max(needed.get(ability.item, 0), ability.level)
        if ability.holder:
            needed[ability.holder] = max(needed.get(ability.holder, 0), 1)
    for level, name in custom_rules.BOAT_LEVELS.items():
        needed[name] = max(needed.get(name, 0), 1)
        needed["Progressive Boat"] = max(needed.get("Progressive Boat", 0), level)
    for name in w["items"].MEMBERS:
        needed[name] = max(needed.get(name, 0), 1)
    # A story event's item may also be a real item (a member who joins in the story, or arrives as an item).
    tracked = {name: count for name, count in needed.items() if name in data.ITEM_NAME_TO_ID}
    unknown = sorted(set(needed) - set(tracked) - event_items)
    if unknown:
        raise SystemExit(f"rules name items the world doesn't have: {unknown}")
    kinds = {item.name: item.kind for item in data.ITEMS}
    items = sorted(({"name": name, "code": code_of(name), "id": data.ITEM_NAME_TO_ID[name], "kind": kinds[name],
                     "max": count} for name, count in tracked.items()), key=lambda i: (i["kind"], i["id"]))

    party = options.StartingPartyMember
    default_member = {party.option_off: -1, party.option_all_three: 3}.get(party.default, party.default - party.option_vi)
    defaults = {}
    for name in w["slot_data"].SLOT_OPTIONS:
        option = option_fields[name]
        default = option.default
        defaults[name] = bool(default) if issubclass(option, options.Toggle) else default
    return {
        "world_version": data.WORLD_VERSION,
        "origin": regions.MENU,
        "entrances": entrances,
        "partners": partners,
        "one_way_to": {f"{d.map}|{d.door}": d.to for d in data.ONE_WAYS},
        "locations": locations,
        "events": events,
        "items": items,
        "members": list(w["items"].MEMBERS),
        "late_member": custom_rules.LATE_MEMBER,
        "boat_levels": {str(level): name for level, name in custom_rules.BOAT_LEVELS.items()},
        "abilities": {name: {"holder": a.holder, "item": a.item, "level": a.level, "base_option": a.base_option}
                      for name, a in abilities.ABILITIES.items()},
        "category_options": dict(options.CATEGORY_OPTIONS),
        "option_names": option_names,
        "option_defaults": defaults,
        "starting_member_default": default_member,
    }


# Lua source for the data: a table literal.

def lua(value: Any, indent: str = "") -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'
    inner = indent + "  "
    if isinstance(value, dict):
        parts = [f"{inner}[{key if isinstance(key, int) else lua(str(key))}] = {lua(item, inner)},"
                 for key, item in value.items() if item is not None]
    else:
        parts = [f"{inner}{lua(item, inner)}," for item in value]
    return "{\n" + "\n".join(parts) + "\n" + indent + "}" if parts else "{}"


# A PNG from rows of RGBA pixels, with the standard library only.

def encode_png(width: int, height: int, rows: list[bytes]) -> bytes:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def png(width: int, height: int, pixel) -> bytes:
    return encode_png(width, height, [b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height)])


class Canvas:
    """RGBA pixels drawn by code."""

    def __init__(self, width: int, height: int, color: tuple[int, int, int, int]) -> None:
        self.width, self.height = width, height
        self.pixels = bytearray(bytes(color) * (width * height))

    def disc(self, cx: float, cy: float, radius: float, color: tuple[int, int, int, int], hole: float = -1) -> None:
        for y in range(int(cy - radius), int(cy + radius) + 2):
            for x in range(int(cx - radius), int(cx + radius) + 2):
                d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if hole < d <= radius and 0 <= x < self.width and 0 <= y < self.height:
                    i = (y * self.width + x) * 4
                    self.pixels[i:i + 4] = bytes(color)

    def line(self, a: tuple[float, float], b: tuple[float, float], width: float,
             color: tuple[int, int, int, int]) -> None:
        steps = max(1, int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))))
        for n in range(steps + 1):
            t = n / steps
            self.disc(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, width / 2, color)

    def box(self, x0: float, y0: float, x1: float, y1: float, fill: tuple[int, int, int, int],
            edge: tuple[int, int, int, int]) -> None:
        left, top = max(0, int(x0)), max(0, int(y0))
        right, bottom = min(self.width - 1, int(x1)), min(self.height - 1, int(y1))
        for y in range(top, bottom + 1):
            row = bytes(edge if y - top < 2 or bottom - y < 2 else fill)
            for x in range(left, right + 1):
                i = (y * self.width + x) * 4
                self.pixels[i:i + 4] = bytes(edge) if x - left < 2 or right - x < 2 else row

    def png(self) -> bytes:
        stride = self.width * 4
        return encode_png(self.width, self.height,
                          [bytes(self.pixels[y * stride:(y + 1) * stride]) for y in range(self.height)])


def hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


def square_icon(color: tuple[int, int, int], size: int = 32, hollow: bool = False) -> bytes:
    edge = tuple(c // 2 for c in color)

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        border = min(x, y, size - 1 - x, size - 1 - y)
        if border < 2:
            return (*edge, 255)
        return (0, 0, 0, 0) if hollow else (*color, 255)
    return png(size, size, pixel)


Rect = tuple[float, float, float, float]


def overlaps(a: Rect, b: Rect, gap: float) -> bool:
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


def logic_doors(room_data: dict[str, dict], doors: Any) -> dict[str, dict]:
    """The dump's rooms with only the logic's doors (the apworld's data/doors.json), each marked two-way or one-way.
    A fixed link names only its two maps, and the dump also lists story transitions between them (a sign, an NPC), so
    it keeps the door nearest its room's edge, where load zones sit. Story copies are dropped."""
    two_way = {(e.map, e.door) for c in doors.connections for e in (c.a, c.b)}
    one_way = {(w.map, w.door) for w in doors.one_way}
    fixed = {tuple(f) for f in doors.fixed}
    out = {}
    for name, room in room_data.items():
        b = room["bounds"]

        def edge(door: dict) -> float:
            return min(door["at"][0] - b[0], b[2] - door["at"][0], door["at"][1] - b[1], b[3] - door["at"][1])
        kept = []
        for door in room["doors"]:
            key = (name, door["name"])
            if key in two_way:
                kept.append(door | {"kind": "two-way"})
            elif key in one_way:
                kept.append(door | {"kind": "one-way"})
        for to in sorted({d["to"] for d in room["doors"] if (name, d["to"]) in fixed}):
            kept.append(min((d for d in room["doors"] if d["to"] == to), key=edge) | {"kind": "two-way"})
        out[name] = {"bounds": b, "doors": kept}
    return out


def insides(names: list[str], rooms: dict[str, dict]) -> dict[str, tuple[str, list[float]]]:
    """Side rooms: a room with one way in, entered through a door inside another room (a house in a town, its cellar)
    or one whose spot by its door would sit on that room (a hall's back-wall doors), each with the room it hangs off
    and that door's spot there. Peeled from the ends inwards: a cellar hangs off its house, the house off its town.
    They're drawn as a small box at the door, since their own frame would sit on the room they're entered from."""
    inside = set(names)
    neighbours: dict[str, set[str]] = {n: set() for n in names}
    door_of: dict[tuple[str, str], dict] = {}
    for n in names:
        for d in rooms[n]["doors"]:
            if d["to"] in inside and d["to"] != n and d["kind"] == "two-way":
                neighbours[n].add(d["to"])
                neighbours[d["to"]].add(n)
                door_of.setdefault((n, d["to"]), d)

    def side_room(parent: str, room: str) -> bool:
        door, b = door_of[(parent, room)], rooms[parent]["bounds"]
        spot = door["at"]
        if min(spot[0] - b[0], b[2] - spot[0], spot[1] - b[1], b[3] - spot[1]) > EDGE:
            return True
        r = rooms[room]["bounds"]
        dx, dz = spot[0] - door["arrive"][0], spot[1] - door["arrive"][1]
        return overlaps((r[0] + dx, r[1] + dz, r[2] + dx, r[3] + dz), tuple(b), -EDGE)

    hanging: dict[str, tuple[str, list[float]]] = {}
    changed = True
    while changed:
        changed = False
        for room in names:
            if room in hanging:
                continue
            rest = [p for p in neighbours[room] if hanging.get(p, ("",))[0] != room]
            if len(rest) != 1 or (rest[0], room) not in door_of:
                continue
            parent = rest[0]
            if side_room(parent, room):
                hanging[room] = (parent, door_of[(parent, room)]["at"])
                changed = True
    return hanging


def crosses_rooms(a: tuple[float, float], b: tuple[float, float], frames: list[Rect]) -> bool:
    """Whether a line from door a to door b runs through a room, its ends' own few pixels aside."""
    steps = max(1, int(math.dist(a, b) / 4))
    for n in range(steps + 1):
        x, y = a[0] + (b[0] - a[0]) * n / steps, a[1] + (b[1] - a[1]) * n / steps
        if min(math.dist((x, y), a), math.dist((x, y), b)) < 12:
            continue
        if any(f[0] + 3 < x < f[2] - 3 and f[1] + 3 < y < f[3] - 3 for f in frames):
            return True
    return False


def free_spot(want: tuple[float, float], taken: list[tuple[float, float]], size: float) -> tuple[float, float]:
    """The nearest point to want, spiralling out, at least size away from every taken point on both axes."""
    for ring in range(0, 200):
        for step in range(max(1, ring * 8)):
            angle = 2 * math.pi * step / max(1, ring * 8)
            spot = (want[0] + ring * 4 * math.cos(angle), want[1] + ring * 4 * math.sin(angle))
            if all(abs(spot[0] - t[0]) >= size or abs(spot[1] - t[1]) >= size for t in taken):
                return spot
    raise SystemExit("no free spot for an inside room")


def layout_area(names: list[str], rooms: dict[str, dict]) -> dict[str, tuple[float, float]]:
    """Each room's offset in one frame of game units: a neighbour goes where its arrival point meets the door that
    leads there (rooms keep their sides: a door on a room's right leads to a room on its right), or the nearest free
    spot when that one is taken. A door places the rooms at either end, so a room only a one-way door joins still sits
    by it. Rooms no door of the area joins make a group of their own, packed beside the rest or below, whichever keeps
    the map nearer the shape of PopTracker's map panel."""
    inside = set(names)
    # (neighbour, offset of the neighbour from this room)
    links: dict[str, list[tuple[str, tuple[float, float]]]] = {n: [] for n in names}
    for n in names:
        for d in rooms[n]["doors"]:
            # A one-way door (a fog maze's wrong turn, a drop) can loop back anywhere: it places nothing.
            if d["to"] in inside and d["to"] != n and d["kind"] == "two-way":
                delta = (d["at"][0] - d["arrive"][0], d["at"][1] - d["arrive"][1])
                links[n].append((d["to"], delta))
                links[d["to"]].append((n, (-delta[0], -delta[1])))
    placed: dict[str, tuple[float, float]] = {}
    rects: list[Rect] = []

    def rect(name: str, at: tuple[float, float]) -> Rect:
        b = rooms[name]["bounds"]
        return b[0] + at[0] - ROOM_PAD, b[1] + at[1] - ROOM_PAD, b[2] + at[0] + ROOM_PAD, b[3] + at[1] + ROOM_PAD

    def free(name: str, want: tuple[float, float], taken: list[Rect]) -> tuple[float, float]:
        for ring in range(0, 400):
            for step in range(max(1, ring * 8)):
                angle = 2 * math.pi * step / max(1, ring * 8)
                at = (want[0] + ring * FREE_STEP * math.cos(angle), want[1] + ring * FREE_STEP * math.sin(angle))
                if not any(overlaps(rect(name, at), other, ROOM_GAP) for other in taken):
                    return at
        raise SystemExit(f"{name}: no room for it")

    def place_group(root: str) -> dict[str, tuple[float, float]]:
        group = {root: (0.0, 0.0)}
        local: list[Rect] = [rect(root, (0.0, 0.0))]
        queue = [root]
        while queue:
            a = queue.pop(0)
            for b, delta in links[a]:
                if b in group:
                    continue
                group[b] = free(b, (group[a][0] + delta[0], group[a][1] + delta[1]), local)
                local.append(rect(b, group[b]))
                queue.append(b)
        return group

    for root in sorted(names, key=lambda n: (-len(links[n]), n)):
        if root in placed:
            continue
        group = place_group(root)
        box = (min(rect(n, at)[0] for n, at in group.items()), min(rect(n, at)[1] for n, at in group.items()),
               max(rect(n, at)[2] for n, at in group.items()), max(rect(n, at)[3] for n, at in group.items()))
        if not placed:
            move = (0.0, 0.0)
        else:
            whole = (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects),
                     max(r[3] for r in rects))
            beside = (whole[2] + GROUP_GAP - box[0], whole[3] - box[3])
            below = (whole[0] - box[0], whole[1] - GROUP_GAP - box[3])

            def misfit(move: tuple[float, float]) -> float:
                width = max(whole[2], box[2] + move[0]) - min(whole[0], box[0] + move[0])
                height = max(whole[3], box[3] + move[1]) - min(whole[1], box[1] + move[1])
                return abs(math.log(width / height / PANEL_SHAPE))
            move = min((beside, below), key=misfit)
        for n, at in group.items():
            placed[n] = (at[0] + move[0], at[1] + move[1])
            rects.append(rect(n, placed[n]))
    return placed


def write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archipelago", required=True, type=Path, help="your Archipelago checkout")
    args = parser.parse_args()
    w = load_world(args.archipelago.resolve())
    logic = build(w)
    logic["randomizer_commit"] = randomizer_commit(Path(w["package"].__file__).resolve().parent)

    # The world map: an area pin where the game's pause map puts its pip, its checks those of its rooms. Each area
    # with checks also has its own map: a pin per room, for now in a grid.
    pip_data = json.loads((PACK / "data/area_pips.json").read_text("utf-8"))
    pips = pip_data["areas"]
    map_area = json.loads((PACK / "data/map_areas.json").read_text("utf-8"))["maps"]
    rooms: dict[str, list[dict[str, Any]]] = {}
    for loc in sorted(logic["locations"], key=lambda loc: loc["name"]):
        if loc["region"] not in map_area:
            raise SystemExit(f"{loc['name']}: no area for map {loc['region']} (tools/map_areas.py)")
        rooms.setdefault(loc["region"], []).append(loc)
    areas = {pip["area"]: [room for room in sorted(rooms) if map_area[room] == pip["area"]] for pip in pips}
    areas = {area: names for area, names in areas.items() if names}
    for room, locs in rooms.items():
        if "/" in room or any("/" in loc["name"] for loc in locs):
            raise SystemExit(f"{room}: a '/' would break PopTracker's @location/section paths")

    left, right = min(p["x"] for p in pips), max(p["x"] for p in pips)
    low, high = min(p["z"] for p in pips), max(p["z"] for p in pips)
    world_size = (round((right - left) * WORLD_SCALE) + 2 * WORLD_MARGIN,
                  round((high - low) * WORLD_SCALE) + 2 * WORLD_MARGIN)
    # As the pause map shows them: +x to the left, +z down.
    spots = {p["area"]: (WORLD_MARGIN + round((right - p["x"]) * WORLD_SCALE),
                         WORLD_MARGIN + round((p["z"] - low) * WORLD_SCALE)) for p in pips}
    world = Canvas(*world_size, (30, 34, 44, 255))
    for a, b in pip_data["lines"]:
        world.line(spots[a], spots[b], 4, (150, 98, 52, 255))
    for x, y in spots.values():
        world.disc(x, y, 9, (110, 116, 130, 255), hole=6)

    maps_json = [{"name": WORLD_MAP, "location_size": 30, "location_border_thickness": 2,
                  "img": f"images/maps/{WORLD_MAP}.png"}]
    write(PACK / f"images/maps/{WORLD_MAP}.png", world.png())
    locations_json = []
    section_paths = {}
    room_data = logic_doors(json.loads((PACK / "data/rooms.json").read_text("utf-8"))["maps"], w["data"].DOORS)
    logic_maps = set(w["data"].MAPS)
    for area, names in areas.items():
        # Every room of the area is drawn, the rooms with checks also get a pin.
        # The logic's maps only: a test or cutscene map that's no region of the apworld is never drawn.
        every = sorted(m for m, a in map_area.items() if a == area and m in room_data and m in logic_maps)
        missing = [room for room in names if room not in every]
        if missing:
            raise SystemExit(f"rooms with checks but no room data (tools/rooms.py): {missing}")
        hanging = insides(every, room_data)
        at = layout_area([n for n in every if n not in hanging], room_data)

        def frame(name: str) -> Rect:
            b = room_data[name]["bounds"]
            return b[0] + at[name][0], b[1] + at[name][1], b[2] + at[name][0], b[3] + at[name][1]
        frames = {name: frame(name) for name in at}
        left = min(f[0] for f in frames.values()) - 2 * ROOM_PAD
        right = max(f[2] for f in frames.values()) + 2 * ROOM_PAD
        low = min(f[1] for f in frames.values()) - 2 * ROOM_PAD
        high = max(f[3] for f in frames.values()) + 2 * ROOM_PAD
        scale = AREA_SIZE / max(right - left, high - low)

        def px(x: float, z: float) -> tuple[float, float]:
            # Game x to the right, z up: as the pause map shows the areas around them.
            return (x - left) * scale, (high - z) * scale
        canvas = Canvas(round((right - left) * scale), round((high - low) * scale), (24, 27, 35, 255))
        for name, f in frames.items():
            x0, y1 = px(f[0] - ROOM_PAD, f[1] - ROOM_PAD)
            x1, y0 = px(f[2] + ROOM_PAD, f[3] + ROOM_PAD)
            canvas.box(x0, y0, x1, y1, (58, 64, 80, 255) if name in rooms else (44, 49, 61, 255),
                       (96, 104, 124, 255))
        def door_spot(room: str, door: dict) -> tuple[float, float]:
            return px(door["at"][0] + at[room][0], door["at"][1] + at[room][1])

        # One line per pair of rooms, from a door to the door that leads back (both ends a dot), where they don't
        # meet already.
        joined: set[frozenset[str]] = set()
        wraps: list[tuple[tuple[float, float], tuple[float, float], tuple[int, int, int, int]]] = []
        pixel_frames = []
        for f in frames.values():
            x0, y1 = px(f[0], f[1])
            x1, y0 = px(f[2], f[3])
            pixel_frames.append((x0, y0, x1, y1))
        for name in frames:
            for door in room_data[name]["doors"]:
                other = door["to"]
                if (door["kind"] != "two-way" or other not in frames or other == name
                        or frozenset((name, other)) in joined):
                    continue
                joined.add(frozenset((name, other)))
                spot = door_spot(name, door)
                back = [d for d in room_data[other]["doors"] if d["to"] == name and d["kind"] == "two-way"]
                end = (min((door_spot(other, d) for d in back), key=lambda p: math.dist(p, spot)) if back
                       else px(door["arrive"][0] + at[other][0], door["arrive"][1] + at[other][1]))
                if math.dist(spot, end) <= 8:
                    continue
                if crosses_rooms(spot, end, pixel_frames):
                    # Rooms that can't sit side by side (a ring of rooms, stacked floors): a pair of matching
                    # rings, one at each door, instead of a line across the map.
                    colour = WRAP_COLOURS[len(wraps) % len(WRAP_COLOURS)]
                    wraps.append((spot, end, colour))
                else:
                    canvas.line(spot, end, 3, (120, 128, 148, 255))
        for spot, end, colour in wraps:
            canvas.disc(*spot, 9, colour, hole=5)
            canvas.disc(*end, 9, colour, hole=5)
        # Doors: grey within the area, orange out of it, a ring for a one-way door (no line: it may loop anywhere).
        for name in frames:
            for door in room_data[name]["doors"]:
                spot = door_spot(name, door)
                if door["kind"] == "one-way":
                    canvas.disc(*spot, 7, (170, 120, 200, 255), hole=4)
                elif door["to"] in frames:
                    canvas.disc(*spot, 4, (170, 176, 190, 255))
                elif map_area.get(door["to"]) != area:
                    canvas.disc(*spot, 6, (200, 130, 60, 255))
        # Inside rooms: a box at the door they're entered by, parents first; a cellar's box beside its house's.
        boxes: dict[str, tuple[float, float]] = {}

        def depth(room: str) -> int:
            return 0 if room not in hanging else 1 + depth(hanging[room][0])
        for room in sorted(hanging, key=lambda r: (depth(r), r)):
            parent, spot = hanging[room]
            want = (px(spot[0] + at[parent][0], spot[1] + at[parent][1]) if parent in frames
                    else (boxes[parent][0] + INSIDE_PX + 4, boxes[parent][1]))
            boxes[room] = free_spot(want, list(boxes.values()), INSIDE_PX + 2)
            x, y = boxes[room]
            half = INSIDE_PX / 2
            canvas.box(x - half, y - half, x + half, y + half,
                       (78, 86, 106, 255) if room in rooms else (58, 64, 80, 255), (150, 158, 178, 255))
        write(PACK / f"images/maps/{area}.png", canvas.png())
        maps_json.append({"name": area, "location_size": PIN, "location_border_thickness": 2,
                          "img": f"images/maps/{area}.png"})
        for room in names:
            if room in boxes:
                x, y = boxes[room]
            else:
                f = frames[room]
                x, y = px((f[0] + f[2]) / 2, (f[1] + f[3]) / 2)
            locations_json.append({
                "name": room,
                "visibility_rules": [f"$bf_room_in_seed|{room}"],
                "chest_unopened_img": "images/chest_closed.png",
                "chest_opened_img": "images/chest_open.png",
                "map_locations": [{"map": area, "x": round(x), "y": round(y)}],
                "sections": [{"name": loc["name"], "access_rules": [f"$bf_location|{loc['id']}"],
                              "visibility_rules": [f"$bf_in_seed|{loc['id']}"]} for loc in rooms[room]],
            })
            for loc in rooms[room]:
                section_paths[loc["id"]] = f"@{room}/{loc['name']}"
        x, y = spots[area]
        locations_json.append({
            "name": display_name(area),
            "visibility_rules": [f"$bf_area_in_seed|{area}"],
            "chest_unopened_img": "images/chest_closed.png",
            "chest_opened_img": "images/chest_open.png",
            "map_locations": [{"map": WORLD_MAP, "x": x, "y": y}],
            "sections": [{"ref": f"{room}/{loc['name']}"} for room in names for loc in rooms[room]],
        })
    logic["section_paths"] = section_paths
    logic["room_areas"] = {room: map_area[room] for room in rooms}
    logic["item_codes_by_id"] = {item["id"]: item["code"] for item in logic["items"]}
    write(PACK / "layouts/maps.json", json.dumps({"map_tabs": {"type": "tabbed", "tabs": [
        {"title": "World", "content": {"type": "map", "maps": [WORLD_MAP]}},
        *({"title": display_name(area), "content": {"type": "map", "maps": [area]}} for area in areas),
    ]}}, indent=2) + "\n")

    items_json = []
    for n, item in enumerate(logic["items"]):
        image = f"images/items/{item['code']}.png"
        write(PACK / image, square_icon(hsv(n / len(logic["items"]), 0.55, 0.85)))
        entry = {"name": item["name"], "img": image, "codes": item["code"]}
        if item["max"] > 1:
            entry |= {"type": "consumable", "max_quantity": item["max"]}
        else:
            entry["type"] = "toggle"
        items_json.append(entry)

    rows: list[list[str]] = []
    for kind in sorted({item["kind"] for item in logic["items"]}):
        codes = [item["code"] for item in logic["items"] if item["kind"] == kind]
        rows += [codes[i:i + 6] for i in range(0, len(codes), 6)]
    write(PACK / "layouts/item_grid.json", json.dumps({"item_grid": {
        "type": "itemgrid", "item_margin": "2,2", "item_size": "32,32", "h_alignment": "left", "rows": rows,
    }}, indent=2) + "\n")
    write(PACK / "scripts/generated/logic_data.lua",
          "-- Generated by tools/export.py from the Bug Fables apworld: never edit by hand.\nreturn "
          + lua(logic) + "\n")
    write(PACK / "items/items.json", json.dumps(items_json, indent=2) + "\n")
    write(PACK / "locations/locations.json", json.dumps(locations_json, indent=2, ensure_ascii=False) + "\n")
    write(PACK / "maps/maps.json", json.dumps(maps_json, indent=2) + "\n")
    write(PACK / "images/chest_closed.png", square_icon((200, 170, 90), 24))
    write(PACK / "images/chest_open.png", square_icon((120, 120, 120), 24, hollow=True))
    print(f"world {logic['world_version']} at {logic['randomizer_commit']}: {len(logic['entrances'])} entrances, "
          f"{len(logic['locations'])} locations in {len(rooms)} rooms of {len(areas)} areas, "
          f"{len(logic['events'])} events, "
          f"{len(logic['items'])} items")


if __name__ == "__main__":
    main()
