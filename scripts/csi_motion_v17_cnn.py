#!/usr/bin/env python3
"""
V17: 1D-CNN on Raw CSI Amplitude Sequences

Skip hand-crafted features entirely. Feed raw amplitude time series
directly into a 1D-CNN that learns its own features.

Input: 4 nodes x 128 subcarriers x T timesteps per window
  -> Reshape to (4*128, T) = (512, T) channels
  -> 1D-CNN learns temporal patterns

Architecture:
  Conv1D(512 -> 64, kernel=3) -> BatchNorm -> ReLU -> Pool
  Conv1D(64 -> 128, kernel=3) -> BatchNorm -> ReLU -> Pool
  Conv1D(128 -> 64, kernel=3) -> BatchNorm -> ReLU -> GlobalAvgPool
  Dense(64 -> 32) -> ReLU -> Dropout -> Dense(n_classes)

Uses PyTorch if available, falls back to sklearn MLP.
"""

import gzip, json, base64, time, warnings, os
import numpy as np
from pathlib import Path
from collections import Counter, defaultdict

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parents[1]
CAPTURES = PROJECT / "temp" / "captures"
t0 = time.time()

print("=" * 70)
print("V17: 1D-CNN on Raw CSI Amplitude Sequences")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 70)

# Check PyTorch
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import TensorDataset, DataLoader
    HAS_TORCH = True
    print(f"  PyTorch {torch.__version__} available")
    if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        DEVICE = torch.device("mps")
        print(f"  Using MPS (Apple Silicon)")
    else:
        DEVICE = torch.device("cpu")
        print(f"  Using CPU")
except ImportError:
    HAS_TORCH = False
    print("  PyTorch not available, using sklearn MLP fallback")

# ── CSI parsing ───────────────────────────────────────────────────────────

CSI_HEADER = 20
NODE_ORDER = ["192.168.1.101", "192.168.1.117", "192.168.1.125", "192.168.1.137"]

def parse_amp(b64):
    raw = base64.b64decode(b64)
    if len(raw) < CSI_HEADER + 40:
        return None
    iq = raw[CSI_HEADER:CSI_HEADER + 256]
    n = len(iq) // 2
    if n < 20:
        return None
    arr = np.frombuffer(iq[:n*2], dtype=np.int8).reshape(-1, 2)
    amp = np.sqrt(arr[:, 0].astype(np.float32)**2 + arr[:, 1].astype(np.float32)**2)
    if len(amp) < 128:
        amp = np.pad(amp, (0, 128 - len(amp)))
    return amp[:128]

# ── Load clips with labels ────────────────────────────────────────────────

def get_clip_label(label):
    """Get binary/coarse label for a clip."""
    # Check summary.json
    sf = CAPTURES / f"{label}.summary.json"
    if sf.exists():
        d = json.load(open(sf))
        pc = d.get("person_count_expected", -1)
        step = d.get("step_name", "").lower()
        if pc >= 0:
            binary = "EMPTY" if pc == 0 or "empty" in step else "OCCUPIED"
            if "walk" in step or "entry" in step or "exit" in step:
                coarse = "MOTION"
            elif pc == 0 or "empty" in step:
                coarse = "EMPTY"
            else:
                coarse = "STATIC"
            return binary, coarse

    # Check clip.json
    cf = CAPTURES / f"{label}.clip.json"
    if cf.exists():
        d = json.load(open(cf))
        ln = d.get("label_name", "").lower()
        pc = d.get("person_count_expected", -1)
        if pc >= 0:
            binary = "EMPTY" if pc == 0 or "empty" in ln else "OCCUPIED"
            if any(x in ln for x in ["walk", "entry", "exit", "corridor", "step"]):
                coarse = "MOTION"
            elif pc == 0 or "empty" in ln:
                coarse = "EMPTY"
            else:
                coarse = "STATIC"
            return binary, coarse

    return None, None

# ── Extract raw CSI windows ───────────────────────────────────────────────

WINDOW_SEC = 3.0  # shorter windows for CNN
WINDOW_PKTS = 75  # ~25 pps * 3s = 75 packets per window per node
N_SUBCARRIERS = 128

print("\n[Phase 1] Extracting raw CSI windows...")

all_windows = []  # list of (X: 4 x 128 x T, binary, coarse, clip_id)
clip_counter = 0
processed = 0

for csi_path in sorted(CAPTURES.glob("*.ndjson.gz")):
    label = csi_path.stem.replace(".ndjson", "")
    binary, coarse = get_clip_label(label)
    if binary is None:
        continue

    # Parse CSI data
    node_packets = defaultdict(list)
    first_ts = None

    with gzip.open(str(csi_path), "rt") as f:
        for line in f:
            try:
                rec = json.loads(line)
                ip = rec.get("src_ip", "")
                if ip not in NODE_ORDER:
                    continue
                amp = parse_amp(rec.get("payload_b64", ""))
                if amp is None:
                    continue
                ts = rec.get("ts_ns", 0)
                if first_ts is None:
                    first_ts = ts
                t_sec = (ts - first_ts) / 1e9
                ni = NODE_ORDER.index(ip)
                node_packets[ni].append((t_sec, amp))
            except:
                continue

    if len(node_packets) < 3:
        continue

    # Build time-aligned windows
    all_t = [t for pkts in node_packets.values() for t, _ in pkts]
    if not all_t:
        continue
    max_t = max(all_t)

    t_start = 0
    while t_start + WINDOW_SEC <= max_t:
        t_end = t_start + WINDOW_SEC

        # For each node, collect packets in this window
        window_ok = True
        node_matrices = []

        for ni in range(4):
            pkts = [(t, a) for t, a in node_packets.get(ni, []) if t_start <= t < t_end]
            if len(pkts) < 5:
                # Pad with zeros if node missing
                mat = np.zeros((WINDOW_PKTS, N_SUBCARRIERS), dtype=np.float32)
            else:
                amps = np.array([a for _, a in pkts], dtype=np.float32)
                # Resample/pad to fixed WINDOW_PKTS
                if len(amps) >= WINDOW_PKTS:
                    # Subsample
                    idx = np.linspace(0, len(amps)-1, WINDOW_PKTS, dtype=int)
                    mat = amps[idx]
                else:
                    # Pad
                    mat = np.zeros((WINDOW_PKTS, N_SUBCARRIERS), dtype=np.float32)
                    mat[:len(amps)] = amps
            node_matrices.append(mat)

        # Stack: (4, WINDOW_PKTS, 128) -> reshape for CNN
        X_window = np.stack(node_matrices)  # (4, 75, 128)

        all_windows.append({
            "X": X_window,
            "binary": binary,
            "coarse": coarse,
            "clip_id": clip_counter,
        })

        t_start += WINDOW_SEC  # no overlap for CNN

    clip_counter += 1
    processed += 1
    if processed % 50 == 0:
        print(f"  {processed} clips, {len(all_windows)} windows...")

print(f"  Total: {processed} clips, {len(all_windows)} windows")
print(f"  Binary: {dict(Counter(w['binary'] for w in all_windows))}")
print(f"  Coarse: {dict(Counter(w['coarse'] for w in all_windows))}")

if len(all_windows) < 100:
    print("  Too few windows, exiting")
    exit(1)

# ── Prepare data ──────────────────────────────────────────────────────────

X = np.array([w["X"] for w in all_windows], dtype=np.float32)  # (N, 4, 75, 128)
y_binary = np.array([1 if w["binary"] == "OCCUPIED" else 0 for w in all_windows])
y_coarse_str = np.array([w["coarse"] for w in all_windows])
groups = np.array([w["clip_id"] for w in all_windows])

from sklearn.preprocessing import LabelEncoder
le_c = LabelEncoder()
y_coarse = le_c.fit_transform(y_coarse_str)

print(f"\n  X shape: {X.shape}")  # (N, 4, 75, 128)
print(f"  Unique clips: {len(np.unique(groups))}")

# Normalize per-window
for i in range(len(X)):
    m = X[i].mean()
    s = X[i].std() + 1e-6
    X[i] = (X[i] - m) / s

# ── Flatten approach (sklearn MLP baseline) ───────────────────────────────

print("\n[Phase 2] Sklearn MLP baseline...")
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.metrics import balanced_accuracy_score

# Flatten X for MLP: (N, 4*75*128) is too large. Use summary stats instead.
# Mean and std per node per subcarrier band
X_flat = []
for i in range(len(X)):
    feats = []
    for ni in range(4):
        node_data = X[i, ni]  # (75, 128)
        # Mean amplitude per subcarrier band
        feats.append(node_data.mean(axis=0).mean())  # global mean
        feats.append(node_data.std(axis=0).mean())   # temporal std
        feats.append(node_data.max(axis=0).mean())   # max
        feats.append(np.abs(np.diff(node_data, axis=0)).mean())  # motion energy
        # Band splits
        feats.append(node_data[:, :30].var(axis=0).mean())  # low band var
        feats.append(node_data[:, 30:60].var(axis=0).mean())  # mid band var
        feats.append(node_data[:, 60:].var(axis=0).mean())  # high band var
    X_flat.append(feats)

X_flat = np.array(X_flat, dtype=np.float32)
X_flat = np.nan_to_num(X_flat, nan=0, posinf=0, neginf=0)
print(f"  Flattened features: {X_flat.shape[1]}")

CV = min(5, len(np.unique(groups)))
sgkf = StratifiedGroupKFold(n_splits=CV, shuffle=True, random_state=42)

for task, y in [("binary", y_binary), ("coarse", y_coarse)]:
    best_ba = 0
    best_name = ""
    for mname, model in [
        ("RF_bal", RandomForestClassifier(n_estimators=500, max_depth=15,
                                          class_weight="balanced", random_state=42, n_jobs=-1)),
        ("HGB_bal", HistGradientBoostingClassifier(max_iter=500, max_depth=8, learning_rate=0.03,
                                                    class_weight="balanced", random_state=42)),
    ]:
        fold_ba = []
        for train_idx, test_idx in sgkf.split(X_flat, y, groups):
            m = type(model)(**model.get_params())
            m.fit(X_flat[train_idx], y[train_idx])
            fold_ba.append(balanced_accuracy_score(y[test_idx], m.predict(X_flat[test_idx])))
        ba = np.mean(fold_ba)
        if ba > best_ba:
            best_ba = ba; best_name = mname; best_std = np.std(fold_ba)
    print(f"  {task:8s}: {best_name} BalAcc={best_ba:.3f}+-{best_std:.3f}")

# ── PyTorch 1D-CNN ────────────────────────────────────────────────────────

if HAS_TORCH:
    print("\n[Phase 3] PyTorch 1D-CNN...")

    class CSI_CNN(nn.Module):
        def __init__(self, n_classes, n_nodes=4, n_sub=128, n_time=75):
            super().__init__()
            # Input: (batch, 4, 75, 128) -> treat as (batch, 4*128, 75)
            in_ch = n_nodes * n_sub  # 512

            self.features = nn.Sequential(
                nn.Conv1d(in_ch, 64, kernel_size=5, padding=2),
                nn.BatchNorm1d(64),
                nn.ReLU(),
                nn.MaxPool1d(2),

                nn.Conv1d(64, 128, kernel_size=3, padding=1),
                nn.BatchNorm1d(128),
                nn.ReLU(),
                nn.MaxPool1d(2),

                nn.Conv1d(128, 64, kernel_size=3, padding=1),
                nn.BatchNorm1d(64),
                nn.ReLU(),
                nn.AdaptiveAvgPool1d(1),
            )
            self.classifier = nn.Sequential(
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Dropout(0.3),
                nn.Linear(32, n_classes),
            )

        def forward(self, x):
            # x: (batch, 4, 75, 128) -> (batch, 512, 75)
            b = x.shape[0]
            x = x.reshape(b, -1, x.shape[2])  # (B, 4*128, 75)
            x = self.features(x)  # (B, 64, 1)
            x = x.squeeze(-1)     # (B, 64)
            return self.classifier(x)

    def train_cnn(X_train, y_train, X_test, y_test, n_classes, epochs=30, lr=0.001):
        # Reshape: (N, 4, 75, 128) -> keep as is, reshape in model
        X_tr = torch.FloatTensor(X_train).to(DEVICE)
        y_tr = torch.LongTensor(y_train).to(DEVICE)
        X_te = torch.FloatTensor(X_test).to(DEVICE)
        y_te = torch.LongTensor(y_test).to(DEVICE)

        model = CSI_CNN(n_classes).to(DEVICE)
        optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)

        # Class weights
        counts = Counter(y_train.tolist())
        weights = torch.FloatTensor([len(y_train) / (n_classes * counts.get(i, 1)) for i in range(n_classes)]).to(DEVICE)
        criterion = nn.CrossEntropyLoss(weight=weights)

        dataset = TensorDataset(X_tr, y_tr)
        loader = DataLoader(dataset, batch_size=64, shuffle=True)

        model.train()
        for epoch in range(epochs):
            total_loss = 0
            for xb, yb in loader:
                optimizer.zero_grad()
                out = model(xb)
                loss = criterion(out, yb)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()

        model.eval()
        with torch.no_grad():
            preds = model(X_te).argmax(dim=1).cpu().numpy()

        return preds

    for task, y in [("binary", y_binary), ("coarse", y_coarse)]:
        n_classes = len(np.unique(y))
        fold_ba = []

        for train_idx, test_idx in sgkf.split(X, y, groups):
            preds = train_cnn(X[train_idx], y[train_idx], X[test_idx], y[test_idx],
                              n_classes, epochs=40, lr=0.001)
            fold_ba.append(balanced_accuracy_score(y[test_idx], preds))

        ba = np.mean(fold_ba)
        std = np.std(fold_ba)
        print(f"  CNN {task:8s}: BalAcc={ba:.3f}+-{std:.3f}")

else:
    print("\n[Phase 3] Skipped (no PyTorch)")

elapsed = time.time() - t0
print(f"\nV17 COMPLETE in {elapsed:.1f}s ({elapsed/60:.1f} min)")
