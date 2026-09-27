# SkyGuard AI — Verification Results

## Current execution

A full `pytest` collection was attempted after the ML integration cleanup.

Result: **BLOCKED DURING TEST COLLECTION**

Reason:

```text
ModuleNotFoundError: No module named 'tensorflow'
```

The error occurs when the FastAPI pipeline and LSTM test module import the TensorFlow/Keras LSTM detector.

This environment therefore cannot honestly report a new test pass count.

## Checks completed successfully outside pytest

- `lstm_metadata.json` reports `Keras_LSTMAutoencoder`.
- `lstm_threshold.joblib` = `0.07097852191878912`.
- LSTM sequence length = `24`.
- LSTM input dimension = `3`.
- Isolation Forest feature count = `16`.
- Isolation Forest scaler = `StandardScaler`.
- `lstm_autoencoder.keras` exists.
- Obsolete `lstm_autoencoder.pt` is absent.
- Obsolete `0.3728` threshold references were removed from source and generated frontend assets.

## Required local verification

After installing the backend dependencies from `requirements.txt`, run:

```bash
python -m pytest -q
```

Then run the frontend with a fresh dependency installation:

```bash
cd frontend
npm install
npm run build
```
