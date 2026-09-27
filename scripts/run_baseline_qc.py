"""Executes Baseline Rule-Based Quality Control across historical AWS observations.

Processes data/processed/cleaned_maitri.parquet, preserves raw observations,
applies all 7 WMO QC detectors, and exports the structured QC result dataset.
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
from backend.app.core.baseline_qc import QCConfig, RuleBasedQC


def run_baseline_qc_pipeline(
    input_parquet: Path = settings.PROCESSED_DATA_DIR / "cleaned_maitri.parquet",
    output_dir: Path = settings.PROCESSED_DATA_DIR,
) -> None:
    """Runs Rule-Based QC over the dataset and exports results."""
    start_time = time.time()
    logger = logging.getLogger("skyguard.qc_runner")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("================================================================================")
    logger.info("SkyGuard AI: Executing Baseline Rule-Based Quality Control (QC)")
    logger.info("================================================================================")
    logger.info("Input Dataset: %s", input_parquet)

    if not input_parquet.exists():
        raise FileNotFoundError(f"Cleaned dataset not found at {input_parquet}. Run Phase 1 first.")

    df = pd.read_parquet(input_parquet)
    logger.info("Loaded %d cleaned observations for QC processing.", len(df))

    qc_engine = RuleBasedQC(config=QCConfig(), station_id=settings.DEFAULT_STATION_ID)
    qc_df = qc_engine.process_dataframe(df)

    # Summary statistics
    flag_counts = qc_df["qc_flag"].value_counts().to_dict()
    temp_spikes = int(qc_df["temperature_spike"].sum())
    press_spikes = int(qc_df["pressure_spike"].sum())
    hum_spikes = int(qc_df["humidity_spike"].sum())
    temp_flatlines = int(qc_df["temperature_flatline"].sum())
    press_flatlines = int(qc_df["pressure_flatline"].sum())
    hum_flatlines = int(qc_df["humidity_flatline"].sum())
    missing_count = int(qc_df["missing_flag"].sum())
    gap_count = int(qc_df["gap_flag"].sum())

    summary = {
        "total_processed": len(qc_df),
        "flag_distribution": flag_counts,
        "detector_triggers": {
            "temperature_spike": temp_spikes,
            "pressure_spike": press_spikes,
            "humidity_spike": hum_spikes,
            "temperature_flatline": temp_flatlines,
            "pressure_flatline": press_flatlines,
            "humidity_flatline": hum_flatlines,
            "missing_observations": missing_count,
            "time_gaps": gap_count,
        },
    }

    # Save QC dataset
    output_dir.mkdir(parents=True, exist_ok=True)
    out_parquet = output_dir / "qc_baseline_results.parquet"
    out_summary_json = output_dir / "qc_baseline_summary.json"

    logger.info("Saving structured QC results to Parquet: %s", out_parquet)
    qc_df.to_parquet(out_parquet, index=False, engine="pyarrow", compression="snappy")

    with open(out_summary_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    elapsed = time.time() - start_time
    logger.info("================================================================================")
    logger.info("Baseline Rule-Based QC Complete in %.2f seconds.", elapsed)
    logger.info("Flag Distribution: %s", flag_counts)
    logger.info(
        "Spikes: T=%d, P=%d, RH=%d | Flatlines: T=%d, P=%d, RH=%d",
        temp_spikes,
        press_spikes,
        hum_spikes,
        temp_flatlines,
        press_flatlines,
        hum_flatlines,
    )
    logger.info("Structured QC Output: %s", out_parquet)
    logger.info("================================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SkyGuard AI Baseline Rule-Based QC")
    parser.add_argument(
        "--input",
        type=Path,
        default=settings.PROCESSED_DATA_DIR / "cleaned_maitri.parquet",
        help="Input cleaned parquet file",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=settings.PROCESSED_DATA_DIR,
        help="Output directory",
    )
    args = parser.parse_args()
    run_baseline_qc_pipeline(input_parquet=args.input, output_dir=args.out_dir)
