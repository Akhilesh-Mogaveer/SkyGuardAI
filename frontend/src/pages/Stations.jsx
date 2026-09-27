import React, { useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { Radio, ChevronDown, ChevronUp, Activity, AlertTriangle } from 'lucide-react';
import AwsNetworkMap from '../components/AwsNetworkMap';
import {
  getClassification,
  getDecision,
  getEvidenceConfidence,
  getRecoveryMeta,
  getRecoveryMethod,
  getHumidity,
  getMaintenanceStatus,
  getPressure,
  getRootCause,
  getSeverity,
  getTemperature,
  getSensorHealthScore,
  formatClassification,
  getObservedValueForParameter,
} from '../utils/observation';

export default function Stations({ observations = [], sensorHealth, stations = [] }) {
  const [selectedParameter, setSelectedParameter] = useState('temperature');
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

  const activeObs = Array.isArray(observations) ? observations : [];
  const latestObs = activeObs[0] || null;
  const latestDecision = getDecision(latestObs || {});
  const latestConfidence = getEvidenceConfidence(latestObs || {});
  const latestClassification = getClassification(latestObs || {});
  const latestSeverity = getSeverity(latestObs || {});
  const latestRootCause = getRootCause(latestObs || {});
  const latestMaintenance = getMaintenanceStatus(latestObs || {});
  const latestRecovery = getRecoveryMeta(latestObs || {});
  const latestEstimatedTemperature = latestRecovery.estimatedValue;
  const latestRecoveryMethod = getRecoveryMethod(latestObs || {});

  const station = stations[0] || {};
  const stationName = station.name || station.station_name || station.station_id || 'AWS station';
  const stationId = station.station_id || station.id || '—';
  const stationLocation = station.location || station.coordinates || (Number.isFinite(Number(station.latitude)) && Number.isFinite(Number(station.longitude)) ? `${Number(station.latitude).toFixed(3)}°, ${Number(station.longitude).toFixed(3)}°` : 'Location not provided by backend');
  const healthValue = getSensorHealthScore(sensorHealth);

  const chartData = activeObs.slice(0, 50).reverse().map((obs) => ({
    timestamp: obs.timestamp ? String(obs.timestamp).split(' ')[1] || obs.timestamp : '—',
    temperature: getTemperature(obs),
    pressure: getPressure(obs),
    humidity: getHumidity(obs),
  }));

  const parameterConfig = {
    temperature: { label: 'Temperature', unit: '°C', value: getTemperature(latestObs || {}) },
    pressure: { label: 'Pressure', unit: 'hPa', value: getPressure(latestObs || {}) },
    humidity: { label: 'Humidity', unit: '%', value: getHumidity(latestObs || {}) },
  };
  const selected = parameterConfig[selectedParameter];

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold text-slate-100">Stations</h2>
        <p className="text-xs text-slate-400 mt-0.5">Current observations, sensor health and latest operational assessment.</p>
      </div>

      <div className="bg-[#090e1a]/80 border border-slate-800 rounded-xl p-4 shadow-md flex flex-col md:flex-row md:items-center justify-between gap-3 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <Radio className="w-5 h-5 text-emerald-400" />
          <div>
            <h3 className="font-bold text-slate-100">{stationName}</h3>
            <p className="text-xs text-slate-400">ID: <span className="font-mono text-cyan-300">{stationId}</span></p>
            <p className="text-xs text-slate-400">{stationLocation}</p>
          </div>
        </div>
        <div className="text-xs text-right">
          <div className="text-slate-400">Sensor Health</div>
          <div className="text-lg font-bold text-slate-100">
            {healthValue !== undefined && healthValue !== null ? `${Number(healthValue).toFixed(1)}%` : '—'}
          </div>
        </div>
      </div>

      {!latestObs ? (
        <div className="bg-[#090e1a]/80 border border-slate-800 rounded-xl p-10 text-center text-sm text-slate-400 shadow-md backdrop-blur-md">
          No observations received yet. Start the backend or Data Replay to populate this station view.
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {Object.entries(parameterConfig).map(([key, cfg]) => (
              <div key={key} className="bg-[#090e1a]/80 border border-slate-800 rounded-xl p-4 shadow-md backdrop-blur-md">
                <div className="text-[11px] uppercase tracking-wide text-slate-400">{cfg.label}</div>
                <div className="text-2xl font-bold text-cyan-300 mt-1 font-mono">
                  {cfg.value !== null && cfg.value !== undefined ? `${cfg.value} ${cfg.unit}` : '—'}
                </div>
              </div>
            ))}
          </div>

          <div className="bg-[#090e1a]/80 border border-slate-800 rounded-xl p-5 shadow-md space-y-4 backdrop-blur-md">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div>
                <h3 className="font-bold text-slate-100">Latest Assessment</h3>
                <p className="text-xs text-slate-400">{latestObs.timestamp || 'Timestamp not provided'}</p>
              </div>
              <span className={`px-2.5 py-1 rounded-md border text-xs font-bold ${
                latestSeverity === 'CRITICAL' ? 'bg-red-950/80 text-red-300 border-red-500/40' :
                latestSeverity === 'HIGH' ? 'bg-orange-950/80 text-orange-300 border-orange-500/40' :
                latestSeverity === 'MEDIUM' ? 'bg-amber-950/80 text-amber-300 border-amber-500/40' :
                'bg-emerald-950/80 text-emerald-300 border-emerald-500/40'
              }`}>
                {latestSeverity}
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
                <div className="text-[10px] uppercase text-slate-400">Observation Status</div>
                <div className="font-bold text-slate-100 mt-1">{formatClassification(latestClassification)}</div>
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
                <div className="text-[10px] uppercase text-slate-400">Evidence Confidence</div>
                <div className="font-bold text-slate-100 mt-1">{latestConfidence !== null ? `${latestConfidence.toFixed(1)}%` : '—'}</div>
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
                <div className="text-[10px] uppercase text-slate-400">Root Cause</div>
                <div className="font-bold text-slate-100 mt-1">{latestRootCause}</div>
              </div>
              <div className="bg-cyan-950/40 border border-cyan-500/30 rounded-lg p-3">
                <div className="text-[10px] uppercase text-cyan-400">{latestRecovery.label}</div>
                <div className="font-bold text-cyan-200 mt-1">{latestEstimatedTemperature !== null ? `${latestEstimatedTemperature.toFixed(1)} ${latestRecovery.unit}` : '—'}</div>
                <div className="text-[10px] text-slate-400 mt-1">Raw value is preserved</div>
              </div>
              <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
                <div className="text-[10px] uppercase text-slate-400">Maintenance</div>
                <div className="font-bold text-slate-100 mt-1">{latestMaintenance}</div>
              </div>
            </div>

            {latestDecision.recommended_operator_action && (
              <div className="bg-amber-950/30 border border-amber-500/40 rounded-lg p-3 text-sm text-slate-200">
                <span className="font-semibold text-amber-300">Recommended action: </span>
                {latestDecision.recommended_operator_action}
              </div>
            )}

            {latestEstimatedTemperature !== null && (
              <div className="bg-cyan-950/30 border border-cyan-500/30 rounded-lg p-3 text-xs text-cyan-200">
                <span className="font-semibold text-cyan-300">Recovery estimate: </span>
                {latestEstimatedTemperature.toFixed(1)} {latestRecovery.unit}
                {latestRecoveryMethod ? ` (${latestRecoveryMethod})` : ''}. This is an estimate for quality recovery; the original observation is not overwritten.
              </div>
            )}
          </div>

          <div className="bg-[#090e1a]/80 border border-slate-800 rounded-xl p-5 shadow-md space-y-4 backdrop-blur-md">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <h3 className="font-bold text-slate-100">Recent Observations</h3>
                <p className="text-xs text-slate-400">Values received from the backend stream.</p>
              </div>
              <div className="flex gap-1">
                {Object.keys(parameterConfig).map((key) => (
                  <button
                    key={key}
                    onClick={() => setSelectedParameter(key)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-semibold transition ${
                      selectedParameter === key ? 'bg-cyan-600 text-white shadow-sm' : 'bg-slate-900 text-slate-400 border border-slate-700 hover:text-slate-200'
                    }`}
                  >
                    {parameterConfig[key].label}
                  </button>
                ))}
              </div>
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="timestamp" tick={{ fontSize: 10, fill: '#64748b' }} stroke="#334155" />
                  <YAxis tick={{ fontSize: 10, fill: '#64748b' }} stroke="#334155" />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#090e1a', borderColor: '#334155', color: '#f8fafc', borderRadius: '8px' }}
                  />
                  <Line type="monotone" dataKey={selectedParameter} stroke="#38bdf8" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <AwsNetworkMap />

          <div className="bg-[#090e1a]/80 border border-slate-800 rounded-xl shadow-md overflow-hidden backdrop-blur-md">
            <button
              onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
              className="w-full px-4 py-3 flex items-center justify-between text-sm font-semibold text-slate-200 hover:bg-slate-900/60"
            >
              <span className="flex items-center gap-2"><Activity className="w-4 h-4 text-cyan-400" /> Technical Details</span>
              {showTechnicalDetails ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
            {showTechnicalDetails && (
              <div className="border-t border-slate-800 p-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs bg-slate-900/60">
                <div><span className="text-slate-400 block">QC</span><b className="text-slate-200 font-mono">{String(latestObs.qc_flag ?? latestObs.QC_FLAG ?? latestDecision.qc_flag ?? '—')}</b></div>
                <div><span className="text-slate-400 block">Isolation Forest</span><b className="text-slate-200 font-mono">{String(latestObs.if_anomaly ?? latestObs.IF_ANOMALY ?? latestDecision.if_anomaly ?? '—')}</b></div>
                <div><span className="text-slate-400 block">LSTM</span><b className="text-slate-200 font-mono">{String(latestObs.lstm_anomaly ?? latestObs.LSTM_ANOMALY ?? latestDecision.lstm_anomaly ?? '—')}</b></div>
                <div><span className="text-slate-400 block">Evidence Count</span><b className="text-slate-200 font-mono">{latestObs.evidence_count ?? latestObs.EVIDENCE_COUNT ?? latestDecision.evidence_count ?? '—'}</b></div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
