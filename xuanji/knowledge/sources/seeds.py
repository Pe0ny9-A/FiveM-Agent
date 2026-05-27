"""FiveM 种子知识库。

M1 阶段先用手写 API 卡片解决最常见的开发查询。M2+ 接爬虫 + 增量更新。
所有内容标 [seed]，避免与未来爬虫导入的版本化文档混淆。

注意：以下卡片的 signature/examples 来自姐姐对 QBCore / ox_lib / FiveM
公开文档的整理，可能与小宝实际使用的 fork 版本不一致——使用前以工程内
源码（`fxmanifest.lua` 锁定的 git tag）为准。
"""

from __future__ import annotations

from xuanji.knowledge.models import Chunk, Source, Symbol

NS_QBCORE = "fivem.qbcore@1.x"
NS_OX_LIB = "fivem.ox_lib@3.x"
NS_OX_INVENTORY = "fivem.ox_inventory@2.x"
NS_FIVEM_CFX = "fivem.cfx@latest"
NS_NPC_AI = "fivem.npc_ai@1.x"
NS_QBOX = "fivem.qbox@main"
NS_ESX = "fivem.esx@1.13"
NS_OXMYSQL = "fivem.oxmysql@2.x"
NS_NATIVES = "fivem.natives@latest"


def seed_sources() -> list[Source]:
    return [
        Source(
            namespace=NS_QBCORE,
            title="QBCore Framework 速查",
            url="https://docs.qbcore.org/qbcore-documentation/",
            version="1.x",
            metadata={"kind": "framework", "lang": "lua"},
        ),
        Source(
            namespace=NS_OX_LIB,
            title="ox_lib 速查",
            url="https://overextended.dev/ox_lib",
            version="3.x",
            metadata={"kind": "library", "lang": "lua"},
        ),
        Source(
            namespace=NS_OX_INVENTORY,
            title="ox_inventory 速查",
            url="https://overextended.dev/ox_inventory",
            version="2.x",
            metadata={"kind": "resource", "lang": "lua"},
        ),
        Source(
            namespace=NS_FIVEM_CFX,
            title="FiveM 资源开发约定",
            url="https://docs.fivem.net/docs/scripting-reference/",
            version="latest",
            metadata={"kind": "platform", "lang": "lua"},
        ),
        Source(
            namespace=NS_NPC_AI,
            title="FiveM NPC 插件开发速查",
            url="https://docs.fivem.net/natives/?_PED",
            version="1.x",
            metadata={"kind": "patterns", "lang": "lua", "topic": "npc_ai"},
        ),
        Source(
            namespace=NS_QBOX,
            title="QBox（QBCore 现代分支）速查",
            url="https://docs.qbox.re/",
            version="main",
            metadata={"kind": "framework", "lang": "lua", "based_on": "qbcore"},
        ),
        Source(
            namespace=NS_ESX,
            title="ESX Legacy 速查",
            url="https://documentation.esx-framework.org/",
            version="1.13",
            metadata={"kind": "framework", "lang": "lua"},
        ),
        Source(
            namespace=NS_OXMYSQL,
            title="oxmysql 速查",
            url="https://overextended.dev/oxmysql",
            version="2.x",
            metadata={"kind": "database", "lang": "lua"},
        ),
        Source(
            namespace=NS_NATIVES,
            title="FiveM Natives 高频速查",
            url="https://docs.fivem.net/natives/",
            version="latest",
            metadata={"kind": "platform", "lang": "lua"},
        ),
    ]


def seed_symbols() -> list[Symbol]:
    return [
        # ---------- QBCore ----------
        Symbol(
            id=f"{NS_QBCORE}::QBCore.Functions.GetPlayer",
            namespace=NS_QBCORE,
            name="QBCore.Functions.GetPlayer",
            kind="function",
            side="server",
            signature="QBCore.Functions.GetPlayer(source) -> Player",
            summary="服务端通过玩家 source（server id）取 Player 对象，含 PlayerData 与方法集合。",
            params=[{"name": "source", "type": "number", "desc": "玩家 server id"}],
            returns="Player（含 PlayerData / Functions / Offline 等）；不存在时返回 nil",
            example=(
                "RegisterNetEvent('myresource:server:UseItem', function()\n"
                "    local src = source\n"
                "    local Player = QBCore.Functions.GetPlayer(src)\n"
                "    if not Player then return end\n"
                "    Player.Functions.RemoveItem('water', 1)\n"
                "end)"
            ),
        ),
        Symbol(
            id=f"{NS_QBCORE}::QBCore.Functions.CreateUseableItem",
            namespace=NS_QBCORE,
            name="QBCore.Functions.CreateUseableItem",
            kind="function",
            side="server",
            signature="QBCore.Functions.CreateUseableItem(itemName, callback)",
            summary="把一个物品注册为可使用物品；玩家在背包点使用时会触发回调。",
            params=[
                {"name": "itemName", "type": "string", "desc": "物品名（必须存在于 items 表）"},
                {"name": "callback", "type": "function(source, item)", "desc": "使用时调用"},
            ],
            example=(
                "QBCore.Functions.CreateUseableItem('water', function(source, item)\n"
                "    local Player = QBCore.Functions.GetPlayer(source)\n"
                "    if not Player then return end\n"
                "    TriggerClientEvent('consumables:client:Drink', source)\n"
                "    Player.Functions.RemoveItem('water', 1)\n"
                "end)"
            ),
        ),
        Symbol(
            id=f"{NS_QBCORE}::Player.Functions.AddItem",
            namespace=NS_QBCORE,
            name="Player.Functions.AddItem",
            kind="function",
            side="server",
            signature="Player.Functions.AddItem(item, amount, slot, info) -> boolean",
            summary="给玩家背包加物品。返回是否成功（如背包满则返回 false）。",
            params=[
                {"name": "item", "type": "string", "desc": "物品名"},
                {"name": "amount", "type": "number", "desc": "数量"},
                {"name": "slot", "type": "number?", "desc": "可选指定槽位"},
                {"name": "info", "type": "table?", "desc": "可选元数据"},
            ],
            example="Player.Functions.AddItem('phone', 1, nil, {serial = 12345})",
        ),
        Symbol(
            id=f"{NS_QBCORE}::Player.Functions.RemoveItem",
            namespace=NS_QBCORE,
            name="Player.Functions.RemoveItem",
            kind="function",
            side="server",
            signature="Player.Functions.RemoveItem(item, amount, slot) -> boolean",
            summary="从玩家背包扣除物品。",
            params=[
                {"name": "item", "type": "string", "desc": "物品名"},
                {"name": "amount", "type": "number", "desc": "数量"},
                {"name": "slot", "type": "number?", "desc": "可选指定槽位"},
            ],
        ),
        Symbol(
            id=f"{NS_QBCORE}::QBCore.Functions.GetPlayerData",
            namespace=NS_QBCORE,
            name="QBCore.Functions.GetPlayerData",
            kind="function",
            side="client",
            signature="QBCore.Functions.GetPlayerData() -> table",
            summary="客户端取当前玩家的 PlayerData 副本。",
            example="local PlayerData = QBCore.Functions.GetPlayerData()",
        ),
        Symbol(
            id=f"{NS_QBCORE}::QBCore.Functions.Notify",
            namespace=NS_QBCORE,
            name="QBCore.Functions.Notify",
            kind="function",
            side="any",
            signature="QBCore.Functions.Notify(text, type, length)",
            summary="弹通知。客户端直接调；服务端可 TriggerClientEvent('QBCore:Notify', src, ...)。",
            params=[
                {"name": "text", "type": "string"},
                {"name": "type", "type": "'success'|'error'|'primary'", "desc": "默认 primary"},
                {"name": "length", "type": "number", "desc": "毫秒，默认 5000"},
            ],
        ),
        # ---------- ox_lib ----------
        Symbol(
            id=f"{NS_OX_LIB}::lib.callback.register",
            namespace=NS_OX_LIB,
            name="lib.callback.register",
            kind="function",
            side="server",
            signature="lib.callback.register(name, fn)",
            summary="注册一个可被 client 端 lib.callback.await 调用的服务端 callback。",
            params=[
                {"name": "name", "type": "string", "desc": "callback 名（建议 resource:scope:action）"},
                {"name": "fn", "type": "function(source, ...)", "desc": "处理函数；返回值会被 await 拿到"},
            ],
            example=(
                "-- server\n"
                "lib.callback.register('myres:getMoney', function(source)\n"
                "    local Player = QBCore.Functions.GetPlayer(source)\n"
                "    return Player and Player.PlayerData.money.cash or 0\n"
                "end)\n"
                "\n"
                "-- client\n"
                "local cash = lib.callback.await('myres:getMoney', false)\n"
            ),
        ),
        Symbol(
            id=f"{NS_OX_LIB}::lib.notify",
            namespace=NS_OX_LIB,
            name="lib.notify",
            kind="function",
            side="any",
            signature="lib.notify(data)",
            summary="ox_lib 自带通知。客户端可直接调；服务端用 TriggerClientEvent('ox_lib:notify', src, data)。",
            params=[
                {"name": "data.title", "type": "string?"},
                {"name": "data.description", "type": "string?"},
                {"name": "data.type", "type": "'success'|'error'|'inform'|'warning'?"},
                {"name": "data.position", "type": "string?", "desc": "默认 top-right"},
                {"name": "data.duration", "type": "number?", "desc": "毫秒"},
            ],
        ),
        Symbol(
            id=f"{NS_OX_LIB}::lib.registerContext",
            namespace=NS_OX_LIB,
            name="lib.registerContext",
            kind="function",
            side="client",
            signature="lib.registerContext(context)",
            summary="注册一个上下文菜单（替代古早的 NUI 自写菜单）。",
            params=[
                {"name": "context.id", "type": "string"},
                {"name": "context.title", "type": "string"},
                {"name": "context.options", "type": "Option[]", "desc": "见 ox_lib 文档"},
            ],
            example=(
                "lib.registerContext({\n"
                "    id = 'main_menu',\n"
                "    title = '玄玑测试菜单',\n"
                "    options = {\n"
                "        { title = '通知一下', icon = 'bell',\n"
                "          onSelect = function() lib.notify({ title = '叮咚' }) end },\n"
                "    },\n"
                "})\n"
                "lib.showContext('main_menu')"
            ),
        ),
        Symbol(
            id=f"{NS_OX_LIB}::lib.requestModel",
            namespace=NS_OX_LIB,
            name="lib.requestModel",
            kind="function",
            side="client",
            signature="lib.requestModel(model, timeout?) -> hash",
            summary="封装好的模型请求；超时返回 nil，避免老式 RequestModel 死循环。",
            params=[
                {"name": "model", "type": "string|number"},
                {"name": "timeout", "type": "number?", "desc": "毫秒，默认 10000"},
            ],
        ),
        # ---------- ox_inventory ----------
        Symbol(
            id=f"{NS_OX_INVENTORY}::exports.ox_inventory:AddItem",
            namespace=NS_OX_INVENTORY,
            name="exports.ox_inventory:AddItem",
            kind="export",
            side="server",
            signature="exports.ox_inventory:AddItem(inventory, item, count, metadata, slot) -> boolean, string?",
            summary="给指定 inventory 加物品。inventory 通常是 source 或 stash id。",
            params=[
                {"name": "inventory", "type": "number|string"},
                {"name": "item", "type": "string"},
                {"name": "count", "type": "number"},
                {"name": "metadata", "type": "table?"},
                {"name": "slot", "type": "number?"},
            ],
        ),
        # ---------- FiveM platform ----------
        Symbol(
            id=f"{NS_FIVEM_CFX}::fxmanifest.lua",
            namespace=NS_FIVEM_CFX,
            name="fxmanifest.lua",
            kind="module",
            side="any",
            summary="资源清单。每个 resource 必备，定义 fx_version、game、依赖、脚本入口。",
            example=(
                "fx_version 'cerulean'\n"
                "game 'gta5'\n"
                "lua54 'yes'\n"
                "\n"
                "shared_scripts { '@ox_lib/init.lua' }\n"
                "client_scripts { 'client/*.lua' }\n"
                "server_scripts { 'server/*.lua' }\n"
                "\n"
                "dependencies { 'qb-core', 'ox_lib' }"
            ),
        ),
        # ---------- NPC AI · ped natives ----------
        Symbol(
            id=f"{NS_NPC_AI}::CreatePed",
            namespace=NS_NPC_AI,
            name="CreatePed",
            kind="native",
            side="client",
            signature=(
                "CreatePed(pedType, modelHash, x, y, z, heading, "
                "isNetwork, bScriptHostPed) -> Ped"
            ),
            summary=(
                "在指定坐标创建一个 ped。模型必须先 RequestModel 加载完成。"
                "isNetwork=true 才会同步给其他玩家；bScriptHostPed=true 让本机当宿主。"
            ),
            params=[
                {"name": "pedType", "type": "number", "desc": "ped 类别，常用 4 = CIVMALE / 5 = CIVFEMALE"},
                {"name": "modelHash", "type": "Hash"},
                {"name": "x/y/z", "type": "number", "desc": "世界坐标"},
                {"name": "heading", "type": "number", "desc": "朝向角度"},
                {"name": "isNetwork", "type": "boolean"},
                {"name": "bScriptHostPed", "type": "boolean"},
            ],
            example=(
                "local model = `a_m_y_business_01`  -- Lua 5.4 hash 字面量\n"
                "lib.requestModel(model)\n"
                "local ped = CreatePed(4, model, 215.0, -810.0, 30.7, 90.0, false, true)\n"
                "SetEntityAsMissionEntity(ped, true, true)\n"
                "SetBlockingOfNonTemporaryEvents(ped, true)\n"
                "FreezeEntityPosition(ped, true)\n"
                "SetModelAsNoLongerNeeded(model)"
            ),
        ),
        Symbol(
            id=f"{NS_NPC_AI}::TaskWanderStandard",
            namespace=NS_NPC_AI,
            name="TaskWanderStandard",
            kind="native",
            side="client",
            signature="TaskWanderStandard(ped, p1, p2)",
            summary=(
                "让 ped 在当前点附近随机游荡（默认半径约 100m）。"
                "最常用的 NPC 巡逻起点，进入战斗/对话时记得 ClearPedTasks。"
            ),
            params=[
                {"name": "ped", "type": "Ped"},
                {"name": "p1", "type": "number", "desc": "通常 10.0"},
                {"name": "p2", "type": "number", "desc": "通常 10"},
            ],
            example="TaskWanderStandard(ped, 10.0, 10)",
        ),
        Symbol(
            id=f"{NS_NPC_AI}::TaskGoToCoordAnyMeans",
            namespace=NS_NPC_AI,
            name="TaskGoToCoordAnyMeans",
            kind="native",
            side="client",
            signature=(
                "TaskGoToCoordAnyMeans(ped, x, y, z, speed, p5, p6, walkingStyle, p8)"
            ),
            summary=(
                "让 ped 想办法走到目标坐标（步行、跑、必要时上车）。"
                "做巡逻路径时按巡逻点序列循环调用即可。"
            ),
            params=[
                {"name": "ped", "type": "Ped"},
                {"name": "x/y/z", "type": "number"},
                {"name": "speed", "type": "number", "desc": "1.0 走 / 2.0 跑"},
                {"name": "walkingStyle", "type": "number", "desc": "通常 786603"},
            ],
        ),
        Symbol(
            id=f"{NS_NPC_AI}::TaskStartScenarioInPlace",
            namespace=NS_NPC_AI,
            name="TaskStartScenarioInPlace",
            kind="native",
            side="client",
            signature="TaskStartScenarioInPlace(ped, scenarioName, unkDelay, playEnterAnim)",
            summary=(
                "让 ped 在原地播放一个内置场景动画（喝咖啡、用手机、看报纸……）。"
                "做静态 NPC 用最方便。"
            ),
            params=[
                {"name": "scenarioName", "type": "string", "desc": "如 'WORLD_HUMAN_AA_COFFEE' / 'WORLD_HUMAN_CLIPBOARD'"},
                {"name": "unkDelay", "type": "number", "desc": "通常 0"},
                {"name": "playEnterAnim", "type": "boolean", "desc": "通常 true"},
            ],
            example="TaskStartScenarioInPlace(ped, 'WORLD_HUMAN_CLIPBOARD', 0, true)",
        ),
        Symbol(
            id=f"{NS_NPC_AI}::SetBlockingOfNonTemporaryEvents",
            namespace=NS_NPC_AI,
            name="SetBlockingOfNonTemporaryEvents",
            kind="native",
            side="client",
            signature="SetBlockingOfNonTemporaryEvents(ped, toggle)",
            summary=(
                "屏蔽非临时事件。NPC 不会因为旁边打架/枪声/车祸而中断当前任务。"
                "做剧情 NPC、商人 NPC 时几乎必加。"
            ),
            example="SetBlockingOfNonTemporaryEvents(ped, true)",
        ),
        Symbol(
            id=f"{NS_NPC_AI}::ClearPedTasks",
            namespace=NS_NPC_AI,
            name="ClearPedTasks",
            kind="native",
            side="client",
            signature="ClearPedTasks(ped)",
            summary="清空 ped 当前任务队列。状态切换前调用，避免新旧任务打架。",
        ),
        Symbol(
            id=f"{NS_NPC_AI}::DeletePed",
            namespace=NS_NPC_AI,
            name="DeletePed",
            kind="native",
            side="client",
            signature="DeletePed(ped)",
            summary=(
                "删除 ped。需要先 SetEntityAsMissionEntity 拿到所有权才能可靠删除，"
                "且参数要传 ped 的指针（Lua 用 local ref = ped; DeletePed(ref)）。"
            ),
            example=(
                "SetEntityAsMissionEntity(ped, true, true)\n"
                "DeletePed(ped)\n"
                "ped = nil"
            ),
        ),
        # ---------- NPC AI · ox_target 交互 ----------
        Symbol(
            id=f"{NS_NPC_AI}::exports.ox_target:addLocalEntity",
            namespace=NS_NPC_AI,
            name="exports.ox_target:addLocalEntity",
            kind="export",
            side="client",
            signature="exports.ox_target:addLocalEntity(entityIds, options)",
            summary=(
                "给本地（非网络）ped 加 ox_target 交互菜单——做对话 NPC 的标准做法。"
                "options 是数组，每项含 name / icon / label / onSelect。"
            ),
            example=(
                "exports.ox_target:addLocalEntity(ped, {\n"
                "    {\n"
                "        name = 'shop_npc_talk',\n"
                "        icon = 'fa-solid fa-comment',\n"
                "        label = '搭话',\n"
                "        onSelect = function()\n"
                "            TriggerEvent('myshop:client:openDialogue', 'merchant_a')\n"
                "        end,\n"
                "    },\n"
                "})"
            ),
        ),
        Symbol(
            id=f"{NS_NPC_AI}::exports.qb-target:AddTargetEntity",
            namespace=NS_NPC_AI,
            name="exports.qb-target:AddTargetEntity",
            kind="export",
            side="client",
            signature="exports['qb-target']:AddTargetEntity(entity, options)",
            summary=(
                "qb-target 版的等价 API。options.options 数组结构与 ox_target 类似但字段稍异。"
                "用 ox_target 的项目优先走它，QBCore 老项目才用这个。"
            ),
        ),
        # ---------- NPC AI · 模板 ----------
        Symbol(
            id=f"{NS_NPC_AI}::pattern.spawn_static_npc",
            namespace=NS_NPC_AI,
            name="pattern.spawn_static_npc",
            kind="module",
            side="client",
            summary=(
                "标准的「生成一个静止 NPC + 接 ox_target 对话」模板。"
                "封装了 model 加载、坐标朝向、防止被打扰、删除清理。"
            ),
            example=(
                "-- client/npc.lua\n"
                "local CreatePed_ = CreatePed\n"
                "local SpawnedPed\n"
                "\n"
                "local function spawnNPC()\n"
                "    local model = `a_m_y_business_01`\n"
                "    if not lib.requestModel(model, 10000) then return end\n"
                "    SpawnedPed = CreatePed_(4, model, 215.0, -810.0, 30.7, 90.0, false, true)\n"
                "    SetEntityAsMissionEntity(SpawnedPed, true, true)\n"
                "    SetBlockingOfNonTemporaryEvents(SpawnedPed, true)\n"
                "    SetEntityInvincible(SpawnedPed, true)\n"
                "    FreezeEntityPosition(SpawnedPed, true)\n"
                "    TaskStartScenarioInPlace(SpawnedPed, 'WORLD_HUMAN_CLIPBOARD', 0, true)\n"
                "    SetModelAsNoLongerNeeded(model)\n"
                "\n"
                "    exports.ox_target:addLocalEntity(SpawnedPed, {\n"
                "        { name = 'npc_talk', icon = 'fa-solid fa-comment', label = '搭话',\n"
                "          onSelect = function() TriggerEvent('myres:client:openDialogue') end },\n"
                "    })\n"
                "end\n"
                "\n"
                "AddEventHandler('onResourceStop', function(res)\n"
                "    if res ~= GetCurrentResourceName() then return end\n"
                "    if SpawnedPed and DoesEntityExist(SpawnedPed) then\n"
                "        DeletePed(SpawnedPed)\n"
                "    end\n"
                "end)\n"
                "\n"
                "CreateThread(spawnNPC)"
            ),
        ),
        Symbol(
            id=f"{NS_NPC_AI}::pattern.patrol_route",
            namespace=NS_NPC_AI,
            name="pattern.patrol_route",
            kind="module",
            side="client",
            summary=(
                "标准的「巡逻 NPC」模板：按巡逻点列表循环 TaskGoToCoordAnyMeans，"
                "到点等待几秒再去下一点。Wait 用 SetTimeout 而不是 while+busy-wait。"
            ),
            example=(
                "local PATROL_POINTS = {\n"
                "    vec3(215.0, -810.0, 30.7),\n"
                "    vec3(220.5, -805.0, 30.7),\n"
                "    vec3(218.0, -795.0, 30.7),\n"
                "}\n"
                "\n"
                "local function patrol(ped)\n"
                "    local idx = 1\n"
                "    CreateThread(function()\n"
                "        while DoesEntityExist(ped) do\n"
                "            local p = PATROL_POINTS[idx]\n"
                "            TaskGoToCoordAnyMeans(ped, p.x, p.y, p.z, 1.5, 0, false, 786603, 0xbf800000)\n"
                "            -- 等到走到附近再换下一点\n"
                "            while DoesEntityExist(ped)\n"
                "                  and #(GetEntityCoords(ped) - p) > 1.2 do\n"
                "                Wait(500)\n"
                "            end\n"
                "            Wait(math.random(2000, 5000))\n"
                "            idx = (idx % #PATROL_POINTS) + 1\n"
                "        end\n"
                "    end)\n"
                "end"
            ),
        ),
        Symbol(
            id=f"{NS_NPC_AI}::pattern.dialogue_tree",
            namespace=NS_NPC_AI,
            name="pattern.dialogue_tree",
            kind="module",
            side="any",
            summary=(
                "对话树标准结构：节点用 id 索引，每个节点含 text + 多个 choice，"
                "每个 choice 指向下一个 node 或动作（give_item / start_quest 等）。"
                "前端用 ox_lib alertDialog / inputDialog 或 NUI 渲染。"
            ),
            example=(
                "-- shared/dialogues.lua\n"
                "return {\n"
                "    merchant_a = {\n"
                "        start = 'greeting',\n"
                "        nodes = {\n"
                "            greeting = {\n"
                "                text = '客官，今儿想看点啥？',\n"
                "                choices = {\n"
                "                    { label = '来杯咖啡', goto = 'buy_coffee' },\n"
                "                    { label = '随便看看', goto = 'browse' },\n"
                "                    { label = '走了',     goto = 'leave' },\n"
                "                },\n"
                "            },\n"
                "            buy_coffee = {\n"
                "                text = '收您 3 块。',\n"
                "                action = { kind = 'give_item', item = 'coffee', qty = 1, price = 3 },\n"
                "                goto = 'leave',\n"
                "            },\n"
                "            browse = { text = '慢慢看～', goto = 'leave' },\n"
                "            leave  = { text = '欢迎下次再来。', terminal = true },\n"
                "        },\n"
                "    },\n"
                "}"
            ),
        ),
        Symbol(
            id=f"{NS_NPC_AI}::pattern.behavior_state_machine",
            namespace=NS_NPC_AI,
            name="pattern.behavior_state_machine",
            kind="module",
            side="client",
            summary=(
                "NPC 行为状态机标准：state ∈ {idle, patrol, talk, alert, flee}，"
                "transitions 表声明合法转移与触发条件。每个 state 有 enter/exit/tick。"
                "tick 用 SetInterval 而不是 while+Wait(0) 避免吃 CPU。"
            ),
            example=(
                "local States = {\n"
                "    idle = {\n"
                "        enter = function(self) ClearPedTasks(self.ped); TaskStandStill(self.ped, -1) end,\n"
                "        tick  = function(self)\n"
                "            local player = PlayerPedId()\n"
                "            if #(GetEntityCoords(self.ped) - GetEntityCoords(player)) < 5.0 then\n"
                "                self:goto('talk')\n"
                "            end\n"
                "        end,\n"
                "    },\n"
                "    patrol = {\n"
                "        enter = function(self) self.patrol(self.ped) end,\n"
                "    },\n"
                "    talk  = { enter = function(self) ClearPedTasks(self.ped) end },\n"
                "    alert = {\n"
                "        enter = function(self) TaskCombatPed(self.ped, PlayerPedId(), 0, 16) end,\n"
                "    },\n"
                "    flee  = { enter = function(self) TaskSmartFleePed(self.ped, PlayerPedId(), 100.0, -1) end },\n"
                "}\n"
                "\n"
                "function NPC:goto(name)\n"
                "    local cur = States[self.state]\n"
                "    if cur and cur.exit then cur.exit(self) end\n"
                "    self.state = name\n"
                "    local nxt = States[name]\n"
                "    if nxt and nxt.enter then nxt.enter(self) end\n"
                "end"
            ),
        ),
        # ---------- QBox（QBCore 现代分支） ----------
        Symbol(
            id=f"{NS_QBOX}::exports.qbx_core:GetPlayer",
            namespace=NS_QBOX,
            name="exports.qbx_core:GetPlayer",
            kind="export",
            side="server",
            signature="exports.qbx_core:GetPlayer(source) -> Player",
            summary=(
                "QBox 等价于 QBCore.Functions.GetPlayer，但只走 export，"
                "没有全局 QBCore 对象。Player 结构与 QBCore 兼容。"
            ),
            example=(
                "local Player = exports.qbx_core:GetPlayer(source)\n"
                "if not Player then return end\n"
                "exports.ox_inventory:RemoveItem(source, 'water', 1)"
            ),
        ),
        Symbol(
            id=f"{NS_QBOX}::exports.qbx_core:Notify",
            namespace=NS_QBOX,
            name="exports.qbx_core:Notify",
            kind="export",
            side="any",
            signature="exports.qbx_core:Notify(text, type, length)",
            summary=(
                "QBox 通知。客户端直接调；服务端可 TriggerClientEvent。"
                "底层依赖 ox_lib 的 lib.notify，所以参数兼容也兼容 ox_lib 风格。"
            ),
        ),
        Symbol(
            id=f"{NS_QBOX}::exports.qbx_core:CreateUseableItem",
            namespace=NS_QBOX,
            name="exports.qbx_core:CreateUseableItem",
            kind="export",
            side="server",
            signature="exports.qbx_core:CreateUseableItem(itemName, callback)",
            summary=(
                "QBox 注册可使用物品。**用 ox_inventory 时不需要这个**——"
                "在 ox_inventory/data/items.lua 给物品配 server.export 即可。"
                "本 export 只在 QBox 配合 qb-inventory 时才用。"
            ),
        ),
        Symbol(
            id=f"{NS_QBOX}::exports.qbx_core:GetPlayerCharInfo",
            namespace=NS_QBOX,
            name="exports.qbx_core:GetPlayerCharInfo",
            kind="export",
            side="server",
            signature="exports.qbx_core:GetPlayerCharInfo(source) -> table",
            summary="只取 charinfo（姓名/出生日期/性别/电话/账户），比 GetPlayer 轻。",
        ),
        # ---------- ESX Legacy ----------
        Symbol(
            id=f"{NS_ESX}::ESX.GetPlayerFromId",
            namespace=NS_ESX,
            name="ESX.GetPlayerFromId",
            kind="function",
            side="server",
            signature="ESX.GetPlayerFromId(source) -> xPlayer",
            summary=(
                "ESX 服务端通过 source 取 xPlayer 对象，含 identifier / job / "
                "money / accounts / inventory（旧版）等字段与方法集合。"
            ),
            example=(
                "RegisterNetEvent('myresource:server:UseItem', function()\n"
                "    local src = source\n"
                "    local xPlayer = ESX.GetPlayerFromId(src)\n"
                "    if not xPlayer then return end\n"
                "    xPlayer.removeInventoryItem('water', 1)\n"
                "end)"
            ),
        ),
        Symbol(
            id=f"{NS_ESX}::ESX.RegisterUsableItem",
            namespace=NS_ESX,
            name="ESX.RegisterUsableItem",
            kind="function",
            side="server",
            signature="ESX.RegisterUsableItem(item, callback)",
            summary=(
                "ESX 把物品注册为可使用——QBCore.Functions.CreateUseableItem 的 ESX 等价。"
                "用 ox_inventory 替代 ESX 默认背包时不需要这个。"
            ),
            example=(
                "ESX.RegisterUsableItem('water', function(source)\n"
                "    local xPlayer = ESX.GetPlayerFromId(source)\n"
                "    if not xPlayer then return end\n"
                "    xPlayer.removeInventoryItem('water', 1)\n"
                "    TriggerClientEvent('consumables:client:Drink', source)\n"
                "end)"
            ),
        ),
        Symbol(
            id=f"{NS_ESX}::xPlayer.addMoney",
            namespace=NS_ESX,
            name="xPlayer.addMoney",
            kind="function",
            side="server",
            signature="xPlayer.addMoney(amount)",
            summary="给 xPlayer 加现金（money 账户）。返回 nil；底层会推送 setAccountMoney 事件。",
        ),
        Symbol(
            id=f"{NS_ESX}::xPlayer.addAccountMoney",
            namespace=NS_ESX,
            name="xPlayer.addAccountMoney",
            kind="function",
            side="server",
            signature="xPlayer.addAccountMoney(account, amount)",
            summary=(
                "给指定账户加钱：'money' / 'bank' / 'black_money'。"
                "addMoney 是 'money' 的快捷方式。"
            ),
        ),
        Symbol(
            id=f"{NS_ESX}::ESX.RegisterServerCallback",
            namespace=NS_ESX,
            name="ESX.RegisterServerCallback",
            kind="function",
            side="server",
            signature="ESX.RegisterServerCallback(name, fn)",
            summary=(
                "ESX 旧式 callback。客户端用 ESX.TriggerServerCallback(name, cb, ...) 调。"
                "新代码推荐改用 ox_lib 的 lib.callback——签名更简洁、超时友好。"
            ),
            example=(
                "ESX.RegisterServerCallback('myres:getMoney', function(source, cb)\n"
                "    local xPlayer = ESX.GetPlayerFromId(source)\n"
                "    cb(xPlayer and xPlayer.getMoney() or 0)\n"
                "end)"
            ),
        ),
        Symbol(
            id=f"{NS_ESX}::ESX.ShowNotification",
            namespace=NS_ESX,
            name="ESX.ShowNotification",
            kind="function",
            side="client",
            signature="ESX.ShowNotification(msg, type, length)",
            summary=(
                "ESX 默认通知。type 是字符串如 'success'/'error'/'info'。"
                "现代项目通常切到 lib.notify 或 ox_lib，看着更现代。"
            ),
        ),
        # ---------- oxmysql ----------
        Symbol(
            id=f"{NS_OXMYSQL}::MySQL.query",
            namespace=NS_OXMYSQL,
            name="MySQL.query",
            kind="function",
            side="server",
            signature="MySQL.query(query, params?, cb?) -> rows | nil",
            summary=(
                "执行 SELECT，返回行数组。在协程里直接用返回值（同步式），"
                "外部调用传 cb 也可。**永远用 ? 占位符**，不要字符串拼接 SQL。"
            ),
            params=[
                {"name": "query", "type": "string", "desc": "SQL，必含 ? 占位符"},
                {"name": "params", "type": "table?", "desc": "占位符值数组"},
                {"name": "cb", "type": "function?", "desc": "异步回调，省略则同步"},
            ],
            example=(
                "local rows = MySQL.query.await(\n"
                "    'SELECT citizenid, charinfo FROM players WHERE license = ?',\n"
                "    { license },\n"
                ")\n"
                "for _, r in ipairs(rows) do print(r.citizenid) end"
            ),
        ),
        Symbol(
            id=f"{NS_OXMYSQL}::MySQL.single",
            namespace=NS_OXMYSQL,
            name="MySQL.single",
            kind="function",
            side="server",
            signature="MySQL.single(query, params?, cb?) -> row | nil",
            summary="只取第一行；查不到返回 nil。配合 LIMIT 1 用。",
        ),
        Symbol(
            id=f"{NS_OXMYSQL}::MySQL.scalar",
            namespace=NS_OXMYSQL,
            name="MySQL.scalar",
            kind="function",
            side="server",
            signature="MySQL.scalar(query, params?, cb?) -> value | nil",
            summary="只取第一行第一列。常用 SELECT COUNT(*) / 单字段查询。",
        ),
        Symbol(
            id=f"{NS_OXMYSQL}::MySQL.update",
            namespace=NS_OXMYSQL,
            name="MySQL.update",
            kind="function",
            side="server",
            signature="MySQL.update(query, params?, cb?) -> affectedRows",
            summary="UPDATE / DELETE 都走它，返回受影响行数。",
        ),
        Symbol(
            id=f"{NS_OXMYSQL}::MySQL.insert",
            namespace=NS_OXMYSQL,
            name="MySQL.insert",
            kind="function",
            side="server",
            signature="MySQL.insert(query, params?, cb?) -> insertId",
            summary="INSERT，返回新行 AUTO_INCREMENT id。",
        ),
        Symbol(
            id=f"{NS_OXMYSQL}::MySQL.transaction",
            namespace=NS_OXMYSQL,
            name="MySQL.transaction",
            kind="function",
            side="server",
            signature="MySQL.transaction(queries, cb?) -> success",
            summary=(
                "批量原子事务。queries 是 {{query, params}, ...}。"
                "任何一条失败整组回滚，cb(true|false)。"
            ),
            example=(
                "MySQL.transaction({\n"
                "    {'UPDATE players SET money = money - ? WHERE citizenid = ?', { 100, src_cid }},\n"
                "    {'UPDATE players SET money = money + ? WHERE citizenid = ?', { 100, dst_cid }},\n"
                "}, function(success) print(success) end)"
            ),
        ),
        # ---------- FiveM Natives 高频 ----------
        Symbol(
            id=f"{NS_NATIVES}::PlayerPedId",
            namespace=NS_NATIVES,
            name="PlayerPedId",
            kind="native",
            side="client",
            signature="PlayerPedId() -> Ped",
            summary=(
                "返回当前玩家控制的 ped（角色切换时会变）。"
                "比 GetPlayerPed(-1) 快——能用 PlayerPedId 就别用 GetPlayerPed。"
            ),
        ),
        Symbol(
            id=f"{NS_NATIVES}::GetEntityCoords",
            namespace=NS_NATIVES,
            name="GetEntityCoords",
            kind="native",
            side="client",
            signature="GetEntityCoords(entity, alive?) -> vector3",
            summary=(
                "取实体世界坐标。alive=true 会跳过已死亡实体的位置缓存。"
                "Lua 5.4 下返回 vector3，可直接 #(a - b) 求距离。"
            ),
        ),
        Symbol(
            id=f"{NS_NATIVES}::SetEntityCoords",
            namespace=NS_NATIVES,
            name="SetEntityCoords",
            kind="native",
            side="client",
            signature="SetEntityCoords(entity, x, y, z, xAxis, yAxis, zAxis, clearArea)",
            summary=(
                "瞬移实体到坐标。clearArea=true 会清掉目标点周围的车辆/ped。"
                "传送玩家通常先 FreezeEntityPosition true、传送、等碰撞 ready 再 unfreeze。"
            ),
        ),
        Symbol(
            id=f"{NS_NATIVES}::IsControlJustPressed",
            namespace=NS_NATIVES,
            name="IsControlJustPressed",
            kind="native",
            side="client",
            signature="IsControlJustPressed(inputGroup, control) -> bool",
            summary=(
                "本帧首次按下时为 true。inputGroup 通常 0；control 见 fivem 控制 id 表。"
                "持续按住请用 IsControlPressed；松开瞬间用 IsControlJustReleased。"
            ),
            example=(
                "if IsControlJustPressed(0, 38) then  -- E\n"
                "    -- 触发交互\n"
                "end"
            ),
        ),
        Symbol(
            id=f"{NS_NATIVES}::TriggerEvent",
            namespace=NS_NATIVES,
            name="TriggerEvent",
            kind="native",
            side="any",
            signature="TriggerEvent(eventName, ...)",
            summary="**本端**触发事件——客户端发给本机、服务端发给本进程。跨端用 TriggerServerEvent / TriggerClientEvent。",
        ),
        Symbol(
            id=f"{NS_NATIVES}::TriggerServerEvent",
            namespace=NS_NATIVES,
            name="TriggerServerEvent",
            kind="native",
            side="client",
            signature="TriggerServerEvent(eventName, ...)",
            summary="客户端→服务端事件。**任何敏感操作必须服务端校验**，client 端可被注入。",
        ),
        Symbol(
            id=f"{NS_NATIVES}::TriggerClientEvent",
            namespace=NS_NATIVES,
            name="TriggerClientEvent",
            kind="native",
            side="server",
            signature="TriggerClientEvent(eventName, source | -1, ...)",
            summary="服务端→客户端。source=-1 广播给所有玩家；写 server id 单播。",
        ),
        Symbol(
            id=f"{NS_NATIVES}::RegisterNetEvent",
            namespace=NS_NATIVES,
            name="RegisterNetEvent",
            kind="native",
            side="any",
            signature="RegisterNetEvent(eventName, handler?)",
            summary=(
                "把一个事件注册为可被网络触发的——必须，否则 TriggerClientEvent / "
                "TriggerServerEvent 收不到。新版 API 接受第二参直接传 handler，"
                "等价于额外 AddEventHandler。"
            ),
            example=(
                "RegisterNetEvent('myres:client:notify', function(text)\n"
                "    lib.notify({ description = text })\n"
                "end)"
            ),
        ),
        Symbol(
            id=f"{NS_NATIVES}::CreateThread",
            namespace=NS_NATIVES,
            name="CreateThread",
            kind="native",
            side="any",
            signature="CreateThread(fn)",
            summary=(
                "起一个独立 Lua 协程。比 Citizen.CreateThread 短。"
                "协程内 Wait(ms) 让出 CPU，0 也算让出（下一帧继续）。"
            ),
        ),
        Symbol(
            id=f"{NS_NATIVES}::SetTimeout",
            namespace=NS_NATIVES,
            name="SetTimeout",
            kind="native",
            side="any",
            signature="SetTimeout(ms, fn)",
            summary="ms 毫秒后跑一次 fn。需要重复用 CreateThread + Wait 循环。",
        ),
        Symbol(
            id=f"{NS_NATIVES}::Wait",
            namespace=NS_NATIVES,
            name="Wait",
            kind="native",
            side="any",
            signature="Wait(ms)",
            summary=(
                "在协程里阻塞 ms 毫秒。**只能在 CreateThread/RegisterNetEvent handler 里用**，"
                "纯 Lua 顶层调会卡死服务器。轮询循环至少 Wait(0)，避免吃满 CPU。"
            ),
        ),
    ]


def seed_chunks() -> list[Chunk]:
    """长一点的"概念性"片段，用于全文检索而非精确锚定。"""
    return [
        Chunk(
            id=f"{NS_QBCORE}:concepts/player-object#0",
            namespace=NS_QBCORE,
            source_title="QBCore Framework 速查",
            section="Player 对象",
            text=(
                "QBCore 的 Player 对象是服务端的玩家身份载体。通过 "
                "QBCore.Functions.GetPlayer(source) 拿到。常用字段："
                "PlayerData.citizenid（身份证）、PlayerData.charinfo、"
                "PlayerData.money（现金/银行/加密货币）、"
                "PlayerData.job（职业）、PlayerData.gang（帮派）、"
                "PlayerData.metadata（自定义键值）。"
                "常用方法集合在 Player.Functions：AddItem / RemoveItem / "
                "AddMoney / RemoveMoney / SetJob / SetMetaData / Save。"
                "客户端没有 Player 对象，只能通过 "
                "QBCore.Functions.GetPlayerData() 取 PlayerData 的副本，"
                "或监听 'QBCore:Player:SetPlayerData' 事件实时同步。"
            ),
        ),
        Chunk(
            id=f"{NS_QBCORE}:concepts/useable-items#0",
            namespace=NS_QBCORE,
            source_title="QBCore Framework 速查",
            section="可使用物品",
            text=(
                "在 QBCore 里把物品注册为可使用，需要：(1) items.lua 里加好物品；"
                "(2) 服务端调用 QBCore.Functions.CreateUseableItem(name, cb)；"
                "(3) 回调里通常 TriggerClientEvent 给客户端做动画或交互，"
                "再 Player.Functions.RemoveItem 扣除。"
                "如果用 ox_inventory 替代默认背包，"
                "需要在 ox_inventory/data/items.lua 里给物品加 server.export 字段，"
                "导出的函数名必须等于 export 名。"
            ),
        ),
        Chunk(
            id=f"{NS_OX_LIB}:concepts/callback-vs-event#0",
            namespace=NS_OX_LIB,
            source_title="ox_lib 速查",
            section="callback vs event",
            text=(
                "ox_lib 的 lib.callback 解决的是「客户端等服务端返回值」这种"
                "「请求-响应」模式。RegisterNetEvent + TriggerServerEvent "
                "是单向的，要拿返回值得自己再发一个事件回来。"
                "lib.callback.register 在服务端注册命名回调，"
                "客户端 lib.callback.await(name, false, ...) 同步等结果，"
                "或 lib.callback(name, false, cb, ...) 异步回调。"
                "命名建议用 resource:scope:action 三段式避免冲突。"
            ),
        ),
        Chunk(
            id=f"{NS_FIVEM_CFX}:concepts/fxmanifest#0",
            namespace=NS_FIVEM_CFX,
            source_title="FiveM 资源开发约定",
            section="fxmanifest 必填字段",
            text=(
                "每个 FiveM 资源根目录必须有 fxmanifest.lua（旧版 __resource.lua "
                "已弃用）。必填：fx_version 'cerulean'（推荐最新）、"
                "game 'gta5'。可选但常用：lua54 'yes' 启用 Lua 5.4；"
                "shared_scripts / client_scripts / server_scripts 定义脚本入口；"
                "dependencies { 'qb-core', 'ox_lib' } 声明依赖；"
                "files / ui_page 用于 NUI；"
                "version / author / description 元数据。"
            ),
        ),
        Chunk(
            id=f"{NS_OX_INVENTORY}:concepts/replace-qb-inventory#0",
            namespace=NS_OX_INVENTORY,
            source_title="ox_inventory 速查",
            section="替换 qb-inventory",
            text=(
                "用 ox_inventory 替换 qb-inventory 后，物品操作要改用 "
                "exports.ox_inventory:AddItem / :RemoveItem / :GetItem / :CanCarryItem。"
                "可使用物品不再走 QBCore.Functions.CreateUseableItem，"
                "而是在 ox_inventory/data/items.lua 里给物品配 server.export 字段，"
                "ox_inventory 会自动调用同名 export。物品图片放到 "
                "ox_inventory/web/images/<item>.png。"
            ),
        ),
        # ---------- NPC AI ----------
        Chunk(
            id=f"{NS_NPC_AI}:concepts/spawn-lifecycle#0",
            namespace=NS_NPC_AI,
            source_title="FiveM NPC 插件开发速查",
            section="ped 生成与回收的生命周期",
            text=(
                "标准 NPC 生命周期：(1) lib.requestModel 加载模型并等超时；"
                "(2) CreatePed 在指定坐标创建；(3) SetEntityAsMissionEntity 让本资源拿到所有权，"
                "否则游戏可能在玩家走远后回收掉；(4) SetBlockingOfNonTemporaryEvents 屏蔽"
                "非临时事件，避免被旁边的事故/枪声打断当前任务；(5) FreezeEntityPosition / "
                "SetEntityInvincible 视需要加；(6) SetModelAsNoLongerNeeded 释放模型缓存；"
                "(7) onResourceStop 时 DeletePed 清理。漏掉所有权或清理会导致 ghost ped 残留。"
            ),
        ),
        Chunk(
            id=f"{NS_NPC_AI}:concepts/static-vs-patrol-vs-fsm#0",
            namespace=NS_NPC_AI,
            source_title="FiveM NPC 插件开发速查",
            section="静态 / 巡逻 / 状态机三种 NPC 模式如何选",
            text=(
                "三种主流 NPC 实现：(a) 静态 NPC——TaskStartScenarioInPlace 播个动画站着，"
                "ox_target 接对话即可，最省 CPU，商人 / 任务 NPC 首选；"
                "(b) 巡逻 NPC——TaskGoToCoordAnyMeans 按巡逻点循环，适合保安、警卫；"
                "(c) 行为状态机——idle/patrol/talk/alert/flee 切换，适合需要响应玩家行为的"
                "复杂剧情 NPC。状态机模式 tick 用 SetInterval(500ms) 即可，"
                "不要 while+Wait(0) 否则一个 NPC 就吃满一格 CPU。"
            ),
        ),
        Chunk(
            id=f"{NS_NPC_AI}:concepts/dialogue-tree-runtime#0",
            namespace=NS_NPC_AI,
            source_title="FiveM NPC 插件开发速查",
            section="对话树离线设计 + 运行时驱动",
            text=(
                "推荐做法：对话树定义放 shared/dialogues.lua（或 JSON），key 为 npc_id，"
                "value 是节点字典 + start 指针。节点含 text / choices[] / action / terminal。"
                "运行时在 client 端拉到当前 NPC 的对话表，用 ox_lib 的 alertDialog 或自己写"
                "NUI 渲染。choice.action 是结构化指令（give_item / start_quest / "
                "trigger_event），由前端派发到对应 handler，**不要**让对话节点直接执行 "
                "Lua 字符串——既不安全又不利于多语言/翻译。LLM 生成内容时也按这个"
                "schema 输出，导出到文件后离线静态资源使用，运行时不再调 LLM。"
            ),
        ),
        Chunk(
            id=f"{NS_NPC_AI}:concepts/networked-vs-local#0",
            namespace=NS_NPC_AI,
            source_title="FiveM NPC 插件开发速查",
            section="networked ped 还是 local ped",
            text=(
                "做对话/商人/巡逻 NPC 时强烈建议用 local ped（CreatePed 第 7 参数 isNetwork=false）。"
                "每个客户端在自己的实例里生成同一坐标的 NPC，对话与交互都本地处理，"
                "数据持久化走 server event。这样：(1) 不占网络对象槽位；(2) 没有 owner 转移问题；"
                "(3) 玩家断线/进出区域不影响其他人。需要全局唯一（如 boss NPC）才用 networked，"
                "并配合 NetworkRegisterEntityAsNetworked + 服务端 ESX/QB 的 NPC 同步资源。"
            ),
        ),
        # ---------- QBox / ESX 框架对照 ----------
        Chunk(
            id=f"{NS_QBOX}:concepts/migration-from-qbcore#0",
            namespace=NS_QBOX,
            source_title="QBox（QBCore 现代分支）速查",
            section="QBCore → QBox 迁移要点",
            text=(
                "QBox 是 QBCore 的现代化分支，移除全局 QBCore 对象，全部走 export："
                "QBCore.Functions.GetPlayer(src) → exports.qbx_core:GetPlayer(src)。"
                "默认强依赖 ox_lib + ox_inventory + ox_target，"
                "不再维护 qb-inventory / qb-target 路径。物品操作建议直接走 "
                "exports.ox_inventory:AddItem / RemoveItem，**不要**再用 "
                "Player.Functions.AddItem，那个 shim 在新版可能不再保留。"
                "Player 对象结构与 QBCore 兼容，charinfo / money / job / metadata 字段不变。"
            ),
        ),
        Chunk(
            id=f"{NS_QBOX}:concepts/which-framework-to-pick#0",
            namespace=NS_QBOX,
            source_title="QBox（QBCore 现代分支）速查",
            section="新项目选 QBCore / QBox / ESX 怎么选",
            text=(
                "2026 年新项目推荐顺序：QBox（最现代、ox 全家桶原生集成）> "
                "QBCore（生态最大、教程多、但要自己拼 ox 替换）> "
                "ESX Legacy（老项目维护用，新项目除非有强 ESX 依赖资源否则不推荐）。"
                "从 ESX 迁 QBox 改动最大（API 完全不同）；"
                "从 QBCore 迁 QBox 改动中等（语法换 export 但语义兼容）；"
                "从 QBCore 迁 ESX 反向迁移几乎没人做，因为 QBCore 设计本身就是 ESX 升级。"
            ),
        ),
        Chunk(
            id=f"{NS_ESX}:concepts/xplayer-vs-qbcore-player#0",
            namespace=NS_ESX,
            source_title="ESX Legacy 速查",
            section="xPlayer 与 QBCore Player 的字段对照",
            text=(
                "ESX 的 xPlayer 与 QBCore 的 Player 在结构上对照大致："
                "xPlayer.identifier ↔ Player.PlayerData.citizenid；"
                "xPlayer.getMoney() ↔ Player.PlayerData.money.cash；"
                "xPlayer.getAccount('bank') ↔ Player.PlayerData.money.bank；"
                "xPlayer.job ↔ Player.PlayerData.job；"
                "xPlayer.addInventoryItem(item, qty) ↔ Player.Functions.AddItem(item, qty)。"
                "ESX 的 set 路径偏函数式（addMoney / removeMoney），"
                "QBCore 偏对象式（Player.Functions.AddMoney(...))。"
                "两个体系都支持用 ox_inventory 替代默认背包；切到 ox 后这些 inventory API "
                "都不再用，统一走 exports.ox_inventory:AddItem。"
            ),
        ),
        # ---------- oxmysql ----------
        Chunk(
            id=f"{NS_OXMYSQL}:concepts/usage-patterns#0",
            namespace=NS_OXMYSQL,
            source_title="oxmysql 速查",
            section="使用模式：同步 / 异步 / 事务",
            text=(
                "oxmysql 在 server 端用，提供四种方法：query/single/scalar/update + insert + transaction。"
                "每个方法有三种调用方式：(a) MySQL.query.await(...) 在协程里同步等结果，"
                "返回值直接拿——**最常用、可读性最好**；"
                "(b) MySQL.query(sql, params, cb) 异步回调；"
                "(c) MySQL.query(sql, params) 不等结果（fire-and-forget）。"
                "**永远用 ? 占位符**，不要字符串拼接 SQL——会被注入。"
                "transaction 用于多语句原子操作（转账、扣费 + 加道具一起做），"
                "任何一条失败整组回滚。"
            ),
        ),
        Chunk(
            id=f"{NS_OXMYSQL}:concepts/migrate-from-ghmattisql#0",
            namespace=NS_OXMYSQL,
            source_title="oxmysql 速查",
            section="从 ghmattimysql / mysql-async 迁移",
            text=(
                "老项目常用 ghmattimysql 或 mysql-async，迁到 oxmysql 时："
                "MySQL.Sync.fetchAll → MySQL.query.await；"
                "MySQL.Sync.fetchScalar → MySQL.scalar.await；"
                "MySQL.Sync.execute → MySQL.update.await；"
                "MySQL.Async.* 系列等价改成 cb 形式或 .await。"
                "oxmysql 的占位符习惯是 ?，命名占位符 :name 也支持但不推荐"
                "（旧代码兼容用，新代码全用 ?）。"
            ),
        ),
        # ---------- FiveM Natives ----------
        Chunk(
            id=f"{NS_NATIVES}:concepts/event-flow#0",
            namespace=NS_NATIVES,
            source_title="FiveM Natives 高频速查",
            section="事件流：本端 / 跨端 / Net 注册",
            text=(
                "FiveM 事件三件套：(1) AddEventHandler 监听**本端**事件；"
                "(2) RegisterNetEvent 把事件名标记为可被网络触发——"
                "**没注册过的事件名**用 TriggerClientEvent / TriggerServerEvent 收不到；"
                "(3) TriggerEvent 仅触发本端，TriggerServerEvent / TriggerClientEvent 跨端。"
                "**安全铁律**：客户端可被注入，所以服务端收 client→server 事件后**必须**重新校验 "
                "玩家身份、距离、物品库存，不要信客户端传来的任何敏感数据（金额、目标 source 等）。"
                "新版 FiveM 允许 RegisterNetEvent('name', handler) 直接传第二参作为 handler，"
                "省一行 AddEventHandler。"
            ),
        ),
        Chunk(
            id=f"{NS_NATIVES}:concepts/threading-and-wait#0",
            namespace=NS_NATIVES,
            source_title="FiveM Natives 高频速查",
            section="协程、Wait 与轮询",
            text=(
                "FiveM 的 Lua 是协程式：每个 CreateThread 创建一个独立协程，"
                "Wait(ms) 让出 CPU 给主帧。**绝不能**在协程外（顶层 Lua）调 Wait——"
                "服务器会卡死整帧。轮询循环至少 Wait(0) 让出帧，"
                "事件驱动的逻辑根本不需要 thread；只有真正要持续 tick（巡逻、距离检测）"
                "才用 CreateThread。能用 SetTimeout 一次性回调就别用 thread+循环。"
                "客户端 60FPS 主循环，服务端 50ms tick——心里有数。"
            ),
        ),
        Chunk(
            id=f"{NS_NATIVES}:concepts/coords-and-vectors#0",
            namespace=NS_NATIVES,
            source_title="FiveM Natives 高频速查",
            section="坐标与向量",
            text=(
                "Lua 5.4（lua54 'yes'）下 GetEntityCoords 返回 vector3（不是 table），"
                "可以直接 v.x v.y v.z 访问，**距离用 #(a - b)**——比 #vec3(a-b) 或 "
                "Vdist 都快。vec3(x,y,z) 字面量也能用。"
                "没启 lua54 时返回的是 {x,y,z} 的 table——必须 GetEntityCoords(ped, true) "
                "再 .x / .y / .z 访问。新项目都开 lua54 'yes'，省心。"
            ),
        ),
    ]
