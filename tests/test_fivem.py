"""FiveM 专精层单测：detector / scaffold / analyzer / 工具。"""

from __future__ import annotations

from pathlib import Path

import pytest

from xuanji.capability.tool import ToolCtx, ToolError
from xuanji.fivem import (
    SCAFFOLD_PRESETS,
    FiveMContext,
    Framework,
    InventoryKind,
    ScaffoldEngine,
    TargetKind,
    detect_fivem_context,
    summarize_for_prompt,
)
from xuanji.fivem.analyzer import analyze_resource
from xuanji.fivem.manifest import parse_fxmanifest
from xuanji.fivem.presets import ScaffoldFile, ScaffoldPreset
from xuanji.tools.fivem import (
    AnalyzeResourceTool,
    DetectProjectTool,
    ProposePresetTool,
)

# ============================================================
# fxmanifest 解析
# ============================================================


def test_parse_fxmanifest_basic_fields() -> None:
    text = """\
fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name 'my-resource'
description 'A test resource'
author 'Xiaobao'
version '1.2.3'

shared_scripts {
    '@ox_lib/init.lua',
    'shared/config.lua',
}

client_scripts { 'client/main.lua' }

server_scripts {
    'server/main.lua',
    'server/util.lua',
}

dependencies { 'qb-core', 'ox_lib' }
dependency 'oxmysql'
"""
    m = parse_fxmanifest(text)
    assert m.fx_version == "cerulean"
    assert m.game == "gta5"
    assert m.lua54 is True
    assert m.name == "my-resource"
    assert m.author == "Xiaobao"
    assert m.version == "1.2.3"
    assert m.shared_scripts == ["@ox_lib/init.lua", "shared/config.lua"]
    assert m.client_scripts == ["client/main.lua"]
    assert m.server_scripts == ["server/main.lua", "server/util.lua"]
    assert "qb-core" in m.dependencies
    assert "ox_lib" in m.dependencies
    assert "oxmysql" in m.dependencies


def test_parse_fxmanifest_handles_comments() -> None:
    """Lua 行注释不应干扰解析。"""
    text = """\
fx_version 'cerulean'
-- 这是一行注释
game 'gta5'
-- name 'fake'
name 'real'
"""
    m = parse_fxmanifest(text)
    assert m.name == "real"


def test_parse_fxmanifest_empty_returns_defaults() -> None:
    m = parse_fxmanifest("")
    assert m.name is None
    assert m.dependencies == []


# ============================================================
# detector
# ============================================================


def _write_fxmanifest(tmp_path: Path, deps: list[str], **fields: str) -> Path:
    deps_block = ", ".join(f"'{d}'" for d in deps)
    fields_block = "\n".join(f"{k} '{v}'" for k, v in fields.items())
    text = (
        f"fx_version 'cerulean'\ngame 'gta5'\n"
        f"{fields_block}\n"
        f"dependencies {{ {deps_block} }}\n"
    )
    fp = tmp_path / "fxmanifest.lua"
    fp.write_text(text, encoding="utf-8")
    return fp


def test_detector_recognizes_qbcore(tmp_path: Path) -> None:
    _write_fxmanifest(tmp_path, ["qb-core", "ox_lib"], name="r1")
    ctx = detect_fivem_context(tmp_path)
    assert ctx.is_fivem_resource
    assert ctx.framework == Framework.QBCORE


def test_detector_recognizes_qbox(tmp_path: Path) -> None:
    _write_fxmanifest(tmp_path, ["qbx_core", "ox_lib"], name="r1")
    ctx = detect_fivem_context(tmp_path)
    assert ctx.framework == Framework.QBOX
    assert ctx.framework_confidence > 0.8


def test_detector_recognizes_esx(tmp_path: Path) -> None:
    _write_fxmanifest(tmp_path, ["es_extended"], name="r1")
    ctx = detect_fivem_context(tmp_path)
    assert ctx.framework == Framework.ESX


def test_detector_recognizes_inventory(tmp_path: Path) -> None:
    _write_fxmanifest(
        tmp_path, ["qb-core", "ox_inventory", "ox_target"], name="r1",
    )
    ctx = detect_fivem_context(tmp_path)
    assert ctx.inventory == InventoryKind.OX_INVENTORY
    assert ctx.target == TargetKind.OX_TARGET


def test_detector_handles_non_fivem_dir(tmp_path: Path) -> None:
    """不是 FiveM resource 时，is_fivem_resource=False，不抛错。"""
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    ctx = detect_fivem_context(tmp_path)
    assert not ctx.is_fivem_resource
    assert ctx.framework == Framework.UNKNOWN


def test_detector_finds_sub_resources(tmp_path: Path) -> None:
    """server bundle 根目录 → 应列出子 resources。"""
    res_dir = tmp_path / "resources" / "[a]" / "my-job"
    res_dir.mkdir(parents=True)
    (res_dir / "fxmanifest.lua").write_text("fx_version 'cerulean'\ngame 'gta5'\n", encoding="utf-8")
    ctx = detect_fivem_context(tmp_path)
    assert not ctx.is_fivem_resource
    assert any(p.name == "my-job" for p in ctx.detected_resources)


def test_detector_uses_server_cfg_as_fallback(tmp_path: Path) -> None:
    (tmp_path / "resources").mkdir()
    res = tmp_path / "resources" / "x"
    res.mkdir()
    (res / "fxmanifest.lua").write_text("fx_version 'cerulean'\ngame 'gta5'\n", encoding="utf-8")
    (tmp_path / "server.cfg").write_text(
        "ensure qbx_core\nensure ox_lib\nensure ox_inventory\n",
        encoding="utf-8",
    )
    ctx = detect_fivem_context(tmp_path)
    assert ctx.framework == Framework.QBOX
    assert ctx.inventory == InventoryKind.OX_INVENTORY


def test_summarize_for_prompt_skips_when_not_fivem(tmp_path: Path) -> None:
    ctx = FiveMContext(project_root=tmp_path)
    assert summarize_for_prompt(ctx) is None


def test_summarize_for_prompt_includes_framework(tmp_path: Path) -> None:
    _write_fxmanifest(tmp_path, ["qbx_core", "ox_inventory"], name="r1")
    ctx = detect_fivem_context(tmp_path)
    summary = summarize_for_prompt(ctx)
    assert summary is not None
    assert "qbox" in summary
    assert "ox_inventory" in summary


# ============================================================
# scaffold
# ============================================================


def test_builtin_presets_all_have_fxmanifest() -> None:
    """每套预设都必须含 fxmanifest.lua——否则不能启动。"""
    for key, preset in SCAFFOLD_PRESETS.items():
        paths = [f.path for f in preset.files]
        assert "fxmanifest.lua" in paths, f"preset {key} 缺 fxmanifest"


def test_builtin_presets_count() -> None:
    assert len(SCAFFOLD_PRESETS) == 6
    assert "qbcore-basic" in SCAFFOLD_PRESETS
    assert "qbox-basic" in SCAFFOLD_PRESETS
    assert "qbcore-job" in SCAFFOLD_PRESETS
    assert "qbox-job" in SCAFFOLD_PRESETS
    assert "ox-target-npc" in SCAFFOLD_PRESETS
    assert "esx-basic" in SCAFFOLD_PRESETS


def test_scaffold_generate_qbox_basic(tmp_path: Path) -> None:
    engine = ScaffoldEngine()
    target = tmp_path / "my-job"
    result = engine.generate(
        "qbox-basic",
        target,
        resource_name="my-job",
        author="Test",
        version="0.1.0",
    )
    assert result.ok
    fxmanifest = target / "fxmanifest.lua"
    assert fxmanifest.exists()
    content = fxmanifest.read_text(encoding="utf-8")
    assert "name 'my-job'" in content
    assert "Test" in content
    assert "qbx_core" in content


def test_scaffold_skip_existing(tmp_path: Path) -> None:
    """已存在的文件应跳过，不覆盖。"""
    engine = ScaffoldEngine()
    target = tmp_path / "r"
    target.mkdir()
    (target / "fxmanifest.lua").write_text("EXISTING", encoding="utf-8")
    result = engine.generate("qbcore-basic", target, resource_name="r")
    assert (target / "fxmanifest.lua").read_text(encoding="utf-8") == "EXISTING"
    assert any(p.name == "fxmanifest.lua" for p in result.files_skipped)


def test_scaffold_overwrite(tmp_path: Path) -> None:
    engine = ScaffoldEngine()
    target = tmp_path / "r"
    target.mkdir()
    (target / "fxmanifest.lua").write_text("OLD", encoding="utf-8")
    engine.generate("qbcore-basic", target, resource_name="r", overwrite=True)
    assert "OLD" not in (target / "fxmanifest.lua").read_text(encoding="utf-8")


def test_scaffold_unknown_preset_raises() -> None:
    engine = ScaffoldEngine()
    with pytest.raises(KeyError, match="未知预设"):
        engine.get("nope")


# ============================================================
# 用户预设持久化
# ============================================================


def test_user_preset_saved_and_loaded(tmp_path: Path) -> None:
    drafts = tmp_path / "drafts"
    presets = tmp_path / "presets"
    engine = ScaffoldEngine(user_presets_dir=presets, drafts_dir=drafts)

    custom = ScaffoldPreset(
        key="qbcore-banking",
        label="QBCore Banking",
        description="custom test",
        framework=Framework.QBCORE,
        inventory=InventoryKind.OX_INVENTORY,
        target=TargetKind.OX_TARGET,
        files=[
            ScaffoldFile(path="fxmanifest.lua", content="fx_version 'cerulean'\ngame 'gta5'\n"),
        ],
    )
    engine.save_draft(custom)

    drafts_list = engine.list_drafts()
    assert len(drafts_list) == 1
    assert drafts_list[0].key == "qbcore-banking"
    # 草案不应出现在 presets 视图
    assert "qbcore-banking" not in engine.presets

    # accept 后才出现在 presets
    engine.accept_draft("qbcore-banking")
    assert "qbcore-banking" in engine.presets
    assert engine.list_drafts() == []  # 草案被消费


def test_user_preset_overrides_builtin(tmp_path: Path) -> None:
    """同名 user preset 覆盖 builtin。"""
    drafts = tmp_path / "drafts"
    presets = tmp_path / "presets"
    engine = ScaffoldEngine(user_presets_dir=presets, drafts_dir=drafts)

    custom = ScaffoldPreset(
        key="qbcore-basic",  # 与 builtin 同名
        label="My Custom QBCore",
        description="overridden",
        framework=Framework.QBCORE,
        inventory=InventoryKind.QB_INVENTORY,
        target=TargetKind.NONE,
        files=[ScaffoldFile(path="fxmanifest.lua", content="custom\n")],
    )
    engine.save_draft(custom)
    engine.accept_draft("qbcore-basic")

    p = engine.get("qbcore-basic")
    assert p.label == "My Custom QBCore"
    assert p.source == "user"


def test_reject_draft_removes_file(tmp_path: Path) -> None:
    drafts = tmp_path / "drafts"
    presets = tmp_path / "presets"
    engine = ScaffoldEngine(user_presets_dir=presets, drafts_dir=drafts)
    engine.save_draft(
        ScaffoldPreset(
            key="x",
            label="x",
            description="x",
            framework=Framework.STANDALONE,
            inventory=InventoryKind.UNKNOWN,
            target=TargetKind.NONE,
            files=[ScaffoldFile(path="fxmanifest.lua", content="x")],
        ),
    )
    assert engine.reject_draft("x") is True
    assert engine.list_drafts() == []
    assert engine.reject_draft("x") is False  # 第二次返回 False


def test_corrupted_user_preset_skipped(tmp_path: Path) -> None:
    """损坏的 user preset JSON 不应让全局崩。"""
    presets = tmp_path / "presets"
    presets.mkdir()
    (presets / "broken.json").write_text("{not json", encoding="utf-8")
    engine = ScaffoldEngine(user_presets_dir=presets, drafts_dir=tmp_path / "drafts")
    # presets 视图应该仍能加载（坏文件被跳过）
    assert "qbcore-basic" in engine.presets


# ============================================================
# analyzer
# ============================================================


def test_analyze_extracts_exports_and_events(tmp_path: Path) -> None:
    _write_fxmanifest(tmp_path, ["qb-core"], name="r1")
    (tmp_path / "client").mkdir()
    (tmp_path / "client" / "main.lua").write_text(
        """
local QBCore = exports['qb-core']:GetCoreObject()

exports('isOnDuty', function() return true end)

RegisterNetEvent('myres:client:hello', function(msg)
    QBCore.Functions.Notify(msg)
end)

CreateThread(function()
    TriggerServerEvent('myres:server:greet')
end)

lib.callback.register('myres:get_money', function() end)
""",
        encoding="utf-8",
    )
    analysis = analyze_resource(tmp_path)
    assert analysis.context.is_fivem_resource
    assert "isOnDuty" in analysis.exports
    assert "myres:client:hello" in analysis.events_registered
    assert "myres:server:greet" in analysis.events_triggered
    assert "myres:get_money" in analysis.callbacks
    assert "QBCore.Functions.Notify" in analysis.framework_api_calls


def test_analyze_non_fivem_returns_empty(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("hi")
    analysis = analyze_resource(tmp_path)
    assert not analysis.context.is_fivem_resource
    assert analysis.exports == []


# ============================================================
# 工具适配
# ============================================================


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(project_root=tmp_path, session_id="s", trace_id="t")


@pytest.mark.asyncio
async def test_detect_project_tool(tmp_path: Path, ctx: ToolCtx) -> None:
    _write_fxmanifest(tmp_path, ["qbx_core", "ox_inventory"], name="my-r")
    res = await DetectProjectTool().execute({"path": "."}, ctx)
    assert res.ok
    assert res.output["framework"] == "qbox"
    assert res.output["inventory"] == "ox_inventory"
    assert "prompt_summary" in res.output


@pytest.mark.asyncio
async def test_analyze_resource_tool(tmp_path: Path, ctx: ToolCtx) -> None:
    _write_fxmanifest(tmp_path, ["qb-core"], name="r1")
    (tmp_path / "client").mkdir()
    (tmp_path / "client" / "main.lua").write_text(
        "exports('hello', function() end)", encoding="utf-8",
    )
    res = await AnalyzeResourceTool().execute({"path": "."}, ctx)
    assert res.ok
    assert "hello" in res.output["exports"]


@pytest.mark.asyncio
async def test_analyze_resource_tool_rejects_missing(
    tmp_path: Path, ctx: ToolCtx,
) -> None:
    with pytest.raises(ToolError, match="不存在"):
        await AnalyzeResourceTool().execute({"path": "ghost"}, ctx)


@pytest.mark.asyncio
async def test_propose_preset_tool_writes_draft(
    tmp_path: Path, ctx: ToolCtx,
) -> None:
    drafts = tmp_path / "drafts"
    presets = tmp_path / "presets"
    engine = ScaffoldEngine(user_presets_dir=presets, drafts_dir=drafts)
    tool = ProposePresetTool(engine)

    res = await tool.execute(
        {
            "key": "qbcore-banking",
            "label": "QBCore 银行",
            "description": "From learning user-bank",
            "framework": "qbcore",
            "inventory": "ox_inventory",
            "target": "ox_target",
            "files": [
                {
                    "path": "fxmanifest.lua",
                    "content": "fx_version 'cerulean'\ngame 'gta5'\n",
                },
                {
                    "path": "client/main.lua",
                    "content": "-- {{name}}\n",
                },
            ],
            "metadata": {"learned_from": "test-bank"},
        },
        ctx,
    )
    assert res.ok
    assert res.output["key"] == "qbcore-banking"
    assert Path(res.output["draft_path"]).exists()
    drafts_list = engine.list_drafts()
    assert len(drafts_list) == 1
    assert drafts_list[0].metadata.get("learned_from") == "test-bank"


@pytest.mark.asyncio
async def test_propose_preset_rejects_bad_key(
    tmp_path: Path, ctx: ToolCtx,
) -> None:
    engine = ScaffoldEngine(
        user_presets_dir=tmp_path / "p", drafts_dir=tmp_path / "d",
    )
    tool = ProposePresetTool(engine)
    with pytest.raises(ToolError, match="key"):
        await tool.execute(
            {
                "key": "BAD KEY!",
                "label": "x",
                "description": "x",
                "framework": "qbcore",
                "files": [
                    {"path": "fxmanifest.lua", "content": "x"},
                ],
            },
            ctx,
        )


@pytest.mark.asyncio
async def test_propose_preset_rejects_no_manifest(
    tmp_path: Path, ctx: ToolCtx,
) -> None:
    engine = ScaffoldEngine(
        user_presets_dir=tmp_path / "p", drafts_dir=tmp_path / "d",
    )
    tool = ProposePresetTool(engine)
    with pytest.raises(ToolError, match=r"fxmanifest\.lua"):
        await tool.execute(
            {
                "key": "no-manifest",
                "label": "x",
                "description": "x",
                "framework": "qbcore",
                "files": [
                    {"path": "client/main.lua", "content": "x"},
                ],
            },
            ctx,
        )


@pytest.mark.asyncio
async def test_propose_preset_rejects_path_traversal(
    tmp_path: Path, ctx: ToolCtx,
) -> None:
    """绝对路径与 .. 应被拒。"""
    engine = ScaffoldEngine(
        user_presets_dir=tmp_path / "p", drafts_dir=tmp_path / "d",
    )
    tool = ProposePresetTool(engine)
    for bad in ("/etc/passwd", "../escape.lua", "C:\\Windows\\evil.lua"):
        with pytest.raises(ToolError, match="path"):
            await tool.execute(
                {
                    "key": "bad-path",
                    "label": "x",
                    "description": "x",
                    "framework": "qbcore",
                    "files": [
                        {"path": "fxmanifest.lua", "content": "x"},
                        {"path": bad, "content": "x"},
                    ],
                },
                ctx,
            )
