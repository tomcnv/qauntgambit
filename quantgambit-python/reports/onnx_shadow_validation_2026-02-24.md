# ONNX Shadow Validation (2026-02-24)

## Scope
- Window: last 2 hours
- Dataset: `quantgambit-python/outputs/prediction_dataset_last2h.csv`
- Samples: 9,826
- Previous model: `prediction_baseline_20260221T183951Z.onnx`
- Current model: `prediction_baseline_20260224T192758Z.onnx`

## Offline model comparison (same samples)
- Previous accuracy: 0.2052
- Current accuracy: 0.2052
- Previous directional_f1_macro (down/up mean): 0.1702
- Current directional_f1_macro (down/up mean): 0.1702
- Previous directional_accuracy (non-flat labels): 0.5250
- Current directional_accuracy (non-flat labels): 0.5250
- Predicted class distribution (previous): down=9826, flat=0, up=0
- Predicted class distribution (current): down=9826, flat=0, up=0

Interpretation:
- In this 2h window both models collapsed to always predicting `down`.
- This is a model-behavior/data-regime issue, not just promotion plumbing.

## Replay validation (pipeline shadow)
- Run ID: `replay_8a7575ddfe79`
- Total replayed: 3,000
- Matches: 2,941
- Changes: 59
- Match rate: 0.9803
- Change category: degraded=59
- Stage shift: `none -> data_readiness` = 59
- API pass flag: true

Interpretation:
- Pipeline is stable and mostly matches prior decisions.
- Diffs are concentrated in data-readiness gate behavior, not broad pipeline divergence.
