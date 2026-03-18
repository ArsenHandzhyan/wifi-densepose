# AGENTCLOUD — Academic Deferred / Rejected Ideas

Дата: 2026-03-18 (updated 2026-03-19 with verified SenseFi engineering details)
Ветка: `codex/agent-cloud-video-curation`

## Роль документа

Этот документ фиксирует, что мы сознательно НЕ переносим сейчас в ESP32 CSI line.

Статусы:

- `deferred`: может понадобиться позже, но не сейчас
- `rejected_now`: не подходит текущей фазе
- `research_only`: допустимо как future research, но не как practical next move

## `WiFlow`

### 1. Full continuous pose decoding to body joints

- Статус:
  `research_only`
- Почему не тащим сейчас:
  наша текущая цель — крупные события и domain-robust event recognition, а не keypoint regression.
- Почему это не practical now:
  у нас нет synced pose ground truth масштаба WiFlow и нет задачи превращать ESP32 line в pose-estimation program на следующем шаге.

### 2. Human-joint structural decoding и full axial-attention pose head

- Статус:
  `deferred`
- Почему не тащим сейчас:
  для наших event targets topology of joints не является supervision target.
- Что остаётся полезным:
  сама идея structure-aware fusion, но не pose head.

### 3. WiFlow-level dataset assumptions

- Статус:
  `rejected_now`
- Почему:
  у WiFlow self-collected dense synchronized pose corpus с другой шкалой labels и другим supervision regime.
  Прямой перенос dataset assumptions на ESP32 event line был бы ложным.

## `DT-Pose`

### 4. GCN+Transformer pose decoder with task prompts

- Статус:
  `research_only`
- Почему не тащим сейчас:
  это решает structural fidelity gap для skeleton output, а у нас downstream target — event classes.

### 5. Direct 2D/3D pose training on external WiFi datasets

- Статус:
  `rejected_now`
- Почему:
  mismatch слишком велик:
  - NIC / antenna regime
  - dataset geometry
  - supervision target
  - CSI format
- Риск:
  это создаст красивую activity without useful transfer to our garage event line.

### 6. Task-prompt pose control as near-term path

- Статус:
  `deferred`
- Почему:
  prompts имеют смысл после появления stable learned encoder и downstream family.
  Сейчас это лишняя сложность.

## `SenseFi`

### 7. Full benchmark/model-zoo reproduction

- Статус:
  `rejected_now`
- Почему:
  переносить все MLP/CNN/RNN/ViT baselines на наш проект ради completeness — слишком дорогой и низкосигнальный ход.
- Что берём вместо этого:
  только minimal benchmark discipline.

### 8. “Deep is better” как default assumption

- Статус:
  `rejected_now`
- Почему:
  SenseFi прямо доказывает обратное из исходного кода:
  - ResNet-18 train ~100% → test 17.91% (Widar). ResNet-101 ещё хуже.
  - CNN-5 (5 layers) > ResNet-101 (101 layers) по cross-environment generalization.
  - MLP (92.00%) > ViT когда данных мало.
  Значит `HGB` остаётся обязательным floor, а не legacy мусором.

### 9. Direct cross-platform transfer claims

- Статус:
  `research_only`
- Почему:
  SenseFi benchmark охватывает несколько CSI platforms, но это не означает, что Intel/NIC-trained weights честно переносятся на наш ESP32 event task.

## Secondary References

### 10. `Person-in-WiFi-3D` as near-term roadmap

- Статус:
  `rejected_now`
- Почему:
  multi-person 3D pose estimation — не следующий practical шаг для гаражного ESP32 corpus.
- Что остаётся полезным:
  reference point для того, как amplitude+phase могут использоваться совместно в более богатой pose-задаче.

### 11. `CSI-Bench` full in-the-wild multitask reproduction

- Статус:
  `deferred`
- Почему:
  сам тезис про in-the-wild diversity нам полезен, но копировать multitask benchmark целиком сейчас преждевременно.
- Что реально берём:
  только напоминание, что long-horizon diversity и standardized splits важнее узкого lucky subset.

### 12. `ESP-CSI` on-device inference push

- Статус:
  `deferred`
- Почему:
  сначала нужен рабочий offline transfer gain.
  On-device compression / inference не должен открываться до того, как learned event encoder вообще докажет превосходство offline.

## Что сейчас не стоит делать

- обещать full pose estimation как ближайший шаг
- тащить чужие public datasets в train-loop как будто они совместимы с ESP32 гаражом
- раздувать benchmark в десятки моделей
- заменять frozen shallow baseline на “глубокую” модель без cross-epoch выигрыша
- выдавать video curation pipeline за academic-transfer outcome

## Bottom Line

Academic extraction не означает “перенести всё интересное”.

На этой фазе мы сознательно НЕ переносим:

- pose targets
- full external benchmark reproduction
- direct external-dataset transfer claims
- on-device deployment ambitions
