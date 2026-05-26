---
name: fxmanifest-audit
description: FiveM 资源 fxmanifest.lua 体检清单——版本号 / 依赖 / 脚本侧分组 / 加密
triggers:
  - fxmanifest
  - fxmanifest.lua
  - 资源清单
  - resource manifest
  - fx_version
  - manifest 体检
tools:
  - read_file
  - knowledge_search
allowed_tools:
  - read_file
  - knowledge_search
metadata:
  xuanji:
    mode: review
    role_hint: 司鉴
    risk_floor: safe
---

# fxmanifest.lua 体检清单

## 必填字段

```lua
fx_version 'cerulean'  -- 或 'bodacious'，新项目用 cerulean
game 'gta5'
lua54 'yes'            -- 想用 // 整除、goto、bit 库就开
```

## 依赖与共享

```lua
shared_scripts {
    '@ox_lib/init.lua',                  -- 必须放最前
    '@qbx_core/modules/lib.lua',         -- QBox 项目
    'shared/*.lua',                      -- 自己的共享代码
}

dependencies { 'ox_lib', 'oxmysql' }     -- 显式声明，启动顺序系统会处理
```

## client / server 分组

```lua
client_scripts {
    'client/main.lua',
    'client/ui.lua',
}
server_scripts {
    '@oxmysql/lib/MySQL.lua',
    'server/*.lua',
}
```

## 资源文件

```lua
files {
    'web/dist/index.html',
    'web/dist/assets/*',
    'config/items.lua',
}
ui_page 'web/dist/index.html'           -- NUI 入口
```

## 体检触点（小宝重点看这几条）

1. **fx_version** 留空 / 写 `'adamant'` → resource 启动会警告，强制升级到 cerulean
2. **dependencies** 漏写 → 启动顺序紊乱，常见症状是「ox_lib 初始化前我先跑了」
3. **shared_scripts 顺序** ox_lib 必须在 qbx_core 之前
4. **files** 漏掉 NUI 资源 → 浏览器报 404，打 F8 就能看到
5. **lua54** 没开但用了 `//` → 资源根本启动不了，启动错误信息很难看
6. **escrow_ignore** 出现 → 这是付费资源加密相关，开源项目不应该有
7. **version** 字段建议遵循 semver，便于 `version_check` 等机制

## 验证
- F8 控制台执行 `start <resource>`，留意红字
- 资源启动后 `restart <resource>` 看冷启动是否依然干净
- `dependencies` 的资源都装了的话，启动日志里有 「Started <name>」 前缀
