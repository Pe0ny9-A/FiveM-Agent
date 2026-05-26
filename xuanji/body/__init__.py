"""工造司 · 工具运行时与治理。

M0 阶段先实装 InProcSandbox（同进程执行 + 超时）。Subprocess / Docker / WASM
留到 M2+ 按 RiskTag 选档。
"""

from xuanji.body.sandbox import InProcSandbox, Sandbox

__all__ = ["InProcSandbox", "Sandbox"]
