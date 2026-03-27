"""
Canonical CSI node inventory shared by recording and API surfaces.
"""

from __future__ import annotations

from typing import Final

CSI_NODE_INVENTORY: Final[list[dict[str, object]]] = [
    {
        "node_id": "node01",
        "ip": "192.168.1.137",
        "role": "core",
        "required": True,
        "position_known": True,
    },
    {
        "node_id": "node02",
        "ip": "192.168.1.117",
        "role": "core",
        "required": True,
        "position_known": True,
    },
    {
        "node_id": "node03",
        "ip": "192.168.1.101",
        "role": "core",
        "required": True,
        "position_known": True,
    },
    {
        "node_id": "node04",
        "ip": "192.168.1.125",
        "role": "core",
        "required": True,
        "position_known": True,
    },
    {
        "node_id": "node05",
        "ip": "192.168.1.33",
        "role": "shadow",
        "required": False,
        "position_known": True,
    },
    {
        "node_id": "node06",
        "ip": "192.168.1.77",
        "role": "shadow",
        "required": False,
        "position_known": True,
    },
    {
        "node_id": "node07",
        "ip": "192.168.1.41",
        "role": "shadow",
        "required": False,
        "position_known": True,
    },
]

CORE_NODE_IPS: Final[list[str]] = sorted(
    str(item["ip"]) for item in CSI_NODE_INVENTORY if bool(item["required"])
)
NODE_IPS: Final[list[str]] = sorted(str(item["ip"]) for item in CSI_NODE_INVENTORY)
NODE_NAMES: Final[dict[str, str]] = {
    str(item["ip"]): str(item["node_id"]) for item in CSI_NODE_INVENTORY
}
NODE_ROLES: Final[dict[str, str]] = {
    str(item["node_id"]): str(item["role"]) for item in CSI_NODE_INVENTORY
}


def list_csi_nodes() -> list[dict[str, object]]:
    """Return a copy of the operator-visible CSI node inventory."""
    return [dict(item) for item in CSI_NODE_INVENTORY]
