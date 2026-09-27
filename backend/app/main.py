"""Main FastAPI application for SkyGuard AI backend.

Exposes RESTful endpoints, OpenAPI documentation, and WebSockets for real-time AWS anomaly detection,
quality control, and long-term sensor health monitoring.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import settings
from backend.app.api.router import router as api_router
from backend.app.api.health_router import router as sensor_health_router

app = FastAPI(
    title="SkyGuard AI — AWS Anomaly Detection & Quality Framework",
    description=(
        "Production-grade software framework for detecting, validating, explaining, "
        "and monitoring anomalies in Automatic Weather Station (AWS) observations.\n\n"
        "### Key Principles:\n"
        "- **Does NOT assume every unusual observation is a sensor fault.**\n"
        "- Distinguishes between: `NORMAL`, `LIKELY_GENUINE_WEATHER_EVENT`, "
        "`LIKELY_SENSOR_DATA_FAULT`, and `UNCERTAIN`.\n"
        "- Combines WMO QC, Isolation Forest, TensorFlow/Keras LSTM Autoencoder, "
        "Magnus Thermodynamics, Spatial Buddy Cross-Validation, and Sensor Historical Health."
    ),
    version="1.0.0",
    root_path="/api",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount primary API router at root level
app.include_router(api_router)
# Also include prefixed sensor health router for backwards compatibility
app.include_router(sensor_health_router)


@app.get("/")
def root():
    return {
        "system": "SkyGuard AI",
        "station_id": settings.DEFAULT_STATION_ID,
        "station_name": settings.DEFAULT_STATION_NAME,
        "status": "OPERATIONAL",
        "documentation": "/api/docs",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8000, reload=True)
