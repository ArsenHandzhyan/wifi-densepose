# Дорожная карта моделей WiFi DensePose CSI

**Дата:** 2026-04-01
**Базовая модель:** V46 drift-robust 3-class (empty/static/motion)
**Текущие метрики:** CV F1_macro = 0.985, 156 сэмплов, 77 признаков
**Инфраструктура:** 7 ESP32 CSI узлов (потолочные), гараж 3x7м, Tenda FW3

---

## Оглавление

1. [Текущее состояние и ограничения](#1-текущее-состояние-и-ограничения)
2. [Этап 1: Расширение static-класса](#2-этап-1-расширение-static-класса)
3. [Этап 2: Модель зональной локализации](#3-этап-2-модель-зональной-локализации)
4. [Этап 3: Модель подсчета людей](#4-этап-3-модель-подсчета-людей)
5. [Этап 4: Иерархический pipeline](#5-этап-4-иерархический-pipeline)
6. [Этап 5: Темпоральные модели](#6-этап-5-темпоральные-модели)
7. [Этап 6: Координатная регрессия и оценка позы](#7-этап-6-координатная-регрессия-и-оценка-позы)
8. [Сводная таблица моделей](#8-сводная-таблица-моделей)

---

## 1. Текущее состояние и ограничения

### Что работает (V46)

| Компонент | Статус | Метрика |
|-----------|--------|---------|
| 3-class occupancy (V46) | Production | F1_macro=0.985 |
| Zone classification (V39) | Production | CV BA=0.986, 2 зоны (center/door_passage) |
| Person count (V57) | Production | F1=0.882, 1 vs 2 человека |
| Drift-resistant features | Работает | 11 фич/нода, ratios вместо абсолютных значений |

### Критические ограничения

1. **Static-класс: 26 сэмплов** -- минимальный класс, bottleneck для обучения. При балансировке target_per_class = 65, static остается underrepresented.
2. **Walking vs slow-static граница** -- center_slow_1 классифицируется как static (95.1% walking detection, 4.9% ошибка на медленном движении).
3. **Zone model V39 -- только 2 зоны** (center vs door_passage), не покрывает deep/zone3/zone4.
4. **Count model V57 -- только 1 vs 2**, нет 0 vs 1 vs 2+.
5. **Нет темпоральности** -- каждое окно (7 пакетов) предсказывается независимо.
6. **Нет координатной регрессии** -- только дискретные зоны.

### Текущий feature pipeline (V46)

```
Raw CSI packets (7-node, ~10 Hz per node)
    |
    v
Window (7 packets per node, stride=1)
    |
    v
11 drift-resistant features × 7 nodes = 77 features:
  [0] std_rssi              -- вариабельность RSSI
  [1] cv_amp                -- коэф. вариации амплитуды (std/mean)
  [2] amp_range_ratio       -- (max-min)/(mean+1)
  [3] temporal_var           -- mean(std across packets per subcarrier) / mean_amp
  [4] low_ratio             -- low_band / mean_amp
  [5] mid_ratio             -- mid_band / mean_amp
  [6] high_ratio            -- high_band / mean_amp
  [7] pkt_std_amp           -- CV per-packet mean amplitudes
  [8] sc_entropy            -- entropy of subcarrier profile
  [9] rssi_range            -- max_rssi - min_rssi
  [10] amp_iqr_ratio        -- IQR / median
    |
    v
GBM-500 (GradientBoostingClassifier) --> empty / static / motion
```

---

## 2. Этап 1: Расширение static-класса

### Проблема

26 static-сэмплов при 65 empty и 65 motion. Коэффициент дисбаланса 2.5x. При cross-validation с 2-5 фолдами на static-классе -- высокий variance.

### Стратегия сбора данных

#### 2.1. Протокол записи static-позиций

```
Каждая сессия = 1 человек стоит неподвижно 3 минуты.
Stride=1, window=7 --> ~170 окон per 3 min (при 10 Hz per node).

Позиции для записи (по маркерам на потолке):
  Marker 1:  x=2.5, y=1  (дверь)
  Marker 4:  x=2.5, y=4  (правый центр)
  Marker 6:  x=1.5, y=5  (центр-глубина)
  Marker 8:  x=0.5, y=4  (левый центр)
  Marker 9:  x=1.5, y=4  (точный центр)
  Marker 11: x=2.0, y=1  (угол прохода)
  Дверной проём: x=2.5, y=0.3

Дополнительные позиции (gap coverage):
  x=1.0, y=3.5  (между node03 и node05)
  x=2.5, y=2.5  (zone3/проход)
  x=0.5, y=3.5  (левый край center)
```

#### 2.2. Условия записи (drift coverage)

Для устойчивости к дрифту нужны записи при разных условиях:

| Условие | Причина | Минимум сессий |
|---------|---------|----------------|
| Утро (8-10) | Холодный гараж, другая влажность | 2 |
| День (14-16) | Прогретый, стабильный | 2 |
| Вечер (20-22) | Текущие записи -- epoch4 вечерний | 2 |
| Открытая дверь | Изменяет multipath | 1 |
| Закрытая дверь | Основной режим | 2 |

**Целевой объём:** 10 позиций x 3 условия x ~170 окон = ~5100 static сэмплов.

#### 2.3. Техника аугментации (до сбора новых данных)

1. **Sliding window overlap** -- использовать stride=1 вместо stride=WINDOW_SIZE для существующих записей (уже используется).
2. **Temporal jitter** -- сдвиг окна на +/-1 пакет с добавлением Gaussian noise (sigma=0.01 * feature_std) к drift-resistant фичам.
3. **Node dropout** -- случайное обнуление 1-2 нод (из 7) для симуляции потери связи. MIN_NODES=5 уже допускает 2 потерянных ноды.
4. **Mixup** -- интерполяция между static-сэмплами разных позиций: x_aug = lambda * x_i + (1-lambda) * x_j, lambda ~ Beta(0.2, 0.2).

```python
# Пример аугментации для static
def augment_static(X_static, n_aug=200, noise_sigma=0.01):
    X_aug = []
    for _ in range(n_aug):
        i, j = np.random.choice(len(X_static), 2, replace=False)
        lam = np.random.beta(0.2, 0.2)
        x_new = lam * X_static[i] + (1 - lam) * X_static[j]
        x_new += np.random.normal(0, noise_sigma, x_new.shape)
        X_aug.append(x_new)
    return np.array(X_aug)
```

#### 2.4. Критерий готовности

- Минимум 150 реальных static-сэмплов (без аугментации)
- CV F1 на static-классе >= 0.95 (5-fold stratified)
- Confusion: static->motion leakage < 3%, static->empty leakage < 2%

---

## 3. Этап 2: Модель зональной локализации

### Текущее состояние

V39 fewshot zone model: RF classifier, 26 фич, 1229 сэмплов, 2 класса (center, door_passage). CV BA = 0.986.

### Целевая архитектура: V50 Zone Model

#### 3.1. Расширение зон

```
Текущие 2 зоны:          Целевые 5 зон:
  center                    door      (y=0-2, x=2-3)
  door_passage              passage   (y=0-3, x=2-3, zone3)
                            center    (y=3-5.5)
                            deep      (y=5.5-7, если ходят)
                            zone4     (y=0-1, x=1-2, FP2)
```

#### 3.2. Feature engineering для зонирования

К 11 drift-resistant фичам V46 добавляем зона-специфичные:

```
Per-node (11 V46 features):
  + 3 новых = 14 per node × 7 nodes = 98 features

Новые per-node features:
  [11] rssi_mean_normalized   -- RSSI / baseline_RSSI (из empty calibration)
  [12] amp_energy_ratio       -- sum(amp^2) / sum(baseline_amp^2)
  [13] phase_gradient_proxy   -- std(diff(subcarrier_amplitudes)) / mean_amp

Inter-node features (крестовые отношения):
  ratio_n01_n02  -- left/right door balance --> door vs passage
  ratio_n03_n07  -- left/right center balance --> center laterality
  ratio_n05_n06  -- center depth indicator
  ratio_n01_n03  -- door-to-center gradient --> depth estimation
  ratio_n02_n04  -- passage-to-center gradient

  Δ_energy(n01, n02) = |energy_n01 - energy_n02| / (energy_n01 + energy_n02)
  ... для всех 21 пар (C(7,2))

Total: 98 + 21 inter-node ratios + 21 delta_energy = 140 features
```

#### 3.3. Данные для обучения

| Зона | Маркеры (потолочные) | Доп. позиции | Мин. сэмплы |
|------|---------------------|-------------|-------------|
| door | mark1, mark11 | у двери (y=0.3) | 300 |
| passage | mark2, mark3, mark10 | проход (x=2.5, y=1.5-3) | 300 |
| center | mark4, mark6, mark8, mark9 | свободные позиции y=3.5-5 | 400 |
| deep | mark5, mark7 | y=5.5-6 (если доступно) | 200 |
| zone4 | --- | x=1.5, y=0.5 (FP2 зона) | 200 |

**Протокол записи:** 1 человек стоит под маркером 2 мин + ходит внутри зоны 2 мин. Каждая сессия помечена zone ground truth. Используется endpoint `/api/v1/csi/marker/record` для привязки к маркерам.

#### 3.4. Модель

```
Архитектура: Stacking ensemble
  Level 0:
    - GBM-500 (как V46, на 140 фичах)
    - RF-1000 (class_weight=balanced)
    - LightGBM (leaf_wise, learning_rate=0.03)
  Level 1:
    - Logistic Regression (meta-learner)

Альтернатива (если данных >2000):
    - 1D CNN на raw subcarrier amplitudes (per-node: 7 × [window × n_subcarriers])
    - Input: (batch, 7_nodes, 7_packets, 128_subcarriers)
    - Conv1D per node --> concat --> Dense --> 5 zones
```

#### 3.5. Критерий готовности

- CV Balanced Accuracy >= 0.92 на 5 зонах
- Per-zone F1 >= 0.85 для каждой из 5 зон
- Confusion: door<->center leakage < 5%

---

## 4. Этап 3: Модель подсчета людей

### Текущее состояние

V57: RF, 903 фичи, 476 окон, F1=0.882 (1 vs 2 человека). Использует raw subcarrier features.

### Целевая архитектура: V60 Count Model

#### 4.1. Расширение классов

```
V57 (текущий):     V60 (целевой):
  1 person           0 (empty)
  2 persons          1 person
                     2 persons
                     3+ persons (опционально)
```

Объединение с V46: V46 уже знает empty. V60 запускается только когда V46 == "occupied" (static | motion).

#### 4.2. Ключевые признаки для count estimation

Физическая основа: 2 человека создают больше scattering --> выше entropy, больше multipath:

```
Count-specific features (на базе V46 features):
  1. total_energy = sum(mean_amp^2) across all nodes
  2. energy_spread = std(per_node_energy) / mean(per_node_energy)
  3. sc_entropy_total = sum(sc_entropy) across nodes / 7
  4. temporal_var_total = sum(temporal_var) across nodes
  5. rssi_diversity = std(mean_rssi) across nodes
  6. amp_coherence = mean(pairwise_correlation of node amp profiles)
  7. multipath_indicator = mean(high_ratio - low_ratio) across nodes

Cross-node correlation features:
  8. amp_correlation_matrix = pearson_corr(node_i_amp, node_j_amp) --> 21 values
  9. temporal_coherence = mean(corr(temporal_var_i, temporal_var_j)) --> 1 value

Spatial diversity:
  10. active_node_ratio = n_nodes_with_high_energy / 7
  11. energy_centroid_spread = std of per-node energy weights
```

#### 4.3. Данные для обучения

| Класс | Существующие записи | Нужно дополнить | Протокол |
|-------|-------------------|----------------|----------|
| 0 (empty) | 57 файлов, ~2000+ окон | Достаточно | --- |
| 1 person | Все marker + walking recordings | Достаточно (~500 окон) | --- |
| 2 persons | 2person_v41 sessions (3 файла) | +5 сессий по 5 мин | 2 человека, разные позиции |
| 3+ persons | 0 | 3 сессии по 3 мин | 3 человека (если возможно) |

**Приоритетный сбор:** 2-person recordings с разными паттернами:
- Оба стоят (static-static)
- Один стоит, другой ходит (static-motion)
- Оба ходят (motion-motion)
- В одной зоне vs в разных зонах

#### 4.4. Модель

```
Архитектура: Two-stage classifier
  Stage 1: V46 binary gate (empty vs occupied) -- уже работает
  Stage 2: Count classifier (при occupied)
    Input: 77 V46 features + 21 cross-corr + 11 count-specific = 109 features
    Model: HistGradientBoostingClassifier(max_iter=500, class_weight='balanced')
    Output: 1 / 2 / 3+
```

#### 4.5. Критерий готовности

- F1_macro >= 0.90 для 1 vs 2 (улучшение с 0.882)
- F1 >= 0.80 для 3+ (если собраны данные)
- False alarm rate (1 -> 2) < 5%

---

## 5. Этап 4: Иерархический pipeline

### Архитектура каскада

```
                    CSI Raw Window (7 nodes × 7 packets)
                              |
                    Feature Extraction (V46)
                              |
                    ┌─────────▼──────────┐
                    │  Model 1: Occupancy │  V46 GBM-500
                    │  empty/static/motion│  77 features
                    └─────────┬──────────┘
                              |
                ┌─────────────┼────────────────┐
                |             |                 |
             empty         static            motion
               |             |                 |
               ▼             ▼                 ▼
            (done)    ┌──────┴──────┐   ┌──────┴──────┐
                      │ Model 2a:   │   │ Model 2b:   │
                      │ Zone (static)│   │ Zone (motion)│
                      │ 5 zones     │   │ 5 zones     │
                      └──────┬──────┘   └──────┬──────┘
                             |                 |
                      ┌──────▼──────┐   ┌──────▼──────┐
                      │ Model 3:    │   │ Model 3:    │
                      │ Count       │   │ Count       │
                      │ 1/2/3+      │   │ 1/2/3+      │
                      └──────┬──────┘   └──────┬──────┘
                             |                 |
                      ┌──────▼──────────────────▼──────┐
                      │ Model 4: Temporal Smoother      │
                      │ (Sequence model / HMM / CRF)    │
                      │ Убирает одиночные флипы          │
                      └──────┬──────────────────────────┘
                             |
                      ┌──────▼──────┐
                      │ Output:      │
                      │  occupancy   │  empty/static/motion
                      │  zone        │  door/passage/center/deep/zone4
                      │  count       │  0/1/2/3+
                      │  confidence  │  [0, 1]
                      └─────────────┘
```

### Правила каскада

```python
class HierarchicalPipeline:
    """
    Runtime inference pipeline.
    Latency budget: <50ms per window (10 Hz cycle).
    """

    def predict(self, features_v46: np.ndarray) -> dict:
        # Stage 1: Occupancy
        occ_pred, occ_proba = self.model_occupancy.predict(features_v46)

        if occ_pred == "empty":
            return {"occupancy": "empty", "zone": None, "count": 0,
                    "confidence": float(max(occ_proba))}

        # Stage 2: Zone
        zone_features = self.extract_zone_features(features_v46)
        if occ_pred == "static":
            zone_pred, zone_proba = self.model_zone_static.predict(zone_features)
        else:  # motion
            zone_pred, zone_proba = self.model_zone_motion.predict(zone_features)

        # Stage 3: Count (only if occupied)
        count_features = self.extract_count_features(features_v46)
        count_pred, count_proba = self.model_count.predict(count_features)

        # Stage 4: Temporal smoothing (optional, uses history buffer)
        smoothed = self.temporal_smoother.smooth(
            occ_pred, zone_pred, count_pred,
            occ_proba, zone_proba, count_proba
        )

        return smoothed
```

### Gate logic (важные правила)

1. **High-confidence empty gate:** Если V46 P(empty) > 0.95 -- пропускаем все остальные модели.
2. **Zone fallback:** Если zone confidence < 0.6 -- возвращаем "unknown_zone" вместо неуверенного предсказания.
3. **Count override:** Если V46 == static и zone == door, count по умолчанию = 1 (упрощенная эвристика для дверного проёма).
4. **Latency guard:** Если inference > 30ms, отключаем count model (наименее критичный).

### Интеграция в csi_prediction_service.py

```python
# В predict_window() добавляется каскад:
async def predict_window(self):
    # ... existing V46 feature extraction ...
    X = extract_features_v46(window_data)

    # V46 occupancy (existing)
    occ_result = self.binary_model.predict_proba(X.reshape(1, -1))

    # Zone model (new) -- triggered if occupied
    if occ_class in ("static", "motion"):
        zone_result = self._predict_zone(X, occ_class)
        count_result = self._predict_count(X)

    # Temporal smoother (new)
    self._history_buffer.append(PredictionFrame(occ, zone, count, ts))
    smoothed = self._temporal_smooth()

    self.current.update({
        "occupancy": smoothed.occupancy,
        "zone": smoothed.zone,
        "person_count": smoothed.count,
        "confidence": smoothed.confidence,
    })
```

---

## 6. Этап 5: Темпоральные модели

### Проблема

Текущий V46 предсказывает каждое окно независимо. Это приводит к:
- Одиночным "флипам" (empty -> static -> empty за 0.3 сек)
- Пропуску плавных переходов (вход через дверь)
- Невозможности отличить "прошёл мимо" от "стоит"

### 5.1. Быстрое решение: скользящий majority vote (уже частично есть)

```
History buffer: последние N=10 предсказаний (3 секунды при 3.3 Hz)

Правила:
  - occupancy: majority vote с весами confidence
  - zone: majority vote, но переключение зоны только если
    новая зона имеет >= 4/10 голосов (hysteresis)
  - count: median of last 10, отфильтровав outliers
```

### 5.2. HMM (Hidden Markov Model) для occupancy transitions

```
States: [empty, static_door, static_center, motion_door, motion_center, ...]
         (occupancy × zone = 3 × 5 = 15 states)

Transition matrix (learned from data):
  P(empty -> static_door) = высокая (человек вошёл)
  P(static_center -> motion_center) = средняя (встал и пошёл)
  P(motion_door -> empty) = высокая (вышел)
  P(empty -> motion_center) = очень низкая (нельзя появиться в центре)

Emission: P(V46_output | true_state) -- calibrated from confusion matrix

Inference: Viterbi decoding на скользящем окне 30 секунд
```

**Данные для обучения HMM:**
- Нужны длинные аннотированные записи (5-10 мин) с метками переходов
- Протокол: записывается видео + CSI параллельно, потом ручная разметка видео -> labels

### 5.3. LSTM / GRU для sequence classification

```
Архитектура:
  Input: sequence of V46 features (T=20 windows = 6 секунд)
  Shape: (batch, T=20, F=77)

  Layer 1: Bidirectional LSTM(hidden=64)
  Layer 2: Dropout(0.3)
  Layer 3: Dense(32, relu)
  Layer 4: Dense(n_classes, softmax)

  Output: (occupancy, zone, count) per window
  Loss: weighted cross-entropy per task (multi-task head)

Advantages over window-level:
  - Captures transition patterns (entering, leaving)
  - Smooths naturally (no explicit hysteresis)
  - Can detect "walking through" vs "standing"
```

**Необходимые данные:**
- Минимум 2 часа аннотированных непрерывных записей
- Разметка: каждое 0.3-sec окно получает (occupancy, zone, count)
- Видео для ground truth + timestamp alignment

### 5.4. TCN (Temporal Convolutional Network) -- рекомендуемый подход

```
Архитектура:
  Input: (batch, T=30, F=77)

  TCN Block × 4:
    CausalConv1D(dilation=2^k, filters=64, kernel=3)
    BatchNorm + ReLU + Dropout(0.2)

  GlobalAveragePooling
  Dense(n_classes)

Преимущества TCN над LSTM:
  - Параллелизуемый (быстрее обучение)
  - Фиксированное receptive field (контролируемая задержка)
  - Меньше переобучения на малых данных
  - Receptive field = 2^4 * (3-1) = 32 окна = ~10 секунд
```

### 5.5. Требования к данным для темпоральных моделей

| Модель | Минимум данных | Формат | Задержка inference |
|--------|---------------|--------|-------------------|
| Majority vote | 0 (правила) | --- | 0ms |
| HMM | 30 мин аннотаций | transition counts | <1ms |
| LSTM | 2 часа | (T, 77) sequences | ~5ms |
| TCN | 2 часа | (T, 77) sequences | ~3ms |

---

## 7. Этап 6: Координатная регрессия и оценка позы

### Долгосрочная цель

Вместо дискретных зон -- непрерывные координаты (x, y) в пространстве гаража (0-3m, 0-7m).

### 6.1. Координатная регрессия (V70+)

#### Физическая основа

Человек на координатах (x, y) изменяет CSI от каждого узла пропорционально расстоянию и углу. При 7 узлах с известными координатами -- система overdetermined (7 уравнений, 2 неизвестных).

```
Модель: Multi-output regression
  Input: 77 V46 features (или 140 расширенных)
  Output: (x, y) in meters

  Архитектура A -- Gradient Boosting Regression:
    MultiOutputRegressor(GBM(n_estimators=500))
    Быстрый baseline, работает на малых данных

  Архитектура B -- MLP Regression:
    Input(140) -> Dense(256, relu) -> Dense(128, relu) -> Dense(64, relu) -> Dense(2)
    Loss: MSE + L1 regularization
    Преимущество: может выучить нелинейные зависимости distance-to-amplitude

  Архитектура C -- Fingerprinting + kNN:
    Офлайн: собираем CSI fingerprints на сетке 0.5m (6x14 = 84 точки)
    Онлайн: kNN(k=5, weighted by distance) к ближайшим fingerprints
    Преимущество: не требует обучения модели, только сбор данных
```

#### Данные для обучения

**Сбор по потолочным маркерам (уже есть инфраструктура):**

```
11 маркеров на потолке с известными координатами:
  mark1:  (2.5, 1.0)   mark7:  (0.5, 5.0)
  mark2:  (2.5, 2.0)   mark8:  (0.5, 4.0)
  mark3:  (2.5, 3.0)   mark9:  (1.5, 4.0) -- точный центр
  mark4:  (2.5, 4.0)   mark10: (2.0, 3.0)
  mark5:  (2.5, 5.0)   mark11: (2.0, 1.0)
  mark6:  (1.5, 5.0)

Протокол:
  1. Стоять под каждым маркером 2 мин --> ~120 окон per marker
  2. Повторить в 3 условиях (утро/день/вечер)
  3. Total: 11 × 3 × 120 = 3960 сэмплов с GT координатами

Дополнительно: сетка 0.5m шагом (между маркерами):
  4. 84 точки × 30 сек × 1 условие = ~2500 сэмплов
```

#### Ожидаемая точность

- MAE < 0.5m на сетке маркеров (baseline с GBM)
- MAE < 0.3m с MLP + temporal smoothing
- Для сравнения: WiFi RSSI fingerprinting обычно дает 1-2m, CSI дает 0.3-0.5m в литературе

### 6.2. Tracking (траектория во времени)

```
Kalman Filter поверх координатной регрессии:
  State: [x, y, vx, vy]
  Measurement: (x_pred, y_pred) от regression model
  Process noise: Q ~ diag(0.1, 0.1, 0.5, 0.5)
  Measurement noise: R ~ diag(0.3, 0.3)  -- из MAE модели

Constraints:
  - x in [0, 3], y in [0, 7]  -- стены гаража
  - |v| < 2 m/s  -- максимальная скорость ходьбы
  - Дверной проём: единственная точка входа/выхода
```

### 6.3. Оценка позы (V100+ -- исследовательский горизонт)

Полная DensePose из WiFi CSI -- конечная цель проекта. Требует значительно больше данных и более сложной архитектуры.

```
Этапы к DensePose:

1. Bounding box estimation (V80):
   Input: CSI features (temporal sequence)
   Output: (x_center, y_center, width, height) -- bbox в 2D
   Архитектура: TCN + regression head
   Данные: видео с bbox разметкой + aligned CSI

2. Keypoint estimation (V90):
   Input: CSI features
   Output: 17 COCO keypoints (x, y, confidence) × person
   Архитектура: Encoder-Decoder с skip connections
   Данные: OpenPose/MediaPipe на видео -> GT keypoints -> aligned с CSI
   Teacher-student: видео-модель = teacher, CSI-модель = student

3. DensePose (V100):
   Input: CSI features
   Output: UV mapping на IUV representation (24 body parts × (u, v))
   Архитектура: U-Net adapted for CSI input
   Данные: DensePose RCNN на видео -> GT -> aligned с CSI

Реалистичная оценка:
  - V80 (bbox): достижимо при 10+ часах видео + CSI
  - V90 (keypoints): требует 50+ часов, accuracy ~30% PCK
  - V100 (densepose): исследовательский уровень, публикации в CVPR/ECCV
```

#### Teacher-Student Pipeline

```
                 Camera Video                    CSI Raw Data
                     |                               |
                     v                               v
            ┌───────────────┐              ┌───────────────┐
            │  OpenPose /    │              │  V46 Feature   │
            │  DensePose RCNN│              │  Extraction    │
            │  (Teacher)     │              │                │
            └───────┬───────┘              └───────┬───────┘
                    |                               |
            poses (GT)                     CSI features
                    |                               |
                    └───────────┬───────────────────┘
                                |
                    ┌───────────▼──────────┐
                    │  Temporal Alignment   │
                    │  (video ts <-> CSI ts)│
                    └───────────┬──────────┘
                                |
                    ┌───────────▼──────────┐
                    │  Student Model        │
                    │  CSI -> Pose          │
                    │  (TCN + Decoder)      │
                    └──────────────────────┘
```

---

## 8. Сводная таблица моделей

| Модель | Версия | Задача | Features | Данные (мин) | Зависит от | Приоритет | Срок |
|--------|--------|--------|----------|-------------|-----------|-----------|------|
| Occupancy | V46 (есть) | empty/static/motion | 77 | 156 окон | --- | Done | --- |
| Occupancy+ | V48 | +static samples | 77 | 500+ | Static recordings | P0 | 1 нед |
| Zone (static) | V50 | 5 зон при static | 140 | 1500+ | Marker recordings | P1 | 2 нед |
| Zone (motion) | V51 | 5 зон при motion | 140 | 1000+ | Walking recordings | P1 | 2 нед |
| Count | V60 | 1/2/3+ человек | 109 | 800+ | 2-person recordings | P2 | 3 нед |
| Temporal HMM | V65 | Smoothing transitions | states | 30 мин annotated | V48+V50 | P2 | 3 нед |
| Temporal TCN | V70 | Sequence occupancy+zone | seq(77) | 2 часа annotated | V48+V50 | P3 | 1 мес |
| Coord regression | V75 | (x,y) coordinates | 140 | 3960+ (markers) | Marker grid | P3 | 1 мес |
| Kalman tracker | V76 | Trajectory smoothing | (x,y) stream | --- | V75 | P3 | 1 мес |
| Bbox estimation | V80 | Bounding box | seq(140) | 10h video+CSI | Video pipeline | P4 | 3 мес |
| Keypoint (COCO) | V90 | 17 keypoints | seq(140) | 50h video+CSI | V80 + OpenPose | P5 | 6 мес |
| DensePose | V100 | Full UV mapping | seq(140+) | 100h+ | V90 + DensePose RCNN | Research | 12 мес |

### Приоритеты выполнения

```
Неделя 1-2:  P0 -- Собрать static данные, обучить V48
Неделя 2-3:  P1 -- Zone model V50/V51 (5 зон)
Неделя 3-4:  P2 -- Count model V60 + HMM smoother V65
Месяц 2:     P3 -- TCN temporal V70 + Coord regression V75
Месяц 3:     P4 -- Bbox estimation V80 (нужна видео-инфраструктура)
Месяц 4-6:   P5 -- Keypoint estimation V90
Месяц 6-12:  Research -- DensePose V100
```

### Метрики успеха по этапам

| Этап | Метрика | Текущее | Цель |
|------|---------|---------|------|
| Occupancy F1 (macro) | F1_macro | 0.985 | 0.99 |
| Static recall | recall(static) | ~0.85* | 0.95 |
| Zone accuracy (5 zones) | balanced_acc | 0.986 (2 zones) | 0.92 (5 zones) |
| Count F1 (1 vs 2) | F1_macro | 0.882 | 0.92 |
| Coord MAE | meters | N/A | <0.5m |
| Temporal flip rate | flips/min | ~2* | <0.5 |
| Bbox IoU | mIoU | N/A | >0.5 |

*оценочные значения, требуют замера.

---

## Зависимости и риски

### Аппаратные зависимости

1. **Стабильность ESP32 нод** -- потеря 3+ нод из 7 разрушает предсказания (MIN_NODES=5).
2. **Tenda router** -- единственный источник CSI. При замене нужен полный retrain.
3. **Камеры для teacher-student** -- нужны 2-3 камеры с перекрытием всего гаража.

### Риски данных

1. **Drift** -- V46 решает drift ratios, но при сильных изменениях среды (лето vs зима) возможна деградация. Рекомендация: пересбор empty baseline каждый месяц.
2. **Multi-person ambiguity** -- 2 человека в одной зоне неразличимы от 1 человека с высокой активностью. Нужны controlled experiments.
3. **Annotation cost** -- temporal/pose модели требуют часы ручной разметки видео. Рассмотреть полу-автоматическую разметку (OpenPose GT + ручная коррекция).

### Техническое доступ

| Ресурс | Наличие | Нужно |
|--------|---------|-------|
| ESP32 ноды (7 шт) | Есть | Стабильность |
| Tenda router + CSI | Есть | --- |
| Потолочные маркеры (11 шт) | Есть | --- |
| Видео камеры | 3 камеры | Синхронизация timestamps |
| GPU для обучения | Нет (CPU sklearn) | Для LSTM/TCN: GPU или Apple MPS |
| Aqara FP2 | Есть | Для GT zone4 |

---

*Документ создан 2026-04-01. Обновлять по мере продвижения по этапам.*
