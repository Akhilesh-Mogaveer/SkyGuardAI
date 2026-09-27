"""Evidence Fusion & Explainable Decision Engine for SkyGuard AI.

Implements multi-source evidential reasoning to classify Automatic Weather Station
observations into one of four mutually exclusive, highly defensible categories:
1. NORMAL
2. LIKELY_GENUINE_WEATHER_EVENT
3. LIKELY_SENSOR_DATA_FAULT
4. UNCERTAIN

Core Principles:
- Never assume every unusual observation is a sensor fault.
- Never average raw anomaly scores without calibration.
- Calibrate model outputs into probabilistic evidence signals.
- Require multi-pillar concordance for fault or weather claims.
- Return UNCERTAIN whenever evidence is conflicting, marginal, or insufficient.
- Provide transparent attribution, severity, probable cause, and actionable recommendations.
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np

from backend.app.core.baseline_qc import QCResult
from backend.app.core.spatial import SpatialCheckResult
from backend.app.core.sensor_history import StationHealthSummary, ParameterHealthRecord

logger = logging.getLogger("skyguard.evidence_fusion")


class DecisionClassification(str, Enum):
    """The four mutually exclusive classification states of SkyGuard AI."""

    NORMAL = "NORMAL"
    LIKELY_GENUINE_WEATHER_EVENT = "LIKELY_GENUINE_WEATHER_EVENT"
    LIKELY_SENSOR_DATA_FAULT = "LIKELY_SENSOR_DATA_FAULT"
    UNCERTAIN = "UNCERTAIN"


class AnomalySeverity(str, Enum):
    """Operational severity level for detected anomalies."""

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class PhysicalCheckResult:
    """Detailed result container for physical & thermodynamic consistency check."""

    status: str  # "CLEAR", "FLAGGED", or "UNAVAILABLE"
    score: float  # [0.0, 1.0]
    explanation: str
    dew_point: Optional[float] = None
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "score": round(self.score, 4),
            "explanation": self.explanation,
            "dew_point": round(self.dew_point, 2) if self.dew_point is not None else None,
            "violations": self.violations,
        }


def get_maintenance_status(
    severity: Optional[Union[str, AnomalySeverity]],
    final_classification: Optional[Union[str, DecisionClassification]] = None,
    primary_root_cause: Optional[str] = None,
    evidence_count: int = 0,
    qc_flag: bool = False,
    if_anomaly: bool = False,
    lstm_anomaly: bool = False,
    multivariate_anomaly: bool = False,
) -> str:
    """Derive the sole operational maintenance status for an assessment.

    The additional evidence arguments are part of the decision contract so this
    function can remain the single policy boundary as evidence sources evolve.
    Severity is authoritative, with the sensor-fault classification safety rule
    preventing a critical/high fault from ever being reported as Normal.
    """
    severity_value = str(severity.value if isinstance(severity, Enum) else severity or "NONE").upper()
    classification_value = str(
        final_classification.value if isinstance(final_classification, Enum) else final_classification or ""
    ).upper().replace(" ", "_").replace("/", "_")

    status_by_severity = {
        "CRITICAL": "Inspection Recommended",
        "HIGH": "Inspection Recommended",
        "MEDIUM": "Monitor Closely",
        "LOW": "Monitor",
        "NORMAL": "Normal",
        "NONE": "Normal",
    }
    status = status_by_severity.get(severity_value, "Normal")
    if (
        classification_value == DecisionClassification.LIKELY_SENSOR_DATA_FAULT.value
        and severity_value in {"CRITICAL", "HIGH"}
    ):
        return "Inspection Recommended"
    return status


def get_maintenance_action(primary_root_cause: Optional[str], fallback: str = "") -> str:
    """Return the root-cause-specific action shown to station operators."""
    cause = str(primary_root_cause or "").strip().lower()
    if "pressure plausibility" in cause:
        return "Flag observation as invalid and inspect the pressure sensor/transducer, signal cable, and A/D converter."
    if "rapid temperature" in cause or "temperature plausibility" in cause:
        return "Flag observation as invalid and inspect the temperature sensor/transducer, signal cable, and A/D converter."
    if "humidity anomaly" in cause or "humidity plausibility" in cause:
        return "Flag observation as invalid and inspect the humidity sensor/transducer and signal connection."
    if "communication" in cause or "data gap" in cause or "transmission dropout" in cause:
        return "Check station communication, power supply, logger, and data transmission path."
    if "multiple sensor" in cause or "multivariate" in cause:
        return "Inspect the affected sensors, station power, logger, communication link, and signal connections."
    if "pressure" in cause:
        return "Flag observation as invalid and inspect the pressure sensor/transducer, signal cable, and A/D converter."
    if "temperature" in cause:
        return "Flag observation as invalid and inspect the temperature sensor/transducer, signal cable, and A/D converter."
    if "humidity" in cause:
        return "Flag observation as invalid and inspect the humidity sensor/transducer and signal connection."
    return fallback or "Review the observation and inspect the affected station components."


def maintenance_status_for_severity(severity: Optional[Union[str, AnomalySeverity]]) -> str:
    """Backward-compatible wrapper for callers that only have severity."""
    return get_maintenance_status(severity)


@dataclass
class FusedDecision:
    """Consolidated operational decision output with full explanation audit trail."""

    timestamp: str
    station_id: str
    classification: DecisionClassification
    severity: AnomalySeverity
    calibrated_confidence: Optional[float]  # [0.0, 1.0] only if well-calibrated; None if UNCERTAIN
    primary_parameter: Optional[str]  # "temperature", "pressure", "humidity", or "multivariate"
    affected_parameters: List[str] = field(default_factory=list)
    contributing_evidence: List[Dict[str, Any]] = field(default_factory=list)
    probable_cause: str = ""
    recommended_operator_action: str = ""
    maintenance_status: Optional[str] = None
    maintenance_action: Optional[str] = None
    evidence_scores: Dict[str, float] = field(default_factory=dict)
    physical_result: Optional[PhysicalCheckResult] = None
    multivariate_anomaly: bool = False
    multivariate_score: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.affected_parameters and self.primary_parameter in {"temperature", "pressure", "humidity"}:
            self.affected_parameters = [self.primary_parameter]
        self.maintenance_status = get_maintenance_status(
            self.severity,
            self.classification,
            self.probable_cause,
            evidence_count=len(self.contributing_evidence),
        )
        self.maintenance_action = get_maintenance_action(self.probable_cause, self.recommended_operator_action)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "station_id": self.station_id,
            "classification": self.classification.value,
            "severity": self.severity.value,
            "calibrated_confidence": (
                round(self.calibrated_confidence, 4)
                if self.calibrated_confidence is not None
                else None
            ),
            "primary_parameter": self.primary_parameter,
            "affected_parameters": self.affected_parameters,
            "contributing_evidence": self.contributing_evidence,
            "probable_cause": self.probable_cause,
            "recommended_operator_action": self.recommended_operator_action,
            "maintenance_status": get_maintenance_status(
                self.severity,
                self.classification,
                self.probable_cause,
                evidence_count=len(self.contributing_evidence),
            ),
            "maintenance_action": self.maintenance_action or get_maintenance_action(
                self.probable_cause,
                self.recommended_operator_action,
            ),
            "evidence_scores": {k: round(v, 4) for k, v in self.evidence_scores.items()},
            "physical_result": self.physical_result.to_dict() if self.physical_result else None,
            "multivariate_anomaly": self.multivariate_anomaly,
            "multivariate_score": round(self.multivariate_score, 4) if self.multivariate_score is not None else None,
        }


class EvidenceFusionEngine:
    """Multi-source evidential reasoning engine for AWS anomaly classification."""

    def __init__(
        self,
        iforest_anomaly_threshold: float = 0.65,
        lstm_error_threshold: float = 0.07097852191878912,
        min_fault_concordance: int = 2,
    ) -> None:
        self.iforest_anomaly_threshold = iforest_anomaly_threshold
        self.lstm_error_threshold = lstm_error_threshold
        self.min_fault_concordance = min_fault_concordance

    def calibrate_iforest_evidence(self, raw_score: float) -> float:
        """Calibrates Isolation Forest raw anomaly score [0, 1] into [0, 1] evidence.
        
        Applies a sigmoid transfer centered around the detection threshold.
        """
        if raw_score is None or np.isnan(raw_score):
            return 0.0
        # Centers response around the threshold so 0.65 maps to ~0.50
        k = 10.0
        z = raw_score - self.iforest_anomaly_threshold
        return float(1.0 / (1.0 + np.exp(-k * z)))

    def calibrate_lstm_evidence(self, reconstruction_mse: float) -> float:
        """Calibrates LSTM reconstruction MSE into a normalized [0, 1] evidence score.
        
        Relative to the empirically derived 98th percentile threshold.
        """
        if reconstruction_mse is None or np.isnan(reconstruction_mse):
            return 0.0
        ratio = reconstruction_mse / max(self.lstm_error_threshold, 1e-6)
        # Ratio: 1.0 -> 0.5; 2.0 -> 0.88; 3.0+ -> ~1.0
        return float(1.0 - np.exp(-0.7 * ratio))

    def evaluate_thermodynamic_consistency(
        self,
        temperature: Optional[float],
        pressure: Optional[float],
        humidity: Optional[float],
        dew_point: Optional[float],
    ) -> PhysicalCheckResult:
        """Evaluates thermodynamic laws between Temperature, Pressure, and RH.
        
        Returns a PhysicalCheckResult containing status (CLEAR, FLAGGED, UNAVAILABLE),
        score, explanation, dew point, and specific violations.
        """
        if temperature is None or humidity is None:
            return PhysicalCheckResult(
                status="UNAVAILABLE",
                score=0.0,
                explanation="Insufficient parameter data to evaluate physical/multivariate consistency.",
                dew_point=dew_point,
                violations=[],
            )

        violations = []
        score = 0.0

        # Law 1: Supersaturation violation (RH > 105% is physically implausible outdoors)
        if humidity > 105.0:
            score = max(score, 1.0)
            violations.append(f"Physical impossibility: Relative humidity ({humidity:.1f}%) exceeds saturation limit (105%)")
        elif humidity < 0.0:
            score = max(score, 1.0)
            violations.append(f"Physical impossibility: Negative relative humidity ({humidity:.1f}%)")

        # Law 2: Dew point cannot exceed dry-bulb temperature (Magnus consistency)
        if dew_point is not None:
            spread = temperature - dew_point
            if spread < -0.5:
                score = max(score, 0.9)
                violations.append(f"Thermodynamic violation: Dew point ({dew_point:.1f}°C) exceeds ambient temperature ({temperature:.1f}°C)")

        # Law 3: Surface temperature range limits (-100°C to +60°C)
        if temperature > 60.0 or temperature < -100.0:
            score = max(score, 1.0)
            violations.append(f"Physical impossibility: Temperature ({temperature:.1f}°C) outside terrestrial range limits")

        # Law 4: Atmospheric pressure range limits (300 hPa to 1100 hPa)
        if pressure is not None and (pressure < 300.0 or pressure > 1100.0):
            score = max(score, 1.0)
            violations.append(f"Physical impossibility: Pressure ({pressure:.1f} hPa) outside surface barometric limits")

        if violations:
            status = "FLAGGED"
            explanation = "; ".join(violations)
        else:
            status = "CLEAR"
            score = 0.0
            explanation = f"Parameters conform to thermodynamic physical laws (Dew point: {dew_point:.1f}°C at {humidity:.1f}% RH)." if dew_point is not None else "Parameters conform to thermodynamic physical laws."

        return PhysicalCheckResult(
            status=status,
            score=score,
            explanation=explanation,
            dew_point=dew_point,
            violations=violations,
        )

    def fuse(
        self,
        timestamp: str,
        station_id: str,
        temperature: Optional[float],
        pressure: Optional[float],
        humidity: Optional[float],
        qc_result: Optional[QCResult] = None,
        iforest_score: Optional[float] = None,
        iforest_flag: Optional[bool] = None,
        lstm_mse: Optional[float] = None,
        lstm_flag: Optional[bool] = None,
        multivariate_anomaly: bool = False,
        multivariate_score: Optional[float] = None,
        spatial_result: Optional[SpatialCheckResult] = None,
        sensor_health: Optional[StationHealthSummary] = None,
        dew_point: Optional[float] = None,
    ) -> FusedDecision:
        """Executes evidential fusion logic across all physical and analytical pillars."""
        contributing_evidence: List[Dict[str, Any]] = []
        scores: Dict[str, float] = {}

        # -------------------------------------------------------------
        # 1. Missing / Gap Handling
        # -------------------------------------------------------------
        if temperature is None and pressure is None and humidity is None:
            return FusedDecision(
                timestamp=str(timestamp),
                station_id=station_id,
                classification=DecisionClassification.UNCERTAIN,
                severity=AnomalySeverity.HIGH,
                calibrated_confidence=None,
                primary_parameter="all",
                contributing_evidence=[{"pillar": "DATA_INTEGRITY", "detail": "All meteorological parameters are missing"}],
                probable_cause="Data transmission dropout, logger power failure, or satellite uplink loss.",
                recommended_operator_action="Inspect station power supply and telemetry transmission status.",
                evidence_scores={"completeness": 0.0},
            )

        # -------------------------------------------------------------
        # 2. Rule-based Quality Control Pillar
        # -------------------------------------------------------------
        qc_reasons = qc_result.qc_reasons if qc_result else []
        qc_flag = qc_result.qc_flag if qc_result else "PASSED"
        qc_score = 0.0

        has_plausibility_violation = False
        has_flatline = False
        has_spike = False

        for reason in qc_reasons:
            r_lower = reason.lower()
            if "plausibility" in r_lower:
                has_plausibility_violation = True
                qc_score = max(qc_score, 1.0)
            elif "flatline" in r_lower:
                has_flatline = True
                qc_score = max(qc_score, 0.85)
            elif "spike" in r_lower or "rate of change" in r_lower:
                has_spike = True
                qc_score = max(qc_score, 0.75)

        if qc_reasons:
            contributing_evidence.append({
                "pillar": "RULE_BASED_QC",
                "flag": qc_flag,
                "reasons": qc_reasons,
                "evidence_score": qc_score,
            })
        scores["rule_qc"] = qc_score

        # -------------------------------------------------------------
        # 3. Isolation Forest Pillar
        # -------------------------------------------------------------
        if_ev = self.calibrate_iforest_evidence(iforest_score) if iforest_score is not None else 0.0
        scores["iforest"] = if_ev
        if iforest_flag or if_ev > 0.6:
            contributing_evidence.append({
                "pillar": "ISOLATION_FOREST",
                "raw_score": iforest_score,
                "calibrated_evidence": if_ev,
                "flag": iforest_flag,
            })

        # -------------------------------------------------------------
        # 4. TensorFlow/Keras LSTM Autoencoder Pillar
        # -------------------------------------------------------------
        lstm_ev = self.calibrate_lstm_evidence(lstm_mse) if lstm_mse is not None else 0.0
        scores["lstm_autoencoder"] = lstm_ev
        if lstm_flag or lstm_ev > 0.6:
            contributing_evidence.append({
                "pillar": "LSTM_AUTOENCODER",
                "reconstruction_mse": lstm_mse,
                "calibrated_evidence": lstm_ev,
                "flag": lstm_flag,
            })

        scores["multivariate_consistency"] = 1.0 if multivariate_anomaly else 0.0
        if multivariate_anomaly:
            contributing_evidence.append({
                "pillar": "MULTIVARIATE_CONSISTENCY",
                "score": multivariate_score,
                "flag": True,
            })

        # -------------------------------------------------------------
        # 5. Thermodynamic Physical Consistency Pillar
        # -------------------------------------------------------------
        thermo_res = self.evaluate_thermodynamic_consistency(
            temperature, pressure, humidity, dew_point
        )
        thermo_score = thermo_res.score
        scores["thermodynamic_violation"] = thermo_score
        if thermo_res.status != "UNAVAILABLE":
            contributing_evidence.append({
                "pillar": "THERMODYNAMICS",
                "status": thermo_res.status,
                "score": thermo_score,
                "explanation": thermo_res.explanation,
                "dew_point": thermo_res.dew_point,
                "violations": thermo_res.violations,
            })

        # -------------------------------------------------------------
        # 6. Spatial Cross-Validation Pillar
        # -------------------------------------------------------------
        spatial_status = spatial_result.spatial_status if spatial_result else "NO_BUDDY_DATA"
        spatial_score = spatial_result.spatial_evidence_score if spatial_result else 0.0
        scores["spatial_evidence"] = spatial_score

        has_spatial_data = spatial_result is not None and spatial_status not in ["NO_BUDDY_DATA", "UNAVAILABLE"]

        if has_spatial_data:
            contributing_evidence.append({
                "pillar": "SPATIAL_CROSS_VALIDATION",
                "status": spatial_status,
                "evidence_score": spatial_score,
                "reasons": spatial_result.reasons,
                "buddy_station": spatial_result.buddy_station_id,
            })
        else:
            contributing_evidence.append({
                "pillar": "SPATIAL_CROSS_VALIDATION",
                "status": "UNAVAILABLE",
                "evidence_score": 0.0,
                "detail": "Single-station operation: No neighboring AWS observation provided.",
            })

        # -------------------------------------------------------------
        # 7. Sensor Historical Health Pillar
        # -------------------------------------------------------------
        overall_health = sensor_health.overall_health_index if sensor_health else 100.0
        scores["station_health"] = overall_health / 100.0
        if sensor_health and sensor_health.overall_status != "OPERATIONAL":
            contributing_evidence.append({
                "pillar": "SENSOR_HISTORY",
                "health_index": overall_health,
                "status": sensor_health.overall_status,
                "alerts": sensor_health.active_alerts,
            })

        # Attribute every parameter flagged by QC, then choose a stable primary
        # parameter for backwards-compatible consumers and recovery ordering.
        temp_violation = any("temp" in r.lower() for r in qc_reasons)
        press_violation = any("press" in r.lower() for r in qc_reasons)
        hum_violation = any("hum" in r.lower() for r in qc_reasons)
        temp_plausibility = any("temp" in r.lower() and "plausibility" in r.lower() for r in qc_reasons)
        press_plausibility = any("press" in r.lower() and "plausibility" in r.lower() for r in qc_reasons)
        hum_plausibility = any("hum" in r.lower() and "plausibility" in r.lower() for r in qc_reasons)

        affected_parameters = []
        if temp_violation or (qc_result and (qc_result.temperature_spike or qc_result.temperature_flatline)):
            affected_parameters.append("temperature")
        if press_violation or (qc_result and (qc_result.pressure_spike or qc_result.pressure_flatline)):
            affected_parameters.append("pressure")
        if hum_violation or (qc_result and (qc_result.humidity_spike or qc_result.humidity_flatline)):
            affected_parameters.append("humidity")

        primary_param = (
            "temperature" if temp_violation else
            "pressure" if press_violation else
            "humidity" if hum_violation else
            affected_parameters[0] if affected_parameters else "multivariate"
        )

        # -------------------------------------------------------------
        # 8. Evidential Decision Synthesis
        # -------------------------------------------------------------
        # Count independent fault indicators
        fault_indicators = 0
        if has_plausibility_violation:
            fault_indicators += 2  # Physical impossibility or extreme spike is strong fault evidence
        if thermo_score >= 0.9:
            fault_indicators += 2
        if has_spatial_data and spatial_score < -0.6:  # Severe discordance with close neighbor
            fault_indicators += 1
        if has_flatline:
            fault_indicators += 1
        if if_ev > 0.8 and lstm_ev > 0.8 and spatial_score <= 0.0:
            fault_indicators += 1
        if multivariate_anomaly:
            fault_indicators += 1

        if sensor_health and sensor_health.overall_health_index < 50.0:
            fault_indicators += 1

        # Check for corroborating weather indicators
        weather_indicators = 0
        if has_spatial_data and spatial_score >= 0.6 and has_spike and (if_ev > 0.5 or lstm_ev > 0.5):
            weather_indicators += 2
        if has_spatial_data and spatial_result and spatial_result.spatial_agreement is True and has_spike:
            weather_indicators += 2

        evidence_count = sum([
            qc_flag != "PASSED",
            bool(iforest_flag),
            bool(lstm_flag),
            bool(multivariate_anomaly),
        ])
        if evidence_count >= 3 and weather_indicators == 0:
            fault_indicators = max(fault_indicators, 2)

        # -------------------------------------------------------------
        # Rule Branch 1: LIKELY_SENSOR_DATA_FAULT
        # -------------------------------------------------------------
        if fault_indicators >= self.min_fault_concordance:
            # Calculate calibrated confidence from number of concordant signals
            conf = min(0.99, 0.70 + (fault_indicators - 2) * 0.10)
            
            # Severity determination
            if has_plausibility_violation or thermo_score >= 0.9 or (has_spatial_data and spatial_score <= -0.9):
                severity = AnomalySeverity.CRITICAL
            elif evidence_count >= 3 or has_flatline:
                severity = AnomalySeverity.HIGH
            else:
                severity = AnomalySeverity.MEDIUM

            # Dynamic probable cause based on actual detector evidence
            if press_plausibility:
                cause = "Pressure Plausibility Violation"
            elif temp_plausibility:
                cause = "Temperature Plausibility Violation"
            elif hum_plausibility:
                cause = "Humidity Plausibility Violation"
            elif qc_result and qc_result.temperature_spike:
                cause = "Rapid Temperature Change"
            elif qc_result and qc_result.pressure_spike:
                cause = "Rapid Pressure Change"
            elif qc_result and qc_result.humidity_spike:
                cause = "Rapid Humidity Change"
            elif has_flatline:
                cause = f"Sensor freezing or mechanical flatline detected on {primary_param}."
            else:
                cause = f"Corroborated sensor failure indicated by multi-model analytical consensus on {primary_param}."

            if has_spatial_data and spatial_result and spatial_result.buddy_station_id:
                action = (
                    f"Immediate operational action: Flag observation as invalid. Invalidate downstream NWP "
                    f"ingestion. Inspect {primary_param} transducer and compare with buddy station {spatial_result.buddy_station_id}."
                )
            else:
                action = (
                    f"Immediate operational action: Flag observation as invalid. Invalidate downstream NWP "
                    f"ingestion. Inspect {primary_param} transducer, signal cable, and A/D converter."
                )

            return FusedDecision(
                timestamp=str(timestamp),
                station_id=station_id,
                classification=DecisionClassification.LIKELY_SENSOR_DATA_FAULT,
                severity=severity,
                calibrated_confidence=conf,
                primary_parameter=primary_param,
                affected_parameters=affected_parameters,
                contributing_evidence=contributing_evidence,
                probable_cause=cause,
                recommended_operator_action=action,
                maintenance_status=maintenance_status_for_severity(severity),
                evidence_scores=scores,
                physical_result=thermo_res,
                multivariate_anomaly=multivariate_anomaly,
                multivariate_score=multivariate_score,
            )

        # -------------------------------------------------------------
        # Rule Branch 2: LIKELY_GENUINE_WEATHER_EVENT
        # -------------------------------------------------------------
        if weather_indicators >= 2 and fault_indicators == 0:
            conf = min(0.95, 0.75 + (weather_indicators - 2) * 0.10)
            severity = AnomalySeverity.MEDIUM
            cause = (
                "Rapid meteorological transition (e.g. cyclonic frontal passage, katabatic wind event, "
                f"or intense temperature inversion breakdown) corroborated by spatial buddy station {spatial_result.buddy_station_id if spatial_result else 'network'}."
            )
            action = (
                "Do NOT flag as sensor fault. Retain observation in climatological record. "
                "Issue mesoscale weather advisory if rate of change exceeds operational aviation thresholds."
            )
            return FusedDecision(
                timestamp=str(timestamp),
                station_id=station_id,
                classification=DecisionClassification.LIKELY_GENUINE_WEATHER_EVENT,
                severity=severity,
                calibrated_confidence=conf,
                primary_parameter=primary_param,
                affected_parameters=affected_parameters,
                contributing_evidence=contributing_evidence,
                probable_cause=cause,
                recommended_operator_action=action,
                maintenance_status=maintenance_status_for_severity(severity),
                evidence_scores=scores,
                physical_result=thermo_res,
                multivariate_anomaly=multivariate_anomaly,
                multivariate_score=multivariate_score,
            )

        # -------------------------------------------------------------
        # Rule Branch 3: UNCERTAIN
        # -------------------------------------------------------------
        # Ambiguous cases: only 1 fault indicator without buddy data, or conflicting evidence
        is_ambiguous = (
            (fault_indicators == 1 and weather_indicators == 0)
            or (fault_indicators > 0 and weather_indicators > 0)
            or (if_ev > 0.7 and spatial_status in ["NO_BUDDY_DATA", "UNAVAILABLE"] and not has_plausibility_violation)
        )

        if is_ambiguous:
            cause_str = (
                "Pressure Plausibility Violation" if press_plausibility else
                "Temperature Plausibility Violation" if temp_plausibility else
                "Humidity Plausibility Violation" if hum_plausibility else
                "Conflicting or insufficient evidence: Single-station anomaly detected by analytical models without decisive spatial corroboration."
            )
            return FusedDecision(
                timestamp=str(timestamp),
                station_id=station_id,
                classification=DecisionClassification.UNCERTAIN,
                severity=AnomalySeverity.LOW,
                calibrated_confidence=None,  # Never claim false confidence when uncertain
                primary_parameter=primary_param,
                affected_parameters=affected_parameters,
                contributing_evidence=contributing_evidence,
                probable_cause=cause_str,
                recommended_operator_action=(
                    "Mark observation for human meteorologist review. Correlate with regional satellite imagery "
                    "or wait for subsequent hourly observations to verify trend continuity."
                ),
                maintenance_status=maintenance_status_for_severity(AnomalySeverity.LOW),
                evidence_scores=scores,
                physical_result=thermo_res,
                multivariate_anomaly=multivariate_anomaly,
                multivariate_score=multivariate_score,
            )

        # -------------------------------------------------------------
        # Rule Branch 4: NORMAL
        # -------------------------------------------------------------
        # Everything is within normal baseline parameters
        conf = 0.98 if (if_ev < 0.3 and lstm_ev < 0.3 and qc_score == 0.0) else 0.85
        return FusedDecision(
            timestamp=str(timestamp),
            station_id=station_id,
            classification=DecisionClassification.NORMAL,
            severity=AnomalySeverity.NONE,
            calibrated_confidence=conf,
            primary_parameter=None,
            contributing_evidence=[],
            probable_cause="No Significant Anomaly",
            recommended_operator_action="Routine continuous monitoring. No operator action required.",
            maintenance_status=maintenance_status_for_severity(AnomalySeverity.NONE),
            evidence_scores=scores,
            physical_result=thermo_res,
            multivariate_anomaly=multivariate_anomaly,
            multivariate_score=multivariate_score,
        )
