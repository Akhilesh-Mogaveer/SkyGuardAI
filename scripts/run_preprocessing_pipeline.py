"""SkyGuard AI Preprocessing Pipeline Runner.

Loads raw Automatic Weather Station observations from imd_maitri.csv,
preserves the raw source immutably, executes validation, sentinel conversion,
timestamp parsing, sorting, deduplication, missing value analysis, gap profiling,
continuous segment tagging, and outputs the cleaned working dataset along with
the comprehensive Data Quality Report.
"""

import argparse
import logging
from pathlib import Path
import sys
import time

# Ensure project root is on Python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import settings
from backend.app.core.ingestion import CSVReplaySource
from backend.app.core.preprocessing import preprocess_aws_dataframe
from backend.app.core.quality_report import DataQualityReport


def setup_pipeline_logging(verbose: bool = False) -> None:
    """Configures structured console logging."""
    log_level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Clear any existing handlers
    root_logger.handlers = [handler]


def run_pipeline(
    raw_csv_path: Path = settings.DEFAULT_RAW_CSV,
    output_dir: Path = settings.PROCESSED_DATA_DIR,
    interpolate_small: bool = False,
    save_csv_copy: bool = True,
) -> None:
    """Executes the end-to-end ingestion and preprocessing pipeline."""
    start_time = time.time()
    logger = logging.getLogger("skyguard.pipeline")
    logger.info("================================================================================")
    logger.info("Starting SkyGuard AI Preprocessing & Quality Control Ingestion Pipeline")
    logger.info("================================================================================")
    logger.info("Raw Data Source: %s", raw_csv_path)
    logger.info("Output Directory: %s", output_dir)
    logger.info("Strict Non-Interpolation Active (interpolate_small=%s)", interpolate_small)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Ingest via CSVReplaySource (with raw file immutability guarantee)
    source = CSVReplaySource(csv_path=raw_csv_path)
    meta = source.get_source_metadata()
    logger.info(
        "Source Verified: %s | Size: %s bytes | SHA-256: %s...",
        meta["file_name"],
        f"{meta['file_size_bytes']:,}",
        meta["file_sha256"][:16],
    )

    raw_df = source.load_all()
    logger.info("Successfully ingested %d raw observations.", len(raw_df))

    # 2. Run Preprocessing Pipeline
    cleaned_df, audit_summary = preprocess_aws_dataframe(
        raw_df=raw_df,
        interpolate_small=interpolate_small,
        max_gap_hours=settings.MAX_ALLOWABLE_INTERPOLATION_HOURS,
    )

    # 3. Save Cleaned Working Datasets
    parquet_path = output_dir / "cleaned_maitri.parquet"
    logger.info("Exporting cleaned working dataset to Parquet: %s", parquet_path)
    cleaned_df.to_parquet(parquet_path, index=False, engine="pyarrow", compression="snappy")

    if save_csv_copy:
        cleaned_csv_path = output_dir / "cleaned_maitri.csv"
        logger.info("Exporting cleaned working dataset copy to CSV: %s", cleaned_csv_path)
        cleaned_df.to_csv(cleaned_csv_path, index=False)

    # 4. Verify raw file immutability post-pipeline
    assert source.verify_file_unmodified(), "FATAL ERROR: Raw source file was altered during pipeline run!"
    logger.info("Integrity Check Passed: Raw file '%s' remains strictly unchanged.", meta["file_name"])

    # 5. Generate and Export Data Quality Reports
    report = DataQualityReport(audit_summary=audit_summary, station_metadata=meta)
    json_path, md_path = report.save(output_dir=output_dir)

    elapsed = time.time() - start_time
    logger.info("================================================================================")
    logger.info("SkyGuard AI Preprocessing Pipeline Completed Successfully in %.2f seconds", elapsed)
    logger.info("Cleaned Records: %d | Continuous Segments: %d", len(cleaned_df), audit_summary["continuous_segments_count"])
    logger.info("Quality Report (Markdown): %s", md_path)
    logger.info("Quality Report (JSON):     %s", json_path)
    logger.info("================================================================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SkyGuard AI Data Ingestion & Preprocessing Pipeline")
    parser.add_argument("--raw-csv", type=Path, default=settings.DEFAULT_RAW_CSV, help="Path to raw AWS CSV")
    parser.add_argument("--out-dir", type=Path, default=settings.PROCESSED_DATA_DIR, help="Destination directory")
    parser.add_argument("--interpolate-small", action="store_true", help="Interpolate small gaps (<= 2 hrs)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()
    setup_pipeline_logging(verbose=args.verbose)
    run_pipeline(
        raw_csv_path=args.raw_csv,
        output_dir=args.out_dir,
        interpolate_small=args.interpolate_small,
    )
