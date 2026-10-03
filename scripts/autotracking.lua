-- Archipelago auto-tracking (PopTracker's doc/AUTOTRACKING.md): the seed from slot_data, items as received, checks
-- as checked.

local last_index = -1

local function reset_item(code)
    local item = Tracker:FindObjectForCode(code)
    if item == nil then return end
    if item.Type == "toggle" then
        item.Active = false
    else
        item.AcquiredCount = 0
    end
end

local function on_clear(slot_data)
    last_index = -1
    for _, item in ipairs(DATA.items) do reset_item(item.code) end
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

Archipelago:AddClearHandler("bug fables clear", on_clear)
Archipelago:AddItemHandler("bug fables item", on_item)
Archipelago:AddLocationHandler("bug fables location", on_location)
