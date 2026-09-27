# SkyGuard AI — Current System Architecture

## 1. System Overview
SkyGuard AI is a software-only AWS data-quality and anomaly-detection framework. The current prototype processes Temperature, Atmospheric Pressure, and Relative Humidity from the real Maitri AWS dataset and supports historical replay as a real-time demonstration.

## 2. Runtime Pipeline

```text
Raw AWS Observation
        ↓
Sentinel / Schema Sanitization
        ↓
Rule-Based Quality Control
        ↓
Isolation Forest (16 features)
        ↓
TensorFlow/Keras LSTM Autoencoder (24-step T/P/RH sequence)
        ↓
T/P/RH Physical Consistency
        ↓
Spatial Validation (only when real buddy data is available)
        ↓
Sensor History / Health
        ↓
Evidence Fusion
        ↓
NORMAL / LIKELY GENUINE WEATHER EVENT / LIKELY SENSOR DATA FAULT / UNCERTAIN
        ↓
Explanation + Optional Recovery Estimate
```

## 3. Current ML Artifacts

### 3.1 Isolation Forest
- Source: `SkyGuardAI_cleaned_final.ipynb`
- Features: 16
- Rolling statistics: 3-hour causal rolling mean/std
- Dynamic features: hourly T/P/RH changes
- Temporal features: hour/day sine and cosine
- Scaler: `StandardScaler`
- Artifacts: `isolation_forest.joblib`, `iforest_scaler.joblib`, `iforest_metadata.json`

### 3.2 TensorFlow/Keras LSTM Autoencoder
- Source: `SkyGuardAI_cleaned_final.ipynb`
- Inputs: Temperature, Pressure, Humidity
- Sequence length: 24 hourly observations
- Scaler: `StandardScaler`
- Threshold: `0.07097852191878912`
- Artifacts: `lstm_autoencoder.keras`, `lstm_scaler.joblib`, `lstm_threshold.joblib`, `lstm_metadata.json`
- Sequence windows are not created across configured time gaps.

## 4. Evidence Fusion
Raw model outputs are converted into bounded evidence signals before fusion. Missing model outputs remain unavailable; the runtime does not substitute fabricated ML scores.

Spatial evidence is marked unavailable when neighboring AWS observations are not supplied. The current Maitri demonstration therefore does not fabricate buddy-station measurements.

## 5. Known Demonstration Case

`2016-09-09 17:00 UTC`

- Temperature: `41.6 °C`
- Pressure: `946.7 hPa`
- Relative Humidity: `100 %`

This observation is used as a real-data demonstration case for the anomaly pipeline.

## 6. Application Architecture

- Backend: FastAPI
- Runtime streaming: WebSocket
- Historical demonstration: CSV replay
- Frontend: React + Vite + Tailwind CSS
- Charts: Recharts
- Maps: Leaflet / React Leaflet
- ML inference: serialized notebook artifacts loaded at runtime
