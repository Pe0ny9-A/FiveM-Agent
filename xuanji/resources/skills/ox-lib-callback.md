---
name: ox-lib-callback
description: ox_lib 的 client/server 双向 callback 注册与调用模板
triggers:
  - ox_lib
  - ox callback
  - lib.callback
  - lib.callback.register
  - 注册回调
  - 双向调用
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

# ox_lib · callback 模板

## server 注册 / client 调用

```lua
-- server.lua
lib.callback.register('myresource:getInventory', function(source)
    local Player = exports.qbx_core:GetPlayer(source)
    return Player and Player.PlayerData.items or nil
end)
```

```lua
-- client.lua（async 风格）
local items = lib.callback.await('myresource:getInventory', false)
if items then
    print(json.encode(items))
end
```

## client 注册 / server 调用

```lua
-- client.lua
lib.callback.register('myresource:getCoords', function()
    return GetEntityCoords(PlayerPedId())
end)
```

```lua
-- server.lua
lib.callback('myresource:getCoords', source, function(coords)
    print(('player %d at %s'):format(source, coords))
end)
```

## 设计要点
- `lib.callback.await(name, source_or_false, ...)` 第二个参数：client → server 调用传 `false`
- 不要在 callback 里跑 >100ms 的逻辑，会卡 caller。重活拆给 `lib.cron` 或 SetTimeout
- 命名约定：`<resource>:<action>` 或 `<resource>:<entity>:<action>`，避免跨 resource 撞名
- 遇到「callback 不返回」99% 是 server-side 漏 `lib.callback.register`，或 resource 启动顺序问题

## 验证
1. server console 加 `print` 在 register 处，重启资源看是否被加载
2. client 用 `lib.callback.await` 时 wrap 在 pcall 里，超时返回 nil 不会卡 thread
3. ox_lib 版本 < 3.x 没有 `lib.callback.await`，必须用回调风格
