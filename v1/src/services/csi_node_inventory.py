"""
Canonical CSI node inventory shared by recording and API surfaces.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final

CSI_NODE_INVENTORY: Final[list[dict[str, object]]] = [
    {
        "node_id": "node01",
        "mac": "3c:0f:02:d9:80:98",
        "ip": "192.168.0.137",
        "role": "core",
        "required": True,
        "position_known": True,
        "mesh_enabled": False,
        "peer_links": ["node02", "node03", "node04", "node05", "node06", "node07"],
    },
    {
        "node_id": "node02",
        "mac": "1c:db:d4:77:f5:64",
        "ip": "192.168.0.117",
        "role": "core",
        "required": True,
        "position_known": True,
        "mesh_enabled": False,
        "peer_links": ["node01", "node03", "node04", "node05", "node06", "node07"],
    },
    {
        "node_id": "node03",
        "mac": "3c:0f:02:d6:b1:e4",
        "ip": "192.168.0.144",
        "role": "core",
        "required": True,
        "position_known": True,
        "mesh_enabled": False,
        "peer_links": ["node01", "node02", "node04", "node05", "node06", "node07"],
    },
    {
        "node_id": "node04",
        "mac": "3c:0f:02:d7:0b:44",
        "ip": "192.168.0.125",
        "role": "core",
        "required": True,
        "position_known": True,
        "mesh_enabled": False,
        "peer_links": ["node01", "node02", "node03", "node05", "node06", "node07"],
    },
    {
        "node_id": "node05",
        "mac": "1c:db:d4:77:ed:b0",
        "ip": "192.168.0.110",
        "role": "core",
        "required": True,
        "position_known": True,
        "mesh_enabled": False,
        "peer_links": ["node01", "node02", "node03", "node04", "node06", "node07"],
    },
    {
        "node_id": "node06",
        "mac": "3c:0f:02:d7:0b:14",
        "ip": "192.168.0.132",
        "role": "core",
        "required": True,
        "position_known": True,
        "mesh_enabled": False,
        "peer_links": ["node01", "node02", "node03", "node04", "node05", "node07"],
    },
    {
        "node_id": "node07",
        "mac": "1c:db:d4:77:ed:40",
        "ip": "192.168.0.153",
        "role": "core",
        "required": True,
        "position_known": True,
        "mesh_enabled": False,
        "peer_links": ["node01", "node02", "node03", "node04", "node05", "node06"],
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

# MAC-based node identification (network-agnostic)
MAC_TO_NODE_ID: Final[dict[str, str]] = {
    str(item["mac"]).lower(): str(item["node_id"])
    for item in CSI_NODE_INVENTORY if "mac" in item
}
NODE_ID_TO_MAC: Final[dict[str, str]] = {
    str(item["node_id"]): str(item["mac"]).lower()
    for item in CSI_NODE_INVENTORY
    if item.get("node_id") and item.get("mac")
}
NODE_ID_TO_DEFAULT_IP: Final[dict[str, str]] = {
    str(item["node_id"]): str(item["ip"]) for item in CSI_NODE_INVENTORY
}

# Dynamic IP mapping — updated at runtime when nodes are discovered
_dynamic_ip_map: dict[str, str] = {}  # actual_ip → canonical_ip

def resolve_ip(actual_ip: str, mac: str | None = None) -> str:
    """Resolve actual IP to canonical IP used by model/features.
    If MAC is provided and matches a known node, update the dynamic mapping."""
    if mac:
        mac_lower = mac.lower()
        node_id = MAC_TO_NODE_ID.get(mac_lower)
        if node_id:
            canonical_ip = NODE_ID_TO_DEFAULT_IP[node_id]
            if actual_ip != canonical_ip:
                _dynamic_ip_map[actual_ip] = canonical_ip
            return canonical_ip
    return _dynamic_ip_map.get(actual_ip, actual_ip)


def list_csi_nodes() -> list[dict[str, object]]:
    """Return a copy of the operator-visible CSI node inventory."""
    return [dict(item) for item in CSI_NODE_INVENTORY]


# ── ESP-NOW mesh link topology ──────────────────────────────────────────
# With 7 nodes (n01-n07) in a full mesh, each broadcasts to the other
# 6 nodes = 42 peer links. Plus 7 router->node links = 49 total links.
# TDMA cycle: 7 slots × 10ms = 70ms → ~14 Hz per link.

MESH_CORE_NODES: Final[list[str]] = ["node01", "node02", "node03", "node04", "node05", "node06", "node07"]
MESH_CORE_SHORT: Final[list[str]] = ["n01", "n02", "n03", "n04", "n05", "n06", "n07"]

def get_mesh_peer_links(node_short_names: list[str] | None = None) -> list[tuple[str, str]]:
    """Generate all peer link pairs (receiver, source) for a mesh topology.

    Args:
        node_short_names: list of short node names (e.g. ["n01","n02","n03","n04"]).
                          Defaults to the 4 core mesh nodes.

    Returns:
        List of (receiver, source) tuples representing directed links.
    """
    nodes = node_short_names or MESH_CORE_SHORT
    return [(rx, tx) for rx in nodes for tx in nodes if rx != tx]


def get_all_link_ids(node_short_names: list[str] | None = None) -> list[str]:
    """Generate all link_ids for a mesh + router topology.

    Returns link_ids like "n01_n02" (peer) and "n01_router" (router).
    """
    nodes = node_short_names or MESH_CORE_SHORT
    links = []
    # Peer links
    for rx, tx in get_mesh_peer_links(nodes):
        links.append(f"{rx}_{tx}")
    # Router links
    for n in nodes:
        links.append(f"{n}_router")
    return sorted(links)


# ── Mesh link quality tracking ───────────────────────────────────────────


@dataclass
class LinkQuality:
    """Quality metrics for a single directed link (src -> dst)."""

    src: str
    dst: str
    packets_per_sec: float = 0.0
    rssi_mean: float = -100.0
    rssi_std: float = 0.0
    drop_rate: float = 0.0
    last_seen: float = 0.0  # monotonic timestamp

    @property
    def healthy(self) -> bool:
        """Link is considered healthy if it has >5 pps and RSSI > -80."""
        return self.packets_per_sec > 5.0 and self.rssi_mean > -80.0


# Runtime link quality state — updated by the mesh link monitor or CSI ingest
_link_quality_store: dict[tuple[str, str], LinkQuality] = {}


def update_link_quality(
    src: str,
    dst: str,
    pps: float,
    rssi_mean: float = -100.0,
    rssi_std: float = 0.0,
    drop_rate: float = 0.0,
) -> None:
    """Update the quality metrics for a specific link.

    Args:
        src: Source node short name (e.g. "n01" or "router").
        dst: Destination node short name.
        pps: Current packets-per-second rate.
        rssi_mean: Mean RSSI over the measurement window.
        rssi_std: Standard deviation of RSSI.
        drop_rate: Fraction of packets dropped (0.0 - 1.0).
    """
    key = (src, dst)
    _link_quality_store[key] = LinkQuality(
        src=src,
        dst=dst,
        packets_per_sec=pps,
        rssi_mean=rssi_mean,
        rssi_std=rssi_std,
        drop_rate=drop_rate,
        last_seen=time.monotonic(),
    )


def get_link_quality(src: str, dst: str) -> LinkQuality | None:
    """Get current quality for a single link, or None if not tracked."""
    return _link_quality_store.get((src, dst))


def get_active_links(
    min_pps: float = 1.0,
    max_age_s: float = 30.0,
) -> list[tuple[str, str, LinkQuality]]:
    """Return list of (src, dst, quality) tuples for all active links.

    A link is considered active if it has been seen within *max_age_s*
    and its packet rate exceeds *min_pps*.

    Args:
        min_pps: Minimum packets-per-second to consider a link active.
        max_age_s: Maximum age in seconds since last update.

    Returns:
        Sorted list of (src, dst, LinkQuality) tuples.
    """
    now = time.monotonic()
    active: list[tuple[str, str, LinkQuality]] = []
    for (src, dst), lq in _link_quality_store.items():
        age = now - lq.last_seen
        if age <= max_age_s and lq.packets_per_sec >= min_pps:
            active.append((src, dst, lq))
    return sorted(active, key=lambda x: (x[0], x[1]))


def get_mesh_status_summary() -> dict[str, object]:
    """Return a summary of mesh health for the operator UI.

    Returns dict with keys: total_links, active_links, healthy_links,
    nodes_with_mesh, link_details.
    """
    active = get_active_links(min_pps=0.5)
    healthy = [a for a in active if a[2].healthy]

    mesh_nodes = {
        str(item["node_id"])
        for item in CSI_NODE_INVENTORY
        if item.get("mesh_enabled")
    }

    return {
        "total_links": len(get_all_link_ids()),
        "active_links": len(active),
        "healthy_links": len(healthy),
        "nodes_with_mesh": sorted(mesh_nodes),
        "link_details": [
            {
                "src": src,
                "dst": dst,
                "pps": round(lq.packets_per_sec, 1),
                "rssi": round(lq.rssi_mean, 1),
                "healthy": lq.healthy,
            }
            for src, dst, lq in active
        ],
    }
