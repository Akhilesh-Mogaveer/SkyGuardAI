"""Chronological Training and Evaluation Pipeline for AWS Isolation Forest.

Enforces strict chronological partitioning:
- Train Split:      2015-01-01 00:00 to 2015-12-31 23:00 (1 full polar seasonal cycle)
- Validation Split: 2016-01-01 00:00 to 2016-06-30 23:00 (Hyperparameter calibration)
- Test Split:       2016-07-01 00:00 to 2016-12-19 12:00 (Held-out evaluation)

Guarantees zero data leakage:
- RobustScaler is fitted strictly on the Train Split.
- Rolling features and step differences are causal and segment-constrained.
- Evaluates held-out anomaly detection, specifically verifying 2016-09-09 17:00.
"""

import argparse
import json
import logging
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from backend.app.config import settings
from backend.app.core.ml_isolation_forest import AWSIsolationForestDetector, IForestConfig


def run_chronological_training(
    input_parquet: Path = settings.PROCESSED_DATA_DIR / "cleaned_maitri.parquet",
    output_dir: Path = settings.DATA_DIR / "models",
    contamination: float = 0.03,
) -> None:
    """Executes chronological train/val/test split and fits the Isolation Forest model."""
    start_time = time.time()
    logger = logging.getLogger("skyguard.train_iforest")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("================================================================================")
    logger.info("SkyGuard AI: Chronological Isolation Forest Training Pipeline")
    logger.info("================================================================================")
    logger.info("Input Dataset: %s", input_parquet)
    logger.info("Configured Contamination: %.3f", contamination)

    df = pd.read_parquet(input_parquet)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(by="timestamp").reset_index(drop=True)

    # Filter to period where all T, P, RH channels are populated
    dense_df = df[df["timestamp"] >= "2015-01-01 00:00:00+00:00"].copy()
    logger.info("Available high-completeness observations (2015-2016): %d", len(dense_df))

    # 1. Chronological Partitioning
    train_mask = (dense_df["timestamp"] >= "2015-01-01 00:00:00+00:00") & (
        dense_df["timestamp"] <= "2015-12-31 23:59:59+00:00"
    )
    val_mask = (dense_df["timestamp"] >= "2016-01-01 00:00:00+00:00") & (
        dense_df["timestamp"] <= "2016-06-30 23:59:59+00:00"
    )
    test_mask = dense_df["timestamp"] >= "2016-07-01 00:00:00+00:00"

    train_df = dense_df[train_mask].copy()
    val_df = dense_df[val_mask].copy()
    test_df = dense_df[test_mask].copy()

    logger.info("Train Partition:      %s to %s (%d records)", train_df["timestamp"].min(), train_df["timestamp"].max(), len(train_df))
    logger.info("Validation Partition: %s to %s (%d records)", val_df["timestamp"].min(), val_df["timestamp"].max(), len(val_df))
    logger.info("Test Partition:       %s to %s (%d records)", test_df["timestamp"].min(), test_df["timestamp"].max(), len(test_df))

    # 2. Fit Detector (Strictly on Train Split)
    cfg = IForestConfig(contamination=contamination)
    detector = AWSIsolationForestDetector(config=cfg, model_path=output_dir / "isolation_forest.joblib", scaler_path=output_dir / "iforest_scaler.joblib")
    detector.fit(train_df=train_df, save_artifacts=True)

    # 3. Inference on Validation and Test Partitions
    logger.info("Evaluating on Validation partition...")
    val_results = detector.transform_dataframe(val_df)
    val_anomalies = int(val_results["iforest_anomaly_flag"].sum())
    val_anomaly_rate = round(val_anomalies / len(val_results) * 100.0, 2)

    logger.info("Evaluating on Held-Out Test partition...")
    test_results = detector.transform_dataframe(test_df)
    test_anomalies = int(test_results["iforest_anomaly_flag"].sum())
    test_anomaly_rate = round(test_anomalies / len(test_results) * 100.0, 2)

    # 4. Specifically audit the known target anomaly: 2016-09-09 17:00
    target_ts = pd.to_datetime("2016-09-09 17:00:00+00:00", utc=True)
    target_match = test_results[test_results["timestamp"] == target_ts]

    target_audit = {}
    if not target_match.empty:
        r = target_match.iloc[0]
        target_audit = {
            "timestamp": str(r["timestamp"]),
            "temperature": float(r["temperature"]),
            "pressure": float(r["pressure"]),
            "humidity": float(r["relative_humidity"]),
            "iforest_anomaly_flag": bool(r["iforest_anomaly_flag"]),
            "iforest_anomaly_score": round(float(r["iforest_anomaly_score"]), 4),
            "iforest_decision_score": round(float(r["iforest_decision_score"]), 4),
        }
        logger.info(
            "Target Anomaly 2016-09-09 17:00 Test: Flag=%s | Anomaly Score=%.4f (Decision=%.4f)",
            target_audit["iforest_anomaly_flag"],
            target_audit["iforest_anomaly_score"],
            target_audit["iforest_decision_score"],
        )

    # 5. Export Evaluation Report
    report = {
        "model": "IsolationForest",
        "contamination": contamination,
        "n_estimators": cfg.n_estimators,
        "feature_names": cfg.feature_names,
        "train_records": len(train_df),
        "validation_records": len(val_df),
        "validation_anomalies": val_anomalies,
        "validation_anomaly_rate_pct": val_anomaly_rate,
        "test_records": len(test_df),
        "test_anomalies": test_anomalies,
        "test_anomaly_rate_pct": test_anomaly_rate,
        "target_anomaly_benchmark": target_audit,
    }

    report_path = settings.PROCESSED_DATA_DIR / "iforest_training_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    elapsed = time.time() - start_time
    logger.info("================================================================================")
    logger.info("Isolation Forest Training Pipeline Completed in %.2f seconds", elapsed)
    logger.info("Val Anomaly Rate: %.2f%% | Test Anomaly Rate: %.2f%%", val_anomaly_rate, test_anomaly_rate)
    logger.info("Saved Artifacts: %s", output_dir)
    logger.info("Training Report: %s", report_path)
    logger.info("================================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train AWS Isolation Forest Model")
    parser.add_argument(
        "--input",
        type=Path,
        default=settings.PROCESSED_DATA_DIR / "cleaned_maitri.parquet",
        help="Path to cleaned dataset",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=settings.DATA_DIR / "models",
        help="Path to models artifact directory",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=0.03,
        help="Contamination factor for Isolation Forest",
    )
    args = parser.parse_args()
    run_chronological_training(
        input_parquet=args.input,
        output_dir=args.out_dir,
        contamination=args.contamination,
    )
