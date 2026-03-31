"""
Compare CSI signals: empty garage vs 2 people — both from v4.1 TEXT format.
Generates spectral heatmaps, temporal plots, and per-node amplitude histograms.
"""

import gzip
import json
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

# ── paths ──────────────────────────────────────────────────────────────────
CAPTURES = Path("temp/captures")

EMPTY_CHUNKS = sorted(CAPTURES.glob("empty_garage_v41_baseline_chunk*.ndjson.gz"))
TWOPERSON_CHUNKS = sorted(CAPTURES.glob("2person_freeform_v41_chunk*.ndjson.gz"))

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

NODE_IP_TO_NAME = {
    "192.168.0.137": "n01", "192.168.0.117": "n02",
    "192.168.0.143": "n03", "192.168.0.125": "n04",
    "192.168.0.110": "n05", "192.168.0.132": "n06",
    "192.168.0.153": "n07",
}


def parse_csi_text_payload(b64_payload: str) -> tuple[dict, np.ndarray | None]:
    """Decode base64 CSI_DATA payload into metadata dict and amplitude array.

    Returns (metadata_dict, amplitude_array_or_None).
    """
    import base64
    try:
        decoded = base64.b64decode(b64_payload).decode("utf-8", errors="replace")
    except Exception:
        return {}, None

    if not decoded.startswith("CSI_DATA"):
        return {}, None

    # Split CSV but preserve the last field which is "[I Q I Q ...]"
    # Find the bracket-enclosed CSI array
    bracket_start = decoded.find('"[')
    if bracket_start < 0:
        bracket_start = decoded.find("[")
    if bracket_start < 0:
        return {}, None

    header_part = decoded[:bracket_start].rstrip(",")
    csi_part = decoded[bracket_start:].strip().strip('"').strip("[]").strip()

    header_fields = header_part.split(",")
    meta = {}
    # CSI_DATA,type,mac,router_mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,
    # not_sounding,aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,
    # channel,secondary_channel,local_timestamp,ant,sig_len,rx_state,
    # real_time_set,real_timestamp,csi_len
    field_names = [
        "tag", "type", "mac", "router_mac", "rssi", "rate", "sig_mode", "mcs",
        "bandwidth", "smoothing", "not_sounding", "aggregation", "stbc",
        "fec_coding", "sgi", "noise_floor", "ampdu_cnt", "channel",
        "secondary_channel", "local_timestamp", "ant", "sig_len", "rx_state",
        "real_time_set", "real_timestamp", "csi_len",
    ]
    for i, name in enumerate(field_names):
        if i < len(header_fields):
            meta[name] = header_fields[i]

    # Parse I,Q pairs from space-separated values
    try:
        vals = [int(v) for v in csi_part.split() if v.lstrip("-").isdigit()]
    except ValueError:
        return meta, None

    if len(vals) < 10 or len(vals) % 2 != 0:
        return meta, None

    arr = np.array(vals, dtype=np.float64)
    I_vals = arr[0::2]
    Q_vals = arr[1::2]
    amplitudes = np.sqrt(I_vals ** 2 + Q_vals ** 2)
    return meta, amplitudes


def load_text_csi_chunks(chunk_files: list[Path]) -> dict[str, list[np.ndarray]]:
    """Load TEXT-format CSI packets grouped by node name.

    Returns {node_name: [amplitude_array_per_packet, ...]}
    """
    node_data: dict[str, list[np.ndarray]] = defaultdict(list)

    for fpath in chunk_files:
        with gzip.open(fpath, "rt") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    pkt = json.loads(line)
                except json.JSONDecodeError:
                    continue

                src_ip = pkt.get("src_ip", "")
                node_name = NODE_IP_TO_NAME.get(src_ip, src_ip)

                b64 = pkt.get("payload_b64", "")
                if not b64:
                    continue

                meta, amps = parse_csi_text_payload(b64)
                if amps is not None and len(amps) > 0:
                    node_data[node_name].append(amps)

    return dict(node_data)


def pad_to_same_length(arrays: list[np.ndarray], target_len: int | None = None) -> np.ndarray:
    """Pad/truncate arrays to same length and stack."""
    if not arrays:
        return np.array([])
    if target_len is None:
        target_len = max(len(a) for a in arrays)
    result = np.zeros((len(arrays), target_len))
    for i, a in enumerate(arrays):
        n = min(len(a), target_len)
        result[i, :n] = a[:n]
    return result


def main():
    print(f"Empty chunks: {len(EMPTY_CHUNKS)}")
    print(f"2-person chunks: {len(TWOPERSON_CHUNKS)}")

    if not EMPTY_CHUNKS:
        print("ERROR: No empty garage v41 baseline chunks found!")
        sys.exit(1)
    if not TWOPERSON_CHUNKS:
        print("ERROR: No 2-person v41 chunks found!")
        sys.exit(1)

    empty_data = load_text_csi_chunks(EMPTY_CHUNKS)
    twop_data = load_text_csi_chunks(TWOPERSON_CHUNKS)

    print(f"\nEmpty data nodes: {sorted(empty_data.keys())} ({sum(len(v) for v in empty_data.values())} pkts)")
    print(f"2-person nodes:   {sorted(twop_data.keys())} ({sum(len(v) for v in twop_data.values())} pkts)")

    if not empty_data or not twop_data:
        print("\nNo CSI amplitude data extracted. Checking raw packet structure...")
        # Debug: show first packet structure
        for label, chunks in [("empty", EMPTY_CHUNKS), ("2person", TWOPERSON_CHUNKS)]:
            with gzip.open(chunks[0], "rt") as f:
                for i, line in enumerate(f):
                    if i >= 3:
                        break
                    pkt = json.loads(line.strip())
                    print(f"\n{label} pkt {i} keys: {sorted(pkt.keys())}")
                    for k, v in pkt.items():
                        vstr = str(v)[:120]
                        print(f"  {k}: {vstr}")
        sys.exit(1)

    nodes = sorted(set(list(empty_data.keys()) + list(twop_data.keys())))
    if not nodes:
        print("No common nodes!")
        sys.exit(1)

    # Determine common subcarrier count
    all_lens = []
    for d in [empty_data, twop_data]:
        for pkts in d.values():
            for p in pkts[:5]:
                all_lens.append(len(p))
    sc_count = int(np.median(all_lens)) if all_lens else 64

    print(f"\nSubcarrier count (median): {sc_count}")
    print(f"Nodes: {nodes}")

    # ── FIGURE 1: Per-node mean amplitude comparison ───────────────────────
    fig1, axes1 = plt.subplots(len(nodes), 1, figsize=(14, 3 * len(nodes)), sharex=True)
    if len(nodes) == 1:
        axes1 = [axes1]

    for i, node in enumerate(nodes):
        ax = axes1[i]
        for label, data, color in [("Empty", empty_data, "#2196F3"), ("2 person", twop_data, "#F44336")]:
            if node in data and data[node]:
                mat = pad_to_same_length(data[node], sc_count)
                mean = np.mean(mat, axis=0)
                std = np.std(mat, axis=0)
                x = np.arange(sc_count)
                ax.plot(x, mean, color=color, label=f"{label} (n={len(data[node])})", linewidth=1.2)
                ax.fill_between(x, mean - std, mean + std, alpha=0.15, color=color)
        ax.set_ylabel("Amplitude")
        ax.set_title(f"{node}", fontweight="bold")
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.3)

    axes1[-1].set_xlabel("Subcarrier index")
    fig1.suptitle("CSI Amplitude: Empty vs 2-Person (v4.1 TEXT format)", fontsize=14, fontweight="bold")
    fig1.tight_layout()
    fig1.savefig(OUTPUT_DIR / "csi_v41_amplitude_comparison.png", dpi=150)
    print(f"\nSaved: {OUTPUT_DIR / 'csi_v41_amplitude_comparison.png'}")

    # ── FIGURE 2: Cohen's d heatmap ───────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(14, max(4, len(nodes) * 0.8)))
    cohens_d = np.zeros((len(nodes), sc_count))

    for i, node in enumerate(nodes):
        if node in empty_data and node in twop_data and empty_data[node] and twop_data[node]:
            e_mat = pad_to_same_length(empty_data[node], sc_count)
            t_mat = pad_to_same_length(twop_data[node], sc_count)
            e_mean = np.mean(e_mat, axis=0)
            t_mean = np.mean(t_mat, axis=0)
            pooled_std = np.sqrt((np.var(e_mat, axis=0) + np.var(t_mat, axis=0)) / 2)
            pooled_std[pooled_std < 1e-6] = 1e-6
            cohens_d[i] = (t_mean - e_mean) / pooled_std

    im = ax2.imshow(cohens_d, aspect="auto", cmap="RdBu_r", vmin=-5, vmax=5,
                    interpolation="nearest")
    ax2.set_yticks(range(len(nodes)))
    ax2.set_yticklabels(nodes)
    ax2.set_xlabel("Subcarrier index")
    ax2.set_title("Cohen's d: 2-Person vs Empty (blue=lower, red=higher with people)", fontweight="bold")
    plt.colorbar(im, ax=ax2, label="Cohen's d")
    fig2.tight_layout()
    fig2.savefig(OUTPUT_DIR / "csi_v41_cohens_d_heatmap.png", dpi=150)
    print(f"Saved: {OUTPUT_DIR / 'csi_v41_cohens_d_heatmap.png'}")

    # ── FIGURE 3: Temporal amplitude (first 120 packets per node) ─────────
    fig3, axes3 = plt.subplots(len(nodes), 1, figsize=(14, 2.5 * len(nodes)), sharex=True)
    if len(nodes) == 1:
        axes3 = [axes3]

    for i, node in enumerate(nodes):
        ax = axes3[i]
        for label, data, color in [("Empty", empty_data, "#2196F3"), ("2 person", twop_data, "#F44336")]:
            if node in data and data[node]:
                # Mean amplitude per packet (temporal series)
                pkts = data[node][:200]
                mean_per_pkt = [np.mean(p) for p in pkts]
                ax.plot(mean_per_pkt, color=color, alpha=0.7, linewidth=0.8, label=label)
        ax.set_ylabel("Mean amp")
        ax.set_title(f"{node}", fontweight="bold", fontsize=10)
        ax.legend(loc="upper right", fontsize=7)
        ax.grid(True, alpha=0.3)

    axes3[-1].set_xlabel("Packet index")
    fig3.suptitle("Temporal Mean Amplitude per Packet", fontsize=14, fontweight="bold")
    fig3.tight_layout()
    fig3.savefig(OUTPUT_DIR / "csi_v41_temporal_comparison.png", dpi=150)
    print(f"Saved: {OUTPUT_DIR / 'csi_v41_temporal_comparison.png'}")

    # ── FIGURE 4: Amplitude distribution histograms ───────────────────────
    fig4, axes4 = plt.subplots(2, (len(nodes) + 1) // 2, figsize=(16, 8))
    axes4 = axes4.flatten()

    for i, node in enumerate(nodes):
        if i >= len(axes4):
            break
        ax = axes4[i]
        for label, data, color in [("Empty", empty_data, "#2196F3"), ("2 person", twop_data, "#F44336")]:
            if node in data and data[node]:
                all_amps = np.concatenate(data[node])
                ax.hist(all_amps, bins=50, alpha=0.5, color=color, label=label, density=True)
        ax.set_title(node, fontweight="bold", fontsize=10)
        ax.legend(fontsize=7)
        ax.set_xlabel("Amplitude")

    for j in range(i + 1, len(axes4)):
        axes4[j].set_visible(False)

    fig4.suptitle("Amplitude Distribution: Empty vs 2-Person", fontsize=14, fontweight="bold")
    fig4.tight_layout()
    fig4.savefig(OUTPUT_DIR / "csi_v41_amplitude_histograms.png", dpi=150)
    print(f"Saved: {OUTPUT_DIR / 'csi_v41_amplitude_histograms.png'}")

    # ── Summary stats ─────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY: Top discriminating subcarriers (|Cohen's d| > 2)")
    print("=" * 60)
    for i, node in enumerate(nodes):
        high_d = np.where(np.abs(cohens_d[i]) > 2.0)[0]
        if len(high_d) > 0:
            top5 = high_d[np.argsort(np.abs(cohens_d[i, high_d]))[-5:]][::-1]
            vals = [(int(sc), f"{cohens_d[i, sc]:+.2f}") for sc in top5]
            print(f"  {node}: {len(high_d)} subcarriers, top: {vals}")
        else:
            print(f"  {node}: no subcarriers with |d|>2")

    print("\nDone!")


if __name__ == "__main__":
    main()
