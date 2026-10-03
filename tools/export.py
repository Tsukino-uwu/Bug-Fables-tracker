"""Writes the pack's generated files from the Bug Fables apworld: its logic as Rule Builder's to_dict writes each rule
(scripts/generated/logic_data.lua), the items, the locations, and the placeholder map and icons, drawn by code.

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
from pathlib import Path
from typing import Any

PACK = Path(__file__).resolve().parent.parent
# Rules the pack's Lua evaluates (scripts/logic.lua): Archipelago's and the apworld's own (its custom_rules.py).
SUPPORTED_RULES = {"And", "Or", "Has", "HasAllCounts", "True_", "False_", "Filtered",
                   "CanUse", "Member", "MoveItem", "Boat", "WayBack"}
MAP_NAME = "overview"
CELL = 40
PIN = 28
COLUMNS = 16


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

def png(width: int, height: int, pixel) -> bytes:
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


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

    # The rooms with checks, each a pin: grouped by the logic's areas in story order, a band per area.
    area_of: dict[str, int] = {}
    for index, area in enumerate(w["logic"].AREAS):
        for loc in getattr(area, "LOCATIONS", ()):
            area_of.setdefault(loc.region, index)
    rooms: dict[str, list[dict[str, Any]]] = {}
    for loc in sorted(logic["locations"], key=lambda loc: (area_of[loc["region"]], loc["name"])):
        rooms.setdefault(loc["region"], []).append(loc)
    places: dict[str, tuple[int, int]] = {}
    bands: list[tuple[int, int, int]] = []
    row = 0
    for index in range(len(w["logic"].AREAS)):
        names = [room for room in rooms if area_of[room] == index]
        if not names:
            continue
        first = row
        for n, room in enumerate(names):
            places[room] = (n % COLUMNS, row + n // COLUMNS)
        row += (len(names) + COLUMNS - 1) // COLUMNS
        bands.append((index, first, row))
    width, height = COLUMNS * CELL, row * CELL

    def map_pixel(x: int, y: int) -> tuple[int, int, int, int]:
        band = next(b for b in bands if b[1] * CELL <= y < b[2] * CELL)
        shade = 34 if band[0] % 2 else 46
        return shade, shade, shade + 8, 255

    locations_json = []
    section_paths = {}
    for room, locs in rooms.items():
        if "/" in room or any("/" in loc["name"] for loc in locs):
            raise SystemExit(f"{room}: a '/' would break PopTracker's @location/section paths")
        x, y = places[room]
        locations_json.append({
            "name": room,
            "visibility_rules": [f"$bf_room_in_seed|{room}"],
            "chest_unopened_img": "images/chest_closed.png",
            "chest_opened_img": "images/chest_open.png",
            "map_locations": [{"map": MAP_NAME, "x": x * CELL + CELL // 2, "y": y * CELL + CELL // 2}],
            "sections": [{"name": loc["name"], "access_rules": [f"$bf_location|{loc['id']}"],
                          "visibility_rules": [f"$bf_in_seed|{loc['id']}"]} for loc in locs],
        })
        for loc in locs:
            section_paths[loc["id"]] = f"@{room}/{loc['name']}"
    logic["section_paths"] = section_paths
    logic["item_codes_by_id"] = {item["id"]: item["code"] for item in logic["items"]}

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
    write(PACK / "maps/maps.json", json.dumps([{"name": MAP_NAME, "location_size": PIN,
                                                 "location_border_thickness": 2,
                                                 "img": "images/map.png"}], indent=2) + "\n")
    write(PACK / "images/map.png", png(width, height, map_pixel))
    write(PACK / "images/chest_closed.png", square_icon((200, 170, 90), 24))
    write(PACK / "images/chest_open.png", square_icon((120, 120, 120), 24, hollow=True))
    print(f"world {logic['world_version']} at {logic['randomizer_commit']}: {len(logic['entrances'])} entrances, "
          f"{len(logic['locations'])} locations in {len(rooms)} rooms, {len(logic['events'])} events, "
          f"{len(logic['items'])} items")


if __name__ == "__main__":
    main()
