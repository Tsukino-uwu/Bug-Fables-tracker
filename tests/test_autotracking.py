"""The pack's Archipelago auto-tracking (scripts/autotracking.lua) in lupa's Lua 5.4, with PopTracker's Archipelago,
Tracker, ScriptHost and Highlight stood in for as its doc/AUTOTRACKING.md and doc/PACKS.md describe them (master
d2af7f1): what it asks the server on connect, and what each answer changes.

    ARCHIPELAGO_DIR=<your Archipelago checkout> python -m pytest tests
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))
import export  # noqa: E402

WORLD = export.load_world(Path(os.environ["ARCHIPELAGO_DIR"]).resolve())

from lupa.lua54 import LuaRuntime  # noqa: E402

from test.general import setup_multiworld  # noqa: E402
from worlds.AutoWorld import call_all  # noqa: E402
from worlds.bug_fables.world import BugFablesWorld  # noqa: E402

STEPS = ("generate_early", "create_regions", "create_items", "set_rules", "connect_entrances", "generate_basic",
         "pre_fill")
# Archipelago's ClientStatus (docs/network protocol.md), which PopTracker's enum carries to the server.
GOAL = 30


class Thing:
    """A PopTracker item or section: the attributes the pack reads and sets."""

    def __init__(self, **attributes) -> None:
        self.__dict__.update(attributes)


class PopTracker:
    """The pack loaded the way PopTracker loads it, connected as one slot."""

    def __init__(self, slot: int = 1, team: int = 0, seed: str = "S1") -> None:
        self.runtime = LuaRuntime(unpack_returned_tuples=True)
        g = self.g = self.runtime.globals()
        scripts = (PACK / "scripts").as_posix()
        self.runtime.execute(f'package.path = "{scripts}/?.lua;{scripts}/?/init.lua;" .. package.path')
        self.objects: dict[str, Thing] = {}
        self.handlers: dict[str, object] = {}
        self.asked: dict[str, list] = {"SetNotify": [], "Get": []}
        self.hints: list[tuple[str, str]] = []
        g.Tracker = self.runtime.table_from({
            "FindObjectForCode": lambda _self, code: self.objects.get(code),
            "ProviderCountForCode": lambda _self, code: int(getattr(self.objects.get(code), "Active", False)),
            "UiHint": lambda _self, name, value: self.hints.append((name, value)),
        })
        g.Highlight = self.runtime.table_from(
            {"Avoid": "Avoid", "None": "None", "NoPriority": "NoPriority", "Unspecified": "Unspecified",
             "Priority": "Priority"})
        g.ScriptHost = self.runtime.table_from(
            {"AddOnFrameHandler": lambda _self, name, f: self.handlers.__setitem__("frame", f)})
        self.archipelago = self.runtime.table_from({
            "PlayerNumber": slot, "TeamNumber": team, "Seed": seed,
            "CheckedLocations": self.runtime.table_from([]), "MissingLocations": self.runtime.table_from([]),
            "ClientStatus": self.runtime.table_from({"GOAL": GOAL}),
            "AddClearHandler": lambda _self, name, f: self.handlers.__setitem__("clear", f),
            "AddItemHandler": lambda _self, name, f: self.handlers.__setitem__("item", f),
            "AddLocationHandler": lambda _self, name, f: self.handlers.__setitem__("location", f),
            "AddRetrievedHandler": lambda _self, name, f: self.handlers.__setitem__("retrieved", f),
            "AddSetReplyHandler": lambda _self, name, f: self.handlers.__setitem__("set_reply", f),
            "AddBouncedHandler": lambda _self, name, f: self.handlers.__setitem__("bounced", f),
            "SetNotify": lambda _self, keys: self.asked["SetNotify"].append(list(keys.values())),
            "Get": lambda _self, keys: self.asked["Get"].append(list(keys.values())),
        })
        g.Archipelago = self.archipelago
        self.runtime.execute('require("logic")')
        data = g.DATA
        for item in data["items"].values():
            self.objects[item["code"]] = Thing(Type="toggle" if item["max"] <= 1 else "consumable", Active=False,
                                               AcquiredCount=0, BadgeText="", BadgeTextColor="")
        self.objects["goal"] = Thing(Type="toggle", Active=False)
        # The settings as a new tracker has them (items.json's initial_active_state).
        self.objects["auto_tab"] = Thing(Type="toggle", Active=True)
        self.objects["show_unvisited"] = Thing(Type="toggle", Active=False)
        self.objects["bf_refresh"] = Thing(Type="toggle", Active=False)
        for path in data["section_paths"].values():
            self.objects[path] = Thing(ChestCount=1, AvailableChestCount=1, Highlight="None")
        self.runtime.execute('require("autotracking")')

    def connect(self, slot_data: dict, checked: list[int] = (), missing: list[int] = ()) -> None:
        # Empty slot_data still names this world's version, as a real seed does.
        slot_data = slot_data or {"world_version": BugFablesWorld.world_version.as_simple_string()}
        self.archipelago.CheckedLocations = self.runtime.table_from(list(checked))
        self.archipelago.MissingLocations = self.runtime.table_from(list(missing))
        self.handlers["clear"](self.runtime.table_from(slot_data, recursive=True))

    def answer(self, key: str, value, how: str = "retrieved") -> None:
        value = self.runtime.table_from(value, recursive=True) if isinstance(value, (list, dict)) else value
        self.handlers[how](key, value) if how == "retrieved" else self.handlers[how](key, value, None)

    def section(self, location_id: int) -> Thing:
        return self.objects[self.g.DATA["section_paths"][location_id]]


def seed(entrance_randomizer: int) -> tuple:
    multiworld = setup_multiworld(BugFablesWorld, steps=(), seed=20261008,
                                  options={"entrance_randomizer": entrance_randomizer})
    for step in STEPS:
        call_all(multiworld, step)
    world = multiworld.worlds[1]
    return multiworld, world, dict(world.fill_slot_data())


class TestConnect(unittest.TestCase):
    def test_asks_for_each_key_then_its_value(self) -> None:
        # PopTracker's ap-storage-example: SetNotify for changes, then Get for the value now, from the Clear handler.
        pack = PopTracker(slot=3, team=1)
        pack.connect({})
        keys = ["bug_fables_doors_1_3", "bug_fables_visited_1_3", "bug_fables_map_1_3", "_read_client_status_1_3",
                "_read_hints_1_3"]
        self.assertEqual(pack.asked["SetNotify"], [keys])
        self.assertEqual(pack.asked["Get"], [keys])

    def test_checks_right_at_connect(self) -> None:
        pack = PopTracker()
        ids = list(pack.g.DATA["section_paths"].keys())[:2]
        pack.connect({}, checked=[ids[0]], missing=[ids[1]])
        self.assertEqual(pack.section(ids[0]).AvailableChestCount, 0)
        self.assertEqual(pack.section(ids[1]).AvailableChestCount, 1)


class TestStorage(unittest.TestCase):
    def test_maps_visited_and_the_map_now(self) -> None:
        pack = PopTracker()
        pack.connect({})
        pack.answer("bug_fables_visited_0_1", ["BugariaOutskirtsOutsideCity", 7, "NearSnakemouth"])
        pack.answer("bug_fables_map_0_1", "NearSnakemouth", how="set_reply")
        storage = pack.g.STORAGE
        self.assertEqual(set(storage.visited.keys()), {"BugariaOutskirtsOutsideCity", "NearSnakemouth"})
        self.assertEqual(storage.map, "NearSnakemouth")
        # Anything but a list of names (or a name) counts as none.
        pack.answer("bug_fables_visited_0_1", {"a": 1})
        pack.answer("bug_fables_map_0_1", 5)
        self.assertEqual(list(pack.g.STORAGE.visited.keys()), [])
        self.assertIsNone(pack.g.STORAGE.map)

    def test_a_new_seed_starts_afresh(self) -> None:
        pack = PopTracker()
        pack.connect({})
        pack.answer("bug_fables_visited_0_1", ["NearSnakemouth"])
        pack.connect({})
        self.assertEqual(list(pack.g.STORAGE.visited.keys()), ["NearSnakemouth"], "the same slot keeps it")
        pack.archipelago.Seed = "S2"
        pack.connect({})
        self.assertEqual(list(pack.g.STORAGE.visited.keys()), [], "another seed starts afresh")

    def test_where_each_door_taken_led(self) -> None:
        # Every door Archipelago connected leads, in the pack, where the seed sent it; a story copy names its door.
        for mode in (1, 2, 3):
            multiworld, world, slot_data = seed(mode)
            pack = PopTracker()
            pack.connect(slot_data)
            doors = {name for name in WORLD["data"].DOOR_NAMES} | {
                WORLD["data"].door_name(w.map, w.door) for w in WORLD["data"].ONE_WAYS}
            made = [e for e in multiworld.get_entrances(1) if e.name in doors]
            self.assertTrue(made)
            for entrance in made:
                with self.subTest(mode=mode, door=entrance.name):
                    region, _map = pack.g.bf_door_led_to(entrance.name)
                    self.assertEqual(region, entrance.connected_region.name)
            for copy, door in pack.g.DATA["one_way_copies"].items():
                self.assertEqual(pack.g.bf_door_led_to(copy)[0], pack.g.bf_door_led_to(door)[0])
            pack.answer("bug_fables_doors_0_1", [made[0].name])
            self.assertEqual(list(pack.g.STORAGE.doors.keys()), [made[0].name])


class TestServerState(unittest.TestCase):
    def test_the_goal(self) -> None:
        pack = PopTracker()
        pack.connect({})
        pack.answer("_read_client_status_0_1", 20)
        self.assertFalse(pack.objects["goal"].Active)
        pack.answer("_read_client_status_0_1", GOAL, how="set_reply")
        self.assertTrue(pack.objects["goal"].Active)

    def test_hints_highlight_this_slots_checks(self) -> None:
        pack = PopTracker()
        pack.connect({})
        ids = list(pack.g.DATA["section_paths"].keys())[:3]
        hint = {"receiving_player": 2, "item": 7, "found": False, "entrance": "", "item_flags": 1}
        pack.answer("_read_hints_0_1", [hint | {"finding_player": 1, "location": ids[0], "status": 30},
                                        hint | {"finding_player": 1, "location": ids[1], "status": 20},
                                        hint | {"finding_player": 2, "location": ids[2], "status": 30}])
        self.assertEqual(pack.section(ids[0]).Highlight, "Priority")
        self.assertEqual(pack.section(ids[1]).Highlight, "Avoid")
        self.assertEqual(pack.section(ids[2]).Highlight, "None", "another slot's location")
        # Found, and a hint gone: back to no highlight.
        pack.answer("_read_hints_0_1", [hint | {"finding_player": 1, "location": ids[0], "status": 40}], how="set_reply")
        self.assertEqual(pack.section(ids[0]).Highlight, "None")
        self.assertEqual(pack.section(ids[1]).Highlight, "None")

    def test_a_deathlink_marks_the_party_for_a_while(self) -> None:
        pack = PopTracker()
        pack.connect({})
        members = [i["code"] for i in pack.g.DATA["items"].values() if i["name"] in WORLD["items"].MEMBERS]
        self.assertEqual(len(members), len(WORLD["items"].MEMBERS))
        pack.handlers["bounced"](pack.runtime.table_from({"tags": ["Lufia"]}, recursive=True))
        self.assertEqual({pack.objects[c].BadgeText for c in members}, {""})
        pack.handlers["bounced"](pack.runtime.table_from(
            {"tags": ["DeathLink"], "data": {"time": 1.0, "source": "Other"}}, recursive=True))
        self.assertEqual({pack.objects[c].BadgeText for c in members}, {"DL"})
        pack.handlers["frame"](4.0)
        self.assertEqual({pack.objects[c].BadgeText for c in members}, {"DL"})
        pack.handlers["frame"](7.0)
        self.assertEqual({pack.objects[c].BadgeText for c in members}, {""})


class TestFollowAndFog(unittest.TestCase):
    def test_the_room_now_opens_its_tabs(self) -> None:
        pack = PopTracker()
        pack.connect({})
        tabs = pack.g.DATA["map_tabs"]
        room = next(m for m, t in tabs.items() if t["room"])
        hallway = next(m for m, t in tabs.items() if not t["room"])
        pack.answer("bug_fables_map_0_1", room, how="set_reply")
        self.assertEqual(pack.hints, [("ActivateTab", tabs[room]["area"]), ("ActivateTab", tabs[room]["room"])])
        # A room without checks: its area's overview.
        pack.hints.clear()
        pack.answer("bug_fables_map_0_1", hallway, how="set_reply")
        self.assertEqual(pack.hints, [("ActivateTab", tabs[hallway]["area"]),
                                      ("ActivateTab", pack.g.DATA["overview_tab"])])
        # The setting off: the tabs stay as they are.
        pack.hints.clear()
        pack.objects["auto_tab"].Active = False
        pack.answer("bug_fables_map_0_1", room, how="set_reply")
        self.assertEqual(pack.hints, [])

    def test_fog_of_war_only_with_the_doors_shuffled(self) -> None:
        pack = PopTracker()
        pack.connect({"options": {"entrance_randomizer": 0}})
        self.assertTrue(pack.g.bf_seen("NearSnakemouth"))
        pack.connect({"options": {"entrance_randomizer": 1}})
        self.assertFalse(pack.g.bf_seen("NearSnakemouth"))
        area = pack.g.DATA["map_tabs"]["NearSnakemouth"]["area_id"]
        self.assertFalse(pack.g.bf_area_seen(area))
        before = pack.objects["bf_refresh"].Active
        pack.answer("bug_fables_visited_0_1", ["NearSnakemouth"], how="set_reply")
        self.assertNotEqual(pack.objects["bf_refresh"].Active, before, "rules asked to run again")
        self.assertTrue(pack.g.bf_seen("NearSnakemouth"))
        self.assertTrue(pack.g.bf_area_seen(area))
        self.assertFalse(pack.g.bf_seen("BugariaOutskirtsOutsideCity"))
        pack.objects["show_unvisited"].Active = True
        self.assertTrue(pack.g.bf_seen("BugariaOutskirtsOutsideCity"))


if __name__ == "__main__":
    unittest.main()
