"""沙箱协议与同进程实现。"""

from core.body.sandbox.base import Sandbox
from core.body.sandbox.inproc import InProcSandbox

__all__ = ["InProcSandbox", "Sandbox"]
