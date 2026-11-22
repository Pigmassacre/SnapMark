-- The part that really marks, in and out of combat alike.
--
-- MarkWheel's key is an override binding that clicks MarkWheelButton, a secure action button, on key down and key
-- up. A secure snippet wrapped around its OnClick does the work:
--
--   key down  centres MarkWheelPad, an invisible secure frame far larger than the screen, on the pointer, so the
--             pointer can never leave it. Esc and right-click now cancel. The wheel you see opens (Wheel.lua).
--   key up    reads the pointer's position on the pad, which is the movement since the key went down, picks the
--             marker with the same rule as ns.pick, and arms Blizzard's own "raidtarget" action for this click.
--
-- The button has pressAndHoldAction set, so Blizzard runs "type" on key down and "typerelease" on key up. Key down
-- has no action, except to target what you point at when you asked for that in combat.
--
-- Who gets marked: out of combat, PreClick (ordinary addon code, which may set attributes outside a fight) works out
-- which unit you pointed at when you pressed and puts it in "mw-unit". In combat it can't, so the snippet marks your
-- target (or focus).

local _, ns = ...

local Secure = {}
ns.Secure = Secure

local PAD_SIZE = 20000 -- UI units; larger than any screen in either direction from any point on it

----------------------------------------------------------------------------------------------------------------------
-- The snippets. Restricted code: no tables, only the restricted environment's functions.

-- self: the button. button: "LeftButton" from the key, "Cancel" from Esc or right-click. down: key down or up.
local ON_CLICK = [[
    local pad = self:GetFrameRef("pad")
    if button == "Cancel" then
        self:SetAttribute("type", nil)
        self:SetAttribute("typerelease", nil)
        self:SetAttribute("mw-unit", nil)
        if pad:IsShown() then
            pad:Hide()
            self:CallMethod("WheelClosed", "cancel")
        end
        return false
    end

    if down then
        self:SetAttribute("type", nil)
        self:SetAttribute("typerelease", nil)
        local targetNow = self:GetAttribute("mw-targetnow")
        self:SetAttribute("mw-targetnow", nil)
        if PlayerInCombat() then self:SetAttribute("mw-unit", nil) end
        pad:ClearAllPoints()
        pad:SetPoint("CENTER", "$cursor", 0, 0)
        pad:Show()
        self:SetBindingClick(true, "ESCAPE", self, "Cancel")
        self:SetBindingClick(true, "BUTTON2", self, "Cancel")
        local first = false
        local inFight = PlayerInCombat() and self:GetAttribute("mw-mode") == "point"
            and self:GetAttribute("mw-combat") == "targetfirst"
        if (targetNow or inFight) and UnitExists("mouseover") then
            self:SetAttribute("unit", "mouseover")
            self:SetAttribute("type", "target")
            first = true
        end
        self:CallMethod("WheelOpened", first)
        return nil, true
    end

    if not pad:IsShown() then
        self:SetAttribute("type", nil)
        self:SetAttribute("typerelease", nil)
        return false
    end
    local x, y = pad:GetMousePosition()
    local dx, dy
    if x and y then
        dx = (x - 0.5) * pad:GetWidth()
        dy = (y - 0.5) * pad:GetHeight()
    end
    pad:Hide()

    local unit = self:GetAttribute("mw-unit")
    self:SetAttribute("mw-unit", nil)
    if not unit then
        if self:GetAttribute("mw-mode") == "focus" then unit = "focus" else unit = "target" end
    end

    local marker, action
    if dx then
        local dead = self:GetAttribute("mw-dead") or 16
        if dx * dx + dy * dy >= dead * dead then
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
            marker, action = best, "toggle"
        else
            local center = self:GetAttribute("mw-center")
            if center == "skull" then
                marker, action = 8, "set"
            elseif center == "clear" then
                marker, action = 8, "clear"
            end
        end
    end

    if marker and unit ~= "lost" then
        self:SetAttribute("unit", unit)
        self:SetAttribute("marker", marker)
        self:SetAttribute("action", action)
        self:SetAttribute("type", "raidtarget")
        self:SetAttribute("typerelease", "raidtarget")
        self:CallMethod("WheelClosed", action, marker)
    else
        self:SetAttribute("type", nil)
        self:SetAttribute("typerelease", nil)
        if marker then
            self:CallMethod("WheelClosed", "lost")
        else
            self:CallMethod("WheelClosed", "none")
        end
    end
    return nil, true
]]

-- After Blizzard's action ran: leave nothing armed.
local AFTER_CLICK = [[
    self:SetAttribute("type", nil)
    self:SetAttribute("typerelease", nil)
    self:SetAttribute("unit", nil)
    self:SetAttribute("marker", nil)
    self:SetAttribute("action", nil)
]]

-- Whenever the pad hides, for any reason, Esc and right-click go back to normal.
local ON_PAD_HIDE = [[ control:ClearBindings() ]]

----------------------------------------------------------------------------------------------------------------------
-- What you pointed at (ordinary addon code)

local plateSerial, serial, targetSerial = {}, 0, 0

ns.On("NAME_PLATE_UNIT_ADDED", function(unit)
    if type(unit) == "string" then serial = serial + 1 plateSerial[unit] = serial end
end)
ns.On("NAME_PLATE_UNIT_REMOVED", function(unit)
    if type(unit) == "string" then serial = serial + 1 plateSerial[unit] = serial end
end)
ns.On("PLAYER_TARGET_CHANGED", function()
    targetSerial = targetSerial + 1
    Secure.trace("your target changed")
end)

local candidates = { "target", "focus", "player", "pet", "targettarget", "focustarget" }
for i = 1, 4 do candidates[#candidates + 1] = "party" .. i candidates[#candidates + 1] = "partypet" .. i end
for i = 1, 40 do candidates[#candidates + 1] = "raid" .. i end
for i = 1, 5 do candidates[#candidates + 1] = "boss" .. i end

local function plateToken(plate)
    local token = ns.plain(plate.namePlateUnitToken)
    if type(token) ~= "string" and plate.UnitFrame then token = ns.plain(plate.UnitFrame.unit) end
    if type(token) == "string" and token:match("^nameplate%d+$") then return token end
end

-- The nameplate token of what the pointer is on, when it's pointing at the body rather than the plate.
local function plateByComparing()
    for i = 1, 40 do
        local token = "nameplate" .. i
        if ns.read(UnitExists, token) and ns.read(UnitIsUnit, "mouseover", token) == true then return token end
    end
end

-- What the pointer is on, as something that can be found again when the key comes up. nil: nothing.
-- targetNow: there is no way to find it again (no readable ID, no nameplate), so the key targets it as it goes down.
function Secure.capture()
    if not ns.read(UnitExists, "mouseover") then return nil end
    local c = { guid = ns.read(UnitGUID, "mouseover"), isTarget = ns.read(UnitIsUnit, "mouseover", "target"),
        targetSerial = targetSerial }
    if C_NamePlate and C_NamePlate.GetNamePlateForUnit then
        local ok, plate = pcall(C_NamePlate.GetNamePlateForUnit, "mouseover")
        local token = ok and type(plate) == "table" and plateToken(plate) or nil
        if not token then
            token = plateByComparing()
            if token then
                local okP, p = pcall(C_NamePlate.GetNamePlateForUnit, token)
                plate = okP and p or nil
            end
        end
        if token and type(plate) == "table" then
            if not plateSerial[token] then serial = serial + 1 plateSerial[token] = serial end
            c.plate, c.token, c.serial = plate, token, plateSerial[token]
        end
    end
    -- Can it be found again when the key comes up, wherever the pointer is by then? Only by a lasting token: its
    -- nameplate, a group token, target or focus. If not (a friendly player outside your group, a body whose ID the
    -- game hides), the key targets it as it goes down and marks your target.
    local again = Secure.resolve(c)
    c.again = again
    c.targetNow = not c.isTarget and (again == nil or again == "mouseover")
    return c
end

-- /markwheel debug: each step of a press and release, in chat.
function Secure.trace(fmt, ...)
    if ns.debug then ns.say("|cff999999" .. string.format(fmt, ...) .. "|r") end
end

-- The unit token for a capture now, or nil when it can't be found again.
function Secure.resolve(c)
    if c.plate and plateSerial[c.token] == c.serial then
        local ok, plate = pcall(C_NamePlate.GetNamePlateForUnit, c.token)
        if ok and plate == c.plate then return c.token end
    end
    if c.guid then
        local token = UnitTokenFromGUID and ns.read(UnitTokenFromGUID, c.guid)
        if type(token) == "string" and token ~= "mouseover" then return token end
        for _, unit in ipairs(candidates) do
            if ns.read(UnitGUID, unit) == c.guid then return unit end
        end
    end
    if c.isTarget and c.targetSerial == targetSerial then return "target" end
    if c.guid and ns.read(UnitGUID, "mouseover") == c.guid then return "mouseover" end
    return nil
end

----------------------------------------------------------------------------------------------------------------------
-- Setup and keeping the button in step with the settings and key

local button, pad, owner
local pending = false

-- Modifier versions of a key that nothing else uses, so the wheel still opens with Shift or Ctrl held.
local MODIFIERS = { "SHIFT-", "CTRL-", "ALT-" }

function Secure.sync()
    if not button then return end
    if InCombatLockdown() then pending = true return end
    pending = false
    local db = ns.db
    button:SetAttribute("mw-mode", db.mode)
    button:SetAttribute("mw-combat", db.combat)
    button:SetAttribute("mw-center", db.center)
    button:SetAttribute("mw-dead", ns.deadZone())
    ClearOverrideBindings(owner)
    for _, key in ipairs(ns.keys()) do
        SetOverrideBindingClick(owner, true, key, button:GetName(), "LeftButton")
        if not key:find("%-") then
            for _, mod in ipairs(MODIFIERS) do
                local action = GetBindingAction(mod .. key)
                if action == nil or action == "" then
                    SetOverrideBindingClick(owner, true, mod .. key, button:GetName(), "LeftButton")
                end
            end
        end
    end
end

function Secure.setup()
    if button then return true end
    if InCombatLockdown() then pending = true return false end

    owner = CreateFrame("Frame")

    pad = CreateFrame("Frame", "MarkWheelPad", UIParent, "SecureHandlerBaseTemplate")
    pad:SetSize(PAD_SIZE, PAD_SIZE)
    pad:SetPoint("CENTER")
    pad:EnableMouse(false)
    pad:Hide()

    button = CreateFrame("Button", "MarkWheelButton", UIParent, "SecureActionButtonTemplate,SecureHandlerBaseTemplate")
    button:SetSize(1, 1)
    button:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", -10, -10)
    button:EnableMouse(false)
    button:RegisterForClicks("AnyDown", "AnyUp")
    button:SetAttribute("pressAndHoldAction", true)
    button:SetFrameRef("pad", pad)

    button.WheelOpened = function(_, first) ns.Wheel.open(first) end
    button.WheelClosed = function(_, how, marker)
        Secure.trace("the wheel closed: %s%s", how, marker and (", marker " .. marker) or "")
        ns.Wheel.close(how, marker)
    end

    -- Runs before the snippet, on every click. Outside a fight it may set attributes: it tells the snippet which
    -- unit you pointed at.
    button:SetScript("PreClick", function(self, which, down)
        if which == "Cancel" then return end
        if down then
            Secure.pointed = Secure.capture()
            local c = Secure.pointed
            if not c then
                Secure.trace("pressed: not pointing at anything, so it marks your %s", ns.db.mode == "focus" and "focus" or "target")
            else
                Secure.trace("pressed: pointing at something. ID %s, nameplate %s, your target %s, found again as %s: %s",
                    c.guid and "readable" or "hidden", c.token or "none", c.isTarget == true and "yes" or "no",
                    tostring(c.again), c.targetNow and "targets it now" or "no need to target it")
            end
            if not InCombatLockdown() then
                self:SetAttribute("mw-unit", nil)
                self:SetAttribute("mw-targetnow",
                    (ns.db.mode == "point" and Secure.pointed and Secure.pointed.targetNow) and true or nil)
            end
        elseif not InCombatLockdown() and ns.db.mode == "point" and Secure.pointed then
            -- Targeted as the key went down: mark the target.
            local unit = Secure.pointed.targetNow and "target" or Secure.resolve(Secure.pointed)
            self:SetAttribute("mw-unit", unit or "lost")
            Secure.trace("let go: marks %s", unit or "nothing (lost it)")
        end
    end)

    SecureHandlerWrapScript(button, "OnClick", button, ON_CLICK, AFTER_CLICK)
    SecureHandlerWrapScript(pad, "OnHide", button, ON_PAD_HIDE)

    ns.ready = true
    Secure.sync()
    return true
end

-- Puts things right when the key's release never arrived (the game lost focus, say). Only outside a fight; in one,
-- Esc clears it, and the next press starts afresh anyway.
function Secure.reset()
    if pad and pad:IsShown() and not InCombatLockdown() then pad:Hide() end
end

function Secure.isOpen()
    return pad and pad:IsShown() or false
end

ns.On("LOGIN", function() Secure.setup() end)
ns.On("PLAYER_REGEN_ENABLED", function()
    if not button then Secure.setup() elseif pending then Secure.sync() end
end)
ns.On("UPDATE_BINDINGS", function() Secure.sync() end)
ns.On("SETTING", function(key)
    if key == "mode" or key == "combat" or key == "center" or key == "size" then Secure.sync() end
end)
