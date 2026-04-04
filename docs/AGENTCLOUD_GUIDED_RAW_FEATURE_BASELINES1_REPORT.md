# AGENTCLOUD_GUIDED_RAW_FEATURE_BASELINES1_REPORT

## Verdict

- Построен первый raw CSI baseline на gold guided session с ручной разметкой door/center/transition.
- Это уже не telemetry/meta слой, а window-level признаки из реальных CSI chunk-ов.

## Dataset

- Recording: `garage_single_freeform_voice_video_20260403_034526`
- Raw windows: `56`
- Zone rows: `46`
- Motion rows: `55`

## Zone Baseline

- Holdout accuracy: `0.458333`
- Holdout f1: `0.628571`
- Holdout balanced_accuracy: `0.458333`
- Train groups: `['cycle_1']`
- Test groups: `['cycle_2']`

## Motion Baseline

- Holdout accuracy: `0.3`
- Holdout f1: `0.222222`
- Holdout balanced_accuracy: `0.375`
- Train groups: `['cycle_1']`
- Test groups: `['cycle_2']`