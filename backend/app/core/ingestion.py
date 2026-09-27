"""Data ingestion engine for SkyGuard AI.

Provides an extensible abstraction for automatic weather station data sources,
including historical CSV replay and future REST/MQTT/WMO streaming feeds.
Guarantees immutability and preservation of raw input datasets.
"""

from abc import ABC, abstractmethod
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, Generator, Iterator, Optional, Union

import pandas as pd

from backend.app.config import settings

logger = logging.getLogger("skyguard.ingestion")


def compute_file_sha256(file_path: Union[str, Path]) -> str:
    """Computes the SHA-256 cryptographic hash of a file to verify immutability."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class BaseWeatherSource(ABC):
    """Abstract interface for all AWS data sources."""

    @abstractmethod
    def load_all(self) -> pd.DataFrame:
        """Load entire available observation record as a DataFrame."""
        pass

    @abstractmethod
    def stream_records(self) -> Iterator[Dict[str, Any]]:
        """Yield single observation records sequentially."""
        pass

    @abstractmethod
    def get_source_metadata(self) -> Dict[str, Any]:
        """Return metadata regarding the station source and file identity."""
        pass


class CSVReplaySource(BaseWeatherSource):
    """Loads and streams historical AWS observation records from a CSV file.
    
    Guarantees raw data preservation: the underlying file is opened strictly in read-only
    mode, its SHA-256 hash is verified before and after operations, and no mutations
    are written back to the raw source.
    """

    def __init__(
        self,
        csv_path: Optional[Union[str, Path]] = None,
        station_id: str = settings.DEFAULT_STATION_ID,
        station_name: str = settings.DEFAULT_STATION_NAME,
    ) -> None:
        self.csv_path = Path(csv_path or settings.DEFAULT_RAW_CSV).resolve()
        self.station_id = station_id
        self.station_name = station_name

        if not self.csv_path.exists():
            raise FileNotFoundError(f"Raw AWS dataset not found at: {self.csv_path}")

        if not self.csv_path.is_file():
            raise ValueError(f"Path is not a regular file: {self.csv_path}")

        # Compute and record baseline file hash for immutability verification
        self._initial_sha256 = compute_file_sha256(self.csv_path)
        self._initial_size = self.csv_path.stat().st_size
        logger.info(
            "Initialized CSVReplaySource for %s (%s). File: %s, Size: %d bytes, SHA256: %s...",
            self.station_name,
            self.station_id,
            self.csv_path.name,
            self._initial_size,
            self._initial_sha256[:12],
        )

    def verify_file_unmodified(self) -> bool:
        """Asserts that the raw input file has remained unchanged on disk."""
        current_sha256 = compute_file_sha256(self.csv_path)
        current_size = self.csv_path.stat().st_size
        is_identical = (current_sha256 == self._initial_sha256) and (current_size == self._initial_size)
        if not is_identical:
            logger.error(
                "CRITICAL: Raw dataset file %s has been modified! Initial SHA: %s, Current SHA: %s",
                self.csv_path,
                self._initial_sha256,
                current_sha256,
            )
        return is_identical

    def load_all(self, nrows: Optional[int] = None) -> pd.DataFrame:
        """Loads the raw observations from CSV into a fresh DataFrame.
        
        Args:
            nrows: Optional row limit for rapid testing.
            
        Returns:
            pd.DataFrame: Deep copy of raw CSV data.
        """
        logger.debug("Reading CSV observations from %s (nrows=%s)...", self.csv_path, nrows)
        # Read strictly without mutating the source
        df = pd.read_csv(self.csv_path, nrows=nrows)
        logger.info("Loaded %d raw observation rows from %s", len(df), self.csv_path.name)
        
        # Verify raw file immutability post-read
        assert self.verify_file_unmodified(), "Raw CSV dataset integrity violated during read!"
        return df.copy()

    def stream_records(self, batch_size: int = 1) -> Generator[Dict[str, Any], None, None]:
        """Streams observation rows sequentially as dictionaries for real-time simulation.
        
        Args:
            batch_size: Number of records to yield per step.
        """
        logger.debug("Streaming records from %s (batch_size=%d)...", self.csv_path, batch_size)
        for chunk in pd.read_csv(self.csv_path, chunksize=batch_size):
            for record in chunk.to_dict(orient="records"):
                yield record

    def get_source_metadata(self) -> Dict[str, Any]:
        """Provides metadata for logging and traceability."""
        stat = self.csv_path.stat()
        return {
            "station_id": self.station_id,
            "station_name": self.station_name,
            "file_path": str(self.csv_path),
            "file_name": self.csv_path.name,
            "file_size_bytes": stat.st_size,
            "file_sha256": self._initial_sha256,
            "last_modified": stat.st_mtime,
        }
