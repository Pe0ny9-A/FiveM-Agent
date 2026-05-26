---
name: qbox-add-useable-item
description: 在 QBox 项目里给一个 item 挂可使用回调的标准步骤（含 ox_inventory 兼容）
triggers:
  - QBox
  - QBcore
  - QBCore
  - useable item
  - 可使用物品
  - 注册物品使用
  - CreateUseableItem
tools:
  - read_file
  - write_file
  - knowledge_search
allowed_tools:
  - read_file
  - write_file
  - knowledge_search
metadata:
  xuanji:
    mode: dev
    role_hint: 百工匠
    risk_floor: io
---

# QBox · 可使用物品挂载

## 前提自检
1. 项目 `fxmanifest.lua` 里 `shared_scripts` 是否已包含 `'@qbx_core/modules/lib.lua'` 或对应版本入口
2. 库存方案是 `qb-inventory` 还是 `ox_inventory`——两套语义不同，先确认

## QBox 原生写法（server-side）

```lua
local QBX = exports.qbx_core
QBX:CreateUseableItem('itemname', function(source, item)
    local Player = exports.qbx_core:GetPlayer(source)
    if not Player then return end
    -- 业务逻辑
    Player.Functions.RemoveItem('itemname', 1)
end)
```

## ox_inventory 写法（推荐 QBox 项目）

```lua
exports.ox_inventory:registerHook('usingItem', function(payload)
    if payload.item.name ~= 'itemname' then return end
    -- 业务逻辑
    return true
end, {
    itemFilter = { itemname = true },
})
```

## 注意点
- 不要同时挂 `qbx_core` 和 `ox_inventory` 两套——一个 item 挂两次会触发两次
- 物品本身要在 `qbx_core/shared/items.lua` 或 `ox_inventory/data/items.lua` 注册
- client 端如果要播放动画，用 `lib.requestAnimDict` + `TaskPlayAnim`，别裸调 native

## 验证
1. 重启 resource：`refresh && ensure <resource_name>`
2. 给玩家发物品：`/giveitem <id> itemname 1`
3. 玩家库存里点击使用，看 server console 是否打印业务日志
