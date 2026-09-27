"""Historical CSV Replay Engine for SkyGuard AI.

Executes chronological replay of historical AWS observations (e.g. `imd_maitri.csv`):
- Reads observations chronologically row by row.
- Passes EVERY observation through the EXACT SAME full SkyGuard pipeline (QC -> IForest -> LSTM -> Thermodynamics -> Spatial -> Sensor History -> Evidence Fusion).
- Configurable replay speed multiplier (1x, 5x, 10x, 50x, or custom delay).
- Broadcasts real-time JSON observation payloads and fusion decisions over WebSockets.
- DOES NOT BYPASS the anomaly detection pipeline during replay!
"""

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from backend.app.config import settings
from backend.app.core.pipeline import SkyGuardPipeline, PipelineProcessingResult
from backend.app.services.websocket_manager import ws_manager
from backend.app.db.alert_db import alert_db

logger = logging.getLogger("skyguard.replay")


@dataclass
class ReplayStatus:
    is_running: bool
    current_index: int
    total_rows: int
    speed_multiplier: float
    current_timestamp: Optional[str]
    anomalies_detected: int
    processed_count: int


class CSVReplayRunner:
    """Asynchronous background worker executing historical CSV replay."""

    def __init__(self, pipeline: Optional[SkyGuardPipeline] = None) -> None:
        self.pipeline = pipeline or SkyGuardPipeline()
        self.is_running: bool = False
        self.should_stop: bool = False
        self._task: Optional[asyncio.Task] = None

        self.csv_path: Path = settings.DEFAULT_RAW_CSV
        self.df_replay: Optional[pd.DataFrame] = None
        self.current_index: int = 0
        self.total_rows: int = 0
        self.speed_multiplier: float = 10.0  # Default 10x speed
        self.anomalies_detected: int = 0
        self.processed_count: int = 0
        self.current_timestamp: Optional[str] = None
        
        # Buffer of recently replayed result payloads for API queries
        self.processed_history: List[Dict[str, Any]] = []

    def load_dataset(self, csv_path: Optional[Path] = None) -> None:
        """Loads and pre-sorts the CSV dataset chronologically."""
        target_csv = csv_path or settings.DEFAULT_RAW_CSV
        if not target_csv.exists():
            raise FileNotFoundError(f"Replay CSV file not found: {target_csv}")

        df = pd.read_csv(target_csv)
        # Standardize timestamp column name
        ts_col = settings.RAW_TIMESTAMP_COL if settings.RAW_TIMESTAMP_COL in df.columns else "timestamp"
        df["parsed_ts"] = pd.to_datetime(df[ts_col], utc=True)
        df = df.sort_values("parsed_ts").reset_index(drop=True)
        
        self.df_replay = df
        self.total_rows = len(df)
        self.current_index = 0
        self.anomalies_detected = 0
        self.processed_count = 0
        self.csv_path = target_csv
        logger.info("Loaded CSV dataset for replay: %d rows from %s", self.total_rows, target_csv.name)

    def preseed_buffer(self, count: int = 100) -> None:
        """Pre-seeds the processed_history buffer with initial rows from the dataset through the pipeline."""
        if self.processed_history:
            return

        if self.df_replay is None:
            self.load_dataset()

        if self.df_replay is None or self.df_replay.empty:
            return

        num_rows = min(count, len(self.df_replay))
        logger.info("Pre-seeding replay buffer with first %d dataset observations...", num_rows)
        for i in range(num_rows):
            row = self.df_replay.iloc[i]
            ts_val = str(row["parsed_ts"])
            t_val = row.get(settings.RAW_TEMPERATURE_COL, row.get("temperature", None))
            p_val = row.get(settings.RAW_PRESSURE_COL, row.get("pressure", None))
            h_val = row.get(settings.RAW_HUMIDITY_COL, row.get("relative_humidity", None))

            res: PipelineProcessingResult = self.pipeline.process_observation(
                timestamp=ts_val,
                temperature=t_val,
                pressure=p_val,
                humidity=h_val,
                dataset_df=self.df_replay,
            )
            res_dict = res.to_dict()
            alert_db.insert_observation(res_dict)
            self.processed_history.append(res_dict)
            if res.decision.classification.value != "NORMAL":
                self.anomalies_detected += 1
            self.processed_count += 1
            self.current_timestamp = ts_val

        self.current_index = num_rows
        logger.info("Pre-seeded replay buffer with %d observations (%d anomalies found).", len(self.processed_history), self.anomalies_detected)


    async def start_replay(
        self,
        speed_multiplier: float = 10.0,
        start_index: int = 0,
        csv_path: Optional[Path] = None,
    ) -> ReplayStatus:
        """Starts background replay task."""
        if self.is_running:
            return self.get_status()

        if self.df_replay is None or csv_path is not None:
            self.load_dataset(csv_path)

        self.speed_multiplier = max(0.1, min(speed_multiplier, 1000.0))
        self.current_index = max(0, min(start_index, self.total_rows - 1))
        self.should_stop = False
        self.is_running = True

        # Launch background async loop
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Started CSV replay task at index %d (Speed: %.1fx)", self.current_index, self.speed_multiplier)
        return self.get_status()

    def stop_replay(self) -> ReplayStatus:
        """Stops the active background replay task."""
        if self.is_running:
            self.should_stop = True
            self.is_running = False
            if self._task and not self._task.done():
                self._task.cancel()
            logger.info("Stopped CSV replay task at index %d", self.current_index)
        return self.get_status()

    def clear_history(self) -> None:
        """Clears the processed_history buffer and resets anomaly counters."""
        self.processed_history.clear()
        self.anomalies_detected = 0
        self.processed_count = 0
        logger.info("Cleared in-memory processed history buffer.")

    def get_status(self) -> ReplayStatus:
        """Returns current operational status of the replay worker."""
        return ReplayStatus(
            is_running=self.is_running,
            current_index=self.current_index,
            total_rows=self.total_rows,
            speed_multiplier=self.speed_multiplier,
            current_timestamp=self.current_timestamp,
            anomalies_detected=self.anomalies_detected,
            processed_count=self.processed_count,
        )

    async def _run_loop(self) -> None:
        """Main asynchronous loop streaming rows chronologically through SkyGuardPipeline."""
        if self.df_replay is None:
            return

        base_delay = 1.0 / self.speed_multiplier  # Replay delay per observation

        try:
            while self.current_index < self.total_rows and not self.should_stop:
                row = self.df_replay.iloc[self.current_index]

                ts_val = str(row["parsed_ts"])
                t_val = row.get(settings.RAW_TEMPERATURE_COL, row.get("temperature", None))
                p_val = row.get(settings.RAW_PRESSURE_COL, row.get("pressure", None))
                h_val = row.get(settings.RAW_HUMIDITY_COL, row.get("relative_humidity", None))

                # Process row through EXACT SAME SkyGuard pipeline!
                res: PipelineProcessingResult = self.pipeline.process_observation(
                    timestamp=ts_val,
                    temperature=t_val,
                    pressure=p_val,
                    humidity=h_val,
                    dataset_df=self.df_replay,
                )

                self.processed_count += 1
                self.current_timestamp = ts_val

                # Check if decision is an anomaly
                if res.decision.classification.value != "NORMAL":
                    self.anomalies_detected += 1

                res_dict = res.to_dict()
                alert_db.insert_observation(res_dict)
                self.processed_history.append(res_dict)

                # Broadcast live event to WebSocket clients
                payload = {
                    "event_type": "OBSERVATION_PROCESSED",
                    "source": "HISTORICAL_CSV_REPLAY",
                    "replay_index": self.current_index,
                    "total_rows": self.total_rows,
                    "data": res_dict,
                }
                await ws_manager.broadcast(payload)

                self.current_index += 1

                # Asynchronous sleep according to replay speed
                await asyncio.sleep(base_delay)

        except asyncio.CancelledError:
            logger.info("CSV replay task cancelled.")
        except Exception as e:
            logger.error("Error during CSV replay execution: %s", e, exc_info=True)
        finally:
            self.is_running = False


# Global replay runner singleton
replay_runner = CSVReplayRunner()
