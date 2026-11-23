-- SnapMark: hold a key, flick toward a target marker, let go.
--
-- Core: saved settings, the markers, the one rule that turns a movement into a marker (shared by the wheel you see
-- and, as text, by the secure snippet that really marks), events, the key and the slash command.
--
-- How marking works: addons may not call SetRaidTarget themselves. SnapMark's key clicks a secure button
-- (Secure.lua); a secure snippet reads the direction from an invisible frame much larger than the screen and hands
-- the marker to Blizzard's own "raidtarget" button action. Wheel.lua only draws.
--
-- A second key opens the same wheel for ground markers: letting go hands the marker to Blizzard's "worldmarker"
-- action, and the game's targeting circle then places it where you click.

local ADDON, ns = ...

ns.ADDON = ADDON
ns.MEDIA = "Interface\\AddOns\\" .. ADDON .. "\\Media\\"
ns.BINDING = "SNAPMARK_HOLD"
ns.GROUND_BINDING = "SNAPMARK_GROUND"

BINDING_HEADER_SNAPMARK = "SnapMark"
BINDING_NAME_SNAPMARK_HOLD = "Marker wheel (hold)"
BINDING_NAME_SNAPMARK_GROUND = "Ground marker wheel (hold)"

----------------------------------------------------------------------------------------------------------------------
-- Settings

ns.DEFAULTS = {
    mode = "point",       -- who gets marked: "point" (what you point at, else your target), "target", "focus"
    combat = "target",    -- in combat with "point": "target" (mark your target) or "targetfirst" (target what you
                          -- point at as you press, then mark it)
    center = "none",      -- letting go in the centre: "none", "skull", "clear"
    groundCenter = "none", -- letting go in the centre of the ground wheel: "none", "clear" (all ground markers)
    size = 1.0,           -- wheel size, 0.7 to 1.5
    background = 0.85,    -- how solid the wheel's backing is, 0 to 1
    names = true,         -- the name of the marker you are about to set, in the centre
    sound = true,         -- a tick when the choice changes and a click when a mark is set
    toldKey = false,      -- said once how to choose a key, when the wheel had none
}

local function loadDB()
    if type(SnapMarkDB) ~= "table" then SnapMarkDB = {} end
    for k, v in pairs(ns.DEFAULTS) do
        if SnapMarkDB[k] == nil then SnapMarkDB[k] = v end
    end
    local db = SnapMarkDB
    if db.mode ~= "point" and db.mode ~= "target" and db.mode ~= "focus" then db.mode = "point" end
    if db.combat ~= "target" and db.combat ~= "targetfirst" then db.combat = "target" end
    if db.center ~= "none" and db.center ~= "skull" and db.center ~= "clear" then db.center = "none" end
    if db.groundCenter ~= "none" and db.groundCenter ~= "clear" then db.groundCenter = "none" end
    if type(db.size) ~= "number" or db.size ~= db.size then db.size = 1 end
    db.size = math.max(0.7, math.min(1.5, db.size))
    if type(db.background) ~= "number" or db.background ~= db.background then db.background = 0.85 end
    db.background = math.max(0, math.min(1, db.background))
    ns.db = db
end

----------------------------------------------------------------------------------------------------------------------
-- The markers, in wheel order: slot 1 at twelve o'clock, then clockwise. Raid target index, name and color, and for
-- the light ones how bright their slice lights up, so it doesn't wash out the icon.

local S = 0.70710678118654752
ns.SLOTS = {
    { marker = 8, name = "Skull", color = { 0.95, 0.95, 0.92 }, x = 0, y = 1, light = 0.45 },
    { marker = 7, name = "Cross", color = { 1.00, 0.30, 0.24 }, x = S, y = S },
    { marker = 6, name = "Square", color = { 0.30, 0.62, 1.00 }, x = 1, y = 0 },
    { marker = 5, name = "Moon", color = { 0.78, 0.86, 1.00 }, x = S, y = -S, light = 0.6 },
    { marker = 4, name = "Triangle", color = { 0.36, 0.90, 0.36 }, x = 0, y = -1 },
    { marker = 3, name = "Diamond", color = { 0.84, 0.42, 1.00 }, x = -S, y = -S },
    { marker = 2, name = "Circle", color = { 1.00, 0.58, 0.16 }, x = -1, y = 0 },
    { marker = 1, name = "Star", color = { 1.00, 0.90, 0.24 }, x = -S, y = S, light = 0.75 },
}
ns.SLOT_OF = {}
for i, s in ipairs(ns.SLOTS) do ns.SLOT_OF[s.marker] = i end

-- How far from where you pressed, in UI units, a movement starts to count. Inside it, letting go is the centre.
ns.DEAD = 16

function ns.deadZone()
    return ns.DEAD * (ns.db and ns.db.size or 1)
end

-- The rule: past the dead zone, the marker whose direction is nearest to the movement, at any distance. dx and dy
-- are UI units from where you pressed, y up. Returns the slot index (1 is the skull at the top), or nil in the centre.
-- The secure snippet in Secure.lua does the same sums in the same order, so both always agree, ties included;
-- tests/run_snapmark.py checks that.
function ns.pick(dx, dy, dead)
    dead = dead or ns.deadZone()
    if dx * dx + dy * dy < dead * dead then return nil end
    local s = 0.70710678118654752
    local best, top, d = 8, dy, 0
    d = (dx + dy) * s
    if d > top then best, top = 7, d end
    d = dx
    if d > top then best, top = 6, d end
    d = (dx - dy) * s
    if d > top then best, top = 5, d end
    d = -dy
    if d > top then best, top = 4, d end
    d = (-dx - dy) * s
    if d > top then best, top = 3, d end
    d = -dx
    if d > top then best, top = 2, d end
    d = (dy - dx) * s
    if d > top then best, top = 1, d end
    return ns.SLOT_OF[best]
end

function ns.markerIcon(marker)
    return "Interface\\TargetingFrame\\UI-RaidTargetingIcon_" .. marker
end

-- Ground markers are numbered differently from raid target markers (ground marker 1 is the square). The game's names
-- for them carry their icons, so the order comes from there; if those can't be read, the order the game has always
-- used.
local GROUND_ORDER = { 6, 4, 3, 7, 1, 2, 5, 8 } -- ground marker index -> raid target marker shown

function ns.groundMarkers()
    local order, seen = {}, {}
    for i = 1, 8 do
        local name = _G["WORLD_MARKER" .. i]
        local icon = type(name) == "string" and tonumber(name:match("RaidTargetingIcon_(%d)"))
        if not icon or seen[icon] then order = GROUND_ORDER break end
        order[i], seen[icon] = icon, true
    end
    local of = {}
    for i, icon in ipairs(order) do of[icon] = i end
    return of -- raid target marker -> ground marker index
end

-- Whether this realm has ground markers at all.
function ns.groundEnabled()
    if IsRaidMarkerSystemEnabled then return ns.read(IsRaidMarkerSystemEnabled) == true end
    return PlaceRaidMarker ~= nil
end

----------------------------------------------------------------------------------------------------------------------
-- Hidden values: this client hides some values from addons (a mob's name in an instance, for one). They may be shown
-- with SetText but not compared or joined.

function ns.isSecret(v)
    return issecretvalue ~= nil and issecretvalue(v) or false
end

function ns.plain(v)
    if ns.isSecret(v) then return nil end
    return v
end

function ns.read(fn, ...)
    if not fn then return nil end
    local ok, v = pcall(fn, ...)
    if not ok then return nil end
    return ns.plain(v)
end

----------------------------------------------------------------------------------------------------------------------
-- Events

local handlers = {}
local frame = CreateFrame("Frame")

function ns.On(event, fn)
    if not handlers[event] then
        handlers[event] = {}
        if event ~= "LOGIN" and event ~= "SETTING" then frame:RegisterEvent(event) end
    end
    table.insert(handlers[event], fn)
end

function ns.fire(event, ...)
    for _, fn in ipairs(handlers[event] or {}) do fn(...) end
end

frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        if ... == ADDON then loadDB() end
        return
    end
    if event == "PLAYER_LOGIN" then
        if not ns.db then loadDB() end
        ns.fire("LOGIN")
    end
    ns.fire(event, ...)
end)

-- Changes a setting and tells the rest of the addon.
function ns.set(key, value)
    if ns.db[key] == value then return end
    ns.db[key] = value
    ns.fire("SETTING", key, value)
end

function ns.say(msg)
    DEFAULT_CHAT_FRAME:AddMessage("|cff8fd3c4SnapMark:|r " .. msg)
end

function ns.play(kit)
    if not (ns.db and ns.db.sound) then return end
    local id = type(kit) == "number" and kit or (SOUNDKIT and SOUNDKIT[kit])
    if id then pcall(PlaySound, id, "SFX") end
end

----------------------------------------------------------------------------------------------------------------------
-- The key

-- binding: ns.BINDING (the marker wheel, when left out) or ns.GROUND_BINDING.
function ns.keys(binding)
    return { GetBindingKey(binding or ns.BINDING) }
end

function ns.keyText(binding)
    local key = GetBindingKey(binding or ns.BINDING)
    if not key then return "Not set" end
    return GetBindingText and GetBindingText(key) or key
end

-- Binds key to a wheel, in place of any key it had, and saves the game's key bindings.
function ns.bindKey(key, binding)
    binding = binding or ns.BINDING
    if InCombatLockdown() then
        ns.say("keys can't change during a fight. Try again after it.")
        return false
    end
    for _, old in ipairs(ns.keys(binding)) do SetBinding(old) end
    SetBinding(key, binding)
    SaveBindings(GetCurrentBindingSet())
    return true
end

-- Once: if the wheel has no key, say where to choose one.
local function tellKey()
    if ns.db.toldKey or GetBindingKey(ns.BINDING) then return end
    ns.db.toldKey = true
    ns.say("choose a key for the marker wheel in Options > AddOns > SnapMark, or type /snapmark.")
end

ns.On("PLAYER_ENTERING_WORLD", function()
    if C_Timer then C_Timer.After(2, tellKey) else tellKey() end
end)

-- Runs only when the key reaches the game's own binding instead of the wheel: before the wheel is ready (it is set
-- up outside a fight).
function SnapMark_OnBinding(keystate)
    if keystate ~= "down" then return end
    if not ns.ready then ns.say("the wheel starts when this fight ends.") end
end

----------------------------------------------------------------------------------------------------------------------
-- Slash command

local function help()
    local ground = ""
    if GetBindingKey(ns.GROUND_BINDING) then
        ground = "For a ground marker, hold " .. ns.keyText(ns.GROUND_BINDING) .. ", let go, then click the ground. "
    end
    ns.say("hold your key (" .. ns.keyText() .. "), move toward a marker and let go. " .. ground
        .. "/snapmark opens the settings; /snapmark preview shows the wheel.")
end

SLASH_SNAPMARK1 = "/snapmark"
SlashCmdList.SNAPMARK = function(msg)
    local cmd = (msg or ""):lower():match("^%s*(%S*)")
    if cmd == "" or cmd == "options" or cmd == "settings" then
        if ns.openOptions then ns.openOptions() else help() end
    elseif cmd == "preview" then
        ns.togglePreview()
    elseif cmd == "debug" then
        ns.debug = not ns.debug
        ns.say(ns.debug and "debug on: each press and release of the wheel is reported here. /snapmark debug again turns it off."
            or "debug off.")
    else
        help()
    end
end

function SnapMark_OnAddonCompartmentClick()
    if ns.openOptions then ns.openOptions() end
end
