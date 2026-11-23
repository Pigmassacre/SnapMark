-- The wheel you see. Ordinary addon art: it can show, hide and animate freely in a fight. It never decides anything;
-- the secure snippet in Secure.lua does, with the same rule (ns.pick) from the same starting point, so what lights up
-- here is what gets marked.

local _, ns = ...

local Wheel = {}
ns.Wheel = Wheel

-- UI units at size 1. Keep in step with tools/make_flickmark_art.py.
local R_IN, R_OUT, R_ICON, RING_SPAN = 36, 116, 78, 248
local ICON = 34
local GROW, PUSH = 1.4, 5        -- the chosen marker: how much bigger, and how far out
local OPEN_TIME = 0.11
local CLOSE_TIME, MARK_TIME = 0.12, 0.26
local NAME_FONT, LABEL_FONT = "Fonts\\FRIZQT__.TTF", "Fonts\\ARIALN.TTF"

local f
local state = {}

local function clamp(v, lo, hi) return math.max(lo, math.min(hi, v)) end
local function approach(cur, target, dt, speed) return cur + (target - cur) * (1 - math.exp(-dt * speed)) end
local function outBack(t)
    local c1 = 1.2
    local c3 = c1 + 1
    t = t - 1
    return 1 + c3 * t * t * t + c1 * t * t
end
local function outCubic(t) t = 1 - t return 1 - t * t * t end

-- Shortest turn from a to b, in radians.
local function turn(a, b)
    local d = (b - a) % (2 * math.pi)
    if d > math.pi then d = d - 2 * math.pi end
    return d
end

local function slotAngle(i) return -(i - 1) * math.pi / 4 end -- texture rotation for a slot; art points up

----------------------------------------------------------------------------------------------------------------------
-- Building it

local function full(tex)
    tex:SetPoint("CENTER")
    tex:SetSize(RING_SPAN, RING_SPAN)
    return tex
end

local function build()
    f = CreateFrame("Frame", "FlickMarkWheel", UIParent)
    f:SetFrameStrata("FULLSCREEN_DIALOG")
    f:SetFrameLevel(60)
    f:SetSize(RING_SPAN, RING_SPAN)
    f:EnableMouse(false)
    f:Hide()

    f.ring = full(f:CreateTexture(nil, "BACKGROUND"))
    f.ring:SetTexture(ns.MEDIA .. "ring")

    f.wedge = full(f:CreateTexture(nil, "BORDER"))
    f.wedge:SetTexture(ns.MEDIA .. "wedge")
    f.wedge:SetBlendMode("ADD")

    f.rim = full(f:CreateTexture(nil, "ARTWORK", nil, 0))
    f.rim:SetTexture(ns.MEDIA .. "rim")
    f.rim:SetVertexColor(1, 1, 1, 0.16)

    f.glow = f:CreateTexture(nil, "ARTWORK", nil, 1)
    f.glow:SetTexture(ns.MEDIA .. "glow")
    f.glow:SetSize(96, 96)
    f.glow:SetBlendMode("ADD")

    f.icons = {}
    for i, s in ipairs(ns.SLOTS) do
        local icon = f:CreateTexture(nil, "ARTWORK", nil, 3)
        icon:SetTexture(ns.markerIcon(s.marker))
        icon:SetSize(ICON, ICON)
        icon:SetPoint("CENTER", f, "CENTER", s.x * R_ICON, s.y * R_ICON)
        f.icons[i] = icon
    end

    f.disc = full(f:CreateTexture(nil, "OVERLAY", nil, 0))
    f.disc:SetTexture(ns.MEDIA .. "disc")

    f.notch = full(f:CreateTexture(nil, "OVERLAY", nil, 1))
    f.notch:SetTexture(ns.MEDIA .. "notch")

    f.name = f:CreateFontString(nil, "OVERLAY")
    f.name:SetFont(NAME_FONT, 12, "OUTLINE")
    f.name:SetPoint("CENTER")
    f.name:SetWidth(2 * R_IN + 24)
    f.name:SetJustifyH("CENTER")
    f.name:SetWordWrap(false)

    -- Under the wheel: who gets marked, and a short note when that needs one.
    f.unit = f:CreateFontString(nil, "OVERLAY")
    f.unit:SetFont(LABEL_FONT, 13, "OUTLINE")
    f.unit:SetPoint("TOP", f, "CENTER", 0, -(R_OUT + 6))
    f.unit:SetWidth(2 * R_OUT)
    f.unit:SetJustifyH("CENTER")
    f.unit:SetWordWrap(false)

    f.note = f:CreateFontString(nil, "OVERLAY")
    f.note:SetFont(LABEL_FONT, 11, "OUTLINE")
    f.note:SetPoint("TOP", f.unit, "BOTTOM", 0, -2)
    f.note:SetWidth(2 * R_OUT + 40)
    f.note:SetJustifyH("CENTER")

    -- The chosen marker, popping as the mark is set.
    f.burst = f:CreateTexture(nil, "OVERLAY", nil, 4)
    f.burst:SetSize(ICON, ICON)
    f.burst:Hide()

    f:SetScript("OnUpdate", function(_, dt) Wheel.update(dt) end)
    f:SetScript("OnHide", function() state.open, state.closing, state.preview = false, nil, false end)
    UISpecialFrames[#UISpecialFrames + 1] = "FlickMarkWheel"
end

----------------------------------------------------------------------------------------------------------------------
-- Placing and painting

local function cursor()
    local x, y = GetCursorPosition()
    local s = UIParent:GetEffectiveScale()
    return x / s, y / s
end

-- Puts the wheel's centre at (cx, cy) in UIParent units, at scale s. Offsets of a scaled frame are in its own units.
local function place(s)
    f:SetScale(s)
    f:ClearAllPoints()
    f:SetPoint("CENTER", UIParent, "BOTTOMLEFT", state.cx / s, state.cy / s)
end

local function color(i)
    if not state.available then return 0.6, 0.6, 0.6 end
    local c = ns.SLOTS[i].color
    return c[1], c[2], c[3]
end

local function paintBacking()
    f.ring:SetVertexColor(0.035, 0.04, 0.05, 0.25 + 0.7 * ns.db.background)
    f.disc:SetVertexColor(0.02, 0.025, 0.03, 0.55 + 0.4 * ns.db.background)
end

-- Who will get marked, for the label under the wheel.
local function who(first)
    local db, combat = ns.db, InCombatLockdown()
    if db.mode == "point" and ns.Secure and ns.Secure.pointed and (not combat or first) then
        -- Pointing at it, or targeting it as the key went down: either way, it's the one under the pointer.
        return "mouseover", nil
    end
    local unit = db.mode == "focus" and "focus" or "target"
    local note
    if db.mode == "point" and combat and ns.read(UnitExists, "mouseover")
        and ns.read(UnitIsUnit, "mouseover", unit) == false then
        note = "Marks your target in a fight"
    end
    return unit, note
end

local function canMark(ground)
    local raid = IsInRaid and IsInRaid()
    if ground and not raid and IsInGroup and not IsInGroup() then
        return false, "Ground markers need a group"
    end
    if raid then
        local lead = (UnitIsGroupLeader and ns.read(UnitIsGroupLeader, "player"))
            or (UnitIsGroupAssistant and ns.read(UnitIsGroupAssistant, "player"))
            or (IsEveryoneAssistant and ns.read(IsEveryoneAssistant))
        if not lead then return false, "Only the leader or an assistant can mark in a raid" end
    end
    return true
end

----------------------------------------------------------------------------------------------------------------------
-- Opening, following the pointer, closing

local function reset(preview)
    if not f then build() end
    state.open, state.preview, state.closing, state.kind = true, preview, nil, "unit"
    state.t, state.sel, state.lastSel = 0, nil, nil
    state.wedgeRot, state.wedgeA, state.glowA, state.notchRot, state.notchA = 0, 0, 0, 0, 0
    state.grow = { 1, 1, 1, 1, 1, 1, 1, 1 }
    state.keySeen, state.keyMissing = false, 0
    f.burst:Hide()
    f.wedge:SetAlpha(0)
    f.glow:SetAlpha(0)
    f.notch:SetAlpha(0)
    f.name:SetText("")
    paintBacking()
end

-- From the secure snippet, on key down. first: it targeted what you point at. kind: "unit" (the marker key) or
-- "ground" (the ground marker key).
function Wheel.open(first, kind)
    reset(false)
    state.kind = kind == "ground" and "ground" or "unit"
    local s = ns.db.size
    state.ox, state.oy = cursor()
    local W, H = UIParent:GetWidth(), UIParent:GetHeight()
    local m = (R_OUT + 6) * s
    state.cx, state.cy = clamp(state.ox, m, W - m), clamp(state.oy, m + 34 * s, H - m)

    local ok, reason, note
    if state.kind == "ground" then
        ok, reason = canMark(true)
        note = "Then click where it goes"
        f.unit:SetText("Ground marker")
    else
        local unit
        unit, note = who(first)
        local exists = ns.read(UnitExists, unit)
        ok, reason = canMark(false)
        if exists == false then
            ok, reason = false, unit == "focus" and "No focus" or "No target"
        end
        if exists ~= false then
            local okName, name = pcall(UnitName, unit)
            f.unit:SetText(okName and name or "")
        else
            f.unit:SetText("")
        end
    end
    state.available, state.reason = ok, reason
    f.unit:SetTextColor(1, 1, 1, 1)
    f.note:SetText(reason or note or "")
    if reason then f.note:SetTextColor(1, 0.45, 0.4, 1) else f.note:SetTextColor(0.75, 0.78, 0.8, 1) end
    for i, icon in ipairs(f.icons) do icon:SetDesaturated(not ok) end

    if IsMouselooking and IsMouselooking() and MouselookStop then pcall(MouselookStop) end
    place(s * 0.86)
    f:SetAlpha(0)
    f:Show()
end

-- From the secure snippet, on key up, Esc or right-click. how: "toggle", "set" or "clear" (a mark was set or taken
-- off), "ground" (a ground marker is on its way: the game's targeting circle is up), "groundclear" (all ground markers
-- removed), "none" (let go in the centre), "cancel", "lost" (what you pointed at is gone).
function Wheel.close(how, marker)
    if not (f and f:IsShown()) or state.preview then return end
    local marked = how == "toggle" or how == "set" or how == "ground"
    if marked and state.available then
        local i = ns.SLOT_OF[marker]
        state.closing = { kind = "mark", t = 0, dur = MARK_TIME, slot = i }
        local icon = f.icons[i]
        f.burst:SetTexture(ns.markerIcon(marker))
        f.burst:ClearAllPoints()
        f.burst:SetPoint("CENTER", f, "CENTER", ns.SLOTS[i].x * (R_ICON + PUSH), ns.SLOTS[i].y * (R_ICON + PUSH))
        f.burst:SetSize(ICON * state.grow[i], ICON * state.grow[i])
        f.burst:Show()
        icon:SetAlpha(0)
        ns.play("IG_MAINMENU_OPTION_CHECKBOX_ON")
    else
        state.closing = { kind = "fade", t = 0, dur = CLOSE_TIME }
        if how == "lost" and UIErrorsFrame then
            UIErrorsFrame:AddMessage("What you pointed at went out of sight before you let go, so nothing was marked.", 1, 0.3, 0.25)
        elseif (marked or how == "clear" or how == "groundclear") and state.reason and UIErrorsFrame then
            UIErrorsFrame:AddMessage(state.reason, 1, 0.3, 0.25)
        end
    end
    state.open = false
end

local function keyStillDown()
    if not IsKeyDown then return nil end
    local any = nil
    for _, binding in ipairs(ns.keys(state.kind == "ground" and ns.GROUND_BINDING or nil)) do
        local key = binding:match("([^%-]+)$")
        local down
        if key:match("^BUTTON%d+$") then
            local names = { BUTTON1 = "LeftButton", BUTTON2 = "RightButton", BUTTON3 = "MiddleButton" }
            if IsMouseButtonDown then down = ns.read(IsMouseButtonDown, names[key] or ("Button" .. key:sub(7))) end
        else
            down = ns.read(IsKeyDown, key)
        end
        if down == true then return true end
        if down == false then any = false end
    end
    return any
end

local function follow(dt)
    local x, y = cursor()
    local dx, dy = x - state.ox, y - state.oy
    local slot = ns.pick(dx, dy)

    if slot ~= state.sel then
        if slot and not state.sel then
            state.wedgeRot = slotAngle(slot) -- appears where it points, then glides between slices
        end
        state.sel = slot
        if slot then ns.play("U_CHAT_SCROLL_BUTTON") end
    end

    local sel = state.sel
    if sel then
        state.wedgeRot = state.wedgeRot + turn(state.wedgeRot, slotAngle(sel)) * (1 - math.exp(-dt * 34))
        local r, g, b = color(sel)
        f.wedge:SetVertexColor(r, g, b, 1)
        f.glow:SetVertexColor(r, g, b, 1)
        f.notch:SetVertexColor(r, g, b, 1)
        local s = ns.SLOTS[sel]
        f.glow:ClearAllPoints()
        f.glow:SetPoint("CENTER", f, "CENTER", s.x * (R_ICON + PUSH), s.y * (R_ICON + PUSH))
        if ns.db.names then
            f.name:SetText(s.name)
            f.name:SetTextColor(r, g, b, 1)
        else
            f.name:SetText("")
        end
    else
        f.name:SetText("")
    end
    f.wedge:SetRotation(state.wedgeRot)
    local bright = sel and (ns.SLOTS[sel].light or 0.9) or 0
    state.wedgeA = approach(state.wedgeA, sel and (state.available and bright or 0.5) or 0, dt, 30)
    state.glowA = approach(state.glowA, (sel and state.available) and 0.55 or 0, dt, 26)
    f.wedge:SetAlpha(state.wedgeA)
    f.glow:SetAlpha(state.glowA)

    -- The pointer on the centre's edge follows the movement itself, not the slice.
    local moved = dx * dx + dy * dy >= ns.deadZone() ^ 2
    if moved then
        local want = math.atan2(dy, dx) - math.pi / 2
        state.notchRot = state.notchRot + turn(state.notchRot, want) * (state.notchA < 0.05 and 1 or (1 - math.exp(-dt * 40)))
    end
    state.notchA = approach(state.notchA, moved and 0.9 or 0, dt, 30)
    f.notch:SetRotation(state.notchRot)
    f.notch:SetAlpha(state.notchA)
    if not sel then f.notch:SetVertexColor(1, 1, 1, 1) end

    for i, icon in ipairs(f.icons) do
        local want = (i == sel) and GROW or 1
        state.grow[i] = approach(state.grow[i], want, dt, 26)
        local g = state.grow[i]
        local push = (g - 1) / (GROW - 1) * PUSH
        icon:SetSize(ICON * g, ICON * g)
        icon:SetPoint("CENTER", f, "CENTER", ns.SLOTS[i].x * (R_ICON + push), ns.SLOTS[i].y * (R_ICON + push))
        local a = 1
        if not state.available then a = 0.4 elseif sel and i ~= sel then a = 0.5 end
        icon:SetAlpha(a)
    end
end

function Wheel.update(dt)
    state.t = (state.t or 0) + dt
    local s = ns.db.size

    if state.closing then
        local c = state.closing
        c.t = c.t + dt
        local k = clamp(c.t / c.dur, 0, 1)
        if c.kind == "mark" then
            local ring = clamp(c.t / CLOSE_TIME, 0, 1)
            place(s * (1 + 0.05 * outCubic(ring)))
            f:SetAlpha(1)
            local fade = 1 - outCubic(ring)
            f.ring:SetAlpha(fade) f.rim:SetAlpha(fade) f.disc:SetAlpha(fade) f.wedge:SetAlpha(state.wedgeA * fade)
            f.notch:SetAlpha(0) f.name:SetAlpha(fade) f.unit:SetAlpha(fade) f.note:SetAlpha(fade)
            for i, icon in ipairs(f.icons) do if i ~= c.slot then icon:SetAlpha(0.5 * fade) end end
            local g = state.grow[c.slot] * (1 + 0.55 * outCubic(k))
            f.burst:SetSize(ICON * g, ICON * g)
            f.burst:SetAlpha(1 - k * k)
            f.glow:SetAlpha(0.55 * (1 - k))
        else
            place(s * (1 - 0.08 * outCubic(k)))
            f:SetAlpha(1 - outCubic(k))
        end
        if k >= 1 then
            f.ring:SetAlpha(1) f.rim:SetAlpha(1) f.disc:SetAlpha(1) f.name:SetAlpha(1) f.unit:SetAlpha(1) f.note:SetAlpha(1)
            f.burst:Hide()
            f:Hide()
        end
        return
    end

    -- Opening: a quick grow with a touch of overshoot.
    local k = clamp(state.t / OPEN_TIME, 0, 1)
    place(s * (0.86 + 0.14 * outBack(k)))
    f:SetAlpha(outCubic(k))

    if state.preview then
        state.ox, state.oy = state.cx, state.cy
    end
    follow(dt)

    -- The key's release never came (the game lost focus, say): close. Only once the game has shown the key as held,
    -- so a key it can't report on never closes the wheel by mistake.
    if not state.preview then
        local down = keyStillDown()
        if down then state.keySeen, state.keyMissing = true, 0
        elseif down == false and state.keySeen then state.keyMissing = state.keyMissing + 1 end
        if state.keyMissing >= 3 then
            state.closing = { kind = "fade", t = 0, dur = CLOSE_TIME }
            state.open = false
            if ns.Secure then ns.Secure.reset() end
        end
    end
end

----------------------------------------------------------------------------------------------------------------------
-- Preview: the wheel in the middle of the screen, following the pointer, marking nothing.

function ns.togglePreview(show)
    if show == nil then show = not (f and f:IsShown() and state.preview) end
    if not show then
        if f and state.preview then f:Hide() end
        return
    end
    if ns.Secure and ns.Secure.isOpen() then return end
    reset(true)
    state.cx, state.cy = UIParent:GetWidth() * 0.5, UIParent:GetHeight() * 0.5
    state.ox, state.oy = state.cx, state.cy
    state.available, state.reason = true, nil
    for _, icon in ipairs(f.icons) do icon:SetDesaturated(false) end
    f.unit:SetText("Preview")
    f.unit:SetTextColor(1, 1, 1, 1)
    f.note:SetText("Move the pointer around the wheel. Nothing gets marked.")
    f.note:SetTextColor(0.75, 0.78, 0.8, 1)
    place(ns.db.size * 0.86)
    f:SetAlpha(0)
    f:Show()
end

function Wheel.isPreview() return f and f:IsShown() and state.preview or false end

ns.On("SETTING", function(key)
    if f and f:IsShown() and (key == "background") then paintBacking() end
end)

ns.Wheel.state = state -- for the tests
