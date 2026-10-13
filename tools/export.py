"""Writes the pack's generated files from the Bug Fables apworld: its logic as Rule Builder's to_dict writes each rule
(scripts/generated/logic_data.lua), the items, the locations, each area's map drawn by code, and placeholder icons.
The World tab's map is the game's own (tools/world_map.py).

    python tools/export.py --archipelago <your Archipelago checkout>

The checkout has the randomizer's apworld linked in as worlds/bug_fables (the randomizer's development.md).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import zlib
from collections import Counter
from pathlib import Path
from typing import Any

PACK = Path(__file__).resolve().parent.parent
# Rules the pack's Lua evaluates (scripts/logic.lua): Archipelago's and the apworld's own (its custom_rules.py).
SUPPORTED_RULES = {"And", "Or", "Has", "HasAllCounts", "HasFromListUnique", "True_", "False_", "Filtered",
                   "CanReachRegion", "CanUse", "Member", "MoveItem", "Boat", "WayBack"}
# World attributes a FromWorldAttr resolver may name, each the slot_data option sending its value (slot_data.py).
WORLD_ATTRS = {"artifacts_required": "artifacts_required"}
# Option filter operators (rule_builder/options.py), each only on the kind of option the Lua compares it for.
NUMBER_OPERATORS = {"eq", "ne", "gt", "lt", "ge", "le"}
WORLD_MAP = "World"
WORLD_PIN = 56
ROOM_PIN = 36  # a check's pin on its room's picture
# The item grid (the user's pick, 2026-10-13): these after the keys and passes, the gears and the boats a row of their
# own.
OTHER_ITEMS = ("G-Bug Ranger Plushie", "Quest Book", "Sun Offering", "Moon Offering", "Extra Freeze")
GOAL_LOOK = "Wasp King's Crown"
# The Events group (the user's pick, 2026-10-13): the story's milestones among the logic's events, each the game's own
# flag, marked by hand for now; with a short word for its drawn icon.
EVENT_ITEMS = {"Snakemouth Den Cleared": "Boss 1", "Chapter 2 Started": "Ch. 2", "Mothiva's Show Seen": "Mothiva",
               "B.O.S.S. Unlocked": "B.O.S.S.", "Malbee's Fight Done": "Malbee",
               "Giant's Lair Bridge Fight Won": "Bridge", "Outside the Fridge Fight Won": "Fridge",
               "Roach Village Scene Seen": "Roaches"}
WAY_ITEMS = ("Small Gear", "Medium Gear", "Big Gear", "Boat Ticket", "Subaquatic Maritime Neotransport",
             "Progressive Boat")


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
    from worlds.bug_fables.world import BugFablesWorld
    return {"package": package, "abilities": abilities, "custom_rules": custom_rules, "data": data_tables,
            "items": items, "logic": logic, "options": options, "regions": regions, "rules": rules,
            "slot_data": slot_data, "world": BugFablesWorld}


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


def check_filter(where: str, f: dict[str, Any], option: type) -> None:
    """Only filters the Lua compares as Archipelago does: a number against a toggle, choice or range; a name in an
    option set ("contains"); the option's number in a list of numbers ("in")."""
    from Options import NumericOption, OptionSet, TextChoice
    op, value = f.get("operator", "eq"), f["value"]
    numeric = issubclass(option, NumericOption) and not issubclass(option, TextChoice)
    if op in NUMBER_OPERATORS:
        ok = numeric and isinstance(value, int)
    elif op == "contains":
        ok = issubclass(option, OptionSet) and isinstance(value, str)
    elif op == "in":
        ok = numeric and isinstance(value, list) and all(isinstance(v, int) for v in value)
    else:
        ok = False
    if not ok:
        raise SystemExit(f"{where}: an option filter the pack's Lua can't compare: {f}")


def build(w: dict[str, Any]) -> dict[str, Any]:
    from Options import OptionSet, Toggle
    data, regions, rules = w["data"], w["regions"], w["rules"]
    abilities, custom_rules, options = w["abilities"], w["custom_rules"], w["options"]
    option_fields = options.BugFablesOptions.type_hints
    option_names = {f"{cls.__module__}.{cls.__name__}": name for name, cls in option_fields.items()}
    sent = set(w["slot_data"].SLOT_OPTIONS)
    known_regions = {regions.MENU, *data.REGIONS}
    area_region = {(a.map, a.name): a.region for a in data.MAP_AREAS}

    def region_of(spot: Any) -> str:
        """A spot's region: its map's, or its map area's (locations.py places them the same way)."""
        return spot.region if getattr(spot, "area", None) is None else area_region[(spot.region, spot.area)]

    door_of = {data.door_name(end.map, end.door): {"map": end.map, "door": end.door}
               for c in data.DOORS.connections for end in (c.a, c.b)}
    one_way_of = {data.door_name(d.map, d.door): {"map": d.map, "door": d.door} for d in data.ONE_WAYS}
    entrances = []
    for e in regions.logic_entrances():
        entrance = {"name": e.name, "from": e.from_map, "to": e.to_map, "rule": rule_dict(e.rule)}
        if e.from_map == regions.MENU:
            # A seed's own start replaces it (regions.py, create_and_connect_regions).
            entrance["start"] = True
        elif e.name in door_of:
            entrance["door"] = door_of[e.name]
        elif e.name in one_way_of:
            entrance["one_way"] = one_way_of[e.name]
        entrances.append(entrance)
    # Where each door leads in the game, as entrances.py connects it: to the region its partner stands in (a door
    # given door_targets' like_door leads where like_door leads, arriving at like_door's partner).
    partners = {}
    for c in data.DOORS.connections:
        for end, other in ((c.a, c.b), (c.b, c.a)):
            partners[f"{end.map}|{end.door}"] = {"region": data.door_region(other.map, other.door),
                                                 "map": other.map, "door": other.door}

    # Pending locations (a quest not yet gone through) are in no seed (world.py).
    # A quiet location (the opening's) sits in Menu when the seed has its own start (locations.py).
    locations = [{"id": data.LOCATION_NAME_TO_ID[loc.name], "name": loc.name, "region": region_of(loc),
                  "map": loc.region, "category": loc.category, "quiet": loc.quiet or None,
                  "rule": rule_dict(rules.spot_rule(loc))}
                 for loc in data.LOCATIONS if not loc.pending]
    # The artifacts' scenes are ordinary locations since the apworld's build step 86, so in the list above.
    events = [{"name": e.name, "item": e.item, "region": region_of(e), "map": e.region, "category": e.category,
               "rule": rule_dict(rules.spot_rule(e))} for e in data.STORY_EVENTS]
    event_items = {e["item"] for e in events}
    for spot in (*locations, *events):
        if spot["region"] not in known_regions:
            raise SystemExit(f"{spot['name']}: no region {spot['region']!r}")
    for e in entrances:
        if e["from"] not in known_regions or e["to"] not in known_regions:
            raise SystemExit(f"{e['name']}: a region the world doesn't have")

    # Every item a rule can need, and the most copies one asks for.
    needed: dict[str, int] = {}
    for spot in (*entrances, *locations, *events):
        for part in walk(spot["rule"]) if spot["rule"] else ():
            if part["rule"] not in SUPPORTED_RULES:
                raise SystemExit(f"{spot['name']}: the pack's Lua has no rule {part['rule']!r}")
            for f in part.get("options", ()):
                name = option_names.get(f["option"])
                if name not in sent:
                    raise SystemExit(f"{spot['name']}: {f['option']} isn't in slot_data's options")
                check_filter(spot["name"], f, option_fields[name])
            args = part.get("args", {})
            for key, value in args.items():
                if isinstance(value, dict) and "resolver" in value and not (
                        part["rule"] == "HasFromListUnique" and key == "count"
                        and value["resolver"] == "FromWorldAttr" and value.get("name") in WORLD_ATTRS):
                    raise SystemExit(f"{spot['name']}: a field resolver the pack's Lua can't evaluate: {value}")
            if part["rule"] == "CanReachRegion" and args["region_name"] not in known_regions:
                raise SystemExit(f"{spot['name']}: no region {args['region_name']!r}")
            if part["rule"] == "Has":
                needed[args["item_name"]] = max(needed.get(args["item_name"], 0), args["count"])
            elif part["rule"] == "HasAllCounts":
                for name, count in args["item_counts"].items():
                    needed[name] = max(needed.get(name, 0), count)
            elif part["rule"] == "HasFromListUnique":
                for name in args["item_names"]:
                    needed[name] = max(needed.get(name, 0), 1)
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
        if issubclass(option, Toggle):
            default = bool(default)
        elif issubclass(option, OptionSet):
            # As slot_data sends a set: a sorted list.
            default = sorted(default)
        defaults[name] = default
    return {
        "world_version": w["world"].world_version.as_simple_string(),
        "origin": regions.MENU,
        "entrances": entrances,
        # slot_data's start ("map|from|door") and the region it begins in; its entrance's name.
        "start_entrance": regions.START_ENTRANCE,
        "start_regions": {f"{s.map}|{s.from_map}|{s.door}": data.start_region(s.to_slot()) for s in data.ROOM_STARTS},
        "partners": partners,
        "one_way_to": {f"{d.map}|{d.door}": {"region": data.landing_region(d), "map": d.to} for d in data.ONE_WAYS},
        # The map each part of a map belongs to (a map's own region is its name).
        "region_maps": {a.region: a.map for a in data.MAP_AREAS},
        # A one-way door's story copies, other doors in the game, are its one entrance in the doors key.
        "one_way_copies": {data.door_name(d.map, copy): data.door_name(d.map, d.door)
                           for d in data.ONE_WAYS for copy in d.copies},
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
        "world_attrs": WORLD_ATTRS,
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


def hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    i = int(h * 6) % 6
    f = h * 6 - int(h * 6)
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]
    return int(r * 255), int(g * 255), int(b * 255)


def labelled_icon(color: tuple[int, int, int], word: str, size: int = 64) -> bytes:
    """A drawn round icon with a word on it, for what the game has no picture of (an event)."""
    from PIL import Image, ImageDraw, ImageFont
    import io
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, size - 3, size - 3), fill=(*color, 255), outline=(20, 20, 20, 255), width=3)
    points = 16
    while points > 8 and draw.textlength(word, font=ImageFont.load_default(size=points)) > size - 10:
        points -= 1
    font = ImageFont.load_default(size=points)
    draw.text(((size - draw.textlength(word, font=font)) / 2, size / 2 - points * 0.6), word, font=font,
              fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def square_icon(color: tuple[int, int, int], size: int = 32, hollow: bool = False) -> bytes:
    edge = tuple(c // 2 for c in color)

    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        border = min(x, y, size - 1 - x, size - 1 - y)
        if border < 2:
            return (*edge, 255)
        return (0, 0, 0, 0) if hollow else (*color, 255)
    return png(size, size, pixel)


def logic_doors(room_data: dict[str, dict], doors: Any) -> dict[str, dict]:
    """The dump's rooms with only the logic's doors (the apworld's data/doors.json), each marked two-way or one-way.
    A fixed link names only its two maps, and the dump also lists story transitions between them (a sign, an NPC), so
    it keeps the door nearest its room's edge, where load zones sit. Story copies are dropped."""
    two_way = {(e.map, e.door) for c in doors.connections for e in (c.a, c.b)}
    one_way = {(w.map, w.door) for w in doors.one_way}
    fixed = {tuple(f) for f in doors.fixed}
    out = {}
    found = set()
    for name, room in room_data.items():
        b = room["bounds"]

        def edge(door: dict) -> float:
            return min(door["at"][0] - b[0], b[2] - door["at"][0], door["at"][1] - b[1], b[3] - door["at"][1])
        # Two doors of one name are told apart by their row, "name#row", as doors.json names them.
        alike = Counter(d["name"] for d in room["doors"])
        kept = []
        for door in room["doors"]:
            key = (name, door["name"] if alike[door["name"]] < 2 else f"{door['name']}#{door['index']}")
            if key in two_way:
                kept.append(door | {"kind": "two-way"})
            elif key in one_way:
                kept.append(door | {"kind": "one-way"})
            else:
                continue
            found.add(key)
        for to in sorted({d["to"] for d in room["doors"] if (name, d["to"]) in fixed}):
            kept.append(min((d for d in room["doors"] if d["to"] == to), key=edge) | {"kind": "two-way"})
        out[name] = {"bounds": b, "doors": kept}
    missing = sorted(key for key in two_way | one_way if key[0] in room_data and key not in found)
    if missing:
        raise SystemExit(f"doors.json doors with no door in the room data (tools/rooms.py): {missing}")
    return out


def rule_text(rule: dict[str, Any] | None) -> str:
    """What a rule asks, in words: its items, abilities and members, "or" between ways and "and" within one."""
    if rule is None:
        return "nothing"
    kind, args = rule["rule"], rule.get("args", {})
    if kind == "Has":
        return args["item_name"] + (f" x{args['count']}" if args.get("count", 1) > 1 else "")
    if kind == "HasAllCounts":
        return " and ".join(f"{name} x{n}" if n > 1 else name for name, n in args["item_counts"].items())
    if kind == "HasFromListUnique":
        count = args["count"]
        return f"{'the set number of' if isinstance(count, dict) else count} of {', '.join(args['item_names'])}"
    if kind in ("CanUse", "MoveItem"):
        return args["ability"]
    if kind == "Member":
        return args["name"]
    if kind == "Boat":
        return f"the boat ({args['level']})"
    if kind == "CanReachRegion":
        return f"reaching {args['region_name']}"
    if kind in ("Filtered", "WayBack"):
        return rule_text(rule["child"])
    if kind == "True_":
        return "nothing"
    if kind == "False_":
        return "no way"
    parts = list(dict.fromkeys(rule_text(child) for child in rule["children"]))
    if kind == "And":
        return " and ".join(f"({part})" if " or " in part else part for part in parts)
    return " or ".join(f"({part})" if " and " in part else part for part in parts)


def door_spot(rooms: dict[str, dict], room: str, door: str) -> list[float] | None:
    """A door's spot in its room (x, z, height), by its name as doors.json gives it ("name#row" for one of two
    alike)."""
    name, _, row = door.partition("#")
    return next(([*d["at"], d["y"]] for d in rooms.get(room, {}).get("doors", ())
                 if d["name"] == name and (not row or d["index"] == int(row))), None)


def walking_order(every: list[str], starts: list[str], rooms: dict[str, dict]) -> list[str]:
    """An area's rooms in walking order: from its first start, through the doors, nearest first (a door's row order);
    the rooms no door of the area reaches after, each from itself."""
    inside = set(every)
    order: list[str] = []
    seen: set[str] = set()
    for start in [*starts, *every]:
        if start in seen:
            continue
        seen.add(start)
        queue = [start]
        while queue:
            room = queue.pop(0)
            order.append(room)
            for door in rooms.get(room, {}).get("doors", ()):
                if door["to"] in inside and door["to"] not in seen:
                    seen.add(door["to"])
                    queue.append(door["to"])
    return order


def room_title(locs: list[dict[str, Any]]) -> str:
    """A room's name as the apworld's location names give it ("Area: Room, Spot"): the one most of its checks use."""
    heads = [loc["name"].partition(", ")[0] for loc in locs if ", " in loc["name"]] or [loc["name"] for loc in locs]
    return Counter(head.partition(": ")[2] or head for head in heads).most_common(1)[0][0]


def spot_name(loc: dict[str, Any]) -> str:
    """A check's own part of its name: "Area: Room, Spot" gives Spot."""
    return loc["name"].partition(", ")[2] or loc["name"].partition(": ")[2] or loc["name"]


def check_spot(source: Any, room: str, rooms: dict[str, dict]) -> list[float] | None:
    """Where a check's own entity stands in its room (x, z, height), as the apworld names it (its Source): an enemy by
    its index, an item on the ground by its activation flag, a respawning pickup by its regional flag, a crystal berry
    by its number (its pickup's data: type 3, the number last), a shop's goods by their keeper, a character by its
    name."""
    def first(test) -> list[float] | None:
        return next(([*e["at"], e["y"]] for e in rooms.get(room, {}).get("entities", ()) if test(e)), None)
    if source.enemy:
        enemy_map, index = source.enemy.split(":")
        return first(lambda e: e["index"] == int(index)) if enemy_map == room else None
    if source.pickup is not None and source.flag is not None:
        return first(lambda e: e["flag"] == source.flag) if source.pickup.map == room else None
    if source.regional is not None:
        return first(lambda e: e["regional"] == source.regional)
    if source.berry is not None:
        # A dig spot holding one: data 1, then the berry's number (NPCControl's crystalbflags[data[1]]).
        return first(lambda e: len(e["data"].split()) >= 4 and e["data"].split()[0] == "3"
                     and e["data"].split()[-1] == str(source.berry)) \
            or first(lambda e: e["type"] == "DigSpot" and e["data"].split()[:2] == ["1", str(source.berry)])
    if source.item_shop is not None:
        return first(lambda e: e["name"] == source.item_shop.keeper) if source.item_shop.map == room else None
    if source.npc:
        return first(lambda e: e["name"] == source.npc)
    return None


def room_middle(room: dict[str, Any]) -> list[float]:
    """The middle of a room's floor (x, z, height): its entities' extent's middle, at their middle height."""
    b = room["bounds"]
    heights = sorted(e["y"] for e in room["entities"])
    return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, heights[len(heights) // 2]]


def pixel(picture: dict[str, Any], at: list[float]) -> tuple[float, float]:
    """Where a spot (x, z, height) lands in its room's picture (data/room_pictures.json); one the camera never shows,
    at the picture's edge."""
    x = (at[0] - picture["left"]) * picture["x_scale"]
    y = (picture["top"] - at[1]) * picture["z_scale"] - at[2] * picture["y_scale"]
    return min(max(x, 0), picture["size"][0]), min(max(y, 0), picture["size"][1])


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

    # The World tab: an area pin where the game's pause map puts its pip, its checks those of its rooms. Then a tab per
    # area, holding a tab per room: the room's picture, a pin at each check's spot (a map's parts, its regions in the
    # logic, share the map's tab).
    pip_data = json.loads((PACK / "data/area_pips.json").read_text("utf-8"))
    pips = pip_data["areas"]
    map_area = json.loads((PACK / "data/map_areas.json").read_text("utf-8"))["maps"]
    rooms: dict[str, list[dict[str, Any]]] = {}
    for loc in sorted(logic["locations"], key=lambda loc: loc["name"]):
        if loc["map"] not in map_area:
            raise SystemExit(f"{loc['name']}: no area for map {loc['map']} (tools/map_areas.py)")
        rooms.setdefault(loc["map"], []).append(loc)
    # A tab per region: areas grouped as the world map's picture groups them, in story order (data/area_pips.json),
    # each area's own name the game's.
    area_names = pip_data["names"]
    tab_area = {area: region["name"] for region in pip_data["regions"] for area in region["areas"]}
    if sorted(tab_area) != sorted(p["area"] for p in pips) or sorted(area_names) != sorted(tab_area):
        raise SystemExit("data/area_pips.json: each area needs its name and exactly one region")
    order = [area for region in pip_data["regions"] for area in region["areas"]]
    raw_rooms = json.loads((PACK / "data/rooms.json").read_text("utf-8"))["maps"]
    areas = {area: [room for room in sorted(rooms) if map_area[room] == area] for area in order}
    for room, locs in rooms.items():
        if "/" in room or any("/" in loc["name"] for loc in locs):
            raise SystemExit(f"{room}: a '/' would break PopTracker's @location/section paths")

    # The game's own pause map (tools/world_map.py), each pip where the game puts it.
    world_map = json.loads((PACK / "data/world_map.json").read_text("utf-8"))
    spots = {p["area"]: tuple(round(world_map["origin"][i] + p["x"] * world_map["x_step"][i]
                                    + p["z"] * world_map["z_step"][i]) for i in (0, 1)) for p in pips}
    maps_json = [{"name": WORLD_MAP, "location_size": WORLD_PIN, "location_border_thickness": 3,
                  "img": f"images/maps/{WORLD_MAP}.png"}]
    locations_json = []
    section_paths = {}
    # Every door of the logic's is in the room data, for the doors' pins to come.
    logic_doors(raw_rooms, w["data"].DOORS)
    room_pictures = json.loads((PACK / "data/room_pictures.json").read_text("utf-8"))["rooms"]
    sources = {w["data"].LOCATION_NAME_TO_ID[loc.name]: loc.source for loc in w["data"].LOCATIONS}
    logic_maps = set(w["data"].MAPS)
    # Each room with a tab: its area's tab and its own.
    map_tabs: dict[str, dict[str, Any]] = {}
    # Each region's area tabs, each with its room tabs, in order.
    tab_rooms: dict[str, dict[str, list[dict[str, Any]]]] = {}
    location_names: set[str] = set()
    walked: dict[str, int] = {}  # each room of the areas before, by its place in the walking order
    parts_of: dict[str, list[Any]] = {}  # each room's parts a roadblock cuts off (MAP_AREAS)
    for part in w["data"].MAP_AREAS:
        parts_of.setdefault(part.map, []).append(part)
    gates_of: dict[str, list[Any]] = {}  # each room's doors that are gates (DOOR_RULES)
    for gate in w["data"].DOOR_RULES:
        gates_of.setdefault(gate.map, []).append(gate)
    entrance_names = {e["name"] for e in logic["entrances"]}
    door_parts = {e["from"] for e in logic["entrances"] if "door" in e or "one_way" in e}  # parts on a way onward
    ability_items = {a["item"] for a in logic["abilities"].values()} | set(logic["members"]) | {"Jump"}

    def road_block(rule: dict[str, Any] | None) -> bool:
        """Something in the road, as crystal-ap-tracker's Sudowoodo: a key item or a story step (a guard, a lock, a
        bridge), or one ability that breaks or clears it (a boulder, a mound); not the terrain, a ledge to jump."""
        if rule is not None and rule["rule"] == "CanUse":
            return rule["args"]["ability"] != "Jump"
        needs = {part["args"]["item_name"] for part in walk(rule) if part["rule"] == "Has"} if rule else set()
        needs |= {name for part in walk(rule) if part["rule"] == "HasAllCounts"
                  for name in part["args"]["item_counts"]} if rule else set()
        return bool(needs - ability_items) or any(part["rule"] == "Boat" for part in walk(rule)) if rule else False
    blocker_count = 0
    placed = 0
    for area, names in areas.items():
        # Every room of the area has a tab, the logic's maps only: a test or cutscene map that's no region of the
        # apworld has none.
        every = sorted(m for m, a in map_area.items() if a == area and m in logic_maps and m in room_pictures)
        missing = [room for room in names if room not in every]
        if missing:
            raise SystemExit(f"rooms with checks but no picture (tools/room_pictures.py): {missing}")
        if not every:
            continue
        # Its rooms' tabs in walking order: from the game's start, or from the room whose door leads to the earliest
        # room walked before it.
        def entered_from(room: str) -> int:
            return min((walked[d["to"]] for d in raw_rooms.get(room, {}).get("doors", ()) if d["to"] in walked),
                       default=len(walked))
        starts = [e["to"] for e in logic["entrances"] if e.get("start") and e["to"] in every]
        starts += sorted((room for room in every if entered_from(room) < len(walked)), key=entered_from)
        every = walking_order(every, starts, raw_rooms)
        walked.update({room: len(walked) + n for n, room in enumerate(every)})
        # A room's checks, each a section, shown at their spots on its tab and on its area's pin on the World tab.
        for room in names:
            locations_json.append({
                "name": room,
                "visibility_rules": [f"$bf_room_in_seed|{room}"],
                "chest_unopened_img": "images/chest_closed.png",
                "chest_opened_img": "images/chest_open.png",
                "sections": [{"name": loc["name"], "access_rules": [f"$bf_location|{loc['id']}"],
                              "visibility_rules": [f"$bf_in_seed|{loc['id']}"]} for loc in rooms[room]],
            })
            location_names.add(room)
            for loc in rooms[room]:
                section_paths[loc["id"]] = f"@{room}/{loc['name']}"
        if names:
            x, y = spots[area]
            locations_json.append({
                "name": area_names[area],
                "visibility_rules": [f"$bf_area_in_seed|{area}"],
                "chest_unopened_img": "images/chest_closed.png",
                "chest_opened_img": "images/chest_open.png",
                "map_locations": [{"map": WORLD_MAP, "x": x, "y": y,
                                   "restrict_visibility_rules": [f"$bf_area_seen|{area}"]}],
                "sections": [{"ref": f"{room}/{loc['name']}"} for room in names for loc in rooms[room]],
            })
            location_names.add(area_names[area])

        # Each room has its own tab, as crystal-ap-tracker's rooms: the game's picture of it, a pin at each check's
        # own spot (its entity's, check_spot), the checks with no such spot together in the room's middle. Room tabs
        # sit in their area's tab, in its region's.
        region = tab_area[area]
        titles: dict[str, str] = {}
        room_tabs = tab_rooms.setdefault(region, {}).setdefault(area_names[area], [])
        for room in every:
            # A room the apworld names only by its map (an enemy's location), or not at all, in words.
            title = base = display_name(room_title(rooms[room]) if room in rooms else room)
            n = 1
            while title in titles.values() or title in (region, area_names[area]):
                n += 1
                title = f"{base} ({n})"
            titles[room] = title
            map_tabs[room] = {"region": region, "area": area_names[area], "area_id": area, "room": title}
            picture = room_pictures[room]
            room_map = f"room_{room}"
            maps_json.append({"name": room_map, "location_size": ROOM_PIN, "location_border_thickness": 2,
                              "img": f"images/rooms/{room}.png"})
            room_tabs.append({"title": title, "content": {"type": "map", "maps": [room_map]}})
            groups: dict[tuple[int, int] | None, list[tuple[list[float] | None, dict[str, Any]]]] = {}
            for loc in rooms.get(room, ()):
                at_spot = check_spot(sources[loc["id"]], room, raw_rooms)
                groups.setdefault(at_spot and (round(at_spot[0]), round(at_spot[1])), []).append((at_spot, loc))
            for key, checks in groups.items():
                x, y = pixel(picture, checks[0][0] or room_middle(raw_rooms[room]))
                if key is None:
                    name = base = f"{title}: elsewhere in the room"
                else:
                    name = base = f"{title}: {spot_name(checks[0][1])}"
                    placed += len(checks)
                n = 1
                while name in location_names:
                    n += 1
                    name = f"{base} ({n})"
                location_names.add(name)
                ids = "|".join(str(loc["id"]) for _, loc in checks)
                locations_json.append({
                    "name": name,
                    "visibility_rules": [f"$bf_any_in_seed|{ids}"],
                    "chest_unopened_img": "images/chest_closed.png",
                    "chest_opened_img": "images/chest_open.png",
                    "map_locations": [{"map": room_map, "x": round(x), "y": round(y),
                                       "restrict_visibility_rules": [f"$bf_seen|{room}"]}],
                    "sections": [{"ref": f"{room}/{loc['name']}"} for _, loc in checks],
                })

            # What blocks the way, as crystal-ap-tracker shows its blockers: each part of the room a roadblock cuts off
            # (where its doors and checks are) and each door that is a gate (on the door), saying what it needs, lit
            # once the logic gets there.
            blockers = []
            for part in parts_of.get(room, ()):
                if part.region not in door_parts or not road_block(rule_dict(part.rule)):
                    continue
                found = [door_spot(raw_rooms, room, e[kind]["door"]) for e in logic["entrances"]
                         if e["from"] == part.region for kind in ("door", "one_way") if kind in e]
                found += [check_spot(sources[loc["id"]], room, raw_rooms) for loc in rooms.get(room, ())
                          if loc["region"] == part.region]
                found = [s for s in found if s]
                at = [sum(s[i] for s in found) / len(found) for i in range(3)] if found else None
                blockers.append((part.name, rule_dict(part.rule), f"$bf_region|{part.region}", at))
            for gate in gates_of.get(room, ()):
                # A door kept shut for good isn't a door of the logic: nothing to show.
                if w["data"].door_name(gate.map, gate.door) not in entrance_names:
                    continue
                blockers.append((gate.door.partition("#")[0], rule_dict(gate.rule),
                                 f"$bf_entrance_open|{w['data'].door_name(gate.map, gate.door)}",
                                 door_spot(raw_rooms, room, gate.door)))
            for what, rule, access, at in blockers:
                x, y = pixel(picture, at or room_middle(raw_rooms[room]))
                name = base = f"{title}: {what}"
                n = 1
                while name in location_names:
                    n += 1
                    name = f"{base} ({n})"
                location_names.add(name)
                locations_json.append({
                    "name": name,
                    "chest_unopened_img": "images/chest_closed.png",
                    "chest_opened_img": "images/chest_open.png",
                    "map_locations": [{"map": room_map, "x": round(x), "y": round(y),
                                       "restrict_visibility_rules": [f"$bf_seen|{room}"]}],
                    "sections": [{"name": f"Needs {rule_text(rule)}", "access_rules": [access]}],
                })
                blocker_count += 1
    # An area of one room shows it straight away, as crystal-ap-tracker's Power Plant: no row of one tab.
    area_tabs = [{"title": region, "content": {"type": "tabbed", "tabs": [
        {"title": area, "content": tabs[0]["content"] if len(tabs) == 1 else {"type": "tabbed", "tabs": tabs}}
        for area, tabs in region_areas.items()]}} for region, region_areas in tab_rooms.items()]
    logic["section_paths"] = section_paths
    logic["room_areas"] = {room: map_area[room] for room in rooms}
    logic["map_tabs"] = map_tabs
    logic["item_codes_by_id"] = {item["id"]: item["code"] for item in logic["items"]}
    write(PACK / "layouts/maps.json", json.dumps({"map_tabs": {"type": "tabbed", "tabs": [
        {"title": "World", "content": {"type": "map", "maps": [WORLD_MAP]}}, *area_tabs,
    ]}}, indent=2) + "\n")

    items_json = []
    # The game's own icon where it has one (tools/item_icons.py), else one drawn here.
    game_icons = json.loads((PACK / "data/item_icons.json").read_text("utf-8"))["icons"]
    for n, item in enumerate(logic["items"]):
        image = game_icons.get(item["code"])
        if image is None:
            image = f"images/items/{item['code']}.png"
            write(PACK / image, square_icon(hsv(n / len(logic["items"]), 0.55, 0.85)))
        entry = {"name": item["name"], "img": image, "codes": item["code"]}
        if item["max"] > 1:
            entry |= {"type": "consumable", "max_quantity": item["max"]}
        else:
            entry["type"] = "toggle"
        items_json.append(entry)

    # Not an Archipelago item: lit once the server reports the goal (autotracking.lua).
    # Its look the last artifact's, the Wasp King's Crown (the user's pick, 2026-10-13).
    goal_image = game_icons.get(code_of(GOAL_LOOK))
    if goal_image is None:
        goal_image = "images/items/goal.png"
        write(PACK / goal_image, square_icon((240, 220, 120)))
    items_json.append({"name": "Goal", "img": goal_image, "codes": "goal", "type": "toggle"})
    # The settings (layouts/settings.json): following the player into their room's tab, on from the start; showing
    # rooms not yet visited when the doors are shuffled (fog of war). And a switch the Lua flips when data storage
    # changes what's visible, since rules run again on an item's change.
    for code, name, colour, on in (("auto_tab", "Follow the player's room", (120, 200, 240), True),
                                   ("show_unvisited", "Show unvisited rooms (doors shuffled)", (200, 200, 200), False)):
        write(PACK / f"images/items/{code}.png", square_icon(colour))
        items_json.append({"name": name, "img": f"images/items/{code}.png", "codes": code, "type": "toggle",
                           "initial_active_state": on})
    items_json.append({"name": "Refresh", "img": "images/items/settings_refresh.png", "codes": "bf_refresh",
                       "type": "toggle"})
    write(PACK / "images/items/settings_refresh.png", square_icon((90, 90, 90)))
    settings = {"type": "itemgrid", "item_margin": "4,4", "item_size": "32,32", "rows": [["auto_tab", "show_unvisited"]]}
    write(PACK / "layouts/settings.json", json.dumps({"settings_popup": settings, "settings_grid": settings},
                                                     indent=2) + "\n")
    # The Events group: the milestones as toggles, marked by hand; each counts for the logic as the event does.
    event_codes = {}
    for name, word in EVENT_ITEMS.items():
        if name not in {e["item"] for e in logic["events"]}:
            raise SystemExit(f"{name}: not one of the logic's story events")
        code = "event_" + code_of(name)
        image = f"images/items/{code}.png"
        write(PACK / image, labelled_icon((200, 170, 90), word))
        items_json.append({"name": name, "img": image, "codes": code, "type": "toggle"})
        event_codes[name] = code
    logic["event_codes"] = event_codes
    logic["artifact_codes"] = [item["code"] for item in logic["items"] if item["kind"] == w["data"].ARTIFACT_KIND]
    write(PACK / "layouts/event_grid.json", json.dumps({"event_grid": {
        "type": "itemgrid", "item_margin": "3,3", "item_size": "40,40", "h_alignment": "left",
        "rows": [list(event_codes.values())[i:i + 4] for i in range(0, len(event_codes), 4)],
    }, "goal_grid": {"type": "itemgrid", "item_margin": "3,3", "item_size": "48,48", "rows": [["goal"]]}},
        indent=2) + "\n")

    # The grid, each lit once received: the party and Jump, the abilities, the artifacts and the Goal, the keys,
    # passes and the like with the other items after them, the gears and the boats.
    code_of_name = {item["name"]: item["code"] for item in logic["items"]}
    other = [code_of_name[name] for name in OTHER_ITEMS if name in code_of_name]
    by_kind = {kind: [item["code"] for item in logic["items"] if item["kind"] == kind and item["code"] not in other]
               for kind in sorted({item["kind"] for item in logic["items"]})}
    ways = [code_of_name[name] for name in WAY_ITEMS if name in code_of_name]
    moves = by_kind.get(w["data"].MOVE_KIND, [])
    groups = [[*by_kind.get(w["data"].MEMBER_KIND, []), *(code for code in moves if code == "jump")],
              [code for code in moves if code != "jump"], by_kind.get(w["data"].ARTIFACT_KIND, []),
              [*(code for code in by_kind.get(w["data"].KEY_ITEM_KIND, []) if code not in ways), *other], ways]
    shown = {code for group in groups for code in group}
    groups.append([item["code"] for item in logic["items"] if item["code"] not in shown])
    rows = [group[i:i + 8] for group in groups for i in range(0, len(group), 8)]
    write(PACK / "layouts/item_grid.json", json.dumps({"item_grid": {
        "type": "itemgrid", "item_margin": "3,3", "item_size": "40,40", "h_alignment": "left", "rows": rows,
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
          f"{len(logic['locations'])} locations in {len(rooms)} rooms ({placed} at their own spot), "
          f"{len(map_tabs)} room tabs in {len(area_tabs)} regions, {blocker_count} blockers, "
          f"{len(logic['events'])} events, "
          f"{len(logic['items'])} items")


if __name__ == "__main__":
    main()
