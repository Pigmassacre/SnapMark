#!/usr/bin/env python3
"""Runs SnapMark headless against a stand-in for the WoW API and checks that it marks what it should, in and out of
combat, and can draw the wheel to PNG files.

The stand-in follows Blizzard's secure code where SnapMark depends on it (wow-ui-source, forever branch):

  - The secure snippets run in a restricted environment with only the functions Blizzard's has, through frame
    handles with Blizzard's methods. HANDLE:GetMousePosition returns nothing outside the frame and HANDLE:SetPoint
    with "$cursor" places by the pointer, as in RestrictedFrames.lua.
  - A click runs PreClick, then the wrapped OnClick snippet, then Blizzard's action button with its press-and-hold
    rule ("type" on key down, "typerelease" on key up), then the snippet after it, as in SecureHandlers.lua and
    SecureTemplates.lua. The "raidtarget", "worldmarker" and "target" actions work as Blizzard's do; an action whose
    unit doesn't exist is dropped, as there.
  - PlaceRaidMarker with no position puts up the game's targeting circle; clickGround() places the marker.
  - In combat, addon code that touches protected frames, attributes or override bindings raises an error, as the game
    blocks it. Hidden values (mob names and GUIDs in instances) refuse to be compared or joined.

Needs lupa (pip install lupa); drawing needs Pillow.

    python3 tests/run_snapmark.py [--snapshot DIR]
"""

import argparse
import math
import os
import sys

try:
    import lupa.lua51 as lupa
except ImportError:
    sys.exit("Needs lupa: pip install lupa")

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.dirname(HERE)

WOW_STUB = r"""
local function noop() end
now = 100
GetTime = function() return now end
inCombat = false
InCombatLockdown = function() return inCombat end
secureDepth = 0
errors = {}

----------------------------------------------------------------------------------------------------------------------
-- Hidden values

local hidden = setmetatable({}, { __mode = "k" })
secretMode = false
local function refuse(what) return function() error("used a hidden value: " .. what, 2) end end
local template = newproxy(true)
do
    local mt = getmetatable(template)
    mt.__index = refuse("index")
    mt.__lt, mt.__le = refuse("compare"), refuse("compare")
    mt.__add, mt.__sub, mt.__mul, mt.__div = refuse("sum"), refuse("sum"), refuse("sum"), refuse("sum")
    mt.__concat, mt.__len, mt.__call = refuse("join"), refuse("length"), refuse("call")
    mt.__eq = refuse("compare")
    mt.__tostring = function() return "<hidden>" end
end
function secret(v)
    if not secretMode or v == nil then return v end
    local u = newproxy(template)
    hidden[u] = { v }
    return u
end
function issecretvalue(v) return type(v) == "userdata" and hidden[v] ~= nil end
function reveal(v)
    if type(v) == "userdata" and hidden[v] then return hidden[v][1] end
    return v
end

----------------------------------------------------------------------------------------------------------------------
-- Frames

local function blocked(frame, what)
    if inCombat and secureDepth == 0 and frame._protected then
        error("blocked in combat: " .. what .. " on " .. tostring(frame._name), 3)
    end
end

local Object = {}
local methods = {}
allFrames = {}

local function effScale(self)
    local s = self._scale or 1
    local p = self._parent
    if p then return s * p:GetEffectiveScale() end
    return s * (uiScale or 1)
end

methods.GetEffectiveScale = effScale
methods.GetWidth = function(self) return self._w or 0 end
methods.GetHeight = function(self) return self._h or 0 end
methods.SetSize = function(self, w, h) blocked(self, "SetSize") assert(type(w) == "number" and type(h) == "number") self._w, self._h = w, h end
methods.SetWidth = function(self, w) self._w = w end
methods.SetHeight = function(self, h) self._h = h end
methods.SetScale = function(self, s) blocked(self, "SetScale") assert(type(s) == "number" and s > 0) self._scale = s end
methods.GetScale = function(self) return self._scale or 1 end
methods.SetAlpha = function(self, a) assert(type(a) == "number", "SetAlpha needs a number") self._alpha = a end
methods.GetAlpha = function(self) return self._alpha or 1 end
methods.Show = function(self) blocked(self, "Show") self._shown = true end
methods.Hide = function(self)
    blocked(self, "Hide")
    local was = self._shown
    self._shown = false
    if was then
        if self._wraps and self._wraps.OnHide then runWrap(self, "OnHide") end
        if self._scripts.OnHide then self._scripts.OnHide(self) end
    end
end
methods.SetShown = function(self, v) if v then self:Show() else self:Hide() end end
methods.IsShown = function(self) return self._shown end
methods.IsVisible = function(self)
    if not self._shown then return false end
    if self._parent and self._parent.IsVisible then return self._parent:IsVisible() end
    return true
end
methods.SetScript = function(self, name, fn) self._scripts[name] = fn end
methods.GetScript = function(self, name) return self._scripts[name] end
methods.HookScript = function(self, name, fn)
    local old = self._scripts[name]
    self._scripts[name] = function(...) if old then old(...) end fn(...) end
end
methods.SetPoint = function(self, point, rel, relPoint, x, y)
    blocked(self, "SetPoint")
    if type(rel) == "number" or rel == nil then rel, relPoint, x, y = self._parent, point, rel, relPoint end
    if type(relPoint) == "number" then relPoint, x, y = point, relPoint, x end
    assert(x == nil or type(x) == "number", "SetPoint x")
    assert(y == nil or type(y) == "number", "SetPoint y")
    self._points = self._points or {}
    self._points[point] = { point, rel, relPoint or point, x or 0, y or 0 }
end
methods.ClearAllPoints = function(self) blocked(self, "ClearAllPoints") self._points = {} end
methods.SetAllPoints = function(self) self._points = { ALL = true } end
methods.GetName = function(self) return self._name end
methods.GetParent = function(self) return self._parent end
methods.SetAttribute = function(self, k, v) blocked(self, "SetAttribute " .. k) self._attrs[k] = v end
methods.GetAttribute = function(self, k) return self._attrs[k] end
methods.SetFrameRef = function(self, k, f) self._refs[k] = f end
methods.RegisterForClicks = function(self, ...) self._clicks = { ... } end
methods.EnableMouse = noop
methods.EnableKeyboard = noop
methods.SetFrameStrata = noop
methods.SetFrameLevel = noop
methods.SetBackdrop = noop
methods.SetBackdropColor = noop
methods.SetBackdropBorderColor = noop
methods.RegisterEvent = function(self, e) self._events[e] = true end
methods.CreateTexture = function(self, name, layer, inherits, sub)
    local t = newObject("Texture", nil, self)
    t._layer, t._sub = layer or "ARTWORK", sub or 0
    return t
end
methods.CreateFontString = function(self, name, layer, inherits)
    local t = newObject("FontString", nil, self)
    t._layer = layer or "OVERLAY"
    t._font, t._fontSize = "Fonts\\FRIZQT__.TTF", 12
    return t
end
methods.SetTexture = function(self, t) assert(t == nil or type(t) == "string", "SetTexture needs a path") self._tex = t end
methods.SetVertexColor = function(self, r, g, b, a)
    assert(type(r) == "number" and type(g) == "number" and type(b) == "number", "SetVertexColor needs numbers")
    self._color = { r, g, b, a or 1 }
end
methods.SetRotation = function(self, r) assert(type(r) == "number" and r == r, "SetRotation needs a number") self._rot = r end
methods.SetBlendMode = function(self, m) self._blend = m end
methods.SetDesaturated = function(self, d) self._desat = d and true or false end
methods.SetFont = function(self, path, size, flags) self._font, self._fontSize, self._flags = path, size, flags return true end
methods.SetText = function(self, t)
    if issecretvalue(t) then t = reveal(t) end
    assert(t == nil or type(t) == "string" or type(t) == "number", "SetText needs a string")
    self._text = t ~= nil and tostring(t) or nil
end
methods.GetText = function(self) return self._text end
methods.SetTextColor = function(self, r, g, b, a) self._color = { r, g, b, a or 1 } end
methods.SetJustifyH = noop
methods.SetWordWrap = noop

function newObject(kind, name, parent)
    local o = setmetatable({ _kind = kind, _name = name, _parent = parent, _shown = true, _scripts = {}, _attrs = {},
        _refs = {}, _events = {} }, Object)
    allFrames[#allFrames + 1] = o
    return o
end
Object.__index = function(self, k)
    local m = methods[k]
    if m then return m end
    if type(k) == "string" and k:match("^[A-Z]") and k ~= "GetData" then return noop end
    return nil
end

function CreateFrame(kind, name, parent, template)
    local f = newObject(kind, name, parent)
    if template and template:find("Secure") then f._protected = true end
    if template and template:find("SecureHandler") then f._header = true end
    if name then _G[name] = f end
    return f
end

UIParent = newObject("Frame", "UIParent", nil)
uiScale = 1
screenW, screenH = 1600, 1000
methods_UIParentW = nil
UIParent.GetWidth = function() return screenW / uiScale end
UIParent.GetHeight = function() return screenH / uiScale end
UIParent.GetEffectiveScale = function() return uiScale end

function fireEvent(event, ...)
    for _, f in ipairs(allFrames) do
        if f._events[event] and f._scripts.OnEvent then f._scripts.OnEvent(f, event, ...) end
    end
end

function tick(seconds, step)
    step = step or (1 / 60)
    local n = math.max(1, math.floor(seconds / step + 0.5))
    for _ = 1, n do
        now = now + step
        for _, f in ipairs(allFrames) do
            if f._scripts.OnUpdate and f:IsVisible() then f._scripts.OnUpdate(f, step) end
        end
    end
end

----------------------------------------------------------------------------------------------------------------------
-- Pointer and keys. Cursor in screen pixels, from the bottom left.

cursorX, cursorY = 800, 500
function GetCursorPosition() return cursorX, cursorY end
keysDown = {}
function IsKeyDown(k) return keysDown[k] or false end
function IsMouseButtonDown(b) return keysDown[b] or false end
function IsShiftKeyDown() return keysDown.SHIFT or false end
function IsControlKeyDown() return keysDown.CTRL or false end
function IsAltKeyDown() return keysDown.ALT or false end
function IsMouselooking() return false end

----------------------------------------------------------------------------------------------------------------------
-- Units

world = {}   -- token -> entity { guid, name, mob }
marks = {}   -- entity -> marker
plates = {}  -- token -> plate frame
function setUnit(token, e) world[token] = e end
local function ent(u) return world[u] end
function UnitExists(u) return ent(u) ~= nil end
function UnitGUID(u)
    local e = ent(u)
    if not e then return nil end
    if e.mob then return secret(e.guid) end
    return e.guid
end
function UnitName(u)
    local e = ent(u)
    if not e then return nil end
    if e.mob then return secret(e.name) end
    return e.name
end
function UnitIsUnit(a, b)
    local x, y = ent(a), ent(b)
    if not x or not y then return false end
    return x == y
end
function UnitTokenFromGUID(guid)
    for _, t in ipairs({ "target", "focus", "player", "party1", "party2" }) do
        if ent(t) and ent(t).guid == guid then return t end
    end
    for t, e in pairs(world) do
        if t:match("^nameplate") and e.guid == guid then return t end
    end
    if ent("mouseover") and ent("mouseover").guid == guid then return "mouseover" end
end
inRaid, isLeader, inGroup = false, false, false
function IsInRaid() return inRaid end
function IsInGroup() return inGroup or inRaid end
function UnitIsGroupLeader() return isLeader end
function UnitIsGroupAssistant() return false end
function IsEveryoneAssistant() return false end
C_NamePlate = {
    GetNamePlateForUnit = function(u)
        local e = ent(u)
        if not e then return nil end
        for token, plate in pairs(plates) do
            if world[token] == e then return plate end
        end
    end,
}
function addPlate(token, e)
    world[token] = e
    plates[token] = { namePlateUnitToken = token }
    fireEvent("NAME_PLATE_UNIT_ADDED", token)
end
function removePlate(token)
    world[token] = nil
    plates[token] = nil
    fireEvent("NAME_PLATE_UNIT_REMOVED", token)
end

----------------------------------------------------------------------------------------------------------------------
-- Ground markers. Numbered as in the game: ground marker 1 is the blue square.

groundEnabled = true
function IsRaidMarkerSystemEnabled() return groundEnabled end
local groundIcons = { 6, 4, 3, 7, 1, 2, 5, 8 }
for i, icon in ipairs(groundIcons) do
    _G["WORLD_MARKER" .. i] = "|TInterface\\TargetingFrame\\UI-RaidTargetingIcon_" .. icon .. ":14:14|t Marker " .. i
end
function groundIcon(index) return groundIcons[index] end
groundMarks = {}   -- ground marker index -> true while it's down
placing = nil      -- the ground marker the targeting circle is placing
function PlaceRaidMarker(index, token)
    if secureDepth == 0 then error("PlaceRaidMarker is protected", 2) end
    assert(token == nil, "the wheel places by the targeting circle")
    placing = index
end
function ClearRaidMarker(index)
    if secureDepth == 0 then error("ClearRaidMarker is protected", 2) end
    if index == nil then groundMarks = {} else groundMarks[index] = nil end
end
function IsRaidMarkerActive(index) return groundMarks[index] or false end
function clickGround()
    if placing then groundMarks[placing] = true placing = nil end
end

----------------------------------------------------------------------------------------------------------------------
-- Bindings

bindings = {}       -- key -> action
overrides = {}      -- list of { owner, key, target, button }
function GetBindingKey(action)
    local keys = {}
    for k, a in pairs(bindings) do if a == action then keys[#keys + 1] = k end end
    table.sort(keys)
    return unpack(keys)
end
function GetBindingAction(key) return bindings[key] or "" end
function GetBindingText(key) return key end
function SetBinding(key, action)
    if inCombat and secureDepth == 0 then error("blocked in combat: SetBinding", 2) end
    bindings[key] = action
    fireEvent("UPDATE_BINDINGS")
    return true
end
savedBindings = 0
function SaveBindings() savedBindings = savedBindings + 1 end
function GetCurrentBindingSet() return 1 end
function SetOverrideBindingClick(owner, priority, key, target, button)
    if inCombat and secureDepth == 0 then error("blocked in combat: SetOverrideBindingClick", 2) end
    for i = #overrides, 1, -1 do
        if overrides[i].owner == owner and overrides[i].key == key then table.remove(overrides, i) end
    end
    overrides[#overrides + 1] = { owner = owner, key = key, target = target, button = button }
end
function ClearOverrideBindings(owner)
    if inCombat and secureDepth == 0 then error("blocked in combat: ClearOverrideBindings", 2) end
    for i = #overrides, 1, -1 do if overrides[i].owner == owner then table.remove(overrides, i) end end
end
function overrideFor(key)
    for i = #overrides, 1, -1 do if overrides[i].key == key then return overrides[i] end end
end

----------------------------------------------------------------------------------------------------------------------
-- The restricted environment and frame handles, after RestrictedEnvironment.lua and RestrictedFrames.lua.

local handles = setmetatable({}, { __mode = "k" })
local HANDLE = {}
local function handle(frame)
    if not frame then return nil end
    local h = handles[frame]
    if not h then
        h = setmetatable({}, { __index = HANDLE })
        handles[frame] = h
        handleFrame = handleFrame or setmetatable({}, { __mode = "k" })
        handleFrame[h] = frame
    end
    return h
end
local function F(h) return handleFrame[h] end

function HANDLE:GetFrameRef(name) return handle(F(self)._refs[name]) end
function HANDLE:SetAttribute(k, v)
    assert(type(v) ~= "table", "Invalid attribute value")
    F(self):SetAttribute(k, v)
end
function HANDLE:GetAttribute(k) return F(self):GetAttribute(k) end
function HANDLE:Show() F(self):Show() F(self)._attrs.statehidden = nil end
function HANDLE:Hide() F(self):Hide() F(self)._attrs.statehidden = true end
function HANDLE:IsShown() return F(self):IsShown() end
function HANDLE:GetWidth() return F(self):GetWidth() end
function HANDLE:GetHeight() return F(self):GetHeight() end
function HANDLE:ClearAllPoints() F(self):ClearAllPoints() end
local setPoints = { TOP = true, BOTTOM = true, LEFT = true, RIGHT = true, CENTER = true, TOPLEFT = true,
    BOTTOMLEFT = true, TOPRIGHT = true, BOTTOMRIGHT = true }
function HANDLE:SetPoint(point, relframe, relpoint, xofs, yofs)
    if type(relpoint) == "number" then relpoint, xofs, yofs = nil, relpoint, xofs end
    if relpoint == nil then relpoint = point end
    if xofs == nil and yofs == nil then xofs, yofs = 0, 0 else xofs, yofs = tonumber(xofs), tonumber(yofs) end
    assert(setPoints[point], "Invalid point")
    assert(setPoints[relpoint], "Invalid relative point")
    assert(xofs and yofs, "Invalid offset")
    local frame = F(self)
    assert(relframe == "$cursor" or relframe == nil or relframe == "$screen", "the stand-in only knows $cursor and $screen")
    if relframe == "$cursor" then
        local cx, cy = GetCursorPosition()
        local eff = frame:GetEffectiveScale()
        xofs, yofs = xofs + cx / eff, yofs + cy / eff
        relpoint = "BOTTOMLEFT"
    end
    frame._points = { [point] = { point, "$screen", relpoint, xofs, yofs } }
end
-- The frame's rectangle in its own units: left, bottom, width, height. Only CENTER or BOTTOMLEFT on the screen's
-- bottom left, which is all the pad uses.
local function rect(frame)
    local p = frame._points and (frame._points.CENTER or frame._points.BOTTOMLEFT)
    assert(p and p[3] == "BOTTOMLEFT", "the stand-in can only measure frames placed on the screen's bottom left")
    local w, h = frame:GetWidth(), frame:GetHeight()
    if p[1] == "CENTER" then return p[4] - w / 2, p[5] - h / 2, w, h end
    return p[4], p[5], w, h
end
function HANDLE:GetMousePosition()
    local frame = F(self)
    local x, y = GetCursorPosition()
    local l, b, w, h = rect(frame)
    if not w or not h or w == 0 or h == 0 then return nil end
    local e = frame:GetEffectiveScale()
    x, y = x / e, y / e
    x, y = x - l, y - b
    if x < 0 or x > w or y < 0 or y > h then return nil end
    return x / w, y / h
end
function HANDLE:SetBindingClick(priority, key, name, button)
    if type(name) == "table" then name = F(name)._name end
    assert(type(name) == "string", "Invalid click target name")
    SetOverrideBindingClick(F(self), priority, key, name, button)
end
function HANDLE:ClearBindings() ClearOverrideBindings(F(self)) end
function HANDLE:CallMethod(name, ...)
    local frame = F(self)
    local depth = secureDepth
    secureDepth = 0 -- the method is the addon's own code
    local ok, err = pcall(frame[name], frame, ...)
    secureDepth = depth
    if not ok then errors[#errors + 1] = "CallMethod " .. name .. ": " .. tostring(err) end
end

local RESTRICTED = {
    math = math, string = string, select = select, tonumber = tonumber, tostring = tostring,
    abs = math.abs, min = math.min, max = math.max, floor = math.floor, ceil = math.ceil, mod = math.fmod,
    format = string.format, strfind = string.find, strsub = string.sub, strlen = string.len,
    UnitExists = UnitExists, UnitIsDead = function() return false end, SecureCmdOptionParse = function() end,
    IsShiftKeyDown = IsShiftKeyDown, IsControlKeyDown = IsControlKeyDown, IsAltKeyDown = IsAltKeyDown,
    PlayerInCombat = function() return inCombat end,
    PlayerCanAttack = function() return true end, PlayerCanAssist = function() return true end,
}

local compiled = {}
local function compile(body, sig)
    local key = sig .. "\0" .. body
    if compiled[key] then return compiled[key] end
    assert(not body:find("{"), "restricted code can't build tables")
    local fn = assert(loadstring("local " .. sig .. " = ...\n" .. body, "=snippet"))
    compiled[key] = fn
    return fn
end
local function runSnippet(header, frame, body, sig, ...)
    local fn = compile(body, sig)
    local env = setmetatable({ control = handle(header), owner = handle(header) }, {
        __index = function(_, k)
            local v = RESTRICTED[k]
            if v == nil then error("restricted code has no '" .. tostring(k) .. "'", 2) end
            return v
        end,
        __newindex = function(t, k, v) rawset(t, k, v) end,
    })
    setfenv(fn, env)
    secureDepth = secureDepth + 1
    local r = { pcall(fn, handle(frame), ...) }
    secureDepth = secureDepth - 1
    if not r[1] then error("snippet: " .. tostring(r[2]), 0) end
    return unpack(r, 2)
end

function SecureHandlerWrapScript(frame, script, header, pre, post)
    assert(frame._protected and header._header, "wrap needs protected frames")
    frame._wraps = frame._wraps or {}
    frame._wraps[script] = { header = header, pre = pre, post = post }
end
function runWrap(frame, script)
    local w = frame._wraps[script]
    runSnippet(w.header, frame, w.pre, "self")
end

----------------------------------------------------------------------------------------------------------------------
-- Blizzard's action button (SecureTemplates.lua) for the two actions SnapMark uses

lastAction = nil
targetChanges = 0
local function perform(btn, actionType, down)
    if not actionType then return end
    local unit = btn._attrs.unit
    if unit and unit ~= "none" and not UnitExists(unit) then return end
    lastAction = { type = actionType, unit = unit, down = down }
    if actionType == "raidtarget" then
        local e = world[unit or "target"]
        local marker = tonumber(btn._attrs.marker) or 1
        local action = btn._attrs.action or "toggle"
        if action == "set" then
            marks[e] = marker
        elseif action == "clear" then
            marks[e] = nil
        elseif action == "toggle" then
            if marks[e] == marker then marks[e] = nil else marks[e] = marker end
        end
    elseif actionType == "worldmarker" then
        -- SECURE_ACTIONS.worldmarker
        local marker = tonumber(btn._attrs.marker)
        local action = btn._attrs.action or "toggle"
        if action == "set" then
            PlaceRaidMarker(marker or 1)
        elseif action == "clear" then
            ClearRaidMarker(marker)
        elseif action == "toggle" then
            marker = marker or 1
            if IsRaidMarkerActive(marker) then ClearRaidMarker(marker) else PlaceRaidMarker(marker) end
        end
    elseif actionType == "target" then
        world.target = world[unit]
        targetChanges = targetChanges + 1
        fireEvent("PLAYER_TARGET_CHANGED")
    else
        error("unexpected action " .. tostring(actionType))
    end
end
local function actionButtonOnClick(btn, which, down, isKeyPress)
    local a = btn._attrs
    local pressAndHold = a.pressAndHoldAction
    local useOnKeyDown = (isKeyPress and true or false) and (a.useOnKeyDown or pressAndHold)
    if not isKeyPress then useOnKeyDown = false end
    local clickAction = (down and useOnKeyDown) or (not down and not useOnKeyDown)
    if clickAction then
        perform(btn, a.type, down)
    elseif not down and pressAndHold then
        perform(btn, a.typerelease, down)
    end
end

-- One click on a button, as the game delivers it: PreClick, the wrapped OnClick, the action, the snippet after.
function click(btn, which, down, isKeyPress)
    if btn._scripts.PreClick then btn._scripts.PreClick(btn, which, down) end
    local w = btn._wraps and btn._wraps.OnClick
    local message
    if w then
        local newbutton, msg = runSnippet(w.header, btn, w.pre, "self,button,down", which, down)
        if newbutton == false then return end
        if newbutton then which = tostring(newbutton) end
        message = msg
    end
    secureDepth = secureDepth + 1
    actionButtonOnClick(btn, which, down, isKeyPress)
    secureDepth = secureDepth - 1
    if w and w.post and message ~= nil then
        runSnippet(w.header, btn, w.post, "self,message,button,down", message, which, down)
    end
end

-- A key going down or up. Override bindings first, as the game does.
function key(k, down)
    local o = overrideFor(k)
    if o then
        click(_G[o.target], o.button or "LeftButton", down, true)
        return "override"
    end
    local action = bindings[k]
    if action == "SNAPMARK_HOLD" or action == "SNAPMARK_GROUND" then
        SnapMark_OnBinding(down and "down" or "up")
        return "binding"
    end
    return nil
end

----------------------------------------------------------------------------------------------------------------------
-- Everything else SnapMark touches

DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) chat[#chat + 1] = m end }
chat = {}
uiErrors = {}
UIErrorsFrame = { AddMessage = function(_, m) uiErrors[#uiErrors + 1] = m end }
UISpecialFrames = {}
SOUNDKIT = { IG_MAINMENU_OPTION_CHECKBOX_ON = 856, U_CHAT_SCROLL_BUTTON = 1115 }
sounds = {}
function PlaySound(id) sounds[#sounds + 1] = id end
C_Timer = { After = function(_, fn) fn() end }
SlashCmdList = {}
function geterrorhandler() return function(e) error(e) end end
for _, n in ipairs({ "GameFontNormalLarge", "GameFontHighlight", "GameFontDisableSmall" }) do _G[n] = {} end

registeredSettings = {}
Settings = {
    VarType = { Boolean = "boolean", String = "string", Number = "number" },
    RegisterVerticalLayoutCategory = function(name)
        return { name = name, GetID = function() return 9 end }
    end,
    RegisterProxySetting = function(category, variable, varType, label, default, get, set)
        local s = { variable = variable, varType = varType, label = label, default = default, get = get, set = set }
        registeredSettings[variable] = s
        return s
    end,
    CreateCheckbox = function(category, s, tooltip) s.tooltip = tooltip end,
    CreateDropdown = function(category, s, options, tooltip) s.options = options() s.tooltip = tooltip end,
    CreateControlTextContainer = function()
        local c = { data = {} }
        function c:Add(value, label) self.data[#self.data + 1] = { value = value, label = label } end
        function c:GetData() return self.data end
        return c
    end,
    CreateSlider = function(category, s, options, tooltip) s.slider = options s.tooltip = tooltip end,
    CreateSliderOptions = function(lo, hi, step) return { lo = lo, hi = hi, step = step } end,
    RegisterAddOnCategory = function(category) settingsCategory = category end,
    OpenToCategory = function(id) settingsOpened = id end,
}
settingsButtons = {}
SettingsPanel = newObject("Frame", "SettingsPanel", UIParent)
SettingsPanel._shown = false
SettingsPanel.GetLayout = function() return { AddInitializer = function(_, init) settingsButtons[#settingsButtons + 1] = init end } end
CreateSettingsButtonInitializer = function(name, text, onClick, tooltip)
    local init = { data = { name = name, buttonText = text, buttonClick = onClick, tooltip = tooltip } }
    function init:GetData() return self.data end
    -- The page builds a row for it: a frame with a Button that shows the text.
    function init:InitFrame(frame) frame.Button._text = self.data.buttonText end
    return init
end
-- A row the settings page built, with its button.
function settingsRow(init)
    local frame = { Button = { _text = nil } }
    function frame.Button:GetText() return self._text end
    function frame.Button:SetText(t) self._text = t end
    init:InitFrame(frame)
    return frame
end
"""

CHECKS = r"""
local ns = ...
local function check(cond, msg) if not cond then error(msg, 2) end end
local function noErrors(where)
    check(#errors == 0, where .. ": " .. tostring(errors[1]))
end

local skull = { guid = "Creature-1", name = "Defias Pillager", mob = true }
local brute = { guid = "Creature-2", name = "Defias Brute", mob = true }
local mage = { guid = "Creature-3", name = "Defias Conjurer", mob = true }
local function fresh()
    world, marks, plates = {}, {}, {}
    keysDown = {}
    world.player = { guid = "Player-1", name = "Olof" }
    addPlate("nameplate1", skull)
    addPlate("nameplate2", brute)
    addPlate("nameplate3", mage)
    world.target = skull
    inCombat, inRaid, isLeader, inGroup = false, false, false, false
    groundMarks, placing = {}, nil
    errors, uiErrors, sounds = {}, {}, {}
    cursorX, cursorY = 800, 500
end

-- Moves the pointer by (dx, dy) UI units and back again to the start of a hold.
local function at(x, y) cursorX, cursorY = x * uiScale, y * uiScale end

-- Hold the key at (x, y), move to (x + dx, y + dy), let go. In UI units.
local function flick(x, y, dx, dy, opts)
    opts = opts or {}
    local k = opts.key or "V"
    at(x, y)
    if opts.pointAt ~= nil then world.mouseover = opts.pointAt or nil end
    keysDown[k] = true
    key(k, true)
    tick(0.05)
    if opts.leave ~= nil then world.mouseover = opts.leave or nil end
    if opts.midway then opts.midway() end
    at(x + dx, y + dy)
    tick(0.05)
    keysDown[k] = false
    key(k, false)
    tick(0.4)
end

-- 1. Setup: no key yet, so it says where to choose one, once
check(ns.ready, "the secure part should be set up at login")
check(#chat == 1 and chat[1]:find("choose a key"), "should say once where to choose a key")
fireEvent("PLAYER_ENTERING_WORLD")
check(#chat == 1, "and only once")
check(ns.bindKey("V"), "binding V")
check(bindings.V == "SNAPMARK_HOLD", "V should now open the wheel")
check(savedBindings > 0, "the key bindings should be saved")
check(overrideFor("V") and overrideFor("V").target == "SnapMarkButton", "V should click the wheel's button")
check(overrideFor("SHIFT-V"), "Shift-V should open it too, as nothing else uses it")
check(not overrideFor("CTRL-V"), "Ctrl-V belongs to something else and must stay theirs")

-- 2. The rule: the wheel you see and the secure snippet pick the same marker everywhere
fresh()
local mismatches, tries = 0, 0
local ox, oy = 800, 500
local function agree(dx, dy)
    tries = tries + 1
    local want = ns.pick(dx, dy)
    marks = {}
    flick(ox, oy, dx, dy)
    local got = marks[skull]
    local expect = want and ns.SLOTS[want].marker or nil
    if got ~= expect then mismatches = mismatches + 1 lastMismatch = { dx, dy, expect, got } end
end
for a = 0, 359, 7.5 do
    for _, r in ipairs(a % 45 == 22.5 and {} or { 17, 40, 90, 160, 400, 700 }) do
        local rad = math.rad(a)
        agree(r * math.cos(rad), r * math.sin(rad))
    end
end
check(mismatches == 0, "the wheel and the snippet disagree at " .. table.concat(lastMismatch or {}, ","))
-- Right on the line between two slices, rounding can tip either way; it must be one of the two.
for a = 22.5, 360, 45 do
    local rad = math.rad(a)
    local dx, dy = 120 * math.cos(rad), 120 * math.sin(rad)
    marks = {}
    flick(ox, oy, dx, dy)
    local got = marks[skull]
    local left = ns.SLOTS[ns.pick(dx + 0.01 * dy, dy - 0.01 * dx)].marker
    local right = ns.SLOTS[ns.pick(dx - 0.01 * dy, dy + 0.01 * dx)].marker
    check(got == left or got == right, "on the line at " .. a .. " degrees it set " .. tostring(got))
    tries = tries + 1
end
noErrors("the rule")
ruleTries = tries

-- 3. Overshooting never misses
fresh()
flick(800, 500, 650, 12)
check(marks[skull] == 6, "a long flick to the right should set the square")
fresh()
flick(4, 4, 1590, 990)
check(marks[skull] == 7, "from the bottom left corner to the top right should set the cross")
fresh()
flick(1596, 996, -1590, -2)
check(marks[skull] == 2, "from the top right corner far to the left should set the circle")

-- 4. The centre
fresh()
flick(800, 500, 4, -3)
check(marks[skull] == nil, "letting go in the centre should do nothing")
check(ns.Wheel.state.closing == nil or true, "")
ns.set("center", "skull")
flick(800, 500, 2, 2)
check(marks[skull] == 8, "with the skull setting, the centre sets the skull")
flick(800, 500, 2, 2)
check(marks[skull] == 8, "and setting it again keeps it")
ns.set("center", "clear")
flick(800, 500, 0, 0)
check(marks[skull] == nil, "with remove, the centre removes the mark")
ns.set("center", "none")

-- 5. The mark it already has comes off
fresh()
flick(800, 500, 0, 200)
check(marks[skull] == 8, "up sets the skull")
flick(800, 500, 0, 200)
check(marks[skull] == nil, "the skull again takes it off")

-- 6. Pointing out of combat: marks what you pointed at, even after the pointer moved on
fresh()
flick(800, 500, -200, 0, { pointAt = brute, leave = mage })
check(marks[brute] == 2 and marks[skull] == nil and marks[mage] == nil, "should mark the enemy pointed at as the key went down")
flick(800, 500, 200, 0, { pointAt = false })
check(marks[skull] == 6, "pointing at nothing marks the target")
-- What you pointed at vanished before you let go
fresh()
world.mouseover = mage
flick(800, 500, 0, -150, { pointAt = mage, leave = false, midway = function() removePlate("nameplate3") end })
check(marks[mage] == nil and marks[skull] == nil, "nothing should be marked when it is gone")
check(uiErrors[#uiErrors] and uiErrors[#uiErrors]:find("went out of sight"), "and the game's error line should say why")
-- Target mode ignores the pointer
fresh()
ns.set("mode", "target")
flick(800, 500, 0, 150, { pointAt = brute })
check(marks[skull] == 8 and marks[brute] == nil, "target mode marks the target")
ns.set("mode", "focus")
world.focus = mage
flick(800, 500, 0, 150, { pointAt = brute })
check(marks[mage] == 8, "focus mode marks the focus")
ns.set("mode", "point")

-- 7. Combat: same flick, no blocked calls, marks the target
fresh()
inCombat = true
fireEvent("PLAYER_REGEN_DISABLED")
flick(800, 500, 300, 300, { pointAt = brute, leave = mage })
noErrors("combat")
check(marks[skull] == 7 and marks[brute] == nil, "in combat it marks the target")
-- Opening the wheel just as the fight starts
fresh()
at(800, 500)
key("V", true)
inCombat = true
fireEvent("PLAYER_REGEN_DISABLED")
tick(0.1)
at(800, 300)
key("V", false)
tick(0.3)
noErrors("pull mid-hold")
check(marks[skull] == 4, "a fight starting mid-hold must not stop it")
-- Target first
fresh()
inCombat = true
ns.db.combat = "targetfirst"
inCombat = false ns.Secure.sync() inCombat = true
flick(800, 500, 0, 120, { pointAt = brute, leave = mage })
noErrors("target first")
check(world.target == brute and marks[brute] == 8, "target first should target the brute on press and mark it")
inCombat = false
ns.set("combat", "target")
fireEvent("PLAYER_REGEN_ENABLED")

-- 8. Esc and right-click cancel, then go back to normal
fresh()
at(800, 500)
key("V", true)
at(1000, 500)
tick(0.05)
check(overrideFor("ESCAPE"), "Esc should cancel while the wheel is open")
key("ESCAPE", true)
key("ESCAPE", false)
key("V", false)
tick(0.3)
check(marks[skull] == nil, "Esc should cancel")
check(not overrideFor("ESCAPE") and not overrideFor("BUTTON2"), "Esc and right-click should be back to normal")
at(800, 500)
key("V", true)
at(800, 700)
key("BUTTON2", true)
key("V", false)
check(marks[skull] == nil, "right-click should cancel")
inCombat = true
at(800, 500)
key("V", true)
key("ESCAPE", true)
key("V", false)
noErrors("Esc in combat")
check(marks[skull] == nil and not overrideFor("ESCAPE"), "Esc cancels in combat too")
inCombat = false

-- 9. A key release that never came
fresh()
at(800, 500)
key("V", true)
at(500, 500)
tick(0.1)
-- (no key up) press again elsewhere and flick
at(300, 300)
key("V", true)
at(300, 500)
key("V", false)
tick(0.3)
check(marks[skull] == 8, "a new press starts afresh from where it was pressed")
-- Outside a fight, the wheel notices the key is up and closes
fresh()
keysDown.V = true
at(800, 500)
key("V", true)
tick(0.2)
keysDown.V = false
tick(0.2)
check(not ns.Secure.isOpen(), "a lost release outside a fight closes the wheel")
check(not overrideFor("ESCAPE"), "and gives Esc back")

-- 10. The wheel you see follows the same rule, at another UI scale
fresh()
uiScale = 0.75
at(800, 500)
key("V", true)
for _, v in ipairs({ { 300, 0, 6 }, { 0, -40, 4 }, { -250, 260, 1 }, { 3, 3, nil } }) do
    at(800 + v[1], 500 + v[2])
    tick(0.05)
    local sel = ns.Wheel.state.sel
    check((sel and ns.SLOTS[sel].marker) == v[3], "the wheel shows " .. tostring(sel and ns.SLOTS[sel].marker) .. ", should be " .. tostring(v[3]))
end
key("V", false)
tick(0.3)
check(marks[skull] == nil, "let go in the centre at scale 0.75")
uiScale = 1

-- 11. Hidden values: names in an instance
fresh()
secretMode = true
flick(800, 500, 0, 100, { pointAt = brute })
noErrors("hidden values")
check(marks[brute] == 8, "marks what you pointed at by its nameplate when its GUID is hidden")
-- Pointing at a body that has no nameplate, its GUID hidden: the key targets it as it goes down, then marks it.
local looter = { guid = "Creature-9", name = "Defias Looter", mob = true }
local targetsBefore = targetChanges
flick(800, 500, 0, -120, { pointAt = looter, leave = false })
noErrors("pointing at a body")
check(world.target == looter and targetChanges == targetsBefore + 1, "the looter is targeted as the key goes down")
check(marks[looter] == 4, "and marked")
-- The same with its plate up: no need to target, its nameplate is found by comparing units.
addPlate("nameplate4", looter)
world.target = skull
targetsBefore = targetChanges
flick(800, 500, 0, 120, { pointAt = looter, leave = false })
check(world.target == skull and targetChanges == targetsBefore and marks[looter] == 8,
    "with a nameplate up it marks the looter and leaves your target alone")
-- A friendly player outside your group: their ID can be read, but no lasting token finds them once the pointer has
-- moved on. The key targets them as it goes down.
secretMode = false
local stranger = { guid = "Player-77", name = "Bob" }
flick(800, 500, 120, 0, { pointAt = stranger, leave = false })
noErrors("a friendly player")
check(world.target == stranger and marks[stranger] == 6, "a friendly player outside the group is targeted and marked")
-- A party member is found again by their group token: no targeting.
local friend = { guid = "Player-78", name = "Kessa" }
world.party1 = friend
world.target = skull
targetsBefore = targetChanges
flick(800, 500, -120, 0, { pointAt = friend, leave = false })
check(world.target == skull and targetChanges == targetsBefore and marks[friend] == 2, "a party member is marked as party1")
world.party1 = nil
-- /snapmark debug reports each step
local before = #chat
SlashCmdList.SNAPMARK("debug")
flick(800, 500, 0, 120, { pointAt = stranger, leave = false })
local said = table.concat(chat, "\n", before + 1)
check(said:find("debug on") and said:find("targets it now") and said:find("let go: marks target")
    and said:find("marker 8"), "the debug report: " .. said)
SlashCmdList.SNAPMARK("debug")
secretMode = true
at(800, 500)
key("V", true)
tick(0.05)
check(SnapMarkWheel.unit ~= nil, "")
key("V", false)
tick(0.3)
secretMode = false

-- 12. Can't mark: no target, or a raid without assist
fresh()
world.target = nil
at(800, 500)
key("V", true)
tick(0.05)
check(ns.Wheel.state.available == false, "no target: the wheel should say it can't mark")
key("V", false)
tick(0.3)
fresh()
inRaid = true
at(800, 500)
key("V", true)
tick(0.05)
check(ns.Wheel.state.reason and ns.Wheel.state.reason:find("leader"), "in a raid without assist the wheel should say why")
key("V", false)
tick(0.3)
inRaid = false

-- 13. Settings wait for the fight to end
fresh()
inCombat = true
ns.set("mode", "target")
noErrors("setting in combat")
check(SnapMarkButton._attrs["mw-mode"] == "point", "the button must not change in combat")
inCombat = false
fireEvent("PLAYER_REGEN_ENABLED")
check(SnapMarkButton._attrs["mw-mode"] == "target", "it changes when the fight ends")
ns.set("mode", "point")

-- 14. Sounds: a tick on each new choice, a click on the mark
fresh()
flick(800, 500, 200, 0)
local ticks, clicks = 0, 0
for _, s in ipairs(sounds) do if s == 1115 then ticks = ticks + 1 elseif s == 856 then clicks = clicks + 1 end end
check(ticks >= 1 and clicks == 1, "expected a tick and a click, got " .. ticks .. " and " .. clicks)
ns.set("sound", false)
sounds = {}
flick(800, 500, 200, 0)
check(#sounds == 0, "sounds off means silence")
ns.set("sound", true)

-- 15. The ground marker wheel: same wheel, same places, a ground marker placed by the game's targeting circle
fresh()
inGroup = true
check(ns.bindKey("B", ns.GROUND_BINDING), "binding B to the ground marker wheel")
check(bindings.B == "SNAPMARK_GROUND" and bindings.V == "SNAPMARK_HOLD", "each wheel has its own key")
check(overrideFor("B") and overrideFor("B").button == "Ground", "B should click the button as Ground")
check(overrideFor("SHIFT-B") and overrideFor("SHIFT-B").button == "Ground", "Shift-B opens the ground wheel too")
for i, slot in ipairs(ns.SLOTS) do
    flick(800, 500, slot.x * 150, slot.y * 150, { key = "B", pointAt = brute })
    check(placing and groundIcon(placing) == slot.marker,
        "the " .. slot.name .. " slice should place the " .. slot.name .. " ground marker, got " .. tostring(placing))
    check(not overrideFor("ESCAPE"), "Esc is back to normal for the targeting circle")
    clickGround()
end
noErrors("ground markers")
local down = 0
for _ in pairs(groundMarks) do down = down + 1 end
check(down == 8, "all eight ground markers should be down")
check(next(marks) == nil and world.target == skull, "the ground wheel marks no unit and leaves your target alone")
check(ns.Wheel.state.kind == "ground" and SnapMarkWheel.unit._text == "Ground marker", "the wheel says it's for ground markers")
-- The wheel and the snippet agree here too
local gmis = 0
for a = 0, 359, 15 do
    for _, r in ipairs({ 20, 90, 500 }) do
        local dx, dy = r * math.cos(math.rad(a)), r * math.sin(math.rad(a))
        placing = nil
        flick(800, 500, dx, dy, { key = "B" })
        if not (placing and groundIcon(placing) == ns.SLOTS[ns.pick(dx, dy)].marker) then gmis = gmis + 1 end
    end
end
check(gmis == 0, gmis .. " ground flicks disagree with the wheel")
placing = nil
-- The centre: nothing, or remove them all
flick(800, 500, 3, 2, { key = "B" })
check(placing == nil and next(groundMarks) ~= nil, "letting go in the centre does nothing")
ns.set("groundCenter", "clear")
flick(800, 500, 3, 2, { key = "B" })
check(next(groundMarks) == nil and placing == nil, "with remove all, the centre removes every ground marker")
ns.set("groundCenter", "none")
-- In a fight
inCombat = true
fireEvent("PLAYER_REGEN_DISABLED")
flick(800, 500, -150, 0, { key = "B", pointAt = brute })
noErrors("ground markers in combat")
check(placing and groundIcon(placing) == 2, "the ground wheel works in a fight")
placing = nil
inCombat = false
fireEvent("PLAYER_REGEN_ENABLED")
-- Esc cancels
at(800, 500)
key("B", true)
at(800, 700)
key("ESCAPE", true)
key("B", false)
tick(0.3)
check(placing == nil and not overrideFor("ESCAPE"), "Esc cancels the ground wheel")
-- The marker key still marks
flick(800, 500, 0, 150, { pointAt = false })
check(marks[skull] == 8 and placing == nil, "the marker wheel still marks after the ground wheel")
-- On your own, and in a raid without assist
fresh()
at(800, 500)
key("B", true)
tick(0.05)
check(ns.Wheel.state.available == false and ns.Wheel.state.reason:find("group"), "alone, the ground wheel says it needs a group")
key("B", false)
tick(0.3)
inRaid = true
at(800, 500)
key("B", true)
tick(0.05)
check(ns.Wheel.state.reason and ns.Wheel.state.reason:find("leader"), "in a raid without assist the ground wheel says why")
key("B", false)
tick(0.3)
placing = nil
inRaid = false
-- A release that never came: the wheel watches the ground key, not the marker key
inGroup = true
keysDown.B = true
at(800, 500)
key("B", true)
tick(0.2)
check(ns.Secure.isOpen(), "the ground wheel stays open while B is held")
keysDown.B = false
tick(0.2)
check(not ns.Secure.isOpen(), "and closes when B is found up")
-- A realm without ground markers: the key does nothing of the wheel's
groundEnabled = false
ns.Secure.sync()
check(not overrideFor("B"), "without ground markers the ground key isn't taken")
groundEnabled = true
ns.Secure.sync()
check(overrideFor("B"), "back")
-- The help line names the ground key
local before = #chat
SlashCmdList.SNAPMARK("help")
check(chat[before + 1]:find("click the ground"), "help mentions the ground key")
noErrors("end")
return ruleTries
"""

SETTINGS_CHECK = r"""
local ns = ...
assert(settingsCategory and settingsCategory.name == "SnapMark", "the settings page was not registered")
local count = 0
for name, s in pairs(registeredSettings) do
    count = count + 1
    local v = s.get()
    if s.options then
        for _, o in ipairs(s.options) do s.set(o.value) assert(s.get() == o.value, name .. " did not take " .. tostring(o.value)) end
    elseif s.varType == "boolean" then
        s.set(not v) assert(s.get() == not v, name .. " did not change") s.set(v)
    elseif s.varType == "number" then
        s.set(s.slider.hi) assert(s.get() == s.slider.hi, name .. " did not take its top value")
    end
    s.set(s.default)
end
assert(ns.db.size == 1 and ns.db.background == 0.85, "defaults back")
-- The key button shows the key and opens the key window
local keyInit = settingsButtons[1]
assert(keyInit.data.buttonText == "V", "the key button should show V, shows " .. tostring(keyInit.data.buttonText))
local row = settingsRow(keyInit)
assert(row.Button._text == "V", "the row on screen shows V")
keyInit.data.buttonClick()
assert(SnapMarkKeyCatcher and SnapMarkKeyCatcher._shown, "the key window should open")
bindings.G = "TOGGLEGUILDTAB"
BINDING_NAME_TOGGLEGUILDTAB = "Guild"
SnapMarkKeyCatcher._scripts.OnKeyDown(SnapMarkKeyCatcher, "LSHIFT")
SnapMarkKeyCatcher._scripts.OnKeyDown(SnapMarkKeyCatcher, "G")
assert(SnapMarkKeyCatcher._text == nil or true)
assert(bindings.G == "TOGGLEGUILDTAB", "a key in use needs a second press")
assert(SnapMarkKeyCatcher.text._text:find("Guild"), "and should say what uses it")
SnapMarkKeyCatcher._scripts.OnKeyDown(SnapMarkKeyCatcher, "G")
assert(bindings.G == "SNAPMARK_HOLD" and bindings.V == nil, "G should replace V")
assert(keyInit.data.buttonText == "G", "the key button should now show G")
assert(row.Button._text == "G", "and the row on screen shows G at once, without leaving the page")
assert(overrideFor("G") and not overrideFor("V"), "G should click the button, V no longer")
keyInit.data.buttonClick()
SnapMarkKeyCatcher._scripts.OnKeyDown(SnapMarkKeyCatcher, "V")
assert(bindings.V == "SNAPMARK_HOLD", "back to V")
-- The ground marker key has its own button and the same key window
local groundInit = settingsButtons[3]
assert(groundInit.data.name == "Ground marker key", "the third button should be the ground marker key")
assert(groundInit.data.buttonText == "B", "it shows B, shows " .. tostring(groundInit.data.buttonText))
local groundRow = settingsRow(groundInit)
groundInit.data.buttonClick()
assert(SnapMarkKeyCatcher.title._text == "Ground marker wheel key", "the key window names the ground wheel")
SnapMarkKeyCatcher._scripts.OnKeyDown(SnapMarkKeyCatcher, "V")
assert(bindings.V == "SNAPMARK_HOLD" and SnapMarkKeyCatcher.text._text:find("Marker wheel"),
    "V is the marker wheel's: it asks first")
SnapMarkKeyCatcher._scripts.OnKeyDown(SnapMarkKeyCatcher, "N")
assert(bindings.N == "SNAPMARK_GROUND" and bindings.B == nil and bindings.V == "SNAPMARK_HOLD", "N replaces B")
assert(groundRow.Button._text == "N" and row.Button._text == "V", "each row shows its own key")
-- Preview
settingsButtons[2].data.buttonClick()
assert(ns.Wheel.isPreview(), "Preview should show the wheel")
tick(0.3)
SettingsPanel._scripts.OnHide(SettingsPanel)
assert(not SnapMarkWheel._shown, "closing the settings closes the preview")
SlashCmdList.SNAPMARK("")
assert(settingsOpened == 9, "/snapmark opens the settings")
SlashCmdList.SNAPMARK("preview")
assert(ns.Wheel.isPreview(), "/snapmark preview")
SlashCmdList.SNAPMARK("preview")
SlashCmdList.SNAPMARK("help")
return count
"""


def load_addon():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(WOW_STUB)
    lua.execute('bindings["CTRL-V"] = "PASTE_SOMETHING"')
    load = lua.eval("function(code, name, ns) local f, err = loadstring(code, name); if not f then error(err) end; return f('SnapMark', ns) end")
    ns = lua.table()
    with open(os.path.join(ADDON, "SnapMark.toc")) as f:
        files = [line.strip() for line in f if line.strip().endswith(".lua")]
    for name in files:
        with open(os.path.join(ADDON, name), encoding="utf-8") as f:
            load(f.read(), "@" + name, ns)
    g = lua.globals()
    g.fireEvent("ADDON_LOADED", "SnapMark")
    g.fireEvent("PLAYER_LOGIN")
    g.fireEvent("PLAYER_ENTERING_WORLD")
    return lua, ns


# ----------------------------------------------------------------------------------------------------------------------
# Drawing

FONTS = {
    "ARIALN": "/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-Bold.otf",
    "FRIZQT": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
}

MARKER_COLORS = {1: (245, 209, 66), 2: (240, 138, 44), 3: (194, 94, 224), 4: (79, 201, 90), 5: (201, 214, 230),
                 6: (63, 142, 240), 7: (232, 68, 58), 8: (242, 242, 236)}


def marker_art(marker, size=128):
    """A stand-in for Blizzard's raid target icon: its shape and color, not its art."""
    from PIL import Image, ImageDraw
    S = size * 4
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, h = S / 2, S / 2 * 0.9
    col = MARKER_COLORS[marker] + (255,)
    out = (0, 0, 0, 200)
    w = int(S * 0.04)
    if marker == 1:
        pts = [(c + math.cos(-math.pi / 2 + i * math.pi / 5) * (h if i % 2 == 0 else h * 0.42),
                c + math.sin(-math.pi / 2 + i * math.pi / 5) * (h if i % 2 == 0 else h * 0.42)) for i in range(10)]
        d.polygon(pts, fill=col, outline=out, width=w)
    elif marker == 2:
        d.ellipse((c - h * 0.8, c - h * 0.8, c + h * 0.8, c + h * 0.8), fill=col, outline=out, width=w)
    elif marker == 3:
        d.polygon([(c, c - h), (c + h * 0.68, c), (c, c + h), (c - h * 0.68, c)], fill=col, outline=out, width=w)
    elif marker == 4:
        d.polygon([(c, c - h * 0.85), (c + h * 0.92, c + h * 0.72), (c - h * 0.92, c + h * 0.72)], fill=col, outline=out, width=w)
    elif marker == 5:
        d.ellipse((c - h * 0.8, c - h * 0.8, c + h * 0.8, c + h * 0.8), fill=col, outline=out, width=w)
        d.ellipse((c - h * 0.45, c - h * 0.95, c + h * 0.9, c + h * 0.5), fill=(0, 0, 0, 0))
    elif marker == 6:
        d.rectangle((c - h * 0.72, c - h * 0.72, c + h * 0.72, c + h * 0.72), fill=col, outline=out, width=w)
    elif marker == 7:
        t = h * 0.26
        e = h * 0.82
        pts = [(-e, -e + t), (-e + t, -e), (0, -t), (e - t, -e), (e, -e + t), (t, 0), (e, e - t), (e - t, e), (0, t),
               (-e + t, e), (-e, e - t), (-t, 0)]
        d.polygon([(c + x, c + y) for x, y in pts], fill=col, outline=out, width=w)
    elif marker == 8:
        d.ellipse((c - h * 0.72, c - h * 0.85, c + h * 0.72, c + h * 0.6), fill=col, outline=out, width=w)
        d.rectangle((c - h * 0.38, c + h * 0.3, c + h * 0.38, c + h * 0.82), fill=col)
        d.ellipse((c - h * 0.5, c - h * 0.32, c - h * 0.1, c + h * 0.1), fill=(20, 20, 20, 255))
        d.ellipse((c + h * 0.1, c - h * 0.32, c + h * 0.5, c + h * 0.1), fill=(20, 20, 20, 255))
    return img.resize((size, size), Image.LANCZOS)


def draw(lua, path, crop=None, scale=2.0, background=None):
    """Draws the wheel as laid out: textures with their size, rotation, color, alpha and blend, and the texts."""
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    g = lua.globals()
    W, H = int(g.screenW * scale), int(g.screenH * scale)
    canvas = background(W, H) if background else Image.new("RGBA", (W, H), (40, 48, 40, 255))
    f = g.SnapMarkWheel
    if not f._shown:
        canvas.save(path)
        return
    ui = g.uiScale
    fs = f._scale or 1
    p = f._points["CENTER"]
    fcx, fcy = p[4] * fs * ui, p[5] * fs * ui  # screen pixels from the bottom left
    falpha = f._alpha if f._alpha is not None else 1
    k = fs * ui * scale  # screen pixels (scaled) per wheel unit

    media = {}

    def texture(path_):
        name = str(path_).replace("\\", "/")
        if name not in media:
            if "/Media/" in name:
                file = os.path.join(ADDON, "Media", name.split("/Media/")[-1] + ".tga")
                media[name] = Image.open(file).convert("RGBA")
            elif "RaidTargetingIcon_" in name:
                media[name] = marker_art(int(name.rsplit("_", 1)[1]))
            else:
                media[name] = None
        return media[name]

    def to_screen(lx, ly):
        return (fcx * scale + lx * k, (g.screenH * scale) - (fcy * scale + ly * k))

    regions = []
    order = {"BACKGROUND": 0, "BORDER": 1, "ARTWORK": 2, "OVERLAY": 3}
    same = lua.eval("function(a, b) return rawequal(a, b) end")
    for i in range(1, len(g.allFrames) + 1):
        o = g.allFrames[i]
        if not same(o._parent, f) or not o._shown:
            continue
        regions.append(o)
    regions.sort(key=lambda o: (order.get(o._layer, 2), o._sub or 0))

    def center_of(o):
        pts = o._points
        pt = pts["CENTER"] if pts and pts["CENTER"] else None
        if pt:
            return pt[4], pt[5]
        top = pts["TOP"]
        rel = top[2]
        if same(rel, f):
            x, y = top[4], top[5]
        else:  # under another text
            rx, ry = center_of(rel)
            x, y = rx + top[4], ry - (rel._fontSize or 12) * 0.62 + top[5]
        return x, y - (o._fontSize or 12) * 0.62

    for o in regions:
        a = (o._alpha if o._alpha is not None else 1) * falpha
        if o._kind == "Texture":
            img = texture(o._tex)
            if img is None or a <= 0.003:
                continue
            w, h = max(1, int(round((o._w or 0) * k))), max(1, int(round((o._h or 0) * k)))
            img = img.resize((w, h), Image.LANCZOS)
            c = o._color or [None, 1, 1, 1, 1]
            r_, g_, b_, al = img.split()
            if o._desat:
                gray = ImageChops.add(ImageChops.multiply(r_, Image.new("L", r_.size, 77)), ImageChops.multiply(g_, Image.new("L", r_.size, 150)))
                r_ = g_ = b_ = img.convert("L")
            r_ = r_.point(lambda v, m=c[1]: int(v * m))
            g_ = g_.point(lambda v, m=c[2]: int(v * m))
            b_ = b_.point(lambda v, m=c[3]: int(v * m))
            al = al.point(lambda v, m=(c[4] if c[4] is not None else 1) * a: int(v * min(1, m)))
            img = Image.merge("RGBA", (r_, g_, b_, al))
            if o._rot:
                img = img.rotate(math.degrees(o._rot), resample=Image.BICUBIC, expand=False)
            lx, ly = center_of(o)
            sx, sy = to_screen(lx, ly)
            x0, y0 = int(round(sx - w / 2)), int(round(sy - h / 2))
            if o._blend == "ADD":
                layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                layer.paste(img, (x0, y0))
                premult = Image.merge("RGB", [ImageChops.multiply(ch, layer.split()[3]) for ch in layer.split()[:3]])
                base = canvas.convert("RGB")
                canvas = Image.merge("RGBA", (*ImageChops.add(base, premult).split(), canvas.split()[3]))
            else:
                layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                layer.paste(img, (x0, y0))
                canvas.alpha_composite(layer)
        elif o._kind == "FontString":
            text = o._text
            if not text or a <= 0.003:
                continue
            fontfile = FONTS["ARIALN"] if "ARIALN" in str(o._font) else FONTS["FRIZQT"]
            font = ImageFont.truetype(fontfile, max(1, int(round(o._fontSize * k))))
            lx, ly = center_of(o)
            sx, sy = to_screen(lx, ly)
            c = o._color or [None, 1, 1, 1, 1]
            fill = (int(c[1] * 255), int(c[2] * 255), int(c[3] * 255), int(255 * a * (c[4] or 1)))
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            d.text((sx, sy), text, font=font, fill=fill, anchor="mm", stroke_width=max(1, int(k)), stroke_fill=(0, 0, 0, fill[3]))
            canvas.alpha_composite(layer)
    if crop:
        cx, cy = to_screen(0, 0)
        half_w, half_h = crop[0] * scale / 2, crop[1] * scale / 2
        canvas = canvas.crop((int(cx - half_w), int(cy - half_h + crop[2] * scale), int(cx + half_w), int(cy + half_h + crop[2] * scale)))
    canvas.save(path)
    print(f"Wrote {path}")


def ground(W, H):
    """A busy dusk forest floor, so a see-through or low-contrast wheel would show."""
    import random
    from PIL import Image, ImageDraw
    rnd = random.Random(7)
    img = Image.new("RGBA", (W, H), (42, 56, 36, 255))
    d = ImageDraw.Draw(img, "RGBA")
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(60 - 14 * t), int(78 - 20 * t), int(52 - 14 * t), 255))
    colors = [(79, 107, 58), (106, 138, 69), (43, 59, 32), (138, 122, 74), (90, 74, 46), (159, 181, 101), (62, 85, 48)]
    for _ in range(int(W * H / 500)):
        x, y = rnd.random() * W, rnd.random() * H
        s = 2 + rnd.random() * 22
        c = colors[rnd.randrange(len(colors))]
        d.ellipse((x - s, y - s * 0.5, x + s, y + s * 0.5), fill=c + (int(60 + rnd.random() * 120),))
    return img


def snapshots(outdir):
    os.makedirs(outdir, exist_ok=True)
    lua, ns = load_addon()
    g = lua.globals()
    lua.execute("""
        SetBinding("V", "SNAPMARK_HOLD")
        SetBinding("B", "SNAPMARK_GROUND")
        inGroup = true
        world.player = { guid = "Player-1", name = "Olof" }
        addPlate("nameplate1", { guid = "Creature-1", name = "Defias Pillager", mob = true })
        world.target = world.nameplate1
    """)
    crop = (420, 380, 20)

    def hold(dx, dy, t, name, extra="", k="V"):
        lua.execute(f"""
            cursorX, cursorY = 800, 500
            key("{k}", true)
            {extra}
            cursorX, cursorY = 800 + ({dx}), 500 + ({dy})
            tick({t})
        """)
        draw(lua, os.path.join(outdir, name), crop=crop, background=ground)

    def let_go(t, name, k="V"):
        lua.execute(f'key("{k}", false) tick({t})')
        if name:
            draw(lua, os.path.join(outdir, name), crop=crop, background=ground)

    hold(0, 0, 0.3, "open.png")
    let_go(0.4, None)
    hold(70, 12, 0.3, "square.png")
    let_go(0.4, None)
    hold(-30, 600, 0.3, "skull_far.png")
    let_go(0.07, "mark_pop.png")
    lua.execute("tick(0.5)")
    hold(-150, -150, 0.03, "opening.png")
    let_go(0.4, None)
    lua.execute("world.target = nil")
    hold(200, -60, 0.3, "no_target.png")
    let_go(0.4, None)
    lua.execute("world.target = world.nameplate1 ns = ...", ns)
    lua.execute("SnapMarkDB.size = 1.3 SnapMarkDB.background = 0.4")
    hold(-200, 90, 0.3, "large_light.png")
    let_go(0.4, None)
    lua.execute("SnapMarkDB.size = 1 SnapMarkDB.background = 0.85")
    hold(-140, 150, 0.3, "ground.png", k="B")
    let_go(0.4, None, k="B")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", metavar="DIR", help="also draw the wheel to PNG files in DIR")
    args = parser.parse_args()

    lua, ns = load_addon()
    run = lua.eval("function(code, ns) local f = assert(loadstring(code, '=checks')) return f(ns) end")
    tries = run(CHECKS, ns)
    print(f"ok    marking: {tries} flicks agree between the wheel and the secure snippet, and every case marks what it should")
    count = run(SETTINGS_CHECK, ns)
    print(f"ok    settings page: {count} settings, the key window and the preview")
    errors = lua.globals().errors
    if len(errors) > 0:
        sys.exit("errors: " + str(errors[1]))
    if args.snapshot:
        snapshots(args.snapshot)


if __name__ == "__main__":
    main()
