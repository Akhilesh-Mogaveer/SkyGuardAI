# SkyGuard AI — Operator Architecture Frontend

This frontend redesign keeps the existing FastAPI/WebSocket/replay integration and reorganizes the UI around the SkyGuard workflow:

AWS Observation → Rule QC → AI Detection → Evidence Fusion → Operational Decision → Recovery → Sensor Health → Maintenance.

## Pages
- Dashboard: operational assessment first, with current T/P/RH, detector evidence, recovery estimate, sensor health, maintenance action, trend and expandable technical details.
- Stations: station-level operational view.
- Alerts: operator work queue.
- Data / Replay: historical data replay.
- Demo Mode: SIH demonstration scenarios.

## Run
```bash
npm install
npm run dev
```

Backend expected at `http://127.0.0.1:8000`.

The frontend does not hardcode the -20°C recovery value. It displays `ESTIMATED_TEMPERATURE` / `estimated_temperature` when the backend returns it.
