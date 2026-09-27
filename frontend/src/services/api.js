/**
 * API Client Service for SkyGuard AI FastAPI Backend
 */

// const API_BASE = 'http://127.0.0.1:8000';
const API_BASE = '/api';

export async function fetchHealth() {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

export async function fetchStations() {
  const res = await fetch(`${API_BASE}/stations`);
  return res.json();
}

export async function fetchStationDetails(stationId) {
  const res = await fetch(`${API_BASE}/stations/${stationId}`);
  return res.json();
}

export async function fetchSensorHealth(stationId = 'AWS-MAITRI-89514', parameter = '') {
  const url = parameter 
    ? `${API_BASE}/sensor-health?station_id=${stationId}&parameter=${parameter}`
    : `${API_BASE}/sensor-health?station_id=${stationId}`;
  const res = await fetch(url);
  return res.json();
}

export async function fetchObservations(limit = 2000, classification = '') {
  const url = classification
    ? `${API_BASE}/observations?limit=${limit}&classification=${classification}`
    : `${API_BASE}/observations?limit=${limit}`;
  const res = await fetch(url);
  const data = await res.json();
  if (Array.isArray(data)) return data;
  return data?.observations || [];
}

export async function fetchAnomalies(limit = 2000, severity = '', classification = '') {
  let url = `${API_BASE}/anomalies?limit=${limit}`;
  if (severity) url += `&severity=${severity}`;
  if (classification) url += `&classification=${classification}`;
  const res = await fetch(url);
  const data = await res.json();
  if (Array.isArray(data)) return data;
  return data?.anomalies || [];
}

export async function fetchAlertsPage({ page = 1, pageSize = 10, severity = '', classification = '', stationId = '', parameter = '', timeRange = '' } = {}) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (severity && severity !== 'ALL') params.set('severity', severity);
  if (classification && classification !== 'ALL') params.set('classification', classification);
  if (stationId && stationId !== 'ALL') params.set('station_id', stationId);
  if (parameter && parameter !== 'ALL') params.set('parameter', parameter.toLowerCase().replace('relative humidity', 'humidity'));
  if (timeRange && timeRange !== 'ALL') params.set('time_range', timeRange);
  const res = await fetch(`${API_BASE}/alerts?${params.toString()}`);
  if (!res.ok) throw new Error(`Failed to load alerts (${res.status})`);
  return res.json();
}

export async function fetchAlertDetails(alertId) {
  const res = await fetch(`${API_BASE}/alerts/${alertId}`);
  if (!res.ok) throw new Error(`Failed to load alert details (${res.status})`);
  return res.json();
}

export async function fetchStatistics() {
  const res = await fetch(`${API_BASE}/statistics`);
  return res.json();
}

export async function processObservation(payload) {
  const res = await fetch(`${API_BASE}/process-observation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function startReplay(speedMultiplier = 10, startIndex = 0) {
  const res = await fetch(`${API_BASE}/replay/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ speed_multiplier: speedMultiplier, start_index: startIndex }),
  });
  return res.json();
}

export async function stopReplay() {
  const res = await fetch(`${API_BASE}/replay/stop`, {
    method: 'POST',
  });
  return res.json();
}

export async function fetchReplayStatus() {
  const res = await fetch(`${API_BASE}/replay/status`);
  return res.json();
}

export async function fetchDemoPresets() {
  const res = await fetch(`${API_BASE}/demo/preset-cases`);
  return res.json();
}

export async function evaluateDemoStep(timestamp, prewarmHours = 48, observation = null) {
  const body = { timestamp, prewarm_hours: prewarmHours };
  if (observation) Object.assign(body, observation);
  const res = await fetch(`${API_BASE}/demo/evaluate-step`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

