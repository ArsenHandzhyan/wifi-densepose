# AGENTCLOUD — Academic Transfer Plan

Дата: 2026-03-18 (updated 2026-03-19 with deep-dive engineering details)
Ветка: `codex/agent-cloud-video-curation`
Предыдущая ветка: `codex/agent6-long-horizon-corpus-mining`

## Роль документа

Это практический transfer plan.

Он жёстко отделяет:

- baseline проекта до academic extraction
- что уже существовало локально
- что реально добавляется из академии
- что пока остаётся hypothesis

## 1. Baseline проекта ДО интеграции academic ideas

Канонический baseline freeze:

- `/Users/arsen/Desktop/wifi-densepose/docs/AGENTCLOUD_ACADEMIC_BASELINE_FREEZE_2026-03-18.md`

Коротко:

- главный production-like floor: hand-crafted + HGB line
- current best offline Agent 6:
  - `clean_support_hierarchy`
  - `presence F1 = 0.871`
  - `motion_binary F1 = 0.876`
  - `3-class macro F1 = 0.507`
- topology:
  - `4x ESP32`
  - ceiling-mounted
  - `128` subcarriers
  - IQ int8 stream
- event targets:
  - `empty`
  - `occupied_static`
  - `entry`
  - `exit`
  - `corridor_walk`
  - `reposition`
- ещё не было:
  - learned raw-CSI encoder
  - self-supervised pretraining
  - domain adaptation
  - neural sequence model

## 2. Что уже было у нас до academic transfer

### Already present locally

- long-horizon corpus inventory и role stratification
- holdout-aware evaluation по epoch domains
- weak/support/hard-negative doctrine
- video teacher path как optional offline label helper
- operator UI v1
- exit-gate / outside-anchor policy split

### Это НЕ является academic transfer deliverable

- `video_curation_pipeline.py`
- video teacher manifests
- UI `v1`

Это соседние линии, но не суть academic extraction.

## 3. Что именно добавляется из academic extraction

Не новый продуктовый surface, а три конкретные вещи:

1. `WiFlow`-style sequence-first raw CSI encoding
2. `DT-Pose`-style domain-consistent self-supervised pretraining
3. `SenseFi`-style minimal benchmark discipline для learned-vs-shallow comparison

## 4. Transfer Tracks

### Track A — WiFlow-lite Event Encoder

- Источник:
  в первую очередь `WiFlow`
- Цель:
  заменить early hand-crafted collapse на lightweight temporal/subcarrier encoder
- Наш target:
  event classification, не pose
- Вход:
  `4s` окна, stride `1s`, canonical four-node tensors

#### Конкретная WiFlow архитектура (из deep-dive):
  - WiFlow input: `[batch, 540, 20]` — 18 antenna links × 30 subcarriers, 600Hz
  - WiFlow encoder: TCN (causal dilated 1D Conv, dilations [1,2,4]) → Asymmetric 2D Conv → Dual Axial Attention
  - WiFlow params: 4.82M, AdamW lr=1e-4, Smooth L1 loss, dropout 0.5
  - WiFlow data bandwidth: 540 × 600 = 324,000 values/sec
  - **Наш data bandwidth: 128 × 4 × 22 = 11,264 values/sec (29× меньше)**
  - WiFlow подтверждает: amplitude-only работает, phase discarded из-за CFO/SFO corruption

#### Наш WiFlow-lite adaptation:
  - Input shape: `[batch, 4_nodes × 52_active_subcarriers, ~88_timesteps]` = `[B, 208, 88]`
    (52 = active bands indices 6-58, excluding dead center; 88 = 4 nodes × 22pps × 1sec per 4sec window)
  - Альтернативный 2D вход: `[B, 4, 52, 88]` (4 channel-nodes, 52 subcarriers, 88 timesteps)
  - TCN encoder: 4-5 TemporalBlocks, channels `[208, 128, 64, 32]`, dilations `[1,2,4,8]`, kernel 3
  - Effective receptive field: 2*(2+4+8+16)+1 = 61 timesteps ≈ 2.8sec (хорошее покрытие 4sec окна)
  - Asymmetric Conv: stride (1,2) — preserve time, reduce subcarrier dimension
  - Classification head: GlobalAvgPool → Linear → 3 classes (empty/static/motion)
  - Expected params: ~200K-500K (vs WiFlow 4.82M)
  - Ключевой insight из WiFlow: subcarrier dimension прогрессивно сжимается, temporal dimension сохраняется до конца

- Что уже было:
  only aggregated handcrafted features (40-106 MI-ranked features → HGB)
- Что добавляется:
  raw subcarrier-time representation через lightweight TCN
- Какие текущие скрипты подходят:
  - `scripts/csi_motion_pipeline_v22_full_grind.py` — feature extraction pipeline
  - `scripts/build_canonical_occupancy_dataset.py` — dataset builder
  - `scripts/agent6_wiflow_lite_ssl_stage1_pretrain.py` — уже существующий Stage 1 скелет
- Какие новые скрипты нужны:
  - `scripts/wiflow_lite_supervised_train.py` — supervised-only TCN training
  - `scripts/wiflow_lite_tensor_builder.py` — raw CSI → tensor converter
- Минимальный benchmark:
  StratifiedGroupKFold на тех же holdout epochs, same 3 metrics
- Expected gain:
  +3-8% на 3-class macro F1 (гипотеза: temporal structure поможет static/motion separation)
- Главный риск:
  при 22pps TCN может не найти достаточно temporal structure; 29× меньше данных чем WiFlow
- Acceptance:
  должен бить frozen HGB floor на тех же three-domain holdouts минимум по coarse line

### Track B — DT-Pose-style Domain-Consistent Pretraining

- Источник:
  в первую очередь `DT-Pose`, частично подтверждённо `SenseFi`
- Цель:
  использовать весь long-horizon корпус без подмены truth

#### Конкретная DT-Pose архитектура (из deep-dive):
  - DT-Pose Phase 1 (MAE): ViT encoder 4 layers, 4 heads, dim 256, decoder 2 layers
  - Patchification: Conv2d kernel=stride=patch_size (2,2) на CSI "image"
  - Mask ratio: 75-80% (config uses 0.80)
  - Loss: MSE reconstruction + 0.01 × uniformity_loss + lambda × InfoNCE contrastive
  - Contrastive: consecutive frame pairs (current + next frame)
  - Lambda schedule: linear ramp 0.0001 → 0.01 over 400 epochs
  - Optimizer: AdamW lr=1.5e-4 × batch/256, betas=(0.9, 0.95), weight_decay=0.05
  - DT-Pose Phase 2: frozen encoder + learnable pose prompts + 3-layer GCN + 3-layer Transformer decoder
  - **Ключевой insight**: MAE masking = бесплатная data augmentation, 80% masking работает

#### Наш DT-Pose-style adaptation:
  - Stage A (pretraining):
    - Input: те же WiFlow-lite tensors `[B, 4, 52, 88]`
    - Mask 70-80% of subcarrier-time patches
    - Reconstruction target: masked CSI amplitude values
    - Contrastive: InfoNCE между соседними 4sec windows того же clip
    - Contrastive negatives: windows из разных clips, hard_negative clips, boundary probes
    - Train on ALL corpus: clean + weak + self_supervised_only + hard_negative (~378 clips, ~2055 windows)
    - Optimizer: AdamW lr=1e-4, warmup 20 epochs, cosine decay over 200 epochs
    - Expected: ~50-100 epochs достаточно при нашем размере данных
  - Stage B (fine-tune):
    - Freeze encoder, add linear classification head
    - Train only on clean_core + clean_support (~66 clips)
    - Loss: CrossEntropy с balanced class weights
    - 50 epochs, SGD lr=1e-3

- Какие текущие скрипты подходят:
  - `scripts/agent6_wiflow_lite_ssl_stage1_pretrain.py` — уже есть Stage 1 скелет
  - `scripts/build_canonical_occupancy_dataset.py` — corpus builder
- Какие новые скрипты нужны:
  - `scripts/wiflow_lite_mae_pretrain.py` — MAE pretraining loop
  - обновить `agent6_wiflow_lite_ssl_stage1_pretrain.py` с конкретными DT-Pose параметрами
- Минимальный benchmark:
  compare pretrained vs from-scratch на тех же holdouts
- Expected gain:
  +2-5% на cross-epoch generalization (гипотеза: SSL снижает domain shift между epochs)
- Главный риск:
  378 clips / 2055 windows — мало для MAE pretraining (DT-Pose использовал ~320K frames)
  Mitigation: увеличить augmentation (noise, time shift, subcarrier dropout)
- Acceptance:
  holdout_count не хуже текущего,
  false-empty не растёт,
  coarse line становится сильнее или устойчивее

### Track C — SenseFi-style Minimal Benchmark Family

- Источник:
  `SenseFi`
- Цель:
  не допустить “single lucky learned model”

#### Verified SenseFi Engineering (из deep-dive исходного кода):
  - 11 моделей: MLP, CNN-5/LeNet, ResNet-18/50/101, RNN, GRU, LSTM, BiLSTM, CNN+GRU, ViT
  - **CNN-5 (5 layers) = best all-around:** fast convergence, best transferability, best SSL result (97.62%)
  - **ResNet depth HURTS generalization:** train ~100% → test 17.91% (Widar). Performance does NOT increase with depth.
  - **MLP outperforms ViT** when training data is insufficient — directly relevant to our 2055-window corpus
  - **Self-supervised (AutoFi) CNN-5: 97.62%** — higher than supervised transfer (96.35%). SSL > supervised transfer.
  - **ViT:** similar accuracy to CNN/MLP but much larger compute. Not recommended for WiFi sensing.
  - Input shapes: UT-HAR `(1,250,90)`, NTU-Fi `(3,114,500)` — **our (4,106,110) is comparable to NTU-Fi**
  - Datasets: UT-HAR (Intel 5300), NTU-Fi (Atheros 114 subcarriers at 40MHz), Widar (BVP not raw CSI)
  - No cross-platform transfer benchmarked (Intel→Atheros→ESP32 remains open problem)

#### Наша adaptation:
  - Минимальный family set:
    1. `HGB handcrafted floor` (frozen baseline: Binary 0.856, 3-class 0.628)
    2. `WiFlow-lite supervised TCN` (Track A)
    3. `WiFlow-lite + DT-style SSL pretraining` (Track B)
    4. Optional: `CNN-5 direct` (SenseFi's best performer as sanity check)
  - SenseFi finding “CNN-5 > ResNet” validates our choice of lightweight TCN over deep ViT/ResNet
  - SenseFi finding “SSL > supervised transfer” validates Track B priority

- Что уже было:
  baseline family для hand-crafted lines
- Что добавляется:
  learned-model family на тех же contracts и ledger
- Acceptance:
  вся новая learned line оценивается на тех же domains и в том же transfer summary

## 5. Mapping: academic inputs -> наш стек

### Temporal windows

| Parameter | WiFlow | DT-Pose | **Наш ESP32** |
|-----------|--------|---------|---------------|
| Sampling rate | 600 Hz | varies (10-20 samples/frame) | ~22 pps/node |
| Window size | 20 samples = 33ms | 10-20 samples = 1 frame | ~88 samples = 4 sec |
| Temporal resolution | micro-movements | per-frame | macro-state transitions |
| Values/sec | 324,000 | ~3,420 | 11,264 |

- Approximation:
  строим per-window tensors `[4, 52, 88]` без потери временной оси
  TCN receptive field 61 timesteps покрывает ~2.8 sec — достаточно для event detection

### Subcarrier patterns

| Parameter | WiFlow | DT-Pose (MM-Fi) | **Наш ESP32** |
|-----------|--------|-----------------|---------------|
| Subcarriers per link | 30 | 114 (or 90) | 128 (52 active per band) |
| Antenna links | 18 (3Tx × 6Rx) | 3 | 1 per node × 4 nodes |
| Total channels | 540 | 342 (3×114) | 512 (4×128) or 208 (4×52 active) |
| Phase used | NO (discarded) | YES (in Person-in-WiFi-3D) | available but untested |

- Что нужно:
  сохранить subcarrier axis до encoder stage
  начать с amplitude-only (WiFlow подтверждает), phase добавить как experiment

### Per-node vs fused topology

| Aspect | WiFlow | DT-Pose | **Наш ESP32** |
|--------|--------|---------|---------------|
| Input structure | 18 links concatenated → 540 dim vector | 3 antenna channels like RGB | 4 independent spatial nodes |
| Fusion strategy | TCN mixes all 540 channels in first layer | Conv2d on 3-channel "image" | **TBD: per-node then fuse vs early concat** |
| Correlation structure | MIMO multipath from 1 TX-RX pair | MIMO from 1 device | 4 spatially separated views |

- Что эквивалентно:
  per-node streams + controlled fusion
  WiFlow concatenates antenna links — мы можем concatenate nodes аналогично
- Чего не хватает:
  learned fusion layer instead of only cross-node summary features
- Рекомендация из deep-dive:
  начать с simple concatenation (4 nodes along channel dim), потом попробовать per-node encoding + late fusion

### Event classification vs pose targets

- Academic: pose regression (15-18 joints, 2D/3D coordinates)
- Наш target: event classification (3-6 classes)
- Значит: encoder architecture transfers, decoder architecture does NOT
- WiFlow decoder (15 joints → AdaptiveAvgPool): заменяется GlobalAvgPool → Linear(3)
- DT-Pose decoder (GCN + Transformer + pose prompts): не переносим

### Domain robustness tricks

| Technique | WiFlow | DT-Pose | **Применимость** |
|-----------|--------|---------|-------------------|
| Contrastive pre-training | none | InfoNCE consecutive frames | **directly transferable** |
| MAE masking | none | 80% patch masking | **directly transferable** |
| Cross-scene evaluation | none | train E01-E03, test E04 | maps to our epoch holdouts |
| Uniformity loss | none | prevents representation collapse | **worth trying** |
| Data augmentation | none | masking only | need CSI-specific augmentations |

- Approximation:
  pretrain on the whole corpus, fine-tune only on curated tiers
  Contrastive + masking = primary SSL strategy

## 6. Что пока только hypothesis

- что learned raw-CSI encoder реально улучшит `corridor/reposition` confusion
- что SSL pretraining даст gain именно на ESP32 event line, а не только на paper-like datasets
- что phase-derived channels окажутся полезнее amplitude-only path

## 7. Что сейчас не стоит делать

- full pose estimation roadmap
- перенос внешних pose targets в наш next step
- large Transformer-first implementation
- broad benchmark recreation across many public datasets
- on-device deployment work до доказанного offline gain

## 8. Canonical cross-repo / worktree memory

- Canonical source of truth:
  `/Users/arsen/Desktop/wifi-densepose`
- Canonical branch lineage for this line:
  `codex/agent6-long-horizon-corpus-mining`
- Worktree:
  execution workspace only, not authoritative source
- Нужны ли отдельные companion notes в другом worktree:
  нет
- Значит:
  canonical docs и machine-readable summary живут в основном repo;
  worktree может держать рабочие копии, но не должен объявляться source of truth.

## 9. Strongest Next Experiment

Один strongest next experiment:

обучить `WiFlow-lite` encoder на наших canonical `4s` four-node windows с `amplitude + phase-derived + delta` каналами, сделать сначала self-supervised masked/contrastive pretraining на всём Agent 6 корпусе, затем fine-tune только `3-class head` (`empty / occupied_static / large_motion`) и сравнить с текущим `clean_support_hierarchy` на тех же трёх holdout epochs.

Почему именно он:

- он объединяет strongest adopted ideas сразу без лишнего product scope
- он бьёт прямо в текущий Agent 6 bottleneck:
  loss of subcarrier-time structure + cross-epoch domain shift
- он не требует притворяться, что next step — pose estimation

## Bottom Line

Academic transfer для нашего проекта — это не “пойти в pose”.

Это:

- сохранить raw CSI structure дольше
- использовать весь long-horizon corpus как pretraining signal
- сравнивать learned tracks против frozen shallow baseline честно и одинаково
