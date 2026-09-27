"""Unit tests for the data ingestion module."""

from pathlib import Path
import tempfile
import pytest
import pandas as pd

from backend.app.core.ingestion import CSVReplaySource, compute_file_sha256
from backend.app.config import settings


@pytest.fixture
def sample_csv_file(tmp_path: Path) -> Path:
    """Creates a temporary sample AWS CSV file for isolated testing."""
    csv_file = tmp_path / "sample_aws.csv"
    data = (
        "TimeStamp,Air Temperature,Air Pressure,Wind Speed,Wind Direction,Relative Humidity\n"
        "1/1/2015 0:00,-5.0,980.0,10,180,65\n"
        "1/1/2015 1:00,-5.2,980.2,12,185,64\n"
        "1/1/2015 2:00,-5.5,980.5,11,190,-999\n"
    )
    csv_file.write_text(data, encoding="utf-8")
    return csv_file


def test_compute_file_sha256(sample_csv_file: Path):
    """Verifies that file hashing produces a consistent 64-char hex string."""
    hash1 = compute_file_sha256(sample_csv_file)
    hash2 = compute_file_sha256(sample_csv_file)
    assert len(hash1) == 64
    assert hash1 == hash2


def test_csv_replay_source_load(sample_csv_file: Path):
    """Tests loading data via CSVReplaySource and verifies file immutability."""
    source = CSVReplaySource(csv_path=sample_csv_file)
    meta = source.get_source_metadata()
    assert meta["file_name"] == "sample_aws.csv"
    assert meta["file_size_bytes"] > 0
    assert len(meta["file_sha256"]) == 64

    df = source.load_all()
    assert len(df) == 3
    assert "Air Temperature" in df.columns
    assert source.verify_file_unmodified() is True


def test_csv_replay_source_streaming(sample_csv_file: Path):
    """Tests record-by-record streaming generator."""
    source = CSVReplaySource(csv_path=sample_csv_file)
    records = list(source.stream_records(batch_size=1))
    assert len(records) == 3
    assert records[0]["Air Temperature"] == -5.0
    assert records[2]["Relative Humidity"] == -999


def test_csv_replay_source_nonexistent_file():
    """Verifies that missing files raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        CSVReplaySource(csv_path="non_existent_weather_file.csv")


def test_real_imd_maitri_file_ingestion():
    """Verifies ingestion and immutability of the actual imd_maitri.csv dataset."""
    if not settings.DEFAULT_RAW_CSV.exists():
        pytest.skip("Real raw dataset not present at configured path.")

    source = CSVReplaySource(csv_path=settings.DEFAULT_RAW_CSV)
    meta = source.get_source_metadata()
    assert meta["file_name"] == "imd_maitri.csv"
    assert meta["file_size_bytes"] > 6_000_000

    # Load small subset to verify read without mutating
    sample_df = source.load_all(nrows=100)
    assert len(sample_df) == 100
    assert source.verify_file_unmodified() is True
