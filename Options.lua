-- The SnapMark page in the game's settings (Options > AddOns), through the Settings API, and the small window that
-- asks for a key. Every control is a proxy over SnapMarkDB and changes it through ns.set.

local _, ns = ...

local category
local keyRows = {} -- binding -> { init = the button's initializer, frame = its row on screen }

----------------------------------------------------------------------------------------------------------------------
-- Choosing the key

local catcher

local MODIFIER_KEYS = {
    LSHIFT = true, RSHIFT = true, LCTRL = true, RCTRL = true, LALT = true, RALT = true, LMETA = true, RMETA = true,
}

local function bindingLabel(action)
    if not action or action == "" then return nil end
    return _G["BINDING_NAME_" .. action] or action
end

local function keyLabel(key)
    return GetBindingText and GetBindingText(key) or key
end

-- The settings page draws a button's text when it builds the row; the row on screen gets the new key too.
local function refreshKeyButtons()
    for binding, row in pairs(keyRows) do
        local init = row.init
        local data = init.GetData and init:GetData() or init.data
        local old = type(data) == "table" and data.buttonText
        local text = ns.keyText(binding)
        if type(data) == "table" then data.buttonText = text end
        local b = row.frame and row.frame.Button
        if b and b.GetText and b.SetText then
            local ok, shown = pcall(b.GetText, b)
            if ok and (shown == old or shown == text) then b:SetText(text) end
        end
    end
end

local function buildCatcher()
    catcher = CreateFrame("Frame", "SnapMarkKeyCatcher", UIParent, "BackdropTemplate")
    catcher:SetSize(340, 132)
    catcher:SetPoint("CENTER", 0, 120)
    catcher:SetFrameStrata("FULLSCREEN_DIALOG")
    catcher:SetFrameLevel(200)
    catcher:EnableMouse(true)
    catcher:EnableKeyboard(true)
    if catcher.SetBackdrop then
        catcher:SetBackdrop({
            bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1,
        })
        catcher:SetBackdropColor(0.04, 0.05, 0.06, 0.96)
        catcher:SetBackdropBorderColor(0.56, 0.83, 0.77, 0.8)
    end

    catcher.title = catcher:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    catcher.title:SetPoint("TOP", 0, -14)

    catcher.text = catcher:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    catcher.text:SetPoint("TOP", catcher.title, "BOTTOM", 0, -10)
    catcher.text:SetWidth(300)
    catcher.text:SetJustifyH("CENTER")

    catcher.hint = catcher:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    catcher.hint:SetPoint("BOTTOM", 0, 12)
    catcher.hint:SetText("Esc cancels")

    local function take(key)
        if MODIFIER_KEYS[key] then return end
        if key == "ESCAPE" then catcher:Hide() return end
        local combo = key
        if IsAltKeyDown() then combo = "ALT-" .. combo end
        if IsControlKeyDown() then combo = "CTRL-" .. combo end
        if IsShiftKeyDown() then combo = "SHIFT-" .. combo end
        local action = GetBindingAction(combo)
        local other = action ~= "" and action ~= catcher.binding and bindingLabel(action)
        if other and catcher.confirm ~= combo then
            catcher.confirm = combo
            catcher.text:SetText(keyLabel(combo) .. " is used for " .. other
                .. ".\nPress " .. keyLabel(combo) .. " again to use it for the wheel, or press another key.")
            return
        end
        if ns.bindKey(combo, catcher.binding) then
            if catcher.binding == ns.GROUND_BINDING then
                ns.say("hold " .. keyLabel(combo) .. ", move toward a marker, let go, then click the ground.")
            else
                ns.say("hold " .. keyLabel(combo) .. ", move toward a marker and let go.")
            end
            refreshKeyButtons()
            catcher:Hide()
        end
    end

    catcher:SetScript("OnKeyDown", function(_, key) take(key) end)
    catcher:SetScript("OnMouseDown", function(_, button)
        local map = { MiddleButton = "BUTTON3", Button4 = "BUTTON4", Button5 = "BUTTON5" }
        if map[button] then take(map[button]) end
    end)
    catcher:Hide()
end

-- binding: ns.BINDING (when left out) or ns.GROUND_BINDING.
function ns.chooseKey(binding)
    binding = binding or ns.BINDING
    if InCombatLockdown() then
        ns.say("keys can't change during a fight. Try again after it.")
        return
    end
    if not catcher then buildCatcher() end
    catcher.binding, catcher.confirm = binding, nil
    local ground = binding == ns.GROUND_BINDING
    catcher.title:SetText(ground and "Ground marker wheel key" or "Marker wheel key")
    catcher.text:SetText("Press the key you want to hold for the " .. (ground and "ground marker wheel" or "wheel")
        .. ".\nNow: " .. ns.keyText(binding))
    catcher:Show()
end

----------------------------------------------------------------------------------------------------------------------
-- The page

local function register()
    category = Settings.RegisterVerticalLayoutCategory("SnapMark")
    local createCheckbox = Settings.CreateCheckbox or Settings.CreateCheckBox
    local createDropdown = Settings.CreateDropdown or Settings.CreateDropDown

    local function check(key, label, tooltip)
        local setting = Settings.RegisterProxySetting(category, "SNAPMARK_" .. key:upper(), Settings.VarType.Boolean,
            label, ns.DEFAULTS[key],
            function() return ns.db[key] and true or false end,
            function(value) ns.set(key, value and true or false) end)
        createCheckbox(category, setting, tooltip)
    end

    local function choice(key, label, options, tooltip)
        local setting = Settings.RegisterProxySetting(category, "SNAPMARK_" .. key:upper(), Settings.VarType.String,
            label, ns.DEFAULTS[key],
            function() return ns.db[key] end,
            function(value) ns.set(key, value) end)
        createDropdown(category, setting, function()
            local container = Settings.CreateControlTextContainer()
            for _, o in ipairs(options) do container:Add(o[1], o[2]) end
            return container:GetData()
        end, tooltip)
    end

    local function slider(key, label, lo, hi, step, tooltip)
        local setting = Settings.RegisterProxySetting(category, "SNAPMARK_" .. key:upper(), Settings.VarType.Number,
            label, math.floor(ns.DEFAULTS[key] * 100 + 0.5),
            function() return math.floor(ns.db[key] * 100 + 0.5) end,
            function(value) ns.set(key, math.max(lo, math.min(hi, value)) / 100) end)
        if Settings.CreateSlider and Settings.CreateSliderOptions then
            local options = Settings.CreateSliderOptions(lo, hi, step)
            if options.SetLabelFormatter and MinimalSliderWithSteppersMixin then
                options:SetLabelFormatter(MinimalSliderWithSteppersMixin.Label.Right, function(v) return v .. "%" end)
            end
            Settings.CreateSlider(category, setting, options, tooltip)
        end
    end

    local function button(label, text, onClick, tooltip)
        if CreateSettingsButtonInitializer and SettingsPanel and SettingsPanel.GetLayout then
            local init = CreateSettingsButtonInitializer(label, text, onClick, tooltip, true)
            SettingsPanel:GetLayout(category):AddInitializer(init)
            return init
        end
    end

    local function keyButton(binding, label, tooltip)
        local init = button(label, ns.keyText(binding), function() ns.chooseKey(binding) end, tooltip)
        if not init then return end
        local row = { init = init }
        keyRows[binding] = row
        -- Remember the row on screen as the page builds it, to change its text when the key changes.
        if type(init.InitFrame) == "function" then
            local initFrame = init.InitFrame
            init.InitFrame = function(self, frame, ...)
                initFrame(self, frame, ...)
                row.frame = frame
            end
        end
    end

    keyButton(ns.BINDING, "Wheel key", "The key you hold to open the wheel. Click, then press a key.")

    button("Preview", "Show", function() ns.togglePreview() end,
        "Shows the wheel in the middle of the screen to try out the size and look. Nothing gets marked.")

    choice("mode", "What to mark", {
        { "point", "What I point at, else my target" }, { "target", "My target" }, { "focus", "My focus" },
    }, "What I point at: the enemy or player under the pointer when you press the key, by its nameplate or model. "
        .. "With nothing there, your target.")

    choice("combat", "In a fight", {
        { "target", "Mark my target" }, { "targetfirst", "Target what I point at, then mark it" },
    }, "In a fight the game doesn't let addons remember what you pointed at, so the wheel marks your target. "
        .. "\"Target what I point at\" targets it as you press the key, which changes your target.")

    choice("center", "Let go in the centre", {
        { "none", "Nothing" }, { "skull", "Skull" }, { "clear", "Remove the mark" },
    }, "What happens when you let go without moving away from the centre.")

    slider("size", "Wheel size", 70, 150, 5, "How big the wheel is.")
    slider("background", "Background", 0, 100, 5, "How solid the wheel's backing is.")

    check("names", "Marker names", "Show the name of the marker you are about to set in the middle of the wheel.")
    check("sound", "Sounds", "A soft tick when the choice changes and a click when a mark is set.")

    if ns.groundEnabled() then
        local header = CreateSettingsListSectionHeaderInitializer
            and SettingsPanel and SettingsPanel.GetLayout and CreateSettingsListSectionHeaderInitializer("Ground markers")
        if header then SettingsPanel:GetLayout(category):AddInitializer(header) end
        keyButton(ns.GROUND_BINDING, "Ground marker key",
            "The key you hold to open the wheel for ground markers. Let go on a marker, then click the ground where "
            .. "it goes. Picking a marker that's already down moves it. Click, then press a key.")
        choice("groundCenter", header and "Let go in the centre" or "Ground: let go in the centre", {
            { "none", "Nothing" }, { "clear", "Remove all ground markers" },
        }, "What happens when you let go of the ground marker key without moving away from the centre.")
    end

    Settings.RegisterAddOnCategory(category)

    if SettingsPanel and SettingsPanel.HookScript then
        SettingsPanel:HookScript("OnHide", function() ns.togglePreview(false) end)
    end
end

ns.On("LOGIN", function()
    if not (Settings and Settings.RegisterVerticalLayoutCategory and Settings.RegisterProxySetting) then return end
    local ok, err = pcall(register)
    if not ok then
        category = nil
        geterrorhandler()(err)
    end
end)

ns.On("UPDATE_BINDINGS", refreshKeyButtons)

function ns.openOptions()
    if category then
        Settings.OpenToCategory(category:GetID())
    else
        ns.say("this client has no settings page for addons. /snapmark preview shows the wheel.")
        ns.chooseKey()
    end
end
