"""FiveM 种子知识库。

M1 阶段先用手写 API 卡片解决最常见的开发查询。M2+ 接爬虫 + 增量更新。
所有内容标 [seed]，避免与未来爬虫导入的版本化文档混淆。

注意：以下卡片的 signature/examples 来自姐姐对 QBCore / ox_lib / FiveM
公开文档的整理，可能与小宝实际使用的 fork 版本不一致——使用前以工程内
源码（`fxmanifest.lua` 锁定的 git tag）为准。
"""

from __future__ import annotations

from core.knowledge.models import Chunk, Source, Symbol

NS_QBCORE = "fivem.qbcore@1.x"
NS_OX_LIB = "fivem.ox_lib@3.x"
NS_OX_INVENTORY = "fivem.ox_inventory@2.x"
NS_FIVEM_CFX = "fivem.cfx@latest"


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
    ]
