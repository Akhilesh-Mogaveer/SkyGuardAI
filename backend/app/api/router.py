"""Main FastAPI REST and WebSocket API Router for SkyGuard AI.

Provides comprehensive API endpoints for:
- System & Station Health (`/health`, `/stations`, `/stations/{station_id}`, `/sensor-health`)
- Telemetry & Data Access (`/observations`, `/anomalies`, `/statistics`)
- Single Observation Ingestion (`/process-observation`)
- Historical CSV Replay (`/replay/start`, `/replay/stop`, `/replay/status`)
- Real-Time WebSocket Streaming (`/ws/observations`)
"""

from dataclasses import asdict
import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
import pandas as pd
from pydantic import BaseModel, Field


from backend.app.config import settings
from backend.app.core.pipeline import SkyGuardPipeline, PipelineProcessingResult
from backend.app.services.websocket_manager import ws_manager
from backend.app.services.replay_service import replay_runner
from backend.app.db.sensor_health_db import SensorHealthDatabase
from backend.app.db.alert_db import alert_db

router = APIRouter()

# Instantiate master pipeline and DB connectors
pipeline = SkyGuardPipeline()
health_db = SensorHealthDatabase()


# -------------------------------------------------------------------
# Request & Response Pydantic Models
# -------------------------------------------------------------------

class SingleObservationInput(BaseModel):
    timestamp: str = Field(..., example="2016-09-09 17:00:00")
    temperature: Optional[float] = Field(None, example=41.6)
    pressure: Optional[float] = Field(None, example=946.0)
    humidity: Optional[float] = Field(None, example=100.0)
    relative_humidity: Optional[float] = Field(None, example=100.0, description="Legacy alias for humidity")
    station_id: Optional[str] = Field(default=settings.DEFAULT_STATION_ID, example=settings.DEFAULT_STATION_ID)
    buddy_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional neighbor station reading for spatial buddy check",
        example={"station_id": "AWS-NOVO-89512", "temperature": -22.0, "pressure": 947.0, "humidity": 45.0},
    )


class ReplayStartInput(BaseModel):
    speed_multiplier: float = Field(default=10.0, ge=0.1, le=1000.0, example=10.0)
    start_index: int = Field(default=0, ge=0, example=0)


# -------------------------------------------------------------------
# 1. Health & Station Management Endpoints
# -------------------------------------------------------------------

@router.get("/health", summary="Get System & Model Health Status", tags=["System & Station"])
def get_system_health() -> Dict[str, Any]:
    """Returns application operational status, model availability, and dataset integrity."""
    return {
        "status": "OPERATIONAL",
        "system": "SkyGuard AI",
        "version": "1.0.0",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "primary_station_id": settings.DEFAULT_STATION_ID,
        "models": {
            "isolation_forest_loaded": pipeline.iforest_loaded,
            "lstm_autoencoder_loaded": pipeline.lstm_loaded,
        },
        "replay_active": replay_runner.is_running,
    }


@router.get("/stations", summary="List Monitored Weather Stations", tags=["System & Station"])
def get_monitored_stations() -> List[Dict[str, Any]]:
    """Returns list of primary and companion AWS stations in the Antarctic network."""
    stations = [
        {
            "station_id": settings.DEFAULT_STATION_ID,
            "station_name": settings.DEFAULT_STATION_NAME,
            "latitude": settings.STATION_LATITUDE,
            "longitude": settings.STATION_LONGITUDE,
            "elevation_m": settings.STATION_ELEVATION_M,
            "is_primary": True,
            "status": "OPERATIONAL",
        }
    ]
    for b in settings.BUDDY_STATIONS:
        stations.append({
            "station_id": b[0],
            "station_name": b[1],
            "latitude": b[2],
            "longitude": b[3],
            "elevation_m": b[4],
            "is_primary": False,
            "status": "SPATIAL_COMPANION",
        })
    return stations


@router.get("/stations/{station_id}", summary="Get Station Details", tags=["System & Station"])
def get_station_details(station_id: str) -> Dict[str, Any]:
    """Returns detailed geographic and operational status for a specific station."""
    stations = get_monitored_stations()
    for s in stations:
        if s["station_id"].lower() == station_id.lower():
            snapshot = health_db.fetch_latest_station_snapshot(s["station_id"])
            s["health_snapshot"] = snapshot.to_dict() if snapshot else None
            return s
    raise HTTPException(status_code=404, detail=f"Station ID '{station_id}' not found.")


# -------------------------------------------------------------------
# 2. Sensor Health Endpoint
# -------------------------------------------------------------------

@router.get("/sensor-health", summary="Get Long-Term Sensor Health Indices", tags=["Sensor Health Monitoring"])
def get_sensor_health(
    station_id: str = Query(settings.DEFAULT_STATION_ID),
    parameter: Optional[str] = Query(None, description="Optional parameter filter (temperature, pressure, humidity)"),
) -> Dict[str, Any]:
    """Returns long-term sensor reliability indices, indicator rates, and active alerts."""
    snapshot = health_db.fetch_latest_station_snapshot(station_id)
    history_by_param = {}
    params = [parameter] if parameter else ["temperature", "pressure", "humidity"]

    for p in params:
        records = health_db.fetch_parameter_health_history(station_id, p, limit=50)
        history_by_param[p] = [r.to_dict() for r in records]

    return {
        "station_id": station_id,
        "overall_snapshot": snapshot.to_dict() if snapshot else None,
        "parameter_history": history_by_param,
    }


# -------------------------------------------------------------------
# 3. Processing & Ingestion Endpoints
# -------------------------------------------------------------------

@router.post("/process-observation", summary="Process Single Observation through Full Pipeline", tags=["Ingestion & Pipeline"])
@router.post("/analyze", summary="Analyze Single Observation through Full Pipeline", tags=["Ingestion & Pipeline"])
async def process_single_observation(input_data: SingleObservationInput) -> Dict[str, Any]:
    """Ingests and processes a single AWS observation through all 7 pipeline stages.
    
    Executes Baseline QC, Isolation Forest, LSTM Autoencoder, Thermodynamics,
    Spatial Validation, Sensor History, and Evidence Fusion.
    Broadcasts payload over active WebSocket connections.
    """
    if replay_runner.df_replay is None:
        try:
            replay_runner.load_dataset()
        except Exception:
            pass

    res: PipelineProcessingResult = pipeline.process_observation(
        timestamp=input_data.timestamp,
        temperature=input_data.temperature,
        pressure=input_data.pressure,
        humidity=input_data.humidity if input_data.humidity is not None else input_data.relative_humidity,
        station_id=input_data.station_id,
        buddy_data=input_data.buddy_data,
        dataset_df=replay_runner.df_replay,
    )

    result_dict = res.to_dict()
    alert_db.insert_observation(result_dict)

    # Broadcast to live WebSockets
    await ws_manager.broadcast({
        "event_type": "SINGLE_OBSERVATION_PROCESSED",
        "source": "API_INGESTION",
        "data": result_dict,
    })

    return result_dict


# -------------------------------------------------------------------
# 4. Telemetry, Anomalies & Statistics Endpoints
# -------------------------------------------------------------------

@router.get("/observations", summary="Query Processed Observations", tags=["Telemetry & Anomalies"])
def get_processed_observations(
    limit: int = Query(500, ge=1, le=2000),
    classification: Optional[str] = Query(None, description="Filter by classification: NORMAL, LIKELY_SENSOR_DATA_FAULT, LIKELY_GENUINE_WEATHER_EVENT, UNCERTAIN"),
) -> Dict[str, Any]:
    """Returns processed observation history stored in database and memory buffer."""
    limit_val = limit if isinstance(limit, int) else getattr(limit, "default", 500)
    if not isinstance(limit_val, int):
        limit_val = 500

    db_obs = alert_db.fetch_observations(limit=limit_val, classification=classification)
    if db_obs:
        return {
            "total_available_in_buffer": len(db_obs),
            "count": len(db_obs),
            "observations": db_obs,
        }

    history = list(replay_runner.processed_history)
    if classification and isinstance(classification, str):
        history = [r for r in history if r.get("decision", {}).get("classification") == classification.upper()]

    return {
        "total_available_in_buffer": len(history),
        "count": min(limit_val, len(history)),
        "observations": history[-limit_val:] if limit_val > 0 else [],
    }


@router.get("/anomalies", summary="Query Detected Anomalies", tags=["Telemetry & Anomalies"])
@router.get("/alerts", summary="Query Alert History", tags=["Telemetry & Anomalies"])
def get_detected_anomalies(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    severity: Optional[str] = Query(None, description="Filter by severity: LOW, MEDIUM, HIGH, CRITICAL"),
    classification: Optional[str] = Query(None, description="Filter: LIKELY_SENSOR_DATA_FAULT, LIKELY_GENUINE_WEATHER_EVENT, UNCERTAIN"),
    station_id: Optional[str] = Query(None),
    parameter: Optional[str] = Query(None),
    time_range: Optional[str] = Query(None, description="Optional time filter: 24H or 7D"),
) -> Dict[str, Any]:
    """Returns a server-side paginated view of persistent alert history."""
    result = alert_db.fetch_anomalies_page(
        page=page,
        page_size=page_size,
        severity=severity,
        classification=classification,
        station_id=station_id,
        parameter=parameter,
        time_range=time_range,
    )
    if result["total"] == 0 and replay_runner.processed_history:
        history = [r for r in replay_runner.processed_history if r.get("decision", {}).get("classification") != "NORMAL"]
        if classification:
            history = [r for r in history if r.get("decision", {}).get("classification") == classification.upper()]
        if severity:
            history = [r for r in history if r.get("decision", {}).get("severity") == severity.upper()]
        history.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        offset = (page - 1) * page_size
        result["items"] = history[offset:offset + page_size]
        result["total"] = len(history)
        result["total_pages"] = (len(history) + page_size - 1) // page_size
    return {
        **result,
        "anomalies_found": result["total"],
        "count": len(result["items"]),
        "anomalies": result["items"],
    }


@router.get("/anomalies/{alert_id}", summary="Get Alert Details", tags=["Telemetry & Anomalies"])
@router.get("/alerts/{alert_id}", summary="Get Alert Details", tags=["Telemetry & Anomalies"])
def get_alert_details(alert_id: int) -> Dict[str, Any]:
    alert = alert_db.fetch_observation_by_id(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.post("/anomalies/clear", summary="Clear Active Alert Queue", tags=["Telemetry & Anomalies"])
@router.delete("/anomalies", summary="Clear Active Alert Queue", tags=["Telemetry & Anomalies"])
def clear_alert_queue() -> Dict[str, Any]:
    """Clears all stored observations and alerts from the database and in-memory buffer."""
    deleted_db_count = alert_db.clear_observations()
    replay_runner.clear_history()
    return {
        "message": "Alert work queue cleared successfully",
        "deleted_records": deleted_db_count,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


@router.get("/statistics", summary="Get Pipeline & Dataset Quality Statistics", tags=["Telemetry & Anomalies"])
def get_pipeline_statistics() -> Dict[str, Any]:
    """Returns dataset summary stats and persistent alert distribution counts."""
    persistent = alert_db.fetch_anomalies_page(page=1, page_size=1)
    history = replay_runner.processed_history
    total = persistent["total"] or len(history)

    counts = {
        "NORMAL": 0,
        "LIKELY_GENUINE_WEATHER_EVENT": 0,
        "LIKELY_SENSOR_DATA_FAULT": 0,
        "UNCERTAIN": 0,
    }
    if persistent["total"]:
        counts = {"NORMAL": 0, "LIKELY_GENUINE_WEATHER_EVENT": 0, "LIKELY_SENSOR_DATA_FAULT": 0, "UNCERTAIN": 0}
        with alert_db.get_connection() as conn:
            rows = conn.execute("SELECT classification, COUNT(*) AS count FROM observations_log GROUP BY classification").fetchall()
        for row in rows:
            counts[row["classification"]] = row["count"]
    else:
        for r in history:
            cls = r.get("decision", {}).get("classification", "NORMAL")
            counts[cls] = counts.get(cls, 0) + 1

    return {
        "station_id": settings.DEFAULT_STATION_ID,
        "buffer_size": total,
        "classification_breakdown": counts,
        "replay_status": asdict(replay_runner.get_status()),
        "dataset_info": {
            "raw_dataset_path": str(settings.DEFAULT_RAW_CSV.name),
            "total_rows_in_file": replay_runner.total_rows,
        },
    }


# -------------------------------------------------------------------
# 5. Historical CSV Replay Endpoints
# -------------------------------------------------------------------

@router.post("/replay/start", summary="Start Historical CSV Replay", tags=["Historical Replay"])
@router.post("/replay", summary="Start Historical CSV Replay", tags=["Historical Replay"])
async def start_csv_replay(input_data: ReplayStartInput) -> Dict[str, Any]:
    """Starts chronological background replay of historical AWS observations through full pipeline.
    
    Broadcasts results over WebSockets in real time at configurable speed.
    """
    status = await replay_runner.start_replay(
        speed_multiplier=input_data.speed_multiplier,
        start_index=input_data.start_index,
    )
    return {
        "message": "Historical CSV replay started",
        "status": asdict(status),
    }


@router.post("/replay/stop", summary="Stop Historical CSV Replay", tags=["Historical Replay"])
def stop_csv_replay() -> Dict[str, Any]:
    """Stops the active CSV replay worker."""
    status = replay_runner.stop_replay()
    return {
        "message": "Historical CSV replay stopped",
        "status": asdict(status),
    }


@router.get("/replay/status", summary="Get Historical Replay Status", tags=["Historical Replay"])
def get_csv_replay_status() -> Dict[str, Any]:
    """Returns progress, current index, and anomaly counts for historical CSV replay."""
    return asdict(replay_runner.get_status())


# -------------------------------------------------------------------
# 7. SkyGuard Demo Mode Endpoints (Separate & Un-mocked)
# -------------------------------------------------------------------

class DemoStepInput(BaseModel):
    timestamp: str = Field(..., example="2016-09-09 17:00:00")
    prewarm_hours: int = Field(default=48, ge=0, le=168, description="Hours of historical context to pre-warm into pipeline buffer")
    temperature: Optional[float] = Field(default=None, example=-5.42)
    pressure: Optional[float] = Field(default=None, example=965.08)
    humidity: Optional[float] = Field(default=None, example=44.42)


@router.get("/demo/preset-cases", summary="Get Demo Mode Preset Benchmark Cases", tags=["SkyGuard Demo Mode"])
def get_demo_preset_cases() -> List[Dict[str, Any]]:
    """Returns curated benchmark demonstration cases from the real Maitri AWS dataset."""
    return [
        {
            "case_id": "temp_spike_2016_09_09",
            "title": "2016-09-09 17:00 (+41.6°C Extreme Jump)",
            "timestamp": "2016-09-09 17:00:00+00:00",
            "temperature": 41.6,
            "pressure": 946.7,
            "humidity": 100.0,
            "category": "SENSOR_FAULT_BENCHMARK",
            "description": "Known Antarctic sensor fault where temperature jumped +63.8°C in 1 hour (from -22.2°C to +41.6°C). Demonstrates multi-pillar fault detection.",
        },
        {
            "case_id": "imd_bharati_2015_11_06",
            "title": "2015-11-06 15:00 (IMD Bharati validation case)",
            "timestamp": "2015-11-06 15:00:00+00:00",
            "temperature": -5.42,
            "pressure": 965.08,
            "humidity": 44.42,
            "category": "VALIDATION_CASE",
            "description": "Deterministic IMD Bharati observation processed by the live pipeline using the supplied values.",
        },
        {
            "case_id": "normal_polar_diurnal",
            "title": "2016-06-15 12:00 (Pristine Polar Winter)",
            "timestamp": "2016-06-15 12:00:00+00:00",
            "temperature": -9.0,
            "pressure": 967.8,
            "humidity": 76.0,
            "category": "NORMAL_BASELINE",
            "description": "Uncontaminated, smooth polar winter diurnal temperature and pressure trace.",
        },
        {
            "case_id": "pressure_gradient_storm",
            "title": "2016-07-22 08:00 (Barometric Pressure Fall)",
            "timestamp": "2016-07-22 08:00:00+00:00",
            "temperature": -22.3,
            "pressure": 965.5,
            "humidity": 39.0,
            "category": "WEATHER_EVENT_BENCHMARK",
            "description": "Rapid barometric pressure fall during an Antarctic coastal cyclone.",
        },
        {
            "case_id": "sensor_flatline",
            "title": "2016-04-10 06:00 (Humidity Flatline Persistence)",
            "timestamp": "2016-04-10 06:00:00+00:00",
            "temperature": -15.7,
            "pressure": 956.1,
            "humidity": 46.0,
            "category": "FLATLINE_BENCHMARK",
            "description": "Multiple consecutive hours of unvarying identical relative humidity reading indicating sensor freezing.",
        },
    ]



_demo_step_cache: Dict[str, Dict[str, Any]] = {}


@router.post("/demo/evaluate-step", summary="Evaluate Single Step in Demo Mode through Real Pipeline", tags=["SkyGuard Demo Mode"])
def evaluate_demo_step(input_data: DemoStepInput) -> Dict[str, Any]:
    """Executes the actual production SkyGuardPipeline for a target historical observation.
    
    Pre-warms historical buffer with continuous preceding dataset observations so rolling
    features (Isolation Forest, LSTM 24h window) are computed on true dataset context.
    Returns structured step-by-step pipeline outputs.
    """
    cache_key = f"{input_data.timestamp}_{input_data.prewarm_hours}"
    if cache_key in _demo_step_cache:
        return _demo_step_cache[cache_key]

    if replay_runner.df_replay is None:
        replay_runner.load_dataset()

    df_raw = replay_runner.df_replay
    if df_raw is None or df_raw.empty:
        raise HTTPException(status_code=500, detail="Maitri dataset not loaded on server.")

    target_ts = pd.to_datetime(input_data.timestamp, utc=True)
    
    matches = df_raw[df_raw["parsed_ts"] == target_ts]
    if matches.empty:
        matches = df_raw[df_raw["parsed_ts"].dt.strftime("%Y-%m-%d %H:%M").str.contains(target_ts.strftime("%Y-%m-%d %H:%M"))]

    direct_observation = any(value is not None for value in (input_data.temperature, input_data.pressure, input_data.humidity))
    if matches.empty and not direct_observation:
        raise HTTPException(status_code=404, detail=f"Timestamp '{input_data.timestamp}' not found in Maitri dataset.")

    target_idx = matches.index[0] if not matches.empty else None
    context_end = target_idx if target_idx is not None else int(
        df_raw["parsed_ts"].searchsorted(target_ts, side="left")
    )

    # Pre-warm pipeline buffer with preceding rows
    if input_data.prewarm_hours > 0 and context_end > 0:
        start_idx = max(0, context_end - input_data.prewarm_hours)
        prewarm_slice = df_raw.iloc[start_idx:context_end]
        for _, row in prewarm_slice.iterrows():
            t_pre = row.get(settings.RAW_TEMPERATURE_COL, row.get("temperature", None))
            p_pre = row.get(settings.RAW_PRESSURE_COL, row.get("pressure", None))
            h_pre = row.get(settings.RAW_HUMIDITY_COL, row.get("relative_humidity", None))
            pipeline.process_observation(
                timestamp=str(row["parsed_ts"]),
                temperature=t_pre,
                pressure=p_pre,
                humidity=h_pre,
                dataset_df=df_raw,
            )

    target_row = df_raw.iloc[target_idx] if target_idx is not None else None
    t_val = input_data.temperature if input_data.temperature is not None else target_row.get(settings.RAW_TEMPERATURE_COL, target_row.get("temperature", None))
    p_val = input_data.pressure if input_data.pressure is not None else target_row.get(settings.RAW_PRESSURE_COL, target_row.get("pressure", None))
    h_val = input_data.humidity if input_data.humidity is not None else target_row.get(settings.RAW_HUMIDITY_COL, target_row.get("relative_humidity", None))

    res: PipelineProcessingResult = pipeline.process_observation(
        timestamp=str(target_row["parsed_ts"] if target_row is not None else target_ts),
        temperature=t_val,
        pressure=p_val,
        humidity=h_val,
        dataset_df=df_raw,
    )

    res_dict = res.to_dict()
    alert_db.insert_observation(res_dict)

    output_payload = {
        "dataset_index": int(target_idx) if target_idx is not None else None,
        "target_timestamp": res.timestamp,
        "stage_1_incoming": {
            "timestamp": res.timestamp,
            "station_id": res.station_id,
            "temperature": res.temperature,
            "pressure": res.pressure,
            "humidity": res.humidity,
        },
        "stage_2_qc": {
            "qc_flag": res.qc_result.qc_flag,
            "qc_reasons": res.qc_result.qc_reasons,
            "temperature_spike": res.qc_result.temperature_spike,
            "pressure_spike": res.qc_result.pressure_spike,
            "humidity_spike": res.qc_result.humidity_spike,
            "temperature_flatline": res.qc_result.temperature_flatline,
            "pressure_flatline": res.qc_result.pressure_flatline,
            "humidity_flatline": res.qc_result.humidity_flatline,
            "missing_flag": res.qc_result.missing_flag,
            "gap_flag": res.qc_result.gap_flag,
        },
        "stage_3_iforest": {
            "anomaly_score": res.iforest_score,
            "is_anomaly": res.iforest_flag,
            "calibrated_evidence": res_dict.get("decision", {}).get("evidence_scores", {}).get("isolation_forest", 0.0),
        },
        "stage_4_lstm": {
            "reconstruction_error_mse": res.lstm_mse,
            "anomaly_threshold": pipeline.lstm_detector.anomaly_threshold,
            "is_anomaly": res.lstm_flag,
            "calibrated_evidence": res_dict.get("decision", {}).get("evidence_scores", {}).get("lstm_autoencoder", 0.0),
        },

        "stage_5_evidence_validation": {
            "dew_point": res.dew_point,
            "thermodynamic_validity": "VALID" if (res.dew_point is None or (res.temperature is not None and res.temperature >= res.dew_point)) else "DEW_POINT_SUPERSATURATED",
            "spatial_status": res.spatial_result.spatial_status,
            "spatial_evidence": res.spatial_result.spatial_evidence_score,
            "sensor_health_jitter": {k: v.health_index for k, v in res.sensor_health.parameters.items()},
        },
        "stage_6_classification": {
            "primary_classification": res.decision.classification.value if hasattr(res.decision.classification, 'value') else str(res.decision.classification),
            "severity": res.decision.severity.value if hasattr(res.decision.severity, 'value') else str(res.decision.severity),
            "calibrated_confidence": res.decision.calibrated_confidence,
            "contributing_evidence": res.decision.contributing_evidence,
        },

        "stage_7_explanation": {
            "probable_cause": res.decision.probable_cause,
            "recommended_operator_action": res.decision.recommended_operator_action,
        },
        "stage_8_sensor_health_update": {
            "overall_status": res.sensor_health.overall_status,
            "parameter_scores": {k: v.health_index for k, v in res.sensor_health.parameters.items()},
        },

        "full_pipeline_result": res_dict,
    }
    _demo_step_cache[cache_key] = output_payload
    return output_payload



# -------------------------------------------------------------------
# 6. WebSocket Real-Time Telemetry Endpoint
# -------------------------------------------------------------------

@router.websocket("/ws/observations")
async def websocket_observations_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for receiving real-time AWS observation streams and anomaly alerts."""
    await ws_manager.connect(websocket)
    try:
        # Send welcome message
        await ws_manager.send_personal_message(
            {
                "event_type": "CONNECTED",
                "message": "Connected to SkyGuard AI Real-Time Telemetry Stream",
                "station_id": settings.DEFAULT_STATION_ID,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            websocket,
        )
        # Keep connection open to listen for client ping/messages
        while True:
            data = await websocket.receive_text()
            # Echo back receipt acknowledgment
            await ws_manager.send_personal_message({"event_type": "ACK", "client_message": data}, websocket)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning("WebSocket error: %s", e)
        ws_manager.disconnect(websocket)

