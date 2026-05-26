"""司辰阁 · 横切权限与高危确认中间件。

核心组件：
- Verdict：策略裁决结果（pass / hitl / deny）
- Policy：根据工具与参数评估风险，给出 Verdict
- HITLBridge：抽象的"询问用户"接口，CLI/Web/Tauri 各自实现
- GateInterceptor：注入到 Conductor.dispatch 的中间件，把 Policy 与 HITLBridge 串起来
"""

from core.gate.bridge import HITLBridge, NoOpHITLBridge
from core.gate.interceptor import GateInterceptor, GateRefusal
from core.gate.policy import DefaultPolicy, Policy, Verdict, VerdictKind

__all__ = [
    "DefaultPolicy",
    "GateInterceptor",
    "GateRefusal",
    "HITLBridge",
    "NoOpHITLBridge",
    "Policy",
    "Verdict",
    "VerdictKind",
]
