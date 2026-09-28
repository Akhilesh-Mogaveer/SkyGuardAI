"""SkyGuard AI Integrated Processing Pipeline.

Orchestrates an incoming AWS observation through all pipeline stages:
1. Preprocessing & Sanitization
2. WMO Rule-Based Quality Control (baseline_qc)
3. Atmospheric Thermodynamics & Magnus Dew Point (physics)
4. Isolation Forest Anomaly Scoring (ml_isolation_forest)
5. TensorFlow/Keras LSTM Autoencoder Reconstruction Error (ml_lstm_autoencoder)
6. Spatial Cross-Validation / Buddy Check (spatial)
7. Sensor Historical Health Tracking (sensor_history)
8. Multi-Source Evidence Fusion & Decision Engine (evidence_fusion)

Ensures consistent processing across live real-time ingestion, single observation API calls,
and historical CSV replay.
"""

from collections import deque
from dataclasses import dataclass, field
import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import numpy as np
import pandas as pd

from backend.app.config import settings
from backend.app.core.baseline_qc import BaselineQCChecker, QCResult
from backend.app.core.physics import calculate_dew_point, saturation_vapor_pressure
from backend.app.core.ml_isolation_forest import IsolationForestDetector
from backend.app.core.ml_lstm_autoencoder import LSTMAutoencoderDetector
from backend.app.core.spatial import SpatialValidator, SpatialCheckResult
from backend.app.core.sensor_history import SensorHealthTracker, StationHealthSummary
from backend.app.core.evidence_fusion import EvidenceFusionEngine, FusedDecision

from backend.app.core.recovery import DataRecoveryEstimator, RecoveryEstimationResult

logger = logging.getLogger("skyguard.pipeline")


@dataclass
class PipelineProcessingResult:
    """Comprehensive result container returned for a processed AWS observation."""

    timestamp: str
    station_id: str
    temperature: Optional[float]
    pressure: Optional[float]
    humidity: Optional[float]
    dew_point: Optional[float]
    qc_result: QCResult
    iforest_score: Optional[float]
    iforest_flag: Optional[bool]
    lstm_mse: Optional[float]
    lstm_flag: Optional[bool]
    spatial_result: SpatialCheckResult
    sensor_health: StationHealthSummary
    decision: FusedDecision
    recovery_result: Optional[RecoveryEstimationResult] = None
    recovery_results: Dict[str, RecoveryEstimationResult] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        rec_dict = self.recovery_result.to_dict() if self.recovery_result else {
            "parameter": self.decision.primary_parameter,
            "recovery_parameter": self.decision.primary_parameter,
            "observed_value": None,
            "observedValue": None,
            "estimated_value": None,
            "estimatedValue": None,
            "unit": "°C",
            "method": None,
            "recovery_method": None,
            "previous_observation_timestamp": None,
            "previous_timestamp": None,
            "next_observation_timestamp": None,
            "next_timestamp": None,
            "available": False,
            "recovery_status": "NOT_APPLICABLE",
            "message": "Recovery not applicable — valid temporal neighbors are unavailable.",
        }

        # Calculate evidence counts across 5 detector pillars
        qc_flag = (self.qc_result.qc_flag != "PASSED")
        if_flag = bool(self.iforest_flag) if self.iforest_flag is not None else False
        lstm_flag = bool(self.lstm_flag) if self.lstm_flag is not None else False
        phys_flag = (self.decision.physical_result.status == "FLAGGED") if self.decision.physical_result else False
        phys_multi_flag = phys_flag or bool(self.decision.multivariate_anomaly)
        spat_flag = (self.spatial_result.spatial_status == "FLAGGED") if self.spatial_result else False

        evidence_count = sum([qc_flag, if_flag, lstm_flag, phys_multi_flag, spat_flag])
        evidence_total = 5

        assessment = {
            "classification": self.decision.classification.value,
            "severity": self.decision.severity.value,
            "evidence_count": evidence_count,
            "evidence_total": evidence_total,
            "evidence_confidence": self.decision.calibrated_confidence,
            "primary_root_cause": self.decision.probable_cause,
            "maintenance_status": self.decision.maintenance_status,
            "maintenance_action": self.decision.maintenance_action,
        }

        detectors = {
            "qc": self.qc_result.to_dict(),
            "isolation_forest": {
                "score": round(self.iforest_score, 4) if self.iforest_score is not None else None,
                "is_anomaly": self.iforest_flag,
                "status": "FLAGGED" if self.iforest_flag else ("CLEAR" if self.iforest_flag is False else "UNAVAILABLE"),
            },
            "lstm": {
                "reconstruction_error": round(self.lstm_mse, 6) if self.lstm_mse is not None else None,
                "is_anomaly": self.lstm_flag,
                "status": "FLAGGED" if self.lstm_flag else ("CLEAR" if self.lstm_flag is False else "UNAVAILABLE"),
                "available": self.lstm_mse is not None,
            },
            "physical_consistency": (
                self.decision.physical_result.to_dict()
                if self.decision.physical_result
                else {
                    "status": "CLEAR",
                    "score": 0.0,
                    "explanation": "Physically consistent"
                }
            ),

            "multivariate_consistency": {
                "status": "FLAGGED" if self.decision.multivariate_anomaly else "CLEAR",
                "score": (
                    round(self.decision.multivariate_score, 4)
                    if self.decision.multivariate_score is not None
                    else None
                ),
                "is_anomaly": self.decision.multivariate_anomaly
            },

            "spatial_validation": self.spatial_result.to_dict(),
        }

        recovery_by_parameter = {
            parameter: result.to_dict()
            for parameter, result in self.recovery_results.items()
        }
        recovery = {
            "available": rec_dict.get("available") or rec_dict.get("recovery_status") == "AVAILABLE",
            "parameter": rec_dict.get("parameter") or rec_dict.get("recovery_parameter") or self.decision.primary_parameter,
            "recovery_parameter": rec_dict.get("recovery_parameter") or rec_dict.get("parameter") or self.decision.primary_parameter,
            "observed_value": rec_dict.get("observed_value"),
            "observedValue": rec_dict.get("observedValue", rec_dict.get("observed_value")),
            "estimated_value": rec_dict.get("estimated_value"),
            "estimatedValue": rec_dict.get("estimatedValue", rec_dict.get("estimated_value")),
            "unit": rec_dict.get("unit"),
            "method": rec_dict.get("method") or rec_dict.get("recovery_method"),
            "previous_timestamp": rec_dict.get("previous_timestamp") or rec_dict.get("previous_observation_timestamp"),
            "next_timestamp": rec_dict.get("next_timestamp") or rec_dict.get("next_observation_timestamp"),
            "message": rec_dict.get("message", ""),
        }

        observation = {
            "timestamp": self.timestamp,
            "temperature": self.temperature,
            "pressure": self.pressure,
            "humidity": self.humidity,
            "dew_point": round(self.dew_point, 2) if self.dew_point is not None else None,
        }

        res = {
            "timestamp": self.timestamp,
            "station_id": self.station_id,
            "temperature": self.temperature,
            "pressure": self.pressure,
            "humidity": self.humidity,
            "dew_point": round(self.dew_point, 2) if self.dew_point is not None else None,
            "qc_result": self.qc_result.to_dict(),
            "iforest_score": round(self.iforest_score, 4) if self.iforest_score is not None else None,
            "iforest_flag": self.iforest_flag,
            "lstm_mse": round(self.lstm_mse, 4) if self.lstm_mse is not None else None,
            "lstm_flag": self.lstm_flag,
            "spatial_result": self.spatial_result.to_dict(),
            "sensor_health": self.sensor_health.to_dict(),
            "decision": self.decision.to_dict(),
            "observed_value": self.temperature,
            "recovery_parameter": rec_dict.get("recovery_parameter") or rec_dict.get("parameter") or self.decision.primary_parameter,
            "parameter": rec_dict.get("parameter") or rec_dict.get("recovery_parameter") or self.decision.primary_parameter,
            "estimated_value": rec_dict.get("estimated_value") if len(recovery_by_parameter) <= 1 else None,
            "unit": rec_dict.get("unit"),
            "recovery_status": rec_dict.get("recovery_status", "NOT_APPLICABLE"),
            "recovery_method": rec_dict.get("method") or rec_dict.get("recovery_method"),
            "previous_observation_timestamp": rec_dict.get("previous_timestamp") or rec_dict.get("previous_observation_timestamp"),
            "next_observation_timestamp": rec_dict.get("next_timestamp") or rec_dict.get("next_observation_timestamp"),
            "observation": observation,
            "assessment": assessment,
            "detectors": detectors,
            "recovery": recovery,
            "recovery_results": recovery_by_parameter,
            "source": "MANUAL_INFERENCE",
        }
        # Keep nested audit structures while exposing the stable API contract.
        res.update({
            "qc_flag": self.qc_result.qc_flag,
            "range_flags": {
                "temperature": any("temperature_plausibility" in reason for reason in self.qc_result.qc_reasons),
                "pressure": any("pressure_plausibility" in reason for reason in self.qc_result.qc_reasons),
                "humidity": any("humidity_plausibility" in reason for reason in self.qc_result.qc_reasons),
            },
            "rate_flags": {
                "temperature": self.qc_result.temperature_spike,
                "pressure": self.qc_result.pressure_spike,
                "humidity": self.qc_result.humidity_spike,
            },
            "spike_flags": {
                "temperature": self.qc_result.temperature_spike,
                "pressure": self.qc_result.pressure_spike,
                "humidity": self.qc_result.humidity_spike,
            },
            "flatline_flags": {
                "temperature": self.qc_result.temperature_flatline,
                "pressure": self.qc_result.pressure_flatline,
                "humidity": self.qc_result.humidity_flatline,
            },
            "gap_flag": self.qc_result.gap_flag,
            "if_anomaly": self.iforest_flag,
            "if_score": self.iforest_score,
            "lstm_anomaly": self.lstm_flag,
            "lstm_error": self.lstm_mse,
            "multivariate_anomaly": self.decision.multivariate_anomaly,
            "multivariate_score": self.decision.multivariate_score,
            "evidence_count": evidence_count,
            "evidence_total": evidence_total,
            "evidence_confidence": self.decision.calibrated_confidence,
            "final_classification": self.decision.classification.value,
            "affected_parameters": self.decision.affected_parameters,
            "root_cause": self.decision.probable_cause,
            "primary_root_cause": self.decision.probable_cause,
            "contributing_causes": self.decision.contributing_evidence,
            "explanation": self.decision.recommended_operator_action,
            "severity": self.decision.severity.value,
            "maintenance_status": self.decision.maintenance_status,
            "operational_decision": self.decision.maintenance_status,
            "recovery_available": recovery["available"],
            "recovery_parameters": [recovery["parameter"]] if recovery["parameter"] else [],
            "estimated_temperature": None,
            "estimated_pressure": None,
            "estimated_humidity": None,
            "recovery_reason": recovery["message"],
        })
        if recovery_by_parameter:
            res["recovery_parameters"] = list(recovery_by_parameter)
            res["recovery_available"] = any(
                item.get("available") for item in recovery_by_parameter.values()
            )
        if recovery["parameter"] == "temperature":
            res["estimated_temperature"] = recovery["estimated_value"]
        elif recovery["parameter"] == "pressure":
            res["estimated_pressure"] = recovery["estimated_value"]
        elif recovery["parameter"] == "humidity":
            res["estimated_humidity"] = recovery["estimated_value"]
        return res


class SkyGuardPipeline:
    """Master pipeline manager holding loaded models and stateful detectors."""

    def __init__(self, station_id: str = settings.DEFAULT_STATION_ID) -> None:
        self.station_id = station_id
        
        # 1. QC Checker
        self.qc_checker = BaselineQCChecker(station_id=station_id)

        # 2. Isolation Forest Detector
        self.iforest_detector = IsolationForestDetector()
        self.iforest_loaded = False
        try:
            self.iforest_detector.load_model()
            self.iforest_loaded = True
            logger.info("Loaded Isolation Forest model successfully.")
        except Exception as e:
            logger.warning("Isolation Forest model could not be loaded automatically: %s", e)

        # 3. LSTM Autoencoder Detector
        self.lstm_detector = LSTMAutoencoderDetector()
        self.lstm_loaded = False
        try:
            self.lstm_detector.load_model()
            self.lstm_loaded = True
            logger.info("Loaded LSTM Autoencoder model successfully.")
        except Exception as e:
            logger.warning("LSTM Autoencoder model could not be loaded automatically: %s", e)

        # 4. Spatial Validator
        self.spatial_validator = SpatialValidator()

        # 5. Sensor Health Tracker
        self.sensor_health_tracker = SensorHealthTracker(station_id=station_id)

        # 6. Evidence Fusion Engine
        self.fusion_engine = EvidenceFusionEngine()

        # 7. Data Recovery Estimator
        self.recovery_estimator = DataRecoveryEstimator()

        # Rolling 24-hour sequence buffer for sequence-based models
        self._recent_observations: deque = deque(maxlen=48)
        self._last_processed_timestamp: Optional[pd.Timestamp] = None

    def process_observation(
        self,
        timestamp: Union[str, pd.Timestamp],
        temperature: Optional[float],
        pressure: Optional[float],
        humidity: Optional[float],
        station_id: Optional[str] = None,
        buddy_data: Optional[Dict[str, Any]] = None,
        dataset_df: Optional[pd.DataFrame] = None,
    ) -> PipelineProcessingResult:
        """Processes a single incoming AWS observation through the entire SkyGuard pipeline."""
        st_id = station_id or self.station_id
        ts_pd = pd.to_datetime(timestamp, utc=True)
        ts_str = ts_pd.strftime("%Y-%m-%d %H:%M:%S%z")

        # Convert sentinel values (-999) to NaN if passed raw
        t_clean = None if (temperature is None or temperature in settings.SENTINEL_VALUES or np.isnan(temperature)) else float(temperature)
        p_clean = None if (pressure is None or pressure in settings.SENTINEL_VALUES or np.isnan(pressure)) else float(pressure)
        h_clean = None if (humidity is None or humidity in settings.SENTINEL_VALUES or np.isnan(humidity)) else float(humidity)

        # Maintain rolling buffer for time-delta step checks and sequence modeling
        prev_obs = self._recent_observations[-1] if len(self._recent_observations) > 0 else None
        
        # Prepare previous observation dictionary if present
        prev_dict = None
        if prev_obs:
            prev_dict = {
                "timestamp": prev_obs["timestamp"],
                "temperature": prev_obs["temperature"],
                "pressure": prev_obs["pressure"],
                "humidity": prev_obs.get("relative_humidity", prev_obs.get("humidity")),
            }

        # 1. WMO Rule-Based QC Check
        qc_res = self.qc_checker.process_observation(
            timestamp=ts_str,
            temperature=t_clean,
            pressure=p_clean,
            humidity=h_clean,
            prev_observation=prev_dict,
        )

        # 2. Physics & Thermodynamics
        dew_pt = calculate_dew_point(t_clean, h_clean) if (t_clean is not None and h_clean is not None) else None

        # Append current observation to rolling buffer
        curr_rec = {
            "timestamp": ts_pd,
            "temperature": t_clean,
            "pressure": p_clean,
            "relative_humidity": h_clean,
            "segment_id": 0,
        }
        self._recent_observations.append(curr_rec)

        # 3. Isolation Forest Inference
        iforest_score = None
        iforest_flag = None
        if self.iforest_loaded and t_clean is not None and p_clean is not None and h_clean is not None:
            try:
                df_window = pd.DataFrame(list(self._recent_observations))
                res_df = self.iforest_detector.transform_dataframe(df_window)
                last_row = res_df.iloc[-1]
                if pd.notna(last_row.get("iforest_anomaly_score")):
                    iforest_score = float(last_row["iforest_anomaly_score"])
                    iforest_flag = bool(last_row["iforest_anomaly_flag"])
            except Exception as e:
                logger.debug("IForest inference exception: %s", e)

        # 4. TensorFlow/Keras LSTM Autoencoder Inference
        lstm_mse = None
        lstm_flag = None
        if self.lstm_loaded:
            try:
                df_seq = None

                # Option A: Check if rolling buffer has 24 observations
                if len(self._recent_observations) >= 24:
                    df_seq = pd.DataFrame(list(self._recent_observations)).iloc[-24:]
                # Option B: Retrieve historical 23 observations from dataset_df
                else:
                    target_df = dataset_df
                    if target_df is None or target_df.empty:
                        try:
                            from backend.app.services.replay_service import replay_runner
                            if replay_runner.df_replay is None:
                                replay_runner.load_dataset()
                            target_df = replay_runner.df_replay
                        except Exception:
                            pass

                    if target_df is not None and not target_df.empty:
                        if "parsed_ts" not in target_df.columns:
                            ts_col = settings.RAW_TIMESTAMP_COL if settings.RAW_TIMESTAMP_COL in target_df.columns else ("timestamp" if "timestamp" in target_df.columns else "TimeStamp")
                            if ts_col in target_df.columns:
                                target_df = target_df.copy()
                                target_df["parsed_ts"] = pd.to_datetime(target_df[ts_col], utc=True)

                        if "parsed_ts" in target_df.columns:
                            hist_rows = target_df[target_df["parsed_ts"] < ts_pd].tail(23)
                        if len(hist_rows) == 23:
                            seq_list = []
                            for _, r in hist_rows.iterrows():
                                seq_list.append({
                                    "TIMESTAMP": r["parsed_ts"],
                                    "TEMPERATURE": r.get(settings.RAW_TEMPERATURE_COL, r.get("temperature", None)),
                                    "PRESSURE": r.get(settings.RAW_PRESSURE_COL, r.get("pressure", None)),
                                    "HUMIDITY": r.get(settings.RAW_HUMIDITY_COL, r.get("relative_humidity", None)),
                                })
                            seq_list.append({
                                "TIMESTAMP": ts_pd,
                                "TEMPERATURE": t_clean,
                                "PRESSURE": p_clean,
                                "HUMIDITY": h_clean,
                            })
                            df_seq = pd.DataFrame(seq_list)

                if df_seq is not None and len(df_seq) == 24:
                    res_df = self.lstm_detector.transform_dataframe(df_seq)
                    last_row = res_df.iloc[-1]
                    if pd.notna(last_row.get("lstm_reconstruction_error")):
                        lstm_mse = float(last_row["lstm_reconstruction_error"])
                        lstm_flag = bool(last_row["lstm_anomaly_flag"])

                # Log debug information per user request #12
                valid_seq = (df_seq is not None and len(df_seq) == 24 and lstm_mse is not None)
                cal_ev = self.fusion_engine.calibrate_lstm_evidence(lstm_mse) if lstm_mse is not None else None
                pred_str = "ANOMALY" if lstm_flag else ("NORMAL" if valid_seq else "UNAVAILABLE")

                logger.info("[LSTM] timestamp: %s", ts_str)
                logger.info("[LSTM] sequence shape: %s", "(1, 24, 3)" if valid_seq else "Insufficient")
                logger.info("[LSTM] valid sequence: %s", valid_seq)
                logger.info("[LSTM] reconstruction MSE: %s", round(lstm_mse, 6) if lstm_mse is not None else "None")
                logger.info("[LSTM] threshold: %.10f", self.lstm_detector.anomaly_threshold)
                logger.info("[LSTM] prediction: %s", pred_str)
                logger.info("[LSTM] evidence: %s", round(cal_ev, 4) if cal_ev is not None else "None")

            except Exception as e:
                logger.error("[LSTM] Error during inference execution: %s", e, exc_info=True)

        # 5. Spatial Validation
        spatial_res = self.spatial_validator.validate_observation(
            timestamp=ts_str,
            target_temp=t_clean,
            target_pressure=p_clean,
            target_humidity=h_clean,
            buddy_data=buddy_data,
        )

        # 6. Sensor Historical Health Tracking
        sensor_health_sum = self.sensor_health_tracker.update_observation(
            temperature=t_clean,
            pressure=p_clean,
            humidity=h_clean,
            qc_reasons=qc_res.qc_reasons,
            is_missing=qc_res.missing_flag,
        )

        # 7. Multivariate T/P/RH consistency from the finalized pipeline.
        if qc_res.qc_flag == "PASSED":
            multivariate_score, multivariate_anomaly = None, False
        else:
            multivariate_score, multivariate_anomaly = self._multivariate_consistency(
                timestamp=ts_pd,
                temperature=t_clean,
                pressure=p_clean,
                humidity=h_clean,
                dataset_df=dataset_df,
            )

        # 8. Evidence Fusion & Decision Engine
        fused_decision = self.fusion_engine.fuse(
            timestamp=ts_str,
            station_id=st_id,
            temperature=t_clean,
            pressure=p_clean,
            humidity=h_clean,
            qc_result=qc_res,
            iforest_score=iforest_score,
            iforest_flag=iforest_flag,
            lstm_mse=lstm_mse,
            lstm_flag=lstm_flag,
            multivariate_anomaly=multivariate_anomaly,
            multivariate_score=multivariate_score,
            spatial_result=spatial_res,
            sensor_health=sensor_health_sum,
            dew_point=dew_pt,
        )

        # 9. Data Recovery Estimation for every parameter attributed by the decision.
        primary_p = fused_decision.primary_parameter or "temperature"
        if primary_p not in ["temperature", "pressure", "humidity"]:
            primary_p = "temperature"

        is_param_flagged = (fused_decision.classification.value != "NORMAL")
        recovery_parameters = [
            parameter for parameter in fused_decision.affected_parameters
            if parameter in {"temperature", "pressure", "humidity"}
        ]
        if not recovery_parameters and fused_decision.primary_parameter in {"temperature", "pressure", "humidity"} and is_param_flagged:
            recovery_parameters = [primary_p]

        values = {"temperature": t_clean, "pressure": p_clean, "humidity": h_clean}
        recovery_results = {
            parameter: self.recovery_estimator.estimate_recovery(
                timestamp=ts_str,
                observed_value=values[parameter],
                parameter_name=parameter,
                is_flagged=is_param_flagged,
                dataset_df=dataset_df,
                recent_buffer=self._recent_observations,
            )
            for parameter in recovery_parameters
        }
        rec_res = recovery_results.get(primary_p)

        return PipelineProcessingResult(
            timestamp=ts_str,
            station_id=st_id,
            temperature=t_clean,
            pressure=p_clean,
            humidity=h_clean,
            dew_point=dew_pt,
            qc_result=qc_res,
            iforest_score=iforest_score,
            iforest_flag=iforest_flag,
            lstm_mse=lstm_mse,
            lstm_flag=lstm_flag,
            spatial_result=spatial_res,
            sensor_health=sensor_health_sum,
            decision=fused_decision,
            recovery_result=rec_res,
            recovery_results=recovery_results,
        )

    def _multivariate_consistency(
        self,
        timestamp: pd.Timestamp,
        temperature: Optional[float],
        pressure: Optional[float],
        humidity: Optional[float],
        dataset_df: Optional[pd.DataFrame],
    ) -> tuple[Optional[float], bool]:
        """Apply the frozen notebook's T/P/RH change-score consistency check."""
        columns = {
            "temperature": settings.RAW_TEMPERATURE_COL,
            "pressure": settings.RAW_PRESSURE_COL,
            "humidity": settings.RAW_HUMIDITY_COL,
        }
        if dataset_df is not None and not dataset_df.empty:
            context = dataset_df.copy()
            ts_col = "parsed_ts" if "parsed_ts" in context.columns else settings.RAW_TIMESTAMP_COL
            if ts_col not in context.columns and "timestamp" in context.columns:
                ts_col = "timestamp"
            if ts_col not in context.columns:
                return None, False
            context["parsed_ts"] = pd.to_datetime(context[ts_col], utc=True)
            context = context[context["parsed_ts"] < timestamp].sort_values("parsed_ts")
            records = []
            for _, row in context.iterrows():
                records.append({
                    key: row.get(raw, row.get(key))
                    for key, raw in columns.items()
                })
        else:
            records = [
                {
                    "temperature": row.get("temperature"),
                    "pressure": row.get("pressure"),
                    "humidity": row.get("relative_humidity", row.get("humidity")),
                }
                for row in self._recent_observations
            ][-24:]

        records.append({"temperature": temperature, "pressure": pressure, "humidity": humidity})
        frame = pd.DataFrame(records).apply(pd.to_numeric, errors="coerce")
        if len(frame) < 3 or frame.isna().any().any():
            return None, False

        changes = frame.diff().iloc[1:]
        means = changes.mean()
        stds = changes.std(ddof=1).replace(0, np.nan)
        z_scores = ((changes.iloc[-1] - means) / stds).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        score = float(np.sqrt(np.square(z_scores).sum()))
        return score, bool(score > 3.0)
