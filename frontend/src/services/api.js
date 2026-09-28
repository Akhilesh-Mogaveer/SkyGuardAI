/**
 * SkyGuard AI
 * API Client Service
 * FastAPI Backend
 */

// ============================================================
// BACKEND URL
// ============================================================

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  'https://skyguard-backend-kmko.onrender.com';


// ============================================================
// HELPER FUNCTIONS
// ============================================================

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body
        ? {
            'Content-Type': 'application/json',
          }
        : {}),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let message = `Request failed: ${response.status} ${response.statusText}`;

    try {
      const errorData = await response.json();

      if (errorData?.detail) {
        message = errorData.detail;
      } else if (errorData?.message) {
        message = errorData.message;
      }
    } catch {
      // Ignore JSON parsing error
    }

    throw new Error(message);
  }

  // Some endpoints may return empty response
  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get('content-type') || '';

  if (contentType.includes('application/json')) {
    return response.json();
  }

  return response.text();
}


// ============================================================
// HEALTH
// ============================================================

export async function fetchHealth() {
  return request(`${API_BASE}/health`);
}


// ============================================================
// STATIONS
// ============================================================

export async function fetchStations() {
  const data = await request(`${API_BASE}/stations`);

  if (Array.isArray(data)) {
    return data;
  }

  return data?.stations || [];
}


export async function fetchStationDetails(stationId) {
  if (!stationId) {
    throw new Error('stationId is required');
  }

  return request(
    `${API_BASE}/stations/${encodeURIComponent(stationId)}`
  );
}


// ============================================================
// SENSOR HEALTH
// ============================================================

export async function fetchSensorHealth(
  stationId = 'AWS-MAITRI-89514',
  parameter = ''
) {
  const params = new URLSearchParams();

  if (stationId) {
    params.set('station_id', stationId);
  }

  if (parameter) {
    params.set('parameter', parameter);
  }

  const query = params.toString();

  return request(
    `${API_BASE}/sensor-health${query ? `?${query}` : ''}`
  );
}


// ============================================================
// OBSERVATIONS
// ============================================================

export async function fetchObservations(
  limit = 2000,
  classification = ''
) {
  const params = new URLSearchParams();

  params.set('limit', String(limit));

  if (classification && classification !== 'ALL') {
    params.set('classification', classification);
  }

  const data = await request(
    `${API_BASE}/observations?${params.toString()}`
  );

  if (Array.isArray(data)) {
    return data;
  }

  return data?.observations || [];
}


// ============================================================
// ANOMALIES
// ============================================================

export async function fetchAnomalies(
  limit = 2000,
  severity = '',
  classification = ''
) {
  const params = new URLSearchParams();

  params.set('limit', String(limit));

  if (severity && severity !== 'ALL') {
    params.set('severity', severity);
  }

  if (classification && classification !== 'ALL') {
    params.set('classification', classification);
  }

  const data = await request(
    `${API_BASE}/anomalies?${params.toString()}`
  );

  if (Array.isArray(data)) {
    return data;
  }

  return data?.anomalies || [];
}


// ============================================================
// ALERTS
// ============================================================

export async function fetchAlertsPage({
  page = 1,
  pageSize = 10,
  severity = '',
  classification = '',
  stationId = '',
  parameter = '',
  timeRange = '',
} = {}) {
  const params = new URLSearchParams();

  params.set('page', String(page));
  params.set('page_size', String(pageSize));

  if (severity && severity !== 'ALL') {
    params.set('severity', severity);
  }

  if (classification && classification !== 'ALL') {
    params.set('classification', classification);
  }

  if (stationId && stationId !== 'ALL') {
    params.set('station_id', stationId);
  }

  if (parameter && parameter !== 'ALL') {
    params.set(
      'parameter',
      parameter
        .toLowerCase()
        .replace('relative humidity', 'humidity')
    );
  }

  if (timeRange && timeRange !== 'ALL') {
    params.set('time_range', timeRange);
  }

  return request(
    `${API_BASE}/alerts?${params.toString()}`
  );
}


export async function fetchAlertDetails(alertId) {
  if (!alertId) {
    throw new Error('alertId is required');
  }

  return request(
    `${API_BASE}/alerts/${encodeURIComponent(alertId)}`
  );
}


// ============================================================
// STATISTICS
// ============================================================

export async function fetchStatistics() {
  return request(`${API_BASE}/statistics`);
}


// ============================================================
// PROCESS OBSERVATION
// ============================================================

export async function processObservation(payload) {
  if (!payload) {
    throw new Error('Observation payload is required');
  }

  return request(`${API_BASE}/process-observation`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}


// ============================================================
// REPLAY
// ============================================================

export async function startReplay(
  speedMultiplier = 10,
  startIndex = 0
) {
  const res = await fetch(`${API_BASE}/replay/start`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      speed_multiplier: Number(speedMultiplier),
      start_index: Number(startIndex),
    }),
  });

  const text = await res.text();

  let data;

  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }

  if (!res.ok) {
    throw new Error(
      data?.detail ||
      data?.message ||
      `Replay start failed (${res.status})`
    );
  }

  return data;
}


export async function stopReplay() {
  return request(`${API_BASE}/replay/stop`, {
    method: 'POST',
  });
}


export async function fetchReplayStatus() {
  return request(`${API_BASE}/replay/status`);
}


// ============================================================
// DEMO MODE
// ============================================================

export async function fetchDemoPresets() {
  return request(`${API_BASE}/demo/preset-cases`);
}


export async function evaluateDemoStep(
  timestamp,
  prewarmHours = 48,
  observation = null
) {
  if (!timestamp) {
    throw new Error('timestamp is required');
  }

  const body = {
    timestamp,
    prewarm_hours: Number(prewarmHours),
  };

  if (observation) {
    Object.assign(body, observation);
  }

  return request(`${API_BASE}/demo/evaluate-step`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}


// ============================================================
// CLEAR ANOMALIES / ALERTS
// ============================================================

export async function clearAnomalies() {
  return request(`${API_BASE}/anomalies/clear`, {
    method: 'POST',
  });
}


// ============================================================
// WEBSOCKET URL
// ============================================================

export function getWebSocketUrl() {
  const url = new URL(API_BASE);

  const protocol =
    url.protocol === 'https:' ? 'wss:' : 'ws:';

  return `${protocol}//${url.host}/ws/observations`;
}


// ============================================================
// EXPORT API BASE URL
// ============================================================

export { API_BASE };