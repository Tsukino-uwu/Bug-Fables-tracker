"""Logic parity: the pack's Lua (scripts/logic.lua, run by lupa's Lua 5.4, the version PopTracker packs run) against
the apworld's own logic, on generated seeds with random options and random item sets. Both answer the same question:
which of the seed's locations can be reached with these items.

    ARCHIPELAGO_DIR=<your Archipelago checkout> python -m pytest tests
"""
from __future__ import annotations

import json
import os
import random
import sys
import unittest
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PACK / "tools"))
import export  # noqa: E402

WORLD = export.load_world(Path(os.environ["ARCHIPELAGO_DIR"]).resolve())

from lupa.lua54 import LuaRuntime  # noqa: E402

from BaseClasses import CollectionState  # noqa: E402
from Options import Choice, Range, Toggle  # noqa: E402
from test.general import setup_multiworld  # noqa: E402
from worlds.AutoWorld import call_all  # noqa: E402
from worlds.bug_fables.world import BugFablesWorld  # noqa: E402

STEPS = ("generate_early", "create_regions", "create_items", "set_rules", "connect_entrances", "generate_basic",
         "pre_fill")
SEEDS = int(os.environ.get("PARITY_SEEDS", "60"))
STATES_PER_SEED = 12
# The options that change the logic or the location set, each rolled at random.
ROLLED = (*WORLD["slot_data"].SLOT_OPTIONS, "starting_party_member", "starting_location")
OPTIONS = BugFablesWorld.options_dataclass.type_hints
# Extra Roadblocks has no roadblocks yet and then takes any name: two stand-ins, so its "contains" filters are compared.
ROADBLOCKS = sorted(OPTIONS["extra_roadblocks"].valid_keys) or ["Test Roadblock A", "Test Roadblock B"]
DOOR_MODES = sorted(set(OPTIONS["entrance_randomizer"].options.values()))
LOCATIONS_JSON = json.loads((PACK / "locations/locations.json").read_text("utf-8"))
# The gates' pins (export.py's blockers), each a rule naming its door's map and the door in the game.
GATE_RULES = [rule for loc in LOCATIONS_JSON for rule in export.rules_of(loc) if rule.startswith("$bf_entrance_open|")]


def call_rule(lua: Lua, rule: str):
    """A '$' rule as PopTracker calls it (src/core/tracker.cpp, 19f0b1f): the function, then each '|' argument as a
    string; a ',' would have split the rule and a ':' cut it to a count."""
    if "," in rule or ":" in rule:
        raise AssertionError(f"a rule PopTracker would cut: {rule}")
    name, *args = rule[1:].split("|")
    return lua.g[name](*args)


def random_options(rng: random.Random) -> dict:
    options = {}
    for name in ROLLED:
        option = OPTIONS[name]
        if issubclass(option, Toggle):
            options[name] = rng.random() < 0.5
        elif issubclass(option, Choice):
            options[name] = rng.choice(sorted(set(option.options.values())))
        elif issubclass(option, Range):
            options[name] = rng.randint(option.range_start, option.range_end)
        elif name == "extra_roadblocks":
            options[name] = [block for block in ROADBLOCKS if rng.random() < 0.5]
    return options


class Lua:
    """The pack's logic in a Lua runtime, with PopTracker's Tracker answering from the counts set here."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.runtime = LuaRuntime(unpack_returned_tuples=True)
        scripts = (PACK / "scripts").as_posix()
        self.runtime.execute(f'package.path = "{scripts}/?.lua;{scripts}/?/init.lua;" .. package.path')
        self.runtime.globals().Tracker = self.runtime.table_from(
            {"ProviderCountForCode": lambda _tracker, code: self.counts.get(code, 0)})
        self.runtime.execute('require("logic")')
        self.g = self.runtime.globals()

    def set_seed(self, slot_data: dict, location_ids: list[int] | None) -> None:
        ids = None if location_ids is None else self.runtime.table_from(location_ids)
        self.g.bf_set_seed(self.runtime.table_from(slot_data, recursive=True), ids)


def every_custom_rule() -> list:
    """Each of the apworld's own rules with each argument it takes, the rules built from them, a region reached, and
    each kind of option filter: the logic may not use one yet, so they're compared one by one too."""
    from rule_builder.options import OptionFilter
    from rule_builder.rules import CanReachRegion, Has

    rules = WORLD["custom_rules"]
    abilities = WORLD["abilities"].ABILITIES
    data = WORLD["data"]
    shops = {loc.region if loc.area is None else f"{loc.region} ({loc.area})"
             for loc in data.LOCATIONS if loc.category == "item_shop"}
    filtered = []
    for resolution in (False, True):
        filtered += [Has("Jump", options=[OptionFilter(OPTIONS["extra_roadblocks"], block, "contains")],
                         filtered_resolution=resolution) for block in ROADBLOCKS]
        filtered += [Has("Jump", options=[OptionFilter(OPTIONS["entrance_randomizer"], [1, 3], "in")],
                         filtered_resolution=resolution),
                     Has("Jump", options=[OptionFilter(OPTIONS["shop_contents"], 1, "ge")],
                         filtered_resolution=resolution)]
    return [*(rules.CanUse(name) for name in abilities), *(rules.MoveItem(name) for name in abilities),
            *(rules.Member(name) for name in WORLD["items"].MEMBERS), rules.Boat(1), rules.Boat(2),
            rules.WayBack(Has("Jump")), rules.one_way(Has("Explorer Permit"), Has("Jump")),
            rules.WHOLE_PARTY, rules.ALL_ATTACKS, WORLD["rules"].JUMP, WORLD["rules"].ARTIFACT_GATE, rules.ItemOnHand(),
            *(CanReachRegion(region) for region in sorted(shops)), CanReachRegion(data.MAP_AREAS[0].region),
            *filtered]


class TestParity(unittest.TestCase):
    def test_rules(self) -> None:
        rng = random.Random(1003)
        lua = Lua()
        codes = {item["name"]: item["code"] for item in export.build(WORLD)["items"]}
        rules = [(rule, lua.runtime.table_from(rule.to_dict(), recursive=True)) for rule in every_custom_rule()]
        for n in range(SEEDS):
            options = random_options(rng)
            multiworld = setup_multiworld(BugFablesWorld, steps=(), seed=rng.getrandbits(32), options=options)
            # Through create_items: the starting members are start inventory there.
            for step in STEPS[:3]:
                call_all(multiworld, step)
            world = multiworld.worlds[1]
            lua.set_seed({"options": WORLD["slot_data"].options_for_slot(world), "door_targets": [],
                          "starting_member": world.starting_member, "start": world.start,
                          "world_version": BugFablesWorld.world_version.as_simple_string()}, None)
            for k in range(STATES_PER_SEED):
                held = {name: rng.randint(0, 2) for name in codes if rng.random() < 0.6}
                state = CollectionState(multiworld)
                for name, count in held.items():
                    for _ in range(count):
                        state.collect(world.create_item(name), prevent_sweep=True)
                lua.counts.clear()
                lua.counts.update({codes[name]: count for name, count in held.items()})
                lua.g.bf_eval_state()
                for rule, table in rules:
                    with self.subTest(rule=str(rule), options=options, held=held):
                        self.assertEqual(lua.g.bf_eval(table), rule.resolve(world)(state))

    def test_seeds(self) -> None:
        rng = random.Random(20261003)
        lua = Lua()
        codes = {item["name"]: item["code"] for item in export.build(WORLD)["items"]}
        for n in range(SEEDS):
            options = random_options(rng)
            # Each door mode as often as the others.
            options["entrance_randomizer"] = DOOR_MODES[n % len(DOOR_MODES)]
            seed = rng.getrandbits(32)
            with self.subTest(seed=seed, options=options):
                multiworld = setup_multiworld(BugFablesWorld, steps=(), seed=seed, options=options)
                for step in STEPS:
                    call_all(multiworld, step)
                world = multiworld.worlds[1]
                ids = sorted(loc.address for loc in world.get_locations() if loc.address is not None)
                slot_data = dict(world.fill_slot_data())

                # Which locations a seed holds: from the server's list, and from the options alone (no server).
                lua.set_seed(slot_data, None)
                self.assertEqual({i for i in WORLD["data"].LOCATION_NAME_TO_ID.values() if lua.g.bf_in_seed(i)},
                                 set(ids), "the categories")
                lua.set_seed(slot_data, ids)

                # Every entrance Archipelago made, door by door, as the pack's Lua has it from door_targets.
                made = {(e.name, e.parent_region.name, e.connected_region.name)
                        for e in multiworld.get_entrances(1)}
                pack = {(e["name"], e["from"], e["to"]) for e in lua.g.bf_entrances().values()}
                self.assertEqual(sorted(made - pack), [], "entrances the pack's Lua doesn't have")

                pool = [item for item in multiworld.itempool if item.player == 1 and item.advancement]
                events = [loc for loc in world.get_locations() if loc.address is None]
                for k in range(STATES_PER_SEED):
                    share = (0.0, 1.0)[k] if k < 2 else rng.random()
                    held = [item for item in pool if rng.random() < share]
                    state = CollectionState(multiworld)
                    for item in held:
                        state.collect(item, prevent_sweep=True)
                    state.sweep_for_advancements(locations=events)
                    expected = {loc.address for loc in world.get_locations()
                                if loc.address is not None and loc.can_reach(state)}
                    lua.counts.clear()
                    for item in held:
                        code = codes.get(item.name)
                        if code:
                            lua.counts[code] = lua.counts.get(code, 0) + 1
                    got = {i for i in ids if lua.g.bf_location(i)}
                    names = {loc.address: loc.name for loc in world.get_locations()}
                    self.assertEqual(sorted(names[i] for i in got - expected), [], f"state {k}: Lua only")
                    self.assertEqual(sorted(names[i] for i in expected - got), [], f"state {k}: apworld only")
                    # The regions reached, a map's parts included.
                    reached = {name for name, on in lua.g.bf_reached().items() if on}
                    self.assertEqual(reached, {r.name for r in multiworld.get_regions(1) if r.can_reach(state)},
                                     f"state {k}: regions")
                    # The gates' pins, their rules called as PopTracker calls them: going through each door that is a
                    # gate, as Archipelago answers it.
                    entrances = {e.name for e in multiworld.get_entrances(1)}
                    self.assertTrue(GATE_RULES)
                    for rule in GATE_RULES:
                        name = WORLD["data"].door_name(*rule.split("|")[1:])
                        if name not in entrances:
                            continue  # a door kept shut for good isn't one of the logic's
                        entrance = multiworld.get_entrance(name, 1)
                        self.assertEqual(bool(call_rule(lua, rule)), entrance.can_reach(state), f"state {k}: {name}")


class TestExport(unittest.TestCase):
    def test_locations(self) -> None:
        logic = export.build(WORLD)
        data = WORLD["data"]
        ids = [loc["id"] for loc in logic["locations"]]
        self.assertEqual(len(ids), len(set(ids)), "a location exported twice")
        pending = {data.LOCATION_NAME_TO_ID[loc.name] for loc in data.LOCATIONS if loc.pending}
        self.assertEqual(set(ids), set(data.LOCATION_NAME_TO_ID.values()) - pending)

    def test_the_doors_key_read_as_universal_tracker_reads_it(self) -> None:
        from worlds.bug_fables import universal_tracker
        self.assertEqual(export.build(WORLD)["door_entrances"], universal_tracker._TAKEN)

    def test_every_rule_calls_the_packs_lua_whole(self) -> None:
        # Each rule as PopTracker reads it: one part (no ','), no count (no ':'), a function the Lua has.
        lua = Lua()
        rules = [rule for loc in LOCATIONS_JSON for rule in export.rules_of(loc)]
        self.assertTrue(rules)
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertNotIn(",", rule)
                self.assertNotIn(":", rule)
                self.assertTrue(rule.startswith("$"))
                self.assertIsNotNone(lua.g[rule[1:].split("|")[0]])


if __name__ == "__main__":
    unittest.main()
