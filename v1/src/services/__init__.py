"""Services package for WiFi-DensePose API.

Expose heavy service classes lazily so lightweight tooling can import
`src.services.*` modules without pulling the entire runtime graph.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ServiceOrchestrator",
    "HealthCheckService",
    "MetricsService",
    "PoseService",
    "StreamService",
    "HardwareService",
    "FP2Service",
]

_LAZY_EXPORTS = {
    "ServiceOrchestrator": (".orchestrator", "ServiceOrchestrator"),
    "HealthCheckService": (".health_check", "HealthCheckService"),
    "MetricsService": (".metrics", "MetricsService"),
    "PoseService": (".pose_service", "PoseService"),
    "StreamService": (".stream_service", "StreamService"),
    "HardwareService": (".hardware_service", "HardwareService"),
    "FP2Service": (".fp2_service", "FP2Service"),
}


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
