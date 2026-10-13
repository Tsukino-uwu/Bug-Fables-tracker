-- Archipelago auto-tracking (PopTracker's doc/AUTOTRACKING.md): the seed from slot_data, items as received, checks
-- as checked, and data storage read as PopTracker's ap-storage-example reads it: SetNotify, then Get, one handler for
-- both answers, each value's type checked.

local last_index = -1

-- What the mod writes to data storage (the randomizer's build steps 55 and 57), as last read: the doors gone through
-- and the maps visited (name -> true), and the map the player is on.
STORAGE = { doors = {}, visited = {}, map = nil }
local session = nil
local keys = {}

-- Archipelago's hint statuses (docs/network protocol.md, HintStatus) as PopTracker's Highlight states.
local HIGHLIGHT_OF_STATUS = {
    [0] = Highlight.Unspecified,
    [10] = Highlight.NoPriority,
    [20] = Highlight.Avoid,
    [30] = Highlight.Priority,
    [40] = Highlight.None,
}
local highlighted = {}

local MEMBER_CODES = {}
for _, item in ipairs(DATA.items) do
    for _, member in ipairs(DATA.members) do
        if item.name == member then MEMBER_CODES[#MEMBER_CODES + 1] = item.code end
    end
end
local DEATH_SECONDS = 10
local death_left = 0

local function reset_item(code)
    local item = Tracker:FindObjectForCode(code)
    if item == nil then return end
    if item.Type == "toggle" then
        item.Active = false
    else
        item.AcquiredCount = 0
    end
end

local function names(value)
    local out = {}
    if type(value) ~= "table" then return out end
    for _, name in ipairs(value) do
        if type(name) == "string" then out[name] = true end
    end
    return out
end

local function show_hints(hints)
    for path in pairs(highlighted) do
        local section = Tracker:FindObjectForCode(path)
        if section then section.Highlight = Highlight.None end
    end
    highlighted = {}
    if type(hints) ~= "table" then return end
    for _, hint in ipairs(hints) do
        -- This slot's own checks: where the hinted items are found.
        if type(hint) == "table" and hint.finding_player == Archipelago.PlayerNumber then
            local path = DATA.section_paths[hint.location]
            local section = path and Tracker:FindObjectForCode(path)
            if section then
                section.Highlight = HIGHLIGHT_OF_STATUS[hint.status] or Highlight.Unspecified
                highlighted[path] = true
            end
        end
    end
end

-- Rules run again when an item changes: a switch flipped makes the fog of war follow the visited key.
local function refresh()
    local switch = Tracker:FindObjectForCode("bf_refresh")
    if switch then switch.Active = not switch.Active end
end

-- With "Follow the player's room" on, the map's region tab, its area's, then its room's.
local function follow(map)
    local setting = Tracker:FindObjectForCode("auto_tab")
    local tab = map and DATA.map_tabs[map]
    if not (setting and setting.Active and tab) then return end
    Tracker:UiHint("ActivateTab", tab.region)
    Tracker:UiHint("ActivateTab", tab.area)
    Tracker:UiHint("ActivateTab", tab.room)
end

local function on_storage(key, value)
    if key == keys.doors then
        STORAGE.doors = names(value)
    elseif key == keys.visited then
        STORAGE.visited = names(value)
        refresh()
    elseif key == keys.map then
        STORAGE.map = type(value) == "string" and value or nil
        follow(STORAGE.map)
    elseif key == keys.goal then
        local goal = Tracker:FindObjectForCode("goal")
        if goal then goal.Active = value == Archipelago.ClientStatus.GOAL end
    elseif key == keys.hints then
        show_hints(value)
    end
end

local function on_clear(slot_data)
    last_index = -1
    for _, item in ipairs(DATA.items) do reset_item(item.code) end
    reset_item("goal")
    for _, path in pairs(DATA.section_paths) do
        local section = Tracker:FindObjectForCode(path)
        if section then section.AvailableChestCount = section.ChestCount end
    end
    local ids = {}
    for _, id in ipairs(Archipelago.MissingLocations or {}) do ids[#ids + 1] = id end
    for _, id in ipairs(Archipelago.CheckedLocations or {}) do ids[#ids + 1] = id end
    bf_set_seed(slot_data, ids)
    for _, id in ipairs(Archipelago.CheckedLocations or {}) do
        local path = DATA.section_paths[id]
        local section = path and Tracker:FindObjectForCode(path)
        if section then section.AvailableChestCount = 0 end
    end

    -- Another seed, team or slot starts the pack's own state afresh; the same one keeps it until the server answers.
    local team, slot = Archipelago.TeamNumber or 0, Archipelago.PlayerNumber
    local identity = tostring(Archipelago.Seed) .. "|" .. team .. "|" .. slot
    if identity ~= session then
        session = identity
        STORAGE = { doors = {}, visited = {}, map = nil }
    end
    local suffix = "_" .. team .. "_" .. slot
    keys = {
        doors = "bug_fables_doors" .. suffix,
        visited = "bug_fables_visited" .. suffix,
        map = "bug_fables_map" .. suffix,
        goal = "_read_client_status" .. suffix,
        hints = "_read_hints" .. suffix,
    }
    local list = { keys.doors, keys.visited, keys.map, keys.goal, keys.hints }
    Archipelago:SetNotify(list)
    Archipelago:Get(list)
end

local function on_item(index, item_id, item_name, player_number)
    if index <= last_index then return end
    last_index = index
    local code = DATA.item_codes_by_id[item_id]
    if code == nil then return end
    local item = Tracker:FindObjectForCode(code)
    if item == nil then return end
    if item.Type == "toggle" then
        item.Active = true
    else
        item.AcquiredCount = item.AcquiredCount + 1
    end
end

local function on_location(location_id, location_name)
    local path = DATA.section_paths[location_id]
    local section = path and Tracker:FindObjectForCode(path)
    if section then section.AvailableChestCount = 0 end
end

local function mark_party(text)
    for _, code in ipairs(MEMBER_CODES) do
        local item = Tracker:FindObjectForCode(code)
        if item then
            item.BadgeText = text
            item.BadgeTextColor = "#ff5050"
        end
    end
end

-- A DeathLink received marks the party for a few seconds.
local function on_bounced(bounce)
    if type(bounce) ~= "table" or type(bounce.tags) ~= "table" then return end
    for _, tag in ipairs(bounce.tags) do
        if tag == "DeathLink" then
            mark_party("DL")
            death_left = DEATH_SECONDS
            return
        end
    end
end

local function on_frame(elapsed)
    if death_left <= 0 then return end
    death_left = death_left - elapsed
    if death_left <= 0 then mark_party("") end
end

Archipelago:AddClearHandler("bug fables clear", on_clear)
Archipelago:AddItemHandler("bug fables item", on_item)
Archipelago:AddLocationHandler("bug fables location", on_location)
Archipelago:AddRetrievedHandler("bug fables retrieved", on_storage)
Archipelago:AddSetReplyHandler("bug fables set reply", on_storage)
Archipelago:AddBouncedHandler("bug fables bounced", on_bounced)
ScriptHost:AddOnFrameHandler("bug fables deathlink", on_frame)
