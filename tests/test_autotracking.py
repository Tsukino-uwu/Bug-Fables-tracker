"""The pack's Archipelago auto-tracking (scripts/autotracking.lua) in lupa's Lua 5.4, with PopTracker's Archipelago,
Tracker, ScriptHost and Highlight stood in for as its doc/AUTOTRACKING.md and doc/PACKS.md describe them (master
d2af7f1): what it asks the server on connect, and what each answer changes.

    ARCHIPELAGO_DIR=<your Archipelago checkout> python -m pytest tests
"""
from __future__ import annotations

import json
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
# Each of the Entrance Randomizer's door shuffles.
SHUFFLED_MODES = sorted(set(BugFablesWorld.options_dataclass.type_hints["entrance_randomizer"].options.values()) - {0})


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
        self.objects["goal"] = Thing(Type="toggle", Active=False, BadgeText="")
        for code in data["event_codes"].values():
            self.objects[code] = Thing(Type="toggle", Active=False)
        # The settings as a new tracker has them (items.json's initial_active_state).
        for entry in json.loads((PACK / "items/items.json").read_text("utf-8")):
            if entry["codes"] not in self.objects:
                self.objects[entry["codes"]] = Thing(Type=entry["type"],
                                                     Active=entry.get("initial_active_state", False))
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


def seed(entrance_randomizer: int, **options) -> tuple:
    multiworld = setup_multiworld(BugFablesWorld, steps=(), seed=20261008,
                                  options={"entrance_randomizer": entrance_randomizer, **options})
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
        # Every door Archipelago connected leads, in the pack, where the seed sent it, by the name the mod writes in the
        # doors key (the game's "<map>: <door>") or its entrance's; a story copy names its door.
        data = WORLD["data"]
        for mode in SHUFFLED_MODES:
            multiworld, world, slot_data = seed(mode)
            pack = PopTracker()
            pack.connect(slot_data)
            made = {e.name: e for e in multiworld.get_entrances(1)}
            doors = [(data.game_door_name(*door), made[name])
                     for door, name in data.DOOR_LABELS.items() if name in made]
            self.assertTrue(doors)
            for written, entrance in doors:
                with self.subTest(mode=mode, door=written):
                    self.assertEqual(pack.g.bf_door_led_to(written)[0], entrance.connected_region.name)
                    self.assertEqual(pack.g.bf_door_led_to(entrance.name)[0], entrance.connected_region.name)
            copies = [(data.game_door_name(w.map, copy), data.door_name(w.map, w.door))
                      for w in data.ONE_WAYS for copy in w.copies]
            self.assertTrue(copies)
            for copy, door in copies:
                self.assertEqual(pack.g.bf_door_led_to(copy)[0], made[door].connected_region.name)
            pack.answer("bug_fables_doors_0_1", [doors[0][0]])
            self.assertEqual(list(pack.g.STORAGE.doors.keys()), [doors[0][0]])


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


class TestGoalAndEvents(unittest.TestCase):
    def test_the_goal_counts_the_artifacts(self) -> None:
        pack = PopTracker()
        pack.connect({"options": {"artifacts_required": 2}})
        self.assertEqual(pack.objects["goal"].BadgeText, "0/2")
        artifact = next(i for i in pack.g.DATA["items"].values() if i["code"] == pack.g.DATA["artifact_codes"][1])
        pack.handlers["item"](0, artifact["id"], artifact["name"], 1)
        self.assertEqual(pack.objects["goal"].BadgeText, "1/2")

    def test_an_event_marked_counts_as_held(self) -> None:
        pack = PopTracker()
        pack.connect({})
        name, code = next(iter(pack.g.DATA["event_codes"].items()))
        rule = pack.runtime.table_from({"rule": "Has", "args": {"item_name": name, "count": 1}}, recursive=True)
        pack.g.bf_eval_state()
        self.assertFalse(pack.g.bf_eval(rule))
        pack.objects[code].Active = True
        pack.g.bf_eval_state()
        self.assertTrue(pack.g.bf_eval(rule))


class TestFollowAndFog(unittest.TestCase):
    def test_the_room_now_opens_its_tabs(self) -> None:
        pack = PopTracker()
        pack.connect({})
        tabs = pack.g.DATA["map_tabs"]
        with_checks = set(pack.g.DATA["room_areas"].keys())
        room = next(m for m in tabs.keys() if m in with_checks)
        hallway = next(m for m in tabs.keys() if m not in with_checks)
        def opened(map_name: str) -> list[tuple[str, str]]:
            return [("ActivateTab", tabs[map_name][level]) for level in ("region", "area", "room")]
        pack.answer("bug_fables_map_0_1", room, how="set_reply")
        self.assertEqual(pack.hints, opened(room))
        # A room without checks has its own tab too.
        pack.hints.clear()
        pack.answer("bug_fables_map_0_1", hallway, how="set_reply")
        self.assertEqual(pack.hints, opened(hallway))
        # A map with no tab (a test map): the tabs stay as they are.
        pack.hints.clear()
        pack.answer("bug_fables_map_0_1", "TestRoom", how="set_reply")
        self.assertEqual(pack.hints, [])
        # The setting off: the tabs stay as they are.
        pack.hints.clear()
        pack.objects["auto_tab"].Active = False
        pack.answer("bug_fables_map_0_1", room, how="set_reply")
        self.assertEqual(pack.hints, [])

    def test_fog_of_war_only_with_the_doors_shuffled(self) -> None:
        pack = PopTracker()
        pack.connect({"options": {"entrance_randomizer": 0}})
        self.assertTrue(pack.g.bf_seen("NearSnakemouth"))
        for mode in SHUFFLED_MODES:
            pack.connect({"options": {"entrance_randomizer": mode}})
            self.assertFalse(pack.g.bf_seen("NearSnakemouth"), f"door shuffle {mode}")
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


class TestOfflineOptions(unittest.TestCase):
    """With no seed connected, each location category's toggle in Settings decides its locations; once connected, the
    seed's own options and location list do."""
    GRASS = "Golden Settlement: Square, Grass by the Lever"
    REWARD = "Bugaria City: Residential District, Old Book Delivery Reward 1"

    def setUp(self) -> None:
        data = WORLD["data"]
        self.grass = data.LOCATION_NAME_TO_ID[self.GRASS]
        spot = next(loc for loc in data.LOCATIONS if loc.name == self.GRASS)
        self.assertEqual(WORLD["options"].CATEGORY_OPTIONS[spot.category], "shuffle_hidden_items")
        self.reward = data.LOCATION_NAME_TO_ID[self.REWARD]

    def test_each_toggle_starts_as_its_options_default(self) -> None:
        pack = PopTracker()
        fields = BugFablesWorld.options_dataclass.type_hints
        for option in set(WORLD["options"].CATEGORY_OPTIONS.values()):
            self.assertEqual(pack.objects[option].Active, bool(fields[option].default), option)

    def test_a_category_toggled_on_offline(self) -> None:
        pack = PopTracker()
        room, name = pack.g.DATA["section_paths"][self.grass][1:].split("/", 1)
        location = next(loc for loc in json.loads((PACK / "locations/locations.json").read_text("utf-8"))
                        if loc["name"] == room)
        section = next(s for s in location["sections"] if s.get("name") == name)
        self.assertEqual(section["visibility_rules"], [f"$bf_in_seed|{self.grass}"])
        self.assertFalse(pack.g.bf_in_seed(self.grass), "Shuffle Hidden Items is off by default")
        pack.objects["shuffle_hidden_items"].Active = True
        self.assertTrue(pack.g.bf_in_seed(self.grass))
        self.assertTrue(pack.g.bf_room_in_seed(room))

    def test_a_category_toggled_off_offline_reruns_the_logic(self) -> None:
        # The quest's own step is a story event of its category: with the category off, it is in no seed.
        pack = PopTracker()
        for item in pack.g.DATA["items"].values():
            pack.objects[item["code"]].Active = True
        self.assertTrue(pack.g.bf_in_seed(self.reward))
        self.assertTrue(pack.g.bf_location(self.reward))
        pack.objects["shuffle_quests"].Active = False
        self.assertFalse(pack.g.bf_in_seed(self.reward))
        self.assertFalse(pack.g.bf_location(self.reward))

    def test_a_connected_seed_ignores_the_toggles(self) -> None:
        multiworld, world, slot_data = seed(0, shuffle_hidden_items=False, shuffle_quests=True)
        ids = [loc.address for loc in world.get_locations() if loc.address is not None]
        pack = PopTracker()
        pack.objects["shuffle_hidden_items"].Active = True
        pack.objects["shuffle_quests"].Active = False
        pack.connect(slot_data, missing=ids)
        # Every item received (the Clear handler resets them).
        for item in pack.g.DATA["items"].values():
            pack.objects[item["code"]].Active = True
        self.assertFalse(pack.g.bf_in_seed(self.grass))
        self.assertTrue(pack.g.bf_in_seed(self.reward))
        self.assertTrue(pack.g.bf_location(self.reward))
        # slot_data's options alone, with no location list.
        pack.g.bf_set_seed(pack.runtime.table_from(slot_data, recursive=True), None)
        self.assertFalse(pack.g.bf_in_seed(self.grass))
        self.assertTrue(pack.g.bf_in_seed(self.reward))
        self.assertTrue(pack.g.bf_location(self.reward))


if __name__ == "__main__":
    unittest.main()
