# AGENTCLOUD_CONVERSATION_SUPERVISION_META_BASELINES1_REPORT

## Verdict

- Построены truth-calibrated meta-baselines на user-confirmed supervision bundle.
- Эти baseline не обучаются на self-labeling runtime verdict, а используют твой подтверждённый truth поверх runtime telemetry / trace features.

## Datasets

- Occupancy rows: `466`
- Zone rows: `398`
- Occupancy groups: `8`
- Zone groups: `7`

## Existing Truth Eval Reference

- `runtime_binary balanced_accuracy = 0.54`
- `candidate_zone balanced_accuracy = 0.7306`

## Trained Baselines

- Occupancy holdout accuracy: `0.5`
- Occupancy holdout f1: `0.666667`
- Occupancy fit-all balanced_accuracy: `1.0`
- Zone holdout accuracy: `0.5`
- Zone holdout f1: `0.0`
- Zone holdout balanced_accuracy: `0.5`
- Zone paired-CV mean balanced_accuracy: `0.409259`

## Artifacts

- `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_meta_baselines1/conversation_supervision_occupancy_runtime_dataset_v1.csv`
- `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_meta_baselines1/conversation_supervision_zone_runtime_dataset_v1.csv`
- `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_meta_baselines1/occupancy_truth_calibrated_v1.summary.json`
- `/Users/arsen/Desktop/wifi-densepose/output/conversation_supervision_meta_baselines1/zone_truth_calibrated_v1.summary.json`