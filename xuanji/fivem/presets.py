"""Scaffold 预设。每套一个 ScaffoldPreset。

姐姐设计预设的原则：
1. **能直接运行**——startup 不报错，能在 server 里 ensure 起来
2. **示范主流 API**——里面带 1-2 个最常见的"hello world 级"用法
3. **README 写清楚下一步**——告诉小宝怎么扩展

6 套核心预设（builtin）：
- qbcore-basic / qbox-basic / qbcore-job / qbox-job / ox-target-npc / esx-basic

加上 0.4.0 引入的"用户预设"机制——玄玑可以通过 `propose_preset` 工具
提交草案，小宝 review 后落到 `<data_dir>/scaffold_presets/<key>.json`，
ScaffoldEngine 启动时合并加载。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from xuanji.fivem.models import Framework, InventoryKind, TargetKind


class ScaffoldFile(BaseModel):
    """一个待写文件。"""

    path: str
    """相对 resource 根的路径。支持 {{var}} 占位符。"""
    content: str


class ScaffoldPreset(BaseModel):
    """一组生成 resource 骨架的模板。

    可 JSON 序列化——便于"用户预设"持久化与"propose_preset"草案落盘。
    """

    key: str
    label: str
    description: str
    framework: Framework
    inventory: InventoryKind
    target: TargetKind
    source: str = "builtin"
    """'builtin' / 'user'。区分内置与用户自学习的。"""
    files: list[ScaffoldFile] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    """学习来源、生成时间、提交人等附加信息。"""


# ============================================================
# 通用片段
# ============================================================


_README_TEMPLATE = """\
# {{name}}

{{description}}

> 由玄玑（FiveM 智能体）生成 · preset: `{preset_key}`

## 启动

1. 把本资源放到 `resources/` 下
2. 编辑 `server.cfg` 加一行：`ensure {{name}}`
3. 重启服务器或 `restart {{name}}`

## 目录结构

```
{{name}}/
├── fxmanifest.lua
├── client/
│   └── main.lua
├── server/
│   └── main.lua
└── shared/
    └── config.lua
```

## 下一步

{next_steps}
"""


def _readme(preset_key: str, next_steps: str) -> str:
    return _README_TEMPLATE.format(preset_key=preset_key, next_steps=next_steps)


# ============================================================
# qbcore-basic
# ============================================================


_QBCORE_BASIC = ScaffoldPreset(
    key="qbcore-basic",
    label="QBCore 最小骨架",
    description="QBCore 框架下的最小 client + server resource 骨架",
    framework=Framework.QBCORE,
    inventory=InventoryKind.QB_INVENTORY,
    target=TargetKind.QB_TARGET,
    files=[
        ScaffoldFile(
            path="fxmanifest.lua",
            content="""\
fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name '{{name}}'
description '{{description}}'
author '{{author}}'
version '{{version}}'

shared_scripts {
    'shared/config.lua',
}

client_scripts {
    'client/main.lua',
}

server_scripts {
    'server/main.lua',
}

dependencies {
    'qb-core',
}
""",
        ),
        ScaffoldFile(
            path="shared/config.lua",
            content="""\
Config = Config or {}

Config.Debug = false
""",
        ),
        ScaffoldFile(
            path="client/main.lua",
            content="""\
local QBCore = exports['qb-core']:GetCoreObject()

-- 客户端起点
CreateThread(function()
    if Config.Debug then
        print('[{{name}}] client started')
    end
end)

RegisterNetEvent('{{name}}:client:hello', function(message)
    QBCore.Functions.Notify(message, 'primary')
end)
""",
        ),
        ScaffoldFile(
            path="server/main.lua",
            content="""\
local QBCore = exports['qb-core']:GetCoreObject()

-- 服务端起点
RegisterNetEvent('{{name}}:server:greet', function()
    local src = source
    local Player = QBCore.Functions.GetPlayer(src)
    if not Player then return end
    TriggerClientEvent(
        '{{name}}:client:hello',
        src,
        ('Hello, %s'):format(Player.PlayerData.charinfo.firstname or 'mate')
    )
end)
""",
        ),
        ScaffoldFile(
            path="README.md",
            content=_readme(
                "qbcore-basic",
                """- 在 `client/main.lua` 加 UI / 命令 / 事件
- 在 `server/main.lua` 用 `QBCore.Functions.GetPlayer(source)` 拿玩家，调 Player.Functions
- 添加可使用物品：`QBCore.Functions.CreateUseableItem('item_name', function(source, item) ... end)`
""",
            ),
        ),
    ],
)


# ============================================================
# qbox-basic
# ============================================================


_QBOX_BASIC = ScaffoldPreset(
    key="qbox-basic",
    label="QBox 最小骨架",
    description="QBox（qbx_core）框架下的最小 resource 骨架，使用 ox_lib",
    framework=Framework.QBOX,
    inventory=InventoryKind.OX_INVENTORY,
    target=TargetKind.OX_TARGET,
    files=[
        ScaffoldFile(
            path="fxmanifest.lua",
            content="""\
fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name '{{name}}'
description '{{description}}'
author '{{author}}'
version '{{version}}'

shared_scripts {
    '@ox_lib/init.lua',
    'shared/config.lua',
}

client_scripts {
    'client/main.lua',
}

server_scripts {
    'server/main.lua',
}

dependencies {
    'qbx_core',
    'ox_lib',
}
""",
        ),
        ScaffoldFile(
            path="shared/config.lua",
            content="""\
Config = Config or {}

Config.Debug = false
""",
        ),
        ScaffoldFile(
            path="client/main.lua",
            content="""\
-- QBox 用法：直接 require 或 exports.qbx_core，配合 ox_lib

CreateThread(function()
    if Config.Debug then
        lib.print.info('[{{name}}] client started')
    end
end)

RegisterNetEvent('{{name}}:client:hello', function(message)
    lib.notify({ title = '{{name}}', description = message, type = 'inform' })
end)
""",
        ),
        ScaffoldFile(
            path="server/main.lua",
            content="""\
-- QBox 服务端：拿玩家用 exports.qbx_core:GetPlayer(source)
-- 或 lib.callback / RegisterNetEvent 配合

RegisterNetEvent('{{name}}:server:greet', function()
    local src = source
    local player = exports.qbx_core:GetPlayer(src)
    if not player then return end
    TriggerClientEvent(
        '{{name}}:client:hello',
        src,
        ('Hello, %s'):format(player.PlayerData.charinfo.firstname or 'mate')
    )
end)
""",
        ),
        ScaffoldFile(
            path="README.md",
            content=_readme(
                "qbox-basic",
                """- 在 `client/main.lua` 用 `lib.notify / lib.callback / lib.requestModel`
- 在 `server/main.lua` 用 `exports.qbx_core:GetPlayer(source)` 拿玩家
- 加可使用物品：在 `ox_inventory/data/items.lua` 给物品配 `server.export = '{{name}}.use_xxx'`，然后 export 同名函数
""",
            ),
        ),
    ],
)


# ============================================================
# qbcore-job · 职业模板
# ============================================================


_QBCORE_JOB = ScaffoldPreset(
    key="qbcore-job",
    label="QBCore 职业模板（含 NPC 对话）",
    description="QBCore + ox_lib + ox_inventory，含 boss NPC + 工作开关",
    framework=Framework.QBCORE,
    inventory=InventoryKind.OX_INVENTORY,
    target=TargetKind.OX_TARGET,
    files=[
        ScaffoldFile(
            path="fxmanifest.lua",
            content="""\
fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name '{{name}}'
description '{{description}}'
author '{{author}}'
version '{{version}}'

shared_scripts {
    '@ox_lib/init.lua',
    'shared/config.lua',
}

client_scripts {
    'client/main.lua',
    'client/npc.lua',
}

server_scripts {
    '@oxmysql/lib/MySQL.lua',
    'server/main.lua',
}

dependencies {
    'qb-core',
    'ox_lib',
    'ox_inventory',
    'ox_target',
}
""",
        ),
        ScaffoldFile(
            path="shared/config.lua",
            content="""\
Config = Config or {}

Config.JobName = '{{name}}'

-- Boss NPC（接活人）位置
Config.BossNpc = {
    model = `a_m_y_business_01`,
    coords = vec4(215.0, -810.0, 30.7, 90.0),
    scenario = 'WORLD_HUMAN_CLIPBOARD',
}

-- 任务点（示意）
Config.JobLocations = {
    vec3(220.0, -800.0, 30.7),
    vec3(225.0, -795.0, 30.7),
}
""",
        ),
        ScaffoldFile(
            path="client/main.lua",
            content="""\
local QBCore = exports['qb-core']:GetCoreObject()

local OnDuty = false

RegisterNetEvent('{{name}}:client:toggleDuty', function()
    OnDuty = not OnDuty
    lib.notify({
        title = '{{name}}',
        description = OnDuty and '已上班' or '已下班',
        type = OnDuty and 'success' or 'inform',
    })
end)

-- 给上级用：查询是否在班
exports('isOnDuty', function() return OnDuty end)
""",
        ),
        ScaffoldFile(
            path="client/npc.lua",
            content="""\
-- Boss NPC：用 ox_target 加交互菜单

local SpawnedPed

local function spawnBoss()
    local model = Config.BossNpc.model
    if not lib.requestModel(model, 10000) then return end
    local c = Config.BossNpc.coords
    SpawnedPed = CreatePed(4, model, c.x, c.y, c.z, c.w, false, true)
    SetEntityAsMissionEntity(SpawnedPed, true, true)
    SetBlockingOfNonTemporaryEvents(SpawnedPed, true)
    SetEntityInvincible(SpawnedPed, true)
    FreezeEntityPosition(SpawnedPed, true)
    TaskStartScenarioInPlace(SpawnedPed, Config.BossNpc.scenario, 0, true)
    SetModelAsNoLongerNeeded(model)

    exports.ox_target:addLocalEntity(SpawnedPed, {
        {
            name = '{{name}}_toggle_duty',
            icon = 'fa-solid fa-clock',
            label = '打卡',
            onSelect = function()
                TriggerServerEvent('{{name}}:server:toggleDuty')
            end,
        },
    })
end

AddEventHandler('onResourceStop', function(res)
    if res ~= GetCurrentResourceName() then return end
    if SpawnedPed and DoesEntityExist(SpawnedPed) then
        DeletePed(SpawnedPed)
    end
end)

CreateThread(spawnBoss)
""",
        ),
        ScaffoldFile(
            path="server/main.lua",
            content="""\
local QBCore = exports['qb-core']:GetCoreObject()

RegisterNetEvent('{{name}}:server:toggleDuty', function()
    local src = source
    local Player = QBCore.Functions.GetPlayer(src)
    if not Player then return end
    if Player.PlayerData.job.name ~= Config.JobName then
        TriggerClientEvent('QBCore:Notify', src, '你不是 ' .. Config.JobName .. ' 的成员', 'error')
        return
    end
    TriggerClientEvent('{{name}}:client:toggleDuty', src)
end)
""",
        ),
        ScaffoldFile(
            path="README.md",
            content=_readme(
                "qbcore-job",
                """- 在 `qb-core/shared/jobs.lua` 加这份职业（与 `Config.JobName` 一致）
- 修改 `shared/config.lua` 里的 NPC 坐标 / 任务点
- 加自己的活儿：监听 ox_target 选项 → server event 校验 → 给奖励
- ox_inventory 物品奖励：`exports.ox_inventory:AddItem(src, 'item_name', 1)`
""",
            ),
        ),
    ],
)


# ============================================================
# qbox-job · QBox 职业模板
# ============================================================


_QBOX_JOB = ScaffoldPreset(
    key="qbox-job",
    label="QBox 职业模板（含 NPC 对话）",
    description="QBox + ox 全家桶，含 boss NPC + 工作开关",
    framework=Framework.QBOX,
    inventory=InventoryKind.OX_INVENTORY,
    target=TargetKind.OX_TARGET,
    files=[
        ScaffoldFile(
            path="fxmanifest.lua",
            content="""\
fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name '{{name}}'
description '{{description}}'
author '{{author}}'
version '{{version}}'

shared_scripts {
    '@ox_lib/init.lua',
    'shared/config.lua',
}

client_scripts {
    'client/main.lua',
    'client/npc.lua',
}

server_scripts {
    '@oxmysql/lib/MySQL.lua',
    'server/main.lua',
}

dependencies {
    'qbx_core',
    'ox_lib',
    'ox_inventory',
    'ox_target',
}
""",
        ),
        ScaffoldFile(
            path="shared/config.lua",
            content="""\
Config = Config or {}

Config.JobName = '{{name}}'

Config.BossNpc = {
    model = `a_m_y_business_01`,
    coords = vec4(215.0, -810.0, 30.7, 90.0),
    scenario = 'WORLD_HUMAN_CLIPBOARD',
}
""",
        ),
        ScaffoldFile(
            path="client/main.lua",
            content="""\
local OnDuty = false

RegisterNetEvent('{{name}}:client:toggleDuty', function()
    OnDuty = not OnDuty
    lib.notify({
        title = '{{name}}',
        description = OnDuty and '已上班' or '已下班',
        type = OnDuty and 'success' or 'inform',
    })
end)

exports('isOnDuty', function() return OnDuty end)
""",
        ),
        ScaffoldFile(
            path="client/npc.lua",
            content="""\
local SpawnedPed

local function spawnBoss()
    local model = Config.BossNpc.model
    if not lib.requestModel(model, 10000) then return end
    local c = Config.BossNpc.coords
    SpawnedPed = CreatePed(4, model, c.x, c.y, c.z, c.w, false, true)
    SetEntityAsMissionEntity(SpawnedPed, true, true)
    SetBlockingOfNonTemporaryEvents(SpawnedPed, true)
    SetEntityInvincible(SpawnedPed, true)
    FreezeEntityPosition(SpawnedPed, true)
    TaskStartScenarioInPlace(SpawnedPed, Config.BossNpc.scenario, 0, true)
    SetModelAsNoLongerNeeded(model)

    exports.ox_target:addLocalEntity(SpawnedPed, {
        {
            name = '{{name}}_toggle_duty',
            icon = 'fa-solid fa-clock',
            label = '打卡',
            onSelect = function()
                TriggerServerEvent('{{name}}:server:toggleDuty')
            end,
        },
    })
end

AddEventHandler('onResourceStop', function(res)
    if res ~= GetCurrentResourceName() then return end
    if SpawnedPed and DoesEntityExist(SpawnedPed) then
        DeletePed(SpawnedPed)
    end
end)

CreateThread(spawnBoss)
""",
        ),
        ScaffoldFile(
            path="server/main.lua",
            content="""\
RegisterNetEvent('{{name}}:server:toggleDuty', function()
    local src = source
    local player = exports.qbx_core:GetPlayer(src)
    if not player then return end
    if player.PlayerData.job.name ~= Config.JobName then
        lib.notify({
            target = src,
            title = '{{name}}',
            description = '你不是 ' .. Config.JobName,
            type = 'error',
        })
        return
    end
    TriggerClientEvent('{{name}}:client:toggleDuty', src)
end)
""",
        ),
        ScaffoldFile(
            path="README.md",
            content=_readme(
                "qbox-job",
                """- 把职业加到 `qbx_core/shared/jobs.lua`
- 修改 `shared/config.lua` 里的 NPC 坐标
- ox_inventory 物品操作：`exports.ox_inventory:AddItem(src, 'item', 1)`
- ox_lib UI：`lib.registerContext` / `lib.callback.register` / `lib.notify`
""",
            ),
        ),
    ],
)


# ============================================================
# ox-target-npc · standalone NPC 对话
# ============================================================


_OX_TARGET_NPC = ScaffoldPreset(
    key="ox-target-npc",
    label="OX 全家桶 NPC 对话（standalone）",
    description="不依赖 framework，只靠 ox_lib + ox_target 做对话 NPC",
    framework=Framework.STANDALONE,
    inventory=InventoryKind.OX_INVENTORY,
    target=TargetKind.OX_TARGET,
    files=[
        ScaffoldFile(
            path="fxmanifest.lua",
            content="""\
fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name '{{name}}'
description '{{description}}'
author '{{author}}'
version '{{version}}'

shared_scripts {
    '@ox_lib/init.lua',
    'shared/config.lua',
    'shared/dialogues.lua',
}

client_scripts {
    'client/main.lua',
}

dependencies {
    'ox_lib',
    'ox_target',
}
""",
        ),
        ScaffoldFile(
            path="shared/config.lua",
            content="""\
Config = Config or {}

Config.Npcs = {
    {
        id = 'merchant_a',
        model = `a_m_y_business_01`,
        coords = vec4(215.0, -810.0, 30.7, 90.0),
        scenario = 'WORLD_HUMAN_CLIPBOARD',
        dialogue = 'merchant_a',
        label = '搭话',
    },
}
""",
        ),
        ScaffoldFile(
            path="shared/dialogues.lua",
            content="""\
-- 对话树。运行时不调 LLM，纯查表。
Dialogues = {
    merchant_a = {
        start = 'greeting',
        nodes = {
            greeting = {
                text = '客官，今儿想看点啥？',
                choices = {
                    { label = '随便看看', goto = 'browse' },
                    { label = '走了',     goto = 'leave' },
                },
            },
            browse = {
                text = '慢慢看～',
                choices = {
                    { label = '买杯咖啡（$3）', goto = 'buy_coffee' },
                    { label = '不了',          goto = 'leave' },
                },
            },
            buy_coffee = {
                text = '收您 3 块。',
                action = { kind = 'give_item', item = 'coffee', qty = 1, price = 3 },
                goto = 'leave',
            },
            leave = { text = '欢迎下次再来。', terminal = true },
        },
    },
}
""",
        ),
        ScaffoldFile(
            path="client/main.lua",
            content="""\
local SpawnedPeds = {}

local function spawnOne(npc)
    if not lib.requestModel(npc.model, 10000) then return end
    local p = CreatePed(4, npc.model, npc.coords.x, npc.coords.y, npc.coords.z, npc.coords.w, false, true)
    SetEntityAsMissionEntity(p, true, true)
    SetBlockingOfNonTemporaryEvents(p, true)
    SetEntityInvincible(p, true)
    FreezeEntityPosition(p, true)
    TaskStartScenarioInPlace(p, npc.scenario, 0, true)
    SetModelAsNoLongerNeeded(npc.model)
    SpawnedPeds[#SpawnedPeds + 1] = p

    exports.ox_target:addLocalEntity(p, {
        {
            name = '{{name}}_' .. npc.id,
            icon = 'fa-solid fa-comment',
            label = npc.label,
            onSelect = function() runDialogue(npc.dialogue) end,
        },
    })
end

function runDialogue(dialogueId)
    local tree = Dialogues[dialogueId]
    if not tree then return end
    local node = tree.nodes[tree.start]
    while node do
        if node.terminal then
            lib.alertDialog({ header = '', content = node.text })
            return
        end
        local choices = {}
        for i, c in ipairs(node.choices or {}) do
            choices[#choices + 1] = { label = c.label, value = i }
        end
        local picked = lib.inputDialog(node.text, {
            { type = 'select', label = '选择', options = choices, required = true },
        })
        if not picked then return end
        local choice = node.choices[picked[1]]
        if choice.action then
            TriggerServerEvent('{{name}}:server:dialogueAction', dialogueId, choice.action)
        end
        node = tree.nodes[choice.goto]
    end
end

AddEventHandler('onResourceStop', function(res)
    if res ~= GetCurrentResourceName() then return end
    for _, p in ipairs(SpawnedPeds) do
        if DoesEntityExist(p) then DeletePed(p) end
    end
end)

CreateThread(function()
    for _, npc in ipairs(Config.Npcs) do spawnOne(npc) end
end)
""",
        ),
        ScaffoldFile(
            path="README.md",
            content=_readme(
                "ox-target-npc",
                """- 在 `shared/config.lua` 加更多 NPC（model + coords + dialogue）
- 在 `shared/dialogues.lua` 写对话树（节点 + 选项 + action）
- 服务端没自带——需要 framework 集成时（如发物品/扣钱），自己加 `server/main.lua` 监听 `{{name}}:server:dialogueAction`
- 这是离线生成的对话树，运行时**不调 LLM**——速度快、零成本
""",
            ),
        ),
    ],
)


# ============================================================
# esx-basic
# ============================================================


_ESX_BASIC = ScaffoldPreset(
    key="esx-basic",
    label="ESX 最小骨架",
    description="ESX 框架下的最小 client + server resource 骨架",
    framework=Framework.ESX,
    inventory=InventoryKind.ESX_INVENTORY,
    target=TargetKind.NONE,
    files=[
        ScaffoldFile(
            path="fxmanifest.lua",
            content="""\
fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name '{{name}}'
description '{{description}}'
author '{{author}}'
version '{{version}}'

shared_scripts {
    '@es_extended/imports.lua',
    'shared/config.lua',
}

client_scripts {
    'client/main.lua',
}

server_scripts {
    'server/main.lua',
}

dependencies {
    'es_extended',
}
""",
        ),
        ScaffoldFile(
            path="shared/config.lua",
            content="""\
Config = Config or {}
Config.Debug = false
""",
        ),
        ScaffoldFile(
            path="client/main.lua",
            content="""\
ESX = exports['es_extended']:getSharedObject()

CreateThread(function()
    while ESX.GetPlayerData().job == nil do Wait(100) end
    if Config.Debug then
        print('[{{name}}] client ready, job=' .. ESX.GetPlayerData().job.name)
    end
end)

RegisterNetEvent('{{name}}:client:hello', function(message)
    ESX.ShowNotification(message)
end)
""",
        ),
        ScaffoldFile(
            path="server/main.lua",
            content="""\
ESX = exports['es_extended']:getSharedObject()

RegisterNetEvent('{{name}}:server:greet', function()
    local src = source
    local xPlayer = ESX.GetPlayerFromId(src)
    if not xPlayer then return end
    TriggerClientEvent(
        '{{name}}:client:hello',
        src,
        ('Hello, %s'):format(xPlayer.getName())
    )
end)
""",
        ),
        ScaffoldFile(
            path="README.md",
            content=_readme(
                "esx-basic",
                """- 客户端用 `ESX.GetPlayerData()` / `ESX.ShowNotification`
- 服务端用 `ESX.GetPlayerFromId(source)` / `xPlayer.addInventoryItem`
- 物品系统看你装的是哪家：esx_inventoryhud / esx_inventory / ox_inventory
""",
            ),
        ),
    ],
)


# ============================================================
# 注册表
# ============================================================


SCAFFOLD_PRESETS: dict[str, ScaffoldPreset] = {
    p.key: p
    for p in [
        _QBCORE_BASIC,
        _QBOX_BASIC,
        _QBCORE_JOB,
        _QBOX_JOB,
        _OX_TARGET_NPC,
        _ESX_BASIC,
    ]
}


__all__ = ["SCAFFOLD_PRESETS", "ScaffoldFile", "ScaffoldPreset"]
