-- The apworld's logic, as tools/export.py writes it (generated/logic_data.lua): each rule as Rule Builder's to_dict
-- writes it, evaluated against the items PopTracker tracks and the seed's options, over a region sweep as
-- Archipelago's own (regions, a map or a part of one, reached through entrances, story events collected where
-- reached, until nothing changes).

DATA = require("generated.logic_data")

local ITEM_CODE = {}
for _, item in ipairs(DATA.items) do
    ITEM_CODE[item.name] = item.code
end
local LOCATION = {}
local IDS_BY_MAP = {}
for _, loc in ipairs(DATA.locations) do
    LOCATION[loc.id] = loc
    IDS_BY_MAP[loc.map] = IDS_BY_MAP[loc.map] or {}
    table.insert(IDS_BY_MAP[loc.map], loc.id)
end

-- The seed: its options, starting member and doors (slot_data), and its locations (the server's); the defaults until
-- a seed is connected.
SEED = {}

local function truthy(value)
    return value == true or (type(value) == "number" and value ~= 0)
end

local function option_number(value)
    if value == true then return 1 end
    if value == false or value == nil then return 0 end
    return value
end

local OPERATORS = {
    eq = function(a, b) return a == b end,
    ne = function(a, b) return a ~= b end,
    gt = function(a, b) return a > b end,
    lt = function(a, b) return a < b end,
    ge = function(a, b) return a >= b end,
    le = function(a, b) return a <= b end,
}

local function category_on(category)
    if category == nil then return true end
    local option = DATA.category_options[category]
    if option then return truthy(SEED.options[option]) end
    if category == "party_member" then return SEED.starting_member >= 0 end
    if category == "story_party" then return SEED.starting_member < 0 end
    return true
end

-- Each door's destination in this seed: door_targets sends a door where like_door leads in the game (a two-way door
-- to the region like_door's partner stands in, a one-way to the region like_door lands in).
local function seed_entrances(door_targets)
    local like = {}
    for _, target in ipairs(door_targets or {}) do
        like[target.map .. "|" .. target.door] = target.like_map .. "|" .. target.like_door
    end
    local entrances = {}
    for _, entrance in ipairs(DATA.entrances) do
        local to = entrance.to
        if entrance.door then
            local key = entrance.door.map .. "|" .. entrance.door.door
            to = DATA.partners[like[key] or key].region
        elseif entrance.one_way then
            local target = like[entrance.one_way.map .. "|" .. entrance.one_way.door]
            if target then to = DATA.one_way_to[target].region end
        end
        entrances[#entrances + 1] = { name = entrance.name, from = entrance.from, to = to, rule = entrance.rule }
    end
    return entrances
end

local cache_key = nil
local cache = nil
local seed_version = 0

-- slot_data as the server sends it, and the seed's location ids (nil: every location its categories include).
function bf_set_seed(slot_data, location_ids)
    SEED.options = {}
    for name, value in pairs(DATA.option_defaults) do SEED.options[name] = value end
    SEED.starting_member = DATA.starting_member_default
    SEED.door_targets = {}
    if slot_data then
        for name, value in pairs(slot_data.options or {}) do SEED.options[name] = value end
        if slot_data.starting_member ~= nil then SEED.starting_member = slot_data.starting_member end
        SEED.door_targets = slot_data.door_targets or {}
        if slot_data.world_version ~= DATA.world_version then
            print(string.format("Bug Fables: this seed is world %s, the pack was made from %s",
                tostring(slot_data.world_version), DATA.world_version))
        end
    end
    SEED.locations = nil
    if location_ids then
        SEED.locations = {}
        for _, id in ipairs(location_ids) do SEED.locations[id] = true end
    end
    SEED.entrances = seed_entrances(SEED.door_targets)
    -- With a starting member, the starting members are start inventory.
    SEED.precollected = {}
    for number, name in ipairs(DATA.members) do
        if SEED.starting_member == 3 or SEED.starting_member == number - 1 then SEED.precollected[name] = 1 end
    end
    seed_version = seed_version + 1
    cache_key = nil
end

local events_held = {}

local function count(name)
    local held = events_held[name] or 0
    local code = ITEM_CODE[name]
    if code then held = held + Tracker:ProviderCountForCode(code) end
    return math.max(held, SEED.precollected[name] or 0)
end

local function item_count(ability)
    local data = DATA.abilities[ability]
    if data.base_option and not truthy(SEED.options[data.base_option]) then return data.level - 1 end
    return data.level
end

local eval
-- The regions the sweep running now has reached, for CanReachRegion.
local reached_now = {}

local RULES = {
    And = function(rule)
        for _, child in ipairs(rule.children) do
            if not eval(child) then return false end
        end
        return true
    end,
    Or = function(rule)
        for _, child in ipairs(rule.children) do
            if eval(child) then return true end
        end
        return false
    end,
    Has = function(rule) return count(rule.args.item_name) >= rule.args.count end,
    HasAllCounts = function(rule)
        for name, needed in pairs(rule.args.item_counts) do
            if count(name) < needed then return false end
        end
        return true
    end,
    True_ = function() return true end,
    False_ = function() return false end,
    Filtered = function(rule) return eval(rule.child) end,
    -- Read against the regions reached so far: a false answer is asked again on the sweep's next pass, as Archipelago
    -- rechecks such an entrance when the region is reached.
    CanReachRegion = function(rule) return reached_now[rule.args.region_name] == true end,
    -- The apworld's own rules (custom_rules.py), each as its _instantiate resolves it.
    CanUse = function(rule)
        local data = DATA.abilities[rule.args.ability]
        if data.holder and (SEED.starting_member >= 0 or data.holder == DATA.late_member)
            and count(data.holder) < 1 then
            return false
        end
        local needed = item_count(rule.args.ability)
        return needed == 0 or count(data.item) >= needed
    end,
    Member = function(rule) return SEED.starting_member < 0 or count(rule.args.name) >= 1 end,
    MoveItem = function(rule)
        local needed = item_count(rule.args.ability)
        return needed == 0 or count(DATA.abilities[rule.args.ability].item) >= needed
    end,
    Boat = function(rule)
        if truthy(SEED.options.progressive_boat) then return count("Progressive Boat") >= rule.args.level end
        return count(DATA.boat_levels[tostring(rule.args.level)]) >= 1
    end,
    WayBack = function(rule) return truthy(SEED.options.points_of_no_return) or eval(rule.child) end,
}

-- As rule_builder/options.py checks a filter: "contains" asks for a name in an option set (a list in slot_data), "in"
-- for the option's value in the filter's list.
local function passes_filter(filter)
    local value = SEED.options[DATA.option_names[filter.option]]
    local operator = filter.operator or "eq"
    if operator == "contains" then
        for _, element in ipairs(value or {}) do
            if element == filter.value then return true end
        end
        return false
    elseif operator == "in" then
        for _, element in ipairs(filter.value) do
            if option_number(element) == option_number(value) then return true end
        end
        return false
    end
    local compare = OPERATORS[operator]
    if compare == nil then error("Bug Fables: no option operator " .. tostring(operator)) end
    return compare(option_number(value), option_number(filter.value))
end

local function passes_options(rule)
    for _, filter in ipairs(rule.options or {}) do
        if not passes_filter(filter) then return false end
    end
    return true
end

eval = function(rule)
    if rule == nil then return true end
    if not passes_options(rule) then return rule.filtered_resolution == true end
    local evaluate = RULES[rule.rule]
    if evaluate == nil then error("Bug Fables: no rule " .. tostring(rule.rule)) end
    return evaluate(rule)
end

local function sweep(without_events)
    events_held = {}
    local reached = { [DATA.origin] = true }
    reached_now = reached
    local collected = {}
    local changed = true
    while changed do
        changed = false
        for _, entrance in ipairs(SEED.entrances) do
            if reached[entrance.from] and not reached[entrance.to] and eval(entrance.rule) then
                reached[entrance.to] = true
                changed = true
            end
        end
        for index, event in ipairs(without_events and {} or DATA.events) do
            if not collected[index] and reached[event.region] and category_on(event.category) and eval(event.rule) then
                collected[index] = true
                events_held[event.item] = (events_held[event.item] or 0) + 1
                changed = true
            end
        end
    end
    local locations = {}
    for _, loc in ipairs(DATA.locations) do
        locations[loc.id] = reached[loc.region] == true and eval(loc.rule)
    end
    return { reached = reached, locations = locations }
end

local function state_key()
    local parts = { seed_version }
    for _, item in ipairs(DATA.items) do
        parts[#parts + 1] = Tracker:ProviderCountForCode(item.code)
    end
    return table.concat(parts, ",")
end

-- The sweep for the items tracked now, redone only when they or the seed change.
function bf_state()
    local key = state_key()
    if key ~= cache_key then
        cache = sweep()
        cache_key = key
    end
    return cache
end

function bf_in_seed(id)
    id = tonumber(id)
    if SEED.locations then return SEED.locations[id] == true end
    -- A pending location (a quest not yet gone through) is in no seed, so it isn't exported.
    if LOCATION[id] == nil then return false end
    return category_on(LOCATION[id].category)
end

function bf_room_in_seed(map)
    for _, id in ipairs(IDS_BY_MAP[map] or {}) do
        if bf_in_seed(id) then return true end
    end
    return false
end

function bf_area_in_seed(area)
    for room, room_area in pairs(DATA.room_areas) do
        if room_area == area and bf_room_in_seed(room) then return true end
    end
    return false
end

function bf_location(id)
    return bf_state().locations[tonumber(id)] == true
end

-- For the parity tests. bf_eval_state, then bf_eval: rules against the tracked items alone, no story events, as a
-- CollectionState the items were collected into without a sweep.
function bf_eval_state()
    sweep(true)
end

function bf_eval(rule)
    return eval(rule)
end

-- The regions the sweep reached, and this seed's entrances.
function bf_reached()
    return bf_state().reached
end

function bf_entrances()
    return SEED.entrances
end

bf_set_seed(nil, nil)
