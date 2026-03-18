# AGENTCLOUD — Academic Adopted Ideas

Дата: 2026-03-18 (updated 2026-03-19 with verified engineering details from source code review)
Ветка: `codex/agent-cloud-video-curation`

## Роль документа

Это не новый literature survey.

Это канонический список того, что Agent 6 реально забирает из уже выбранных academic sources в ESP32 CSI line.

Baseline до интеграции уже зафиксирован отдельно:

- `/Users/arsen/Desktop/wifi-densepose/docs/AGENTCLOUD_ACADEMIC_BASELINE_FREEZE_2026-03-18.md`

## Что у нас уже было до academic extraction

- `4x ESP32` ceiling-mounted topology как канон.
- Event-oriented targets, а не pose targets:
  - `empty`
  - `occupied_static`
  - `entry`
  - `exit`
  - `corridor_walk`
  - `reposition`
- Holdout-aware offline line `clean_support_hierarchy` с cross-epoch проверкой.
- Hand-crafted feature regime:
  - amplitude / phase aggregates
  - packet rate
  - cross-node statistics
  - short temporal context
- Жёсткое разделение `clean_core / clean_support / weak / hard_negative`.
- Optional offline video-teacher path и CSI-only operator UI, но не academic transfer line.

## Adopted Ideas

### 1. `WiFlow` -> sequence-first CSI encoder вместо image-like collapse

- Что забираем:
  lightweight spatio-temporal encoder, который обрабатывает CSI как временную последовательность по subcarrier axis, а не как уже схлопнутые summary-features.
- Почему:
  текущий baseline слишком рано теряет структуру `subcarrier x time x node`, а именно там, вероятно, лежит часть boundary / motion discrimination.
- Статус переноса:
  `adaptable with moderate changes`

#### Verified WiFlow Engineering (из исходного кода):
  - WiFlow TCN: 3 TemporalBlocks, каждый = 2× causal Conv1d + Chomp1d + ReLU + dropout(0.5) + residual
  - Channel progression: 540→360→240, kernel=3, dilations=[1,2,4]
  - Asymmetric Conv2d: stride (1,2) — time axis НИКОГДА не сжимается, только subcarrier axis
  - Subcarrier dim: 240→120→60→30→15 (ровно 15 = число keypoints)
  - Dual Axial Attention: 8 groups, Conv1d-based QKV, BN on similarity matrix
  - Training: AdamW lr=1e-4, weight_decay=5e-5, batch=64, 50 epochs, mixed precision
  - Loss: Smooth L1 (beta=0.1) + 0.2× bone length constraint
  - **Key finding: amplitude-only confirmed — phase discarded as computationally expensive to sanitize**

#### Наша adaptation:
  - TCN: 4 TemporalBlocks, channels 208→128→64→32, dilations [1,2,4,8], kernel=3
  - Input: `[B, 208, 88]` (4×52 subcarriers concat, 88 timesteps per 4sec window)
  - Asymmetric Conv: preserve time, reduce subcarrier → event embedding
  - Classification head: GlobalAvgPool(time) → Linear(32, 3) вместо pose decoder
  - Dropout: 0.3 (vs WiFlow 0.5 — у нас меньше данных, нужна регуляризация но не чрезмерная)
  - Expected: ~200-500K params vs WiFlow 4.82M

- Как отображается на наш ESP32 CSI stack:
  - вход не pose-dataset tensor из paper, а наш window tensor:
    - `node` (4 ESP32)
    - `subcarrier` (52 active per node)
    - `time` (~22 samples/sec × 4sec)
    - `channel`: amplitude (confirmed sufficient by WiFlow)
  - целевая голова:
    - сначала `empty / occupied_static / large_motion`
    - не keypoints и не skeleton decoding
- Что именно не переносим вместе с этим пунктом:
  full continuous pose decoder, axial attention (overkill для 3-class), bone length constraint loss.

### 2. `WiFlow` -> decoupled per-node encoding + поздний topology-aware fusion

- Что забираем:
  decouple temporal/subcarrier extraction от более позднего fusion шага.
- Почему:
  у нас topology itself уже играет роль, и `source_signature` нельзя схлопывать слишком рано в несколько агрегатов.
- Статус переноса:
  `adaptable`
- Как отображается на наш ESP32 CSI stack:
  - сначала кодируем каждый node stream отдельно
  - затем делаем controlled fusion
  - fusion должен быть aware of:
    - `node01..node04`
    - missing-node cases
    - `source_signature`
  - это лучше соответствует нашей реальной corpus stratification, чем прямое early flattening

### 3. `DT-Pose` -> domain-consistent pretraining на всём корпусе

- Что забираем:
  two-phase logic, где сначала учится representation, устойчивый к domain shift, а потом уже downstream head.
- Почему:
  главный Agent 6 bottleneck сейчас не только class overlap, но и cross-epoch shift:
  - loose sensors
  - fixed ceiling
  - post-fix no-teacher
  - reflash / teacher-adjacent regimes
- Статус переноса:
  `adaptable with moderate changes`

#### Verified DT-Pose Engineering (из исходного кода):
  - MAE Encoder: 4 Transformer layers, 4 heads, emb_dim=256
  - MAE Decoder: 2 Transformer layers, 4 heads, emb_dim=256
  - Patch size: (2,2) на CSI "image" → для MM-Fi (114,10): 285 patches
  - **Mask ratio: 0.80 (80% patches masked — key for data augmentation)**
  - Loss: MSE_reconstruction + 0.01×uniformity_loss + lambda×InfoNCE
  - Lambda schedule: linear 0.0001→0.01 over 400 epochs (gradual contrastive ramp)
  - Contrastive: consecutive frames = positive pairs
  - Batch: 4096 (gradient accumulation from 256)
  - Optimizer: AdamW lr=1.5e-4×batch/256, betas=(0.9,0.95), weight_decay=0.05
  - Phase 2: **all encoder params frozen** (requires_grad=False), only head trains
  - **Key finding: uniformity loss prevents representation collapse — critical for small datasets**

#### Наша adaptation:
  - Не копируем ViT (overkill для нашего размера данных)
  - Берём принцип: masked reconstruction на WiFlow-lite TCN encoder
  - Mask 70% of subcarrier-time слотов в input tensor
  - Reconstruct masked values → teaches encoder CSI structure
  - Contrastive: adjacent 4sec windows from same clip = positive, different clips = negative
  - Uniformity loss: включаем (prevents collapse при малом batch)
  - Lambda schedule: linear ramp over 100 epochs (у нас меньше данных — короче)

- Как отображается на наш ESP32 CSI stack:
  - stage A:
    self-supervised pretraining на `clean + weak + self_supervised_only + hard_negative`
    (~378 clips, ~2055 windows — 3 порядка меньше чем DT-Pose ~320K frames)
  - stage B:
    supervised fine-tune только на `clean_core + clean_support` (~66 clips)
    encoder frozen, only classification head trains
  - acceptance gate остаётся Agent 6 holdout-aware, а не scalar-only

### 4. `DT-Pose` -> masked reconstruction + temporal-consistent contrastive signal mining

- Что забираем:
  self-supervised masking/reconstruction и temporal-consistent contrastive training как способ использовать noisy archive без подмены truth.
- Почему:
  это прямо совпадает с Agent 6 corpus doctrine:
  noisy data нельзя игнорировать, но нельзя и выдавать за clean truth.
- Статус переноса:
  `adaptable`
- Как отображается на наш ESP32 CSI stack:
  - mask части subcarrier-time tensor
  - восстанавливать masked regions или соседние temporal slices
  - contrastive positives:
    соседние устойчивые окна того же clip / pack
  - contrastive negatives:
    hard negatives, boundary probes, contaminated domains

### 5. `SenseFi` -> benchmark discipline, а не вера в одну модель

- Что забираем:
  benchmark-first discipline:
  один и тот же dataset contract, одинаковые splits, несколько baseline families, machine-readable comparison.
- Почему:
  нам нужен не “новый красивый encoder”, а честная проверка против уже замороженного HGB baseline.
- Статус переноса:
  `directly_transferable`

#### Verified SenseFi Engineering (из deep-dive исходного кода):
  - **ResNet depth hurts:** ResNet-18 train ~100% → test 17.91% (Widar). ResNet-101 worst generalization.
  - **CNN-5 (5 layers) best everywhere:** fast convergence (<25 epochs), best transfer, best SSL.
  - **Self-supervised AutoFi: CNN-5 = 97.62%** > supervised transfer (96.35%). KL divergence + MI + kernel density loss.
  - **MLP: 92.00% UT-HAR, 93.91% NTU-Fi Human-ID** — outperforms ViT when data insufficient.
  - Protocol: fixed splits (not k-fold), Adam lr=1e-3, CrossEntropy. Metrics: accuracy, FLOPs, params.
  - **No cross-platform transfer benchmarked** — Intel 5300 vs Atheros evaluated independently.

- Как отображается на наш ESP32 CSI stack:
  - HGB baseline остаётся floor (SenseFi confirms shallow wins cross-environment)
  - learned encoder сравнивается на тех же holdouts
  - transfer ledger и summary обязательны
  - deep model не считается improvement без cross-epoch доказательства
  - **Note:** SenseFi finding confirms our TCN choice — CNN-5 style lightweight > deep ResNet/ViT

### 6. `SenseFi` -> transferability-first evaluation и небольшой model family

- Что забираем:
  не full model zoo, а минимальное семейство из 2–3 реально сравнимых tracks:
  - shallow baseline (HGB)
  - supervised lightweight temporal encoder (WiFlow-lite TCN)
  - self-supervised pretrained lightweight encoder (WiFlow-lite + DT-style SSL)
- Почему:
  SenseFi прямо показывает, что shallow models могут выигрывать у deeper nets в cross-environment setting.
  Конкретно: CNN-5 (5 layers) > ResNet-101 (101 layers) по generalization.
  MLP > ViT при малых данных.
- Статус переноса:
  `directly_transferable`
- Как отображается на наш ESP32 CSI stack:
  - не убираем `HGB`
  - не прыгаем сразу в large Transformer stack
  - SenseFi input (3,114,500) ≈ наш (4,106,110) — масштаб совпадает
  - все новые tracks сравниваем по:
    - holdout_count
    - presence / motion metrics
    - false empty behavior

## Источники, на которые опирается adoption judgment

- `WiFlow`:
  - arXiv: `https://arxiv.org/abs/2602.08661`
  - repo: `https://github.com/DY2434/WiFlow-WiFi-Pose-Estimation-with-Spatio-Temporal-Decoupling`
- `DT-Pose`:
  - arXiv: `https://arxiv.org/abs/2501.09411`
  - repo: `https://github.com/cseeyangchen/DT-Pose`
- `SenseFi`:
  - paper: `https://doi.org/10.1016/j.patter.2023.100703`
  - repo: `https://github.com/xyanchen/WiFi-CSI-Sensing-Benchmark`

## Bottom Line

Мы забираем из академии не pose target и не чужие leaderboard claims.

Мы забираем три вещи:

1. sequence-first CSI representation
2. self-supervised domain-robust pretraining
3. benchmark discipline with a frozen shallow baseline floor
