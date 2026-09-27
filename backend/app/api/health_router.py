"""FastAPI API Router for Station & Sensor Health Monitoring.

Exposes RESTful endpoints to query long-term sensor reliability metrics, parameter health breakdowns,
active maintenance alerts, and historical health time series data.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.app.config import settings
from backend.app.db.sensor_health_db import SensorHealthDatabase
from backend.app.services.sensor_health_service import SensorHealthCalculationService, HealthIndicatorConfig
from backend.app.services.health_chart_service import HealthChartService

router = APIRouter(prefix="/api/v1/health", tags=["Sensor Health Monitoring"])

db = SensorHealthDatabase()
health_service = SensorHealthCalculationService(db=db)
chart_service = HealthChartService(db=db)


# Response Pydantic Models
class IndicatorBreakdown(BaseModel):
    anomaly_frequency: float = Field(..., description="Frequency of anomalies over evaluation window [0, 1]")
    missing_frequency: float = Field(..., description="Frequency of missing observations [0, 1]")
    flatline_frequency: float = Field(..., description="Frequency of flatline/frozen sensor states [0, 1]")
    qc_violation_rate: float = Field(..., description="Rate of WMO QC rule violations [0, 1]")
    recent_anomaly_trend: float = Field(..., description="Recent 24h anomaly rate vs 30d baseline (-1.0 to +1.0)")


class ParameterHealthResponse(BaseModel):
    timestamp: str
    station_id: str
    parameter_name: str
    health_index: float = Field(..., description="Composite long-term reliability index (0 to 100%)")
    status: str = Field(..., description="Operational status: HEALTHY, DEGRADING, MAINTENANCE_REQUIRED, FAILED")
    indicators: IndicatorBreakdown
    evaluation_window_hours: int


class StationHealthResponse(BaseModel):
    timestamp: str
    station_id: str
    overall_health_index: float = Field(..., description="Weighted average health index across all parameters (0 to 100%)")
    overall_status: str = Field(..., description="Overall station status: OPERATIONAL, DEGRADED, CRITICAL_ATTENTION")
    parameter_scores: Dict[str, float]
    active_alerts: List[str]


class RecalculateRequest(BaseModel):
    station_id: str = settings.DEFAULT_STATION_ID
    anomaly_weight: float = 30.0
    missing_weight: float = 25.0
    flatline_weight: float = 20.0
    qc_weight: float = 15.0
    trend_weight: float = 10.0


@router.get("/station/{station_id}", response_model=StationHealthResponse)
def get_station_health_summary(station_id: str) -> StationHealthResponse:
    """Returns the most recent overall health snapshot and active warnings for a weather station."""
    snapshot = db.fetch_latest_station_snapshot(station_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="No pipeline-generated sensor health is available for this station.")
    return StationHealthResponse(**snapshot.to_dict())


@router.get("/parameter/{station_id}/{parameter_name}", response_model=ParameterHealthResponse)
def get_parameter_health(station_id: str, parameter_name: str) -> ParameterHealthResponse:
    """Returns detailed long-term health indicators, trend momentum, and status for a specific parameter."""
    records = db.fetch_parameter_health_history(station_id, parameter_name, limit=1)
    if not records:
        raise HTTPException(status_code=404, detail="No pipeline-generated parameter health is available.")
    return ParameterHealthResponse(**records[0].to_dict())


@router.get("/history/{station_id}")
def get_station_health_history(
    station_id: str,
    parameter: Optional[str] = Query(None, description="Optional parameter filter (temperature, pressure, humidity)"),
    limit: int = Query(100, ge=1, le=1000),
) -> Dict[str, Any]:
    """Returns historical health index time-series records for charting and trend analysis."""
    params = [parameter] if parameter else ["temperature", "pressure", "humidity"]
    history_by_param = {}

    for p in params:
        records = db.fetch_parameter_health_history(station_id, p, limit=limit)
        history_by_param[p] = [r.to_dict() for r in records]

    return {
        "station_id": station_id,
        "history": history_by_param,
    }


@router.get("/alerts/{station_id}")
def get_active_health_alerts(station_id: str) -> Dict[str, Any]:
    """Returns active degradation alerts and maintenance warnings for a station."""
    snapshot = db.fetch_latest_station_snapshot(station_id)
    alerts = snapshot.active_alerts if snapshot else []
    status = snapshot.overall_status if snapshot else "OPERATIONAL"

    return {
        "station_id": station_id,
        "overall_status": status,
        "active_alerts_count": len(alerts),
        "alerts": alerts,
        "active_alerts": alerts,
    }


@router.post("/recalculate")
def recalculate_health(request: RecalculateRequest) -> Dict[str, Any]:
    """Recalculates station health scores using updated indicator weight configurations."""
    custom_config = HealthIndicatorConfig(
        anomaly_frequency_weight=request.anomaly_weight,
        missing_frequency_weight=request.missing_weight,
        flatline_frequency_weight=request.flatline_weight,
        qc_violation_weight=request.qc_weight,
        recent_trend_weight=request.trend_weight,
    )
    svc = SensorHealthCalculationService(config=custom_config, db=db)

    # Load cleaned maitri dataset if available
    cleaned_path = settings.PROCESSED_DATA_DIR / "cleaned_maitri.parquet"
    if cleaned_path.exists():
        import pandas as pd
        df = pd.read_parquet(cleaned_path)
    else:
        import pandas as pd
        df = pd.DataFrame({"temperature": [-15.0]*100, "pressure": [980.0]*100, "relative_humidity": [60.0]*100})

    import datetime
    ts_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    snapshot = svc.evaluate_station_health(request.station_id, df, ts_now)
    chart_service.generate_health_chart(request.station_id)

    return {
        "message": "Health metrics successfully recalculated",
        "station_health": snapshot.to_dict(),
    }
