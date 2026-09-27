# SkyGuard AI — Current Integration Audit

**Audit scope:** consistency between the finalized notebook artifacts and the Antigravity-generated runtime application.

## Current Status

**ML artifact integration: VERIFIED**

- Isolation Forest: 16 features, StandardScaler, notebook-sourced artifacts.
- LSTM: TensorFlow/Keras, 24-step T/P/RH sequences, StandardScaler.
- LSTM threshold: `0.07097852191878912` in both metadata and threshold artifact.
- Obsolete `.pt` LSTM artifact: removed.
- Obsolete `0.3728` LSTM threshold references: removed from source and generated frontend bundle.
- Fake ML fallback scores: not present in the current runtime pipeline; inference failures leave ML evidence unavailable.
- Spatial data: not fabricated when buddy observations are absent.

## Verification Performed

1. Loaded and inspected `lstm_metadata.json`.
2. Loaded `lstm_threshold.joblib` and confirmed it matches the metadata threshold.
3. Inspected `iforest_metadata.json` and confirmed 16 features and StandardScaler.
4. Confirmed `lstm_autoencoder.keras` exists.
5. Confirmed the obsolete `lstm_autoencoder.pt` artifact is absent.
6. Searched the project for the obsolete `0.3728`, PyTorch LSTM, and `.pt` references and removed stale references.
7. Added `requirements.txt` containing the backend runtime dependencies.

## Test Environment Limitation

A full pytest run could not be completed in this execution environment because TensorFlow is not installed. The failure occurred during test collection with `ModuleNotFoundError: No module named 'tensorflow'`; this is an environment dependency issue, not a reported model-inference failure.

The frontend production build was also not re-run here because the supplied `node_modules` installation is missing Rollup's platform-specific optional package. The source changes were applied to the frontend source and existing distribution bundle.

Therefore this audit does **not** claim a new 100% test pass rate. The project should be run in the intended development environment after installing `requirements.txt` and running `npm install`.
