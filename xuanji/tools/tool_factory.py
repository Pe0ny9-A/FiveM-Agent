"""ToolFactory 自动实现链路（小宝触发，非玄玑自动）。

四步流水线，每步小宝显式触发：

    propose_tool (玄玑)            xuanji tool list
        ↓                               ↓
    drafts/<slug>.json            xuanji tool show <slug>
        ↓
    xuanji tool generate <slug>   ← 小宝触发：用 LLM 把草案转 Python
        ↓
    staged/<slug>.py + test_<slug>.py（生成的代码 + 单测）
        ↓
    xuanji tool test <slug>       ← 小宝触发：subprocess 跑单测
        ↓
    通过 ✓ → 状态变 'tested'
        ↓
    xuanji tool publish <slug>    ← 小宝最终拍板：复制到 published/
        ↓
    next chat 启动时被自动加载

**安全核心**：玄玑不能自己跑 generate/test/publish——这些是 CLI 命令，
LLM 没法触发。生成的代码先进 staged/，跑过 test 再人工 publish。
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xuanji.config.profiles import Profile
from xuanji.config.sqlite_conn import tune_for_multiprocess
from xuanji.llm.providers.base import Message
from xuanji.llm.providers.factory import build_provider


@dataclass
class FactoryStatus:
    """工具的生命周期状态。"""

    slug: str
    status: str  # 'draft' / 'generated' / 'tested' / 'published' / 'rejected' / 'failed_after_retries'
    draft_path: Path | None = None
    code_path: Path | None = None
    test_path: Path | None = None
    last_test_output: str = ""
    last_test_passed: bool | None = None
    repair_rounds: int = 0
    repair_log: list[dict[str, Any]] = field(default_factory=list)
    updated_at: float = 0.0


# ============================================================
# 状态持久化（SQLite）
# ============================================================


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tool_lifecycle (
    slug              TEXT PRIMARY KEY,
    status            TEXT NOT NULL,
    draft_path        TEXT,
    code_path         TEXT,
    test_path         TEXT,
    last_test_output  TEXT,
    last_test_passed  INTEGER,
    repair_rounds     INTEGER NOT NULL DEFAULT 0,
    repair_log        TEXT,
    updated_at        REAL NOT NULL
);
"""


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """老库迁移：补上 repair_rounds / repair_log 列。

    Why: 0.3 之前没有自修复字段，老用户库要无缝升级。
    """
    cur = conn.execute("PRAGMA table_info(tool_lifecycle)")
    existing = {row[1] for row in cur.fetchall()}
    if "repair_rounds" not in existing:
        conn.execute(
            "ALTER TABLE tool_lifecycle ADD COLUMN repair_rounds INTEGER NOT NULL DEFAULT 0"
        )
    if "repair_log" not in existing:
        conn.execute("ALTER TABLE tool_lifecycle ADD COLUMN repair_log TEXT")


class FactoryRegistry:
    """跟踪每个 slug 的生命周期状态。"""

    def __init__(self, db_path: Path) -> None:
        self._db = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            _ensure_columns(conn)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db)
        tune_for_multiprocess(conn)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert(self, status: FactoryStatus) -> None:
        with self._connect() as conn:
            last_passed_int: int | None
            if status.last_test_passed is None:
                last_passed_int = None
            else:
                last_passed_int = 1 if status.last_test_passed else 0
            conn.execute(
                """
                INSERT INTO tool_lifecycle
                    (slug, status, draft_path, code_path, test_path,
                     last_test_output, last_test_passed,
                     repair_rounds, repair_log, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    status=excluded.status,
                    draft_path=excluded.draft_path,
                    code_path=excluded.code_path,
                    test_path=excluded.test_path,
                    last_test_output=excluded.last_test_output,
                    last_test_passed=excluded.last_test_passed,
                    repair_rounds=excluded.repair_rounds,
                    repair_log=excluded.repair_log,
                    updated_at=excluded.updated_at
                """,
                (
                    status.slug,
                    status.status,
                    str(status.draft_path) if status.draft_path else None,
                    str(status.code_path) if status.code_path else None,
                    str(status.test_path) if status.test_path else None,
                    status.last_test_output,
                    last_passed_int,
                    status.repair_rounds,
                    json.dumps(status.repair_log, ensure_ascii=False)
                    if status.repair_log
                    else None,
                    status.updated_at or time.time(),
                ),
            )

    def get(self, slug: str) -> FactoryStatus | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tool_lifecycle WHERE slug = ?", (slug,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        return FactoryStatus(
            slug=d["slug"],
            status=d["status"],
            draft_path=Path(d["draft_path"]) if d["draft_path"] else None,
            code_path=Path(d["code_path"]) if d["code_path"] else None,
            test_path=Path(d["test_path"]) if d["test_path"] else None,
            last_test_output=d["last_test_output"] or "",
            last_test_passed=bool(d["last_test_passed"])
            if d["last_test_passed"] is not None
            else None,
            repair_rounds=d.get("repair_rounds") or 0,
            repair_log=json.loads(d["repair_log"]) if d.get("repair_log") else [],
            updated_at=d["updated_at"],
        )

    def all(self) -> list[FactoryStatus]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM tool_lifecycle ORDER BY updated_at DESC"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            out.append(
                FactoryStatus(
                    slug=d["slug"],
                    status=d["status"],
                    draft_path=Path(d["draft_path"]) if d["draft_path"] else None,
                    code_path=Path(d["code_path"]) if d["code_path"] else None,
                    test_path=Path(d["test_path"]) if d["test_path"] else None,
                    last_test_output=d["last_test_output"] or "",
                    last_test_passed=bool(d["last_test_passed"])
                    if d["last_test_passed"] is not None
                    else None,
                    repair_rounds=d.get("repair_rounds") or 0,
                    repair_log=json.loads(d["repair_log"]) if d.get("repair_log") else [],
                    updated_at=d["updated_at"],
                ),
            )
        return out


# ============================================================
# Code Generator
# ============================================================


_CODEGEN_SYSTEM = """\
你是玄玑工具工厂的代码生成器。给你一份工具草案 JSON，你产出**完整可运行**的 Python 代码：

要求：
1. 输出**两个**文件，用以下格式分隔：
```python:tool
# core/tools/staged/<slug>.py 的完整内容
...
```
```python:test
# tests/staged/test_<slug>.py 的完整内容（pytest）
...
```

2. 工具实现：
- 继承 xuanji.capability.tool.Tool
- name / description / risk / schema 与草案一致
- 用 ClassVar 标注 schema
- async def execute(self, args, ctx) -> ToolResult
- 不产生副作用以外的事——严格按 schema 接受参数
- 失败抛 ToolError 或返回 ToolResult(ok=False)

3. 单测：
- 至少 3 个测试：正常路径、边界、错误路径
- 用 pytest + tmp_path / tmp_factory 做 fixture
- 不依赖网络/外部进程；如需文件系统操作用 tmp_path
- 测试文件**必须**先 `sys.path.insert(0, str(Path(__file__).parent))`，再 `from <slug> import ...`，
  这样 subprocess 跑 pytest 时能从 staged 目录直接 import 同名模块

4. **不要**：
- 不写 import os / subprocess / shutil 之外的破坏性 import
- 不读环境变量 / 不读用户目录
- 不发网络请求（NET 风险工具暂不在 codegen 范围）
- 不动 sys.path / __builtins__ / monkeypatch 全局状态（除上面说的 sys.path.insert(0, ...) 外）

5. 严格遵守输出格式，姐姐会按代码块切割文件。
"""


_REPAIR_SYSTEM = """\
你是玄玑工具工厂的**修复助手**。上一轮生成的工具代码 + 单测跑挂了，
现在给你三样东西：(a) 原草案 JSON，(b) 失败那一版的代码与单测，(c) pytest 输出。

你要做的：
1. **找根因**——是工具实现 bug、还是测试断言写错、还是 import 路径不对？
2. 产出**修好后**的新代码与新单测，输出格式与初版一致：
```python:tool
...
```
```python:test
...
```
3. 修最小集：能不动的别动，把失败的根因解决掉。
4. 测试文件不要去掉 `sys.path.insert(0, str(Path(__file__).parent))` 这行——subprocess 跑测时靠它 import。
5. 不要写"修复说明"散文，只输出两个代码块即可。
"""


def _extract_blocks(text: str) -> tuple[str, str]:
    """从 LLM 输出里抽 ```python:tool 与 ```python:test 两段代码。"""
    tool_code = ""
    test_code = ""
    in_block: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```python:tool"):
            in_block = "tool"
            buf = []
            continue
        if stripped.startswith("```python:test"):
            in_block = "test"
            buf = []
            continue
        if stripped == "```" and in_block:
            joined = "\n".join(buf)
            if in_block == "tool":
                tool_code = joined
            elif in_block == "test":
                test_code = joined
            in_block = None
            buf = []
            continue
        if in_block:
            buf.append(line)
    return tool_code, test_code


# ============================================================
# ToolFactory：流程协调器
# ============================================================


class ToolFactory:
    """ToolFactory 协调四步流水线。"""

    def __init__(
        self,
        *,
        drafts_dir: Path,
        staged_dir: Path,
        published_dir: Path,
        registry: FactoryRegistry,
        profile: Profile | None = None,
        model: str | None = None,
    ) -> None:
        self.drafts_dir = drafts_dir
        self.staged_dir = staged_dir
        self.published_dir = published_dir
        self.registry = registry
        self.profile = profile
        self.model = model
        for d in (drafts_dir, staged_dir, published_dir):
            d.mkdir(parents=True, exist_ok=True)
        # __init__.py 让 published 成为可 import 的包
        init_file = published_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

    # ------ 1. 列举草案 ------

    def list_drafts(self) -> list[Path]:
        return sorted(self.drafts_dir.glob("*.json"))

    def load_draft(self, slug: str) -> dict[str, Any]:
        path = self.drafts_dir / f"{slug}.json"
        if not path.exists():
            raise FileNotFoundError(f"草案不存在：{path}")
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    # ------ 2. 生成代码（async，需 LLM） ------

    async def generate(self, slug: str) -> FactoryStatus:
        if self.profile is None:
            raise RuntimeError("ToolFactory 需要 profile 才能生成代码")
        draft = self.load_draft(slug)
        provider = build_provider(self.profile)
        prompt = (
            "工具草案：\n"
            + json.dumps(draft, ensure_ascii=False, indent=2)
            + "\n\n按 system 要求产出两个代码块。"
        )
        msg = await provider.chat(
            model=self.model or self.profile.default_model,
            messages=[Message(role="user", content=prompt)],
            system=_CODEGEN_SYSTEM,
            max_tokens=4096,
        )
        tool_code, test_code = _extract_blocks(msg.text)
        if not tool_code or not test_code:
            raise ValueError(
                f"LLM 输出格式不对，没找到 ```python:tool 与 ```python:test 块。"
                f"原文前 500 字：{msg.text[:500]}"
            )
        code_path = self.staged_dir / f"{slug}.py"
        test_path = self.staged_dir / f"test_{slug}.py"
        code_path.write_text(tool_code.strip() + "\n", encoding="utf-8")
        test_path.write_text(test_code.strip() + "\n", encoding="utf-8")

        status = FactoryStatus(
            slug=slug,
            status="generated",
            draft_path=self.drafts_dir / f"{slug}.json",
            code_path=code_path,
            test_path=test_path,
            updated_at=time.time(),
        )
        self.registry.upsert(status)
        return status

    # ------ 3. 单测（subprocess 隔离） ------

    def test(self, slug: str, *, timeout_sec: float = 60.0) -> FactoryStatus:
        existing = self.registry.get(slug)
        if existing is None or existing.code_path is None:
            raise FileNotFoundError(f"slug={slug} 还未生成代码，先 generate")
        test_path = existing.test_path
        if test_path is None or not test_path.exists():
            raise FileNotFoundError(f"测试文件不存在：{test_path}")
        # subprocess 跑 pytest 隔离环境
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", str(test_path)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            output = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
            passed = proc.returncode == 0
        except subprocess.TimeoutExpired:
            output = f"测试超时（{timeout_sec}s）"
            passed = False

        existing.last_test_output = output[-4000:]  # 截断防爆库
        existing.last_test_passed = passed
        existing.status = "tested" if passed else "generated"
        existing.updated_at = time.time()
        self.registry.upsert(existing)
        return existing

    # ------ 4. 发布 ------

    def publish(self, slug: str) -> FactoryStatus:
        existing = self.registry.get(slug)
        if existing is None:
            raise FileNotFoundError(f"slug={slug} 不在工厂注册表里")
        if existing.last_test_passed is not True:
            raise ValueError(
                f"slug={slug} 测试未通过或未跑过，不能 publish。"
                "先 xuanji tool test 跑过再来。"
            )
        if existing.code_path is None or not existing.code_path.exists():
            raise FileNotFoundError(f"代码文件不存在：{existing.code_path}")
        # 复制到 published/<slug>.py
        published_path = self.published_dir / f"{slug}.py"
        published_path.write_text(
            existing.code_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        existing.status = "published"
        existing.updated_at = time.time()
        self.registry.upsert(existing)
        return existing

    def reject(self, slug: str, reason: str = "") -> FactoryStatus:
        existing = self.registry.get(slug) or FactoryStatus(slug=slug, status="rejected")
        existing.status = "rejected"
        existing.last_test_output = f"rejected: {reason}".strip()
        existing.updated_at = time.time()
        self.registry.upsert(existing)
        return existing

    # ------ 5. 修复（async，需 LLM） ------

    async def repair(self, slug: str) -> FactoryStatus:
        """喂 LLM 当前代码 + pytest 输出，让它产出修好的版本。

        返回的 status 是修过 staged 文件后的快照，**不**自动跑 test——
        repair 只负责改代码，下一步是否 test 由 autofix 协调。
        """
        if self.profile is None:
            raise RuntimeError("ToolFactory 需要 profile 才能修复代码")
        existing = self.registry.get(slug)
        if existing is None or existing.code_path is None or existing.test_path is None:
            raise FileNotFoundError(f"slug={slug} 还没生成过代码，先 generate")
        if not existing.code_path.exists() or not existing.test_path.exists():
            raise FileNotFoundError(
                f"代码或测试文件丢失：{existing.code_path} / {existing.test_path}"
            )

        draft = self.load_draft(slug)
        broken_code = existing.code_path.read_text(encoding="utf-8")
        broken_test = existing.test_path.read_text(encoding="utf-8")
        provider = build_provider(self.profile)
        prompt = (
            "工具草案：\n"
            + json.dumps(draft, ensure_ascii=False, indent=2)
            + "\n\n失败的实现代码：\n```python:tool\n"
            + broken_code
            + "\n```\n\n失败的单测：\n```python:test\n"
            + broken_test
            + "\n```\n\npytest 输出（截断）：\n"
            + (existing.last_test_output or "(empty)")
            + "\n\n按 system 要求产出修好后的两个代码块。"
        )
        msg = await provider.chat(
            model=self.model or self.profile.default_model,
            messages=[Message(role="user", content=prompt)],
            system=_REPAIR_SYSTEM,
            max_tokens=4096,
        )
        tool_code, test_code = _extract_blocks(msg.text)
        if not tool_code or not test_code:
            raise ValueError(
                f"修复 LLM 输出格式不对，没找到 ```python:tool 与 ```python:test 块。"
                f"原文前 500 字：{msg.text[:500]}"
            )
        existing.code_path.write_text(tool_code.strip() + "\n", encoding="utf-8")
        existing.test_path.write_text(test_code.strip() + "\n", encoding="utf-8")

        existing.repair_rounds += 1
        existing.repair_log = [
            *existing.repair_log,
            {
                "round": existing.repair_rounds,
                "ts": time.time(),
                "prev_test_output_tail": (existing.last_test_output or "")[-800:],
            },
        ]
        # 修过代码后状态退回 generated，等下一步 test 复核
        existing.status = "generated"
        existing.last_test_passed = None
        existing.last_test_output = ""
        existing.updated_at = time.time()
        self.registry.upsert(existing)
        return existing

    # ------ 6. autofix：generate → test → 失败则 repair → test，最多 N 轮 ------

    async def autofix(self, slug: str, *, max_rounds: int = 3) -> FactoryStatus:
        """端到端跑 generate + 自修复回路。

        流程：
        1. 还没 generate 过 → 先 generate
        2. test → 通过则结束（status=tested）
        3. 失败则 repair → test，重复直到 max_rounds 用完
        4. 用完仍失败 → status='failed_after_retries'，等小宝介入
        """
        if max_rounds < 1:
            raise ValueError("max_rounds 至少 1")

        existing = self.registry.get(slug)
        if existing is None or existing.code_path is None:
            existing = await self.generate(slug)

        # 第 0 轮：原版 test
        existing = self.test(slug)
        if existing.last_test_passed:
            return existing

        # 第 1..N 轮：repair → test
        for _ in range(max_rounds):
            existing = await self.repair(slug)
            existing = self.test(slug)
            if existing.last_test_passed:
                return existing

        # 全跑完还失败：标记 failed_after_retries，等小宝介入
        existing.status = "failed_after_retries"
        existing.updated_at = time.time()
        self.registry.upsert(existing)
        return existing


__all__ = [
    "FactoryRegistry",
    "FactoryStatus",
    "ToolFactory",
    "_extract_blocks",
]
