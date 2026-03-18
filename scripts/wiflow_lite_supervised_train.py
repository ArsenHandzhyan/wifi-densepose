#!/usr/bin/env python3
"""
WiFlow-lite Supervised Event Encoder — Track A experiment scaffold.

Academic source: WiFlow (arXiv:2602.08661)
Adapted for: ESP32 CSI 4-node event classification (empty/static/motion)

Key differences from WiFlow:
  - WiFlow: 540 channels (18 links × 30 subcarriers), 600 Hz, pose regression
  - Ours:   208 channels (4 nodes × 52 active subcarriers), 22 pps, 3-class events
  - WiFlow: 4.82M params, Smooth L1 loss, 15-joint output
  - Ours:   ~200-500K params, CrossEntropy, 3-class output

Architecture (from WiFlow source code review):
  1. TCN encoder: causal dilated 1D Conv, dilations [1,2,4,8]
  2. Asymmetric 2D Conv: stride (1,2) — preserve time, reduce subcarrier
  3. Classification head: GlobalAvgPool → Linear → 3 classes

Usage:
  venv/bin/python3 scripts/wiflow_lite_supervised_train.py \
    --dataset-path temp/analysis/wiflow_lite_dataset.npz \
    --mode supervised \
    --epochs 100

Pre-integration baseline (AGENTCLOUD_ACADEMIC_BASELINE_FREEZE):
  - HGB Binary BalAcc: 0.856 (V28 smooth)
  - HGB 3-class macro F1: 0.628 (V27)
  - Features: 40-106 hand-crafted, MI-ranked
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

import numpy as np

# --- Hyperparameters (from WiFlow deep-dive, adapted) ---

HPARAMS = {
    # Input shape
    "n_nodes": 4,
    "n_subcarriers_active": 52,  # indices 6-58 of 128 total
    "window_sec": 4.0,
    "stride_sec": 1.0,
    "pps_per_node": 22,
    # => input tensor: [B, 4*52, 4*22] = [B, 208, 88]

    # TCN encoder (adapted from WiFlow: 540→360→240, dilations [1,2,4])
    "tcn_channels": [208, 128, 64, 32],
    "tcn_kernel_size": 3,
    "tcn_dilations": [1, 2, 4, 8],
    "tcn_dropout": 0.3,  # WiFlow uses 0.5, we reduce (smaller dataset)

    # Classification head
    "n_classes": 3,  # empty, occupied_static, large_motion
    "class_names": ["empty", "occupied_static", "large_motion"],

    # Training (adapted from WiFlow: AdamW lr=1e-4, 50 epochs)
    "optimizer": "adamw",
    "lr": 1e-4,
    "weight_decay": 5e-5,
    "batch_size": 32,  # WiFlow uses 64, we have less data
    "epochs": 100,
    "patience": 15,  # early stopping
    "scheduler": "plateau",  # ReduceLROnPlateau, factor=0.5, patience=5

    # Evaluation
    "eval_method": "stratified_group_kfold",
    "n_folds": 5,
    "holdout_by": "epoch",  # group by recording epoch

    # WiFlow reference metrics (for context only)
    "wiflow_pck02": 0.9700,
    "wiflow_params": 4_820_000,
    "wiflow_data_bandwidth_per_sec": 324_000,
    "our_data_bandwidth_per_sec": 11_264,
}


def build_raw_tensor_from_ndjson(ndjson_gz_path: str, window_sec: float = 4.0,
                                  stride_sec: float = 1.0) -> np.ndarray:
    """
    Convert raw .ndjson.gz CSI capture to tensor windows.

    Returns: array of shape [N_windows, 4_nodes, 52_subcarriers, T_timesteps]
    where T_timesteps = int(window_sec * pps_per_node) ≈ 88

    This replaces the hand-crafted feature extraction
    (mean, std, max, range, pps, temporal_var, etc.)
    with raw subcarrier-time tensors that preserve structure.
    """
    import gzip

    # Active subcarrier indices (lo band: 6-58, skip dead center)
    ACTIVE_LO = list(range(6, 59))  # 53 subcarriers, take first 52
    ACTIVE_LO = ACTIVE_LO[:52]

    node_ips = {
        "192.168.1.137": 0,  # node01
        "192.168.1.117": 1,  # node02
        "192.168.1.101": 2,  # node03
        "192.168.1.125": 3,  # node04
    }

    # Parse packets
    packets = {i: [] for i in range(4)}
    with gzip.open(ndjson_gz_path, "rt") as f:
        for line in f:
            try:
                pkt = json.loads(line)
            except json.JSONDecodeError:
                continue
            src_ip = pkt.get("src_ip", "")
            if src_ip not in node_ips:
                continue
            node_idx = node_ips[src_ip]
            ts_ns = pkt.get("ts_ns", 0)

            # Decode IQ payload
            import base64
            payload_b64 = pkt.get("payload_b64", "")
            if not payload_b64:
                continue
            raw = base64.b64decode(payload_b64)
            iq = np.frombuffer(raw, dtype=np.int8)
            if len(iq) < 256:
                continue

            # Extract amplitude from IQ pairs
            i_vals = iq[0::2].astype(np.float32)
            q_vals = iq[1::2].astype(np.float32)
            amplitude = np.sqrt(i_vals**2 + q_vals**2)

            # Take active subcarriers only
            if len(amplitude) >= max(ACTIVE_LO) + 1:
                amp_active = amplitude[ACTIVE_LO]
                packets[node_idx].append((ts_ns, amp_active))

    # Sort by timestamp per node
    for nid in range(4):
        packets[nid].sort(key=lambda x: x[0])

    if not any(packets[nid] for nid in range(4)):
        return np.array([])

    # Find common time range
    all_ts = []
    for nid in range(4):
        if packets[nid]:
            all_ts.extend([p[0] for p in packets[nid]])
    t_start = min(all_ts)
    t_end = max(all_ts)
    duration_sec = (t_end - t_start) / 1e9

    # Build windows
    pps = HPARAMS["pps_per_node"]
    samples_per_window = int(window_sec * pps)
    stride_samples = int(stride_sec * pps)

    windows = []
    window_start_ns = t_start
    window_duration_ns = int(window_sec * 1e9)
    stride_ns = int(stride_sec * 1e9)

    while window_start_ns + window_duration_ns <= t_end:
        window_end_ns = window_start_ns + window_duration_ns
        tensor = np.zeros((4, 52, samples_per_window), dtype=np.float32)

        for nid in range(4):
            node_pkts = [
                p for p in packets[nid]
                if window_start_ns <= p[0] < window_end_ns
            ]
            for idx, (_, amp) in enumerate(node_pkts[:samples_per_window]):
                tensor[nid, :, idx] = amp

        windows.append(tensor)
        window_start_ns += stride_ns

    if windows:
        return np.stack(windows)
    return np.array([])


class TemporalBlock:
    """
    WiFlow-style causal temporal block.
    2× Conv1d + Chomp (causal padding) + ReLU + Dropout + Residual.

    From WiFlow source: kernel_size=3, dilations=[1,2,4]
    Our adaptation: dilations=[1,2,4,8] for larger receptive field
    """
    pass  # PyTorch implementation below


def build_model_pytorch():
    """
    Build WiFlow-lite TCN classifier.

    Architecture (adapted from WiFlow source code):
      Input: [B, 208, 88] (4nodes × 52subcarriers, 88 timesteps)
      TCN: 4 TemporalBlocks [208→128→64→32], dilations [1,2,4,8], kernel=3
      GlobalAvgPool over time dimension
      Linear: 32 → 3 (empty/static/motion)

    WiFlow original:
      Input: [B, 540, 20]
      TCN: 3 blocks [540→360→240], dilations [1,2,4], kernel=3
      Asymmetric Conv2d: reduces subcarrier dim 240→15
      Dual Axial Attention
      Decoder: Conv2d 64→2, AdaptiveAvgPool to (15,1) → 15 joints × 2 coords
    """
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        print("ERROR: PyTorch not installed. Install with: pip install torch")
        sys.exit(1)

    class Chomp1d(nn.Module):
        """Remove future timesteps for causal convolution (from WiFlow)."""
        def __init__(self, chomp_size):
            super().__init__()
            self.chomp_size = chomp_size

        def forward(self, x):
            return x[:, :, :-self.chomp_size].contiguous()

    class TemporalBlock(nn.Module):
        """WiFlow-style temporal block with causal convolutions."""
        def __init__(self, in_ch, out_ch, kernel_size, dilation, dropout):
            super().__init__()
            padding = (kernel_size - 1) * dilation
            self.conv1 = nn.Conv1d(in_ch, out_ch, kernel_size,
                                    padding=padding, dilation=dilation)
            self.chomp1 = Chomp1d(padding)
            self.relu1 = nn.ReLU()
            self.drop1 = nn.Dropout(dropout)

            self.conv2 = nn.Conv1d(out_ch, out_ch, kernel_size,
                                    padding=padding, dilation=dilation)
            self.chomp2 = Chomp1d(padding)
            self.relu2 = nn.ReLU()
            self.drop2 = nn.Dropout(dropout)

            self.downsample = nn.Conv1d(in_ch, out_ch, 1) if in_ch != out_ch else None
            self.relu = nn.ReLU()

        def forward(self, x):
            out = self.drop1(self.relu1(self.chomp1(self.conv1(x))))
            out = self.drop2(self.relu2(self.chomp2(self.conv2(out))))
            res = x if self.downsample is None else self.downsample(x)
            return self.relu(out + res)

    class WiFlowLiteClassifier(nn.Module):
        """
        WiFlow-lite adapted for ESP32 CSI event classification.
        ~200-500K params vs WiFlow's 4.82M.
        """
        def __init__(self, hparams=None):
            super().__init__()
            hp = hparams or HPARAMS
            channels = hp["tcn_channels"]
            kernel = hp["tcn_kernel_size"]
            dilations = hp["tcn_dilations"]
            dropout = hp["tcn_dropout"]

            # TCN encoder
            blocks = []
            for i in range(len(channels) - 1):
                blocks.append(TemporalBlock(
                    channels[i], channels[i + 1],
                    kernel, dilations[i], dropout
                ))
            self.tcn = nn.Sequential(*blocks)

            # Classification head
            self.pool = nn.AdaptiveAvgPool1d(1)
            self.classifier = nn.Linear(channels[-1], hp["n_classes"])

        def forward(self, x):
            # x: [B, 208, 88] (channels=4*52 subcarriers, time=88)
            out = self.tcn(x)        # [B, 32, 88]
            out = self.pool(out)      # [B, 32, 1]
            out = out.squeeze(-1)     # [B, 32]
            return self.classifier(out)  # [B, 3]

    model = WiFlowLiteClassifier(HPARAMS)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"WiFlow-lite model: {n_params:,} parameters")
    print(f"  (WiFlow original: {HPARAMS['wiflow_params']:,} parameters)")
    print(f"  (Reduction: {HPARAMS['wiflow_params'] / n_params:.1f}×)")
    return model


def main():
    parser = argparse.ArgumentParser(description="WiFlow-lite supervised training")
    parser.add_argument("--dataset-path", type=str, default=None,
                        help="Path to pre-built dataset .npz")
    parser.add_argument("--capture-dir", type=str, default="temp/captures",
                        help="Directory with .ndjson.gz captures")
    parser.add_argument("--mode", choices=["supervised", "build_dataset", "dry_run"],
                        default="dry_run",
                        help="Mode: supervised training, build dataset, or dry run")
    parser.add_argument("--epochs", type=int, default=HPARAMS["epochs"])
    parser.add_argument("--output-dir", type=str, default="output")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    if args.mode == "dry_run":
        print("=" * 60)
        print("WiFlow-lite Event Encoder — DRY RUN")
        print("=" * 60)
        print()
        print("Hyperparameters:")
        for k, v in HPARAMS.items():
            print(f"  {k}: {v}")
        print()

        model = build_model_pytorch()
        print()
        print("Input shape: [B, 208, 88]")
        print("  = [batch, 4_nodes × 52_subcarriers, 4sec × 22pps]")
        print()
        print("Baseline to beat:")
        print("  HGB Binary BalAcc: 0.856")
        print("  HGB 3-class macro F1: 0.628")
        print()
        print("To run supervised training:")
        print(f"  {sys.executable} {__file__} --mode supervised --dataset-path <path>")
        return

    if args.mode == "build_dataset":
        print("Building raw tensor dataset from captures...")
        capture_dir = Path(args.capture_dir)
        ndjson_files = sorted(capture_dir.glob("*.ndjson.gz"))
        print(f"Found {len(ndjson_files)} capture files")

        all_windows = []
        all_labels = []
        all_groups = []

        for f in ndjson_files:
            # Load summary for labels
            summary_path = f.with_suffix("").with_suffix(".summary.json")
            if not summary_path.exists():
                continue
            with open(summary_path) as sf:
                summary = json.load(sf)

            person_count = summary.get("person_count_expected", -1)
            if person_count < 0:
                continue

            # Map to 3-class label
            label_name = summary.get("label_prefix", f.stem)
            if person_count == 0:
                label = 0  # empty
            elif "static" in label_name or "hold" in label_name:
                label = 1  # occupied_static
            else:
                label = 2  # large_motion (default for occupied + any activity)

            windows = build_raw_tensor_from_ndjson(str(f))
            if len(windows) == 0:
                continue

            n = len(windows)
            all_windows.append(windows)
            all_labels.extend([label] * n)
            # Group by capture file (for GroupKFold)
            group_id = hash(f.stem) % 10000
            all_groups.extend([group_id] * n)

            print(f"  {f.name}: {n} windows, label={HPARAMS['class_names'][label]}")

        if all_windows:
            X = np.concatenate(all_windows, axis=0)
            y = np.array(all_labels, dtype=np.int64)
            groups = np.array(all_groups, dtype=np.int64)

            out_path = output_dir / f"wiflow_lite_dataset_{ts}.npz"
            np.savez_compressed(out_path, X=X, y=y, groups=groups)
            print(f"\nSaved dataset: {out_path}")
            print(f"  Shape: X={X.shape}, y={y.shape}")
            print(f"  Classes: {dict(zip(*np.unique(y, return_counts=True)))}")
        else:
            print("No valid captures found!")
        return

    if args.mode == "supervised":
        print("=" * 60)
        print("WiFlow-lite Supervised Training")
        print("=" * 60)

        if not args.dataset_path:
            print("ERROR: --dataset-path required for supervised mode")
            sys.exit(1)

        try:
            import torch
            import torch.nn as nn
            from torch.utils.data import DataLoader, TensorDataset
        except ImportError:
            print("ERROR: PyTorch required. Install with: pip install torch")
            sys.exit(1)

        # Load dataset
        data = np.load(args.dataset_path)
        X = data["X"]  # [N, 4, 52, 88]
        y = data["y"]
        groups = data["groups"]

        # Reshape to [N, 208, 88] (concat nodes along channel dim)
        N, nodes, subs, time = X.shape
        X_flat = X.reshape(N, nodes * subs, time)

        print(f"Dataset: {N} windows, shape {X_flat.shape}")
        print(f"Classes: {dict(zip(*np.unique(y, return_counts=True)))}")

        # Simple train/val split (TODO: replace with StratifiedGroupKFold)
        from sklearn.model_selection import StratifiedGroupKFold
        sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
        train_idx, val_idx = next(sgkf.split(X_flat, y, groups))

        X_train = torch.FloatTensor(X_flat[train_idx])
        y_train = torch.LongTensor(y[train_idx])
        X_val = torch.FloatTensor(X_flat[val_idx])
        y_val = torch.LongTensor(y[val_idx])

        train_loader = DataLoader(
            TensorDataset(X_train, y_train),
            batch_size=HPARAMS["batch_size"], shuffle=True
        )
        val_loader = DataLoader(
            TensorDataset(X_val, y_val),
            batch_size=HPARAMS["batch_size"]
        )

        # Build model
        model = build_model_pytorch()
        device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        model = model.to(device)

        # Class weights for imbalanced data
        class_counts = np.bincount(y[train_idx], minlength=3).astype(float)
        class_weights = 1.0 / (class_counts + 1e-6)
        class_weights /= class_weights.sum()
        loss_fn = nn.CrossEntropyLoss(
            weight=torch.FloatTensor(class_weights).to(device)
        )

        optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=HPARAMS["lr"],
            weight_decay=HPARAMS["weight_decay"]
        )
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, factor=0.5, patience=5, verbose=True
        )

        # Training loop
        best_val_acc = 0
        patience_counter = 0

        for epoch in range(args.epochs):
            model.train()
            train_loss = 0
            for xb, yb in train_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb)
                loss = loss_fn(pred, yb)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                train_loss += loss.item()

            # Validation
            model.eval()
            correct = 0
            total = 0
            val_loss = 0
            with torch.no_grad():
                for xb, yb in val_loader:
                    xb, yb = xb.to(device), yb.to(device)
                    pred = model(xb)
                    val_loss += loss_fn(pred, yb).item()
                    correct += (pred.argmax(1) == yb).sum().item()
                    total += len(yb)

            val_acc = correct / total if total > 0 else 0
            scheduler.step(val_loss)

            if (epoch + 1) % 10 == 0 or epoch == 0:
                print(f"Epoch {epoch+1}/{args.epochs}: "
                      f"train_loss={train_loss/len(train_loader):.4f}, "
                      f"val_loss={val_loss/len(val_loader):.4f}, "
                      f"val_acc={val_acc:.4f}")

            if val_acc > best_val_acc:
                best_val_acc = val_acc
                patience_counter = 0
                model_path = output_dir / f"wiflow_lite_best_{ts}.pt"
                torch.save(model.state_dict(), model_path)
            else:
                patience_counter += 1
                if patience_counter >= HPARAMS["patience"]:
                    print(f"Early stopping at epoch {epoch+1}")
                    break

        print(f"\nBest val accuracy: {best_val_acc:.4f}")
        print(f"Model saved: {model_path}")
        print(f"\nBaseline comparison:")
        print(f"  HGB Binary BalAcc: 0.856")
        print(f"  HGB 3-class macro F1: 0.628")
        print(f"  WiFlow-lite val acc: {best_val_acc:.4f}")


if __name__ == "__main__":
    main()
