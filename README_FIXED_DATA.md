# SkyGuard AI — fixed dashboard/data package

## Important data fix
The backend must replay `data/raw/imd_maitri_skyguard.csv`, not `data/raw/imd_maitri.csv`.

- `imd_maitri.csv` contains the full historical source beginning in 1985 and many early rows have `Relative Humidity = -999`.
- `imd_maitri_skyguard.csv` is the selected 2015–2016 high-completeness T/P/RH dataset used by the SkyGuard models.

This package already points `DEFAULT_RAW_CSV` to `imd_maitri_skyguard.csv`.

## Run backend
From this folder:

```powershell
python -m uvicorn backend.app.main:app --reload --port 8000
```

Keep that terminal running.

## Run frontend
In another terminal:

```powershell
cd frontend4
npm install
npm run dev
```

Open `http://localhost:3000`.

## Dashboard fixes
- Reads nested backend QC/IForest/LSTM/evidence fields.
- Shows actual detector test values when available.
- Reads sensor health from `overall_snapshot.overall_health_index`.
- Handles WebSocket payloads sent under `data`.
- Restores the India AWS network map on Stations.
- Map markers represent state/UT network totals from the source document, not exact station coordinates.
