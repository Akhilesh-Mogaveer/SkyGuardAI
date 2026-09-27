"""Unit tests for the DataQualityReport generator."""

import json
from pathlib import Path
import pytest
import pandas as pd

from backend.app.core.preprocessing import preprocess_aws_dataframe
from backend.app.core.quality_report import DataQualityReport


@pytest.fixture
def sample_audit_summary() -> dict:
    """Generates an audit summary dictionary from a sample frame."""
    sample_df = pd.DataFrame({
        "TimeStamp": ["1/1/2015 0:00", "1/1/2015 1:00", "1/1/2015 4:00"],
        "Air Temperature": [-10.0, -11.0, -999],
        "Air Pressure": [980.0, 981.0, 982.0],
        "Wind Speed": [10, 12, 14],
        "Wind Direction": [180, 185, 190],
        "Relative Humidity": [60, -999, 65],
    })
    _, audit = preprocess_aws_dataframe(sample_df)
    return audit


def test_quality_report_dict_structure(sample_audit_summary: dict):
    """Verifies that all required metrics are present in the report dictionary."""
    report = DataQualityReport(audit_summary=sample_audit_summary)
    d = report.to_dict()

    # Verify overview requirements
    assert "overview" in d
    assert "raw_rows" in d["overview"]
    assert "date_range" in d["overview"]
    assert "duplicate_timestamps" in d["overview"]

    # Verify missing values
    assert "missing_values" in d
    assert "temperature" in d["missing_values"]

    # Verify time gaps
    assert "time_gaps" in d
    assert "total_gaps" in d["time_gaps"]
    assert "statistics" in d["time_gaps"]
    assert "top_longest_gaps" in d["time_gaps"]

    # Verify parameter statistics
    assert "parameter_statistics" in d
    assert "temperature" in d["parameter_statistics"]


def test_quality_report_markdown_generation(sample_audit_summary: dict):
    """Verifies that Markdown output contains headings for all required sections."""
    report = DataQualityReport(audit_summary=sample_audit_summary)
    md = report.to_markdown()

    assert "SkyGuard AI — Data Quality & Integrity Report" in md
    assert "Dataset Overview & Chronology" in md
    assert "Missing Value Analysis" in md
    assert "Time Gap Detection & Duration Profiling" in md
    assert "Parameter Statistical Distributions" in md


def test_quality_report_save(sample_audit_summary: dict, tmp_path: Path):
    """Verifies saving JSON and Markdown reports to a temporary directory."""
    report = DataQualityReport(audit_summary=sample_audit_summary)
    json_file, md_file = report.save(output_dir=tmp_path)

    assert json_file.exists()
    assert md_file.exists()

    with open(json_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
        assert loaded["overview"]["raw_rows"] == 3
