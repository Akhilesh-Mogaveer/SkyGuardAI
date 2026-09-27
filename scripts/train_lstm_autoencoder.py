"""Legacy compatibility wrapper for the finalized SkyGuard Keras LSTM artifact.

The production model is trained and exported by ``SkyGuardAI_cleaned_final.ipynb``.
This script intentionally does not retrain or create a PyTorch artifact. It only
verifies that the finalized Keras artifact, scaler, threshold and metadata load.
"""

from pathlib import Path
import json
import joblib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_ROOT / "data" / "models"

EXPECTED_THRESHOLD = 0.07097852191878912

def verify_artifacts() -> None:
    model_path = MODEL_DIR / "lstm_autoencoder.keras"
    scaler_path = MODEL_DIR / "lstm_scaler.joblib"
    threshold_path = MODEL_DIR / "lstm_threshold.joblib"
    metadata_path = MODEL_DIR / "lstm_metadata.json"

    for path in (model_path, scaler_path, threshold_path, metadata_path):
        if not path.exists():
            raise FileNotFoundError(f"Missing finalized LSTM artifact: {path}")

    threshold = float(joblib.load(threshold_path))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert abs(threshold - EXPECTED_THRESHOLD) < 1e-12
    assert metadata.get("model_type") == "Keras_LSTMAutoencoder"
    assert metadata.get("sequence_length") == 24
    assert metadata.get("input_dim") == 3

    print("Finalized TensorFlow/Keras LSTM artifacts verified successfully.")
    print(f"Model: {model_path.name}")
    print(f"Sequence length: {metadata['sequence_length']}")
    print(f"Threshold: {threshold}")

if __name__ == "__main__":
    verify_artifacts()
