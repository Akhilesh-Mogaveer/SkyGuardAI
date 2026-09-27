import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  Gauge,
  ShieldCheck,
  Thermometer,
  Droplets,
  Wrench,
  Activity,
} from 'lucide-react';
import {
  formatClassification,
  getClassification,
  getEvidenceConfidence,
  getMaintenanceStatus,
  getPressure,
  getRecoveryMeta,
  getRecoveryMethod,
  getRootCause,
  getSeverity,
  getTemperature,
  getHumidity,
  getSensorHealthScore,
  getObservedValueForParameter,
} from '../utils/observation';

function firstValue(...values) {
  return values.find((value) => value !== undefined && value !== null && value !== '');
}

function formatNumber(value, digits = 3) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : '—';
}

function formatTime(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function severityTone(severity) {
  const value = String(severity || '').toUpperCase();
  if (value === 'CRITICAL') return 'bg-red-950/70 text-red-300 border-red-500/40 font-bold';
  if (value === 'HIGH') return 'bg-orange-950/70 text-orange-300 border-orange-500/40 font-bold';
  if (value === 'MEDIUM') return 'bg-amber-950/70 text-amber-300 border-amber-500/40 font-semibold';
  if (value === 'LOW') return 'bg-slate-900 text-slate-300 border-slate-700 font-medium';
  return 'bg-emerald-950/70 text-emerald-300 border-emerald-500/40 font-medium';
}

function assessmentTone(classification) {
  const value = String(classification || '').toUpperCase();
  if (value === 'LIKELY_SENSOR_DATA_FAULT') return 'text-red-400';
  if (value === 'LIKELY_GENUINE_WEATHER_EVENT') return 'text-cyan-400';
  if (value === 'UNCERTAIN') return 'text-amber-400';
  return 'text-emerald-400';
}

function Metric({ icon: Icon, label, value, unit }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 backdrop-blur-md p-4 shadow-sm">
      <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-slate-400">
        <Icon className="h-4 w-4 text-cyan-400" />
        {label}
      </div>
      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-2xl font-extrabold tracking-tight text-white">{value ?? '—'}</span>
        {unit && <span className="text-xs font-semibold text-slate-400">{unit}</span>}
      </div>
    </div>
  );
}

function EvidenceRow({ label, active, detail }) {
  return (
    <div className="flex items-center justify-between border-b border-slate-800/60 py-2.5 last:border-0">
      <div>
        <div className="text-sm font-semibold text-slate-200">{label}</div>
        {detail && <div className="mt-0.5 text-[11px] text-slate-400">{detail}</div>}
      </div>
      {active ? (
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-red-400 bg-red-950/40 border border-red-500/30 px-2 py-0.5 rounded">
          <CircleAlert className="h-3.5 w-3.5" /> Flagged
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-400 bg-emerald-950/40 border border-emerald-500/30 px-2 py-0.5 rounded">
          <CheckCircle2 className="h-3.5 w-3.5" /> Clear
        </span>
      )}
    </div>
  );
}

export default function Dashboard({ statistics, sensorHealth, stations = [], observations = [], onNavigateTab }) {
  const [showTechnical, setShowTechnical] = useState(false);

  const latest = observations?.[0] || null;
  const latestClassification = getClassification(latest || {});
  const latestSeverity = getSeverity(latest || {});
  const latestRecovery = getRecoveryMeta(latest || {});
  const latestEstimated = latestRecovery.estimatedValue;
  const latestTemperature = getTemperature(latest || {});
  const latestPressure = getPressure(latest || {});
  const latestHumidity = getHumidity(latest || {});
  const latestConfidence = getEvidenceConfidence(latest || {});
  const latestRootCause = getRootCause(latest || {});
  const latestMaintenance = getMaintenanceStatus(latest || {});
  const recoveryMethod = getRecoveryMethod(latest || {});

  const decision = latest?.decision || {};
  const detectors = latest?.detectors || {};
  const qc = detectors.qc || {};
  const isolationForest = detectors.isolation_forest || {};
  const lstm = detectors.lstm || {};
  const physical = detectors.physical_consistency || {};
  const spatial = detectors.spatial_validation || {};
  const qcFlag = qc.status === 'FLAGGED' || qc.qc_flag === 'SUSPECT';
  const ifScore = firstValue(latest?.iforest_score, latest?.IFOREST_SCORE);
  const lstmMse = firstValue(latest?.lstm_mse, latest?.LSTM_MSE);
  const ifFlag = isolationForest.status === 'FLAGGED';
  const lstmFlag = lstm.status === 'FLAGGED';
  const physicalScore = Number(physical.score ?? 0);
  const physicalFlag = physical.status === 'FLAGGED';
  const spatialScore = Number(spatial.evidence_score ?? 0);
  const spatialAvailable = spatial.status !== 'UNAVAILABLE';
  const evidenceCount = Number(latest?.evidence_count ?? latest?.assessment?.evidence_count ?? 0);
  const evidenceTotal = Number(latest?.evidence_total ?? latest?.assessment?.evidence_total ?? 0);
  const decisionConfidence = firstValue(
    latest?.calibrated_confidence,
    latest?.CALIBRATED_CONFIDENCE,
    decision?.calibrated_confidence,
  );
  const evidenceAgreement = evidenceTotal > 0 ? (evidenceCount / evidenceTotal) * 100 : 0;

  const stationName = firstValue(
    latest?.station_name,
    latest?.station,
    latest?.station_id && stations.find((s) => s.station_id === latest.station_id)?.name,
    stations[0]?.name,
    'AWS Station',
  );

  const trend = useMemo(() => observations.slice(0, 24).reverse(), [observations]);
  const tempMin = trend.length ? Math.min(...trend.map((o) => Number(getTemperature(o))).filter(Number.isFinite)) : null;
  const tempMax = trend.length ? Math.max(...trend.map((o) => Number(getTemperature(o))).filter(Number.isFinite)) : null;

  const isAnomaly = latestClassification !== 'NORMAL';
  const healthValue = getSensorHealthScore(sensorHealth);

  return (
    <div className="space-y-6">
      {/* Identity / Station Status */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/80 backdrop-blur-md px-6 py-5 shadow-lg">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-cyan-950/80 border border-cyan-500/30 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wider text-cyan-300">
                Automatic Weather Station
              </span>
              <span className="text-xs text-slate-400 font-medium">Real-Time Operational Observation Engine</span>
            </div>
            <h2 className="mt-2 text-2xl font-extrabold tracking-tight text-white">{stationName}</h2>
            <p className="mt-1 max-w-2xl text-xs text-slate-400 leading-relaxed">
              SkyGuard continuously evaluates AWS observations, combines multi-pillar evidence, and derives real-time maintenance decisions.
            </p>
          </div>
          <div
            className={`inline-flex shrink-0 items-center gap-3 rounded-xl border px-4 py-3 shadow-md ${
              isAnomaly ? 'border-red-500/40 bg-red-950/50' : 'border-emerald-500/40 bg-emerald-950/50'
            }`}
          >
            {isAnomaly ? <AlertTriangle className="h-6 w-6 text-red-400" /> : <ShieldCheck className="h-6 w-6 text-emerald-400" />}
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Observation Status</div>
              <div className={`text-sm font-extrabold ${isAnomaly ? 'text-red-300' : 'text-emerald-300'}`}>
                {formatClassification(latestClassification)}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Current Observations */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 backdrop-blur-md p-5 shadow-md">
        <div className="flex flex-col gap-1 border-b border-slate-800 pb-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-400">1 · Incoming Telemetry</div>
            <h3 className="mt-1 text-lg font-bold text-white">Current Station Measurements</h3>
          </div>
          <div className="inline-flex items-center gap-1.5 text-xs text-slate-400">
            <Clock3 className="h-3.5 w-3.5 text-cyan-400" /> {formatTime(latest?.timestamp || latest?.TIMESTAMP)}
          </div>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <Metric icon={Thermometer} label="Temperature" value={latestTemperature} unit="°C" />
          <Metric icon={Gauge} label="Pressure" value={latestPressure} unit="hPa" />
          <Metric icon={Droplets} label="Relative Humidity" value={latestHumidity} unit="%" />
        </div>
      </section>

      {/* Decision Engine Assessment */}
      <section
        className={`rounded-xl border bg-slate-900/80 backdrop-blur-md shadow-lg ${
          isAnomaly ? 'border-red-500/40' : 'border-slate-800'
        }`}
      >
        <div className="flex flex-col gap-3 border-b border-slate-800 px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-400">2 · SkyGuard Decision Engine</div>
            <h3 className={`mt-1 text-xl font-extrabold ${assessmentTone(latestClassification)}`}>
              {formatClassification(latestClassification)}
            </h3>
          </div>
          <span className={`w-fit rounded-md border px-3 py-1 text-[10px] uppercase tracking-wider ${severityTone(latestSeverity)}`}>
            {latestSeverity}
          </span>
        </div>

        <div className="grid lg:grid-cols-[1.2fr_0.8fr]">
          <div className="p-6 space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Evidence Agreement</div>
                <div className="mt-2 text-2xl font-extrabold text-white">
                  {evidenceCount} / {evidenceTotal || '—'}
                </div>
                <div className="mt-1 text-xs text-cyan-400 font-medium">{evidenceAgreement.toFixed(0)}% Detector Concordance</div>
              </div>
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Decision Confidence</div>
                <div className="mt-2 text-2xl font-extrabold text-white">
                  {decisionConfidence != null
                    ? `${(Number(decisionConfidence) <= 1 ? Number(decisionConfidence) * 100 : Number(decisionConfidence)).toFixed(0)}%`
                    : 'Not calibrated'}
                </div>
                <div className="mt-1 text-xs text-slate-400">Calibrated decision Engine output</div>
              </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-5 space-y-3">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Primary Root Cause / Attribution</div>
              <div className="text-sm font-extrabold text-cyan-300">{latestRootCause}</div>
              <p className="text-xs leading-relaxed text-slate-400">
                SkyGuard synthesizes WMO quality control, Isolation Forest, LSTM autoencoders, thermodynamics, and spatial validation before producing the final classification.
              </p>
              <div className="grid gap-3 sm:grid-cols-3 pt-2">
                <div className="rounded-lg bg-slate-900 border border-slate-800 p-3">
                  <div className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Severity</div>
                  <div className="mt-1 text-sm font-extrabold text-white">{latestSeverity}</div>
                </div>
                <div className="rounded-lg bg-slate-900 border border-slate-800 p-3">
                  <div className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Primary Cause</div>
                  <div className="mt-1 text-sm font-extrabold text-slate-200 truncate">{latestRootCause}</div>
                </div>
                <div className="rounded-lg bg-slate-900 border border-slate-800 p-3">
                  <div className="text-[9px] font-bold uppercase tracking-wider text-slate-400">Action Status</div>
                  <div className="mt-1 text-sm font-extrabold text-amber-300">{latestMaintenance}</div>
                </div>
              </div>
            </div>
          </div>

          <div className="border-t border-slate-800 p-6 lg:border-l lg:border-t-0 bg-slate-950/30">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mb-3">Pillar Detector Evidence</div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/90 px-4 py-1">
              <EvidenceRow
                label="Rule-based Quality Control"
                active={qcFlag}
                detail={`QC: ${qc.qc_flag || 'PASSED'} · spike ${[qc.temperature_spike, qc.pressure_spike, qc.humidity_spike].filter(Boolean).length} · flatline ${[qc.temperature_flatline, qc.pressure_flatline, qc.humidity_flatline].filter(Boolean).length}`}
              />
              <EvidenceRow
                label="Isolation Forest (ML)"
                active={ifFlag}
                detail={`Score: ${formatNumber(ifScore, 4)} · ${ifFlag ? 'Anomaly' : 'Normal'}`}
              />
              <EvidenceRow
                label="LSTM Autoencoder (DL)"
                active={lstmFlag}
                detail={`MSE: ${formatNumber(lstmMse, 4)} · ${lstmFlag ? 'Anomaly' : 'Normal'}`}
              />
              <EvidenceRow
                label="Physical Consistency"
                active={physicalFlag}
                detail={`Score: ${formatNumber(physicalScore, 3)} · ${physicalFlag ? 'Violation' : 'Within Limits'}`}
              />
              <EvidenceRow
                label="Spatial Companion Check"
                active={spatialAvailable && spatialScore < 0}
                detail={spatialAvailable ? `Score: ${formatNumber(spatialScore, 3)}` : 'Single-station context'}
              />
            </div>
          </div>
        </div>
      </section>

      {/* Data Recovery / Estimation */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/80 backdrop-blur-md p-6 shadow-md">
        <div className="flex items-center justify-between gap-3 border-b border-slate-800 pb-4">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-400">3 · Data Recovery & Imputation</div>
            <h3 className="mt-1 text-lg font-bold text-white">Preserve Raw Values, Estimate Clean Signals</h3>
          </div>
          <Wrench className="h-5 w-5 text-cyan-400" />
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-3">
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
              Observed {latestRecovery.parameter === 'pressure' ? 'Pressure' : latestRecovery.parameter === 'humidity' ? 'Humidity' : 'Temperature'}
            </div>
            <div className="mt-2 text-2xl font-extrabold text-white">
              {getObservedValueForParameter(latest || {}, latestRecovery.parameter) != null
                ? `${getObservedValueForParameter(latest || {}, latestRecovery.parameter)} ${latestRecovery.unit}`
                : '—'}
            </div>
          </div>
          <div className="rounded-xl border border-cyan-500/30 bg-cyan-950/30 p-4 shadow-[0_0_15px_rgba(6,182,212,0.1)]">
            <div className="text-[10px] font-bold uppercase tracking-wider text-cyan-300">{latestRecovery.label}</div>
            <div className="mt-2 text-2xl font-extrabold text-cyan-200">
              {latestEstimated != null ? `${latestEstimated.toFixed(1)} ${latestRecovery.unit}` : '—'}
            </div>
            <div className="mt-1 text-[11px] text-slate-400 font-medium">{recoveryMethod || 'Temporal neighbor estimation'}</div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Data Integrity Policy</div>
            <div className="mt-2 text-sm font-bold text-emerald-400">Raw Value Preserved</div>
            <div className="mt-1 text-[11px] text-slate-400">Estimated values are stored in parallel fields.</div>
          </div>
        </div>
      </section>

      {/* Sensor Health & Maintenance Action */}
      <section className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/80 backdrop-blur-md p-6 shadow-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-400">4 · Long-Term Sensor Health</div>
          <div className="mt-3 flex items-end justify-between gap-4">
            <div>
              <div className="text-3xl font-extrabold text-white">
                {healthValue != null ? `${Number(healthValue).toFixed(1)}%` : '—'}
              </div>
              <div className="mt-1 text-xs text-slate-400">Station Reliability Index</div>
            </div>
            <Gauge className="h-8 w-8 text-cyan-400" />
          </div>
          <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-slate-950 border border-slate-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-300"
              style={{ width: `${Math.max(0, Math.min(100, Number(healthValue) || 0))}%` }}
            />
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/80 backdrop-blur-md p-6 shadow-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-400">5 · Maintenance Action</div>
          <div className="mt-3 flex items-start gap-3">
            {latestMaintenance !== 'Normal' ? (
              <AlertTriangle className="mt-0.5 h-6 w-6 text-amber-400 shrink-0" />
            ) : (
              <CheckCircle2 className="mt-0.5 h-6 w-6 text-emerald-400 shrink-0" />
            )}
            <div>
              <div className="text-base font-extrabold text-white">{latestMaintenance}</div>
              <div className="mt-1 text-xs leading-relaxed text-slate-400">
                Action generated automatically from multi-pillar concordance and evidence confidence.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Recent Sequence Sparkline */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/80 backdrop-blur-md p-6 shadow-md">
        <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between border-b border-slate-800 pb-3">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-400">Recent Sequence Trace</div>
            <h3 className="mt-1 text-lg font-bold text-white">24-Hour Temperature Sequence</h3>
          </div>
          <div className="text-xs text-slate-400 font-medium">Last {trend.length || 0} observations</div>
        </div>
        <div className="mt-4 overflow-x-auto">
          <div className="flex min-w-[720px] items-end gap-1.5 border-b border-slate-800/80 pb-3" style={{ height: 140 }}>
            {trend.map((obs, index) => {
              const value = Number(getTemperature(obs));
              const ratio = Number.isFinite(value) && tempMin !== tempMax ? (value - tempMin) / (tempMax - tempMin) : 0.5;
              const flagged = getClassification(obs) !== 'NORMAL';
              return (
                <div key={`${obs.timestamp || obs.TIMESTAMP || index}-${index}`} className="flex h-full flex-1 min-w-[18px] flex-col justify-end">
                  <div
                    title={`${formatTime(obs.timestamp || obs.TIMESTAMP)} · ${Number.isFinite(value) ? `${value}°C` : '—'}`}
                    className={`w-full rounded-t transition-all ${flagged ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]' : 'bg-cyan-500'}`}
                    style={{ height: `${Math.max(8, 18 + ratio * 95)}px` }}
                  />
                </div>
              );
            })}
          </div>
        </div>
        <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400">
          <span>{trend[0] ? formatTime(trend[0].timestamp || trend[0].TIMESTAMP) : '—'}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-red-500" /> Flagged anomaly</span>
          <span>{trend[trend.length - 1] ? formatTime(trend[trend.length - 1].timestamp || trend[trend.length - 1].TIMESTAMP) : '—'}</span>
        </div>
      </section>

      {/* Technical Evidence Expansion */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden shadow-sm">
        <button
          onClick={() => setShowTechnical((v) => !v)}
          className="flex w-full items-center justify-between px-6 py-4 text-left hover:bg-slate-800/50 transition"
        >
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wider text-cyan-400">Technical Details</div>
            <div className="mt-0.5 text-sm font-bold text-white">Pipeline Architecture & Evidence Flow</div>
          </div>
          {showTechnical ? <ChevronDown className="h-5 w-5 text-slate-400" /> : <ChevronRight className="h-5 w-5 text-slate-400" />}
        </button>
        {showTechnical && (
          <div className="border-t border-slate-800 px-6 py-4 bg-slate-950/40">
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 text-xs text-slate-300">
                <div className="font-bold text-cyan-300">Pipeline Pipeline Flow</div>
                <div className="mt-2 leading-relaxed text-slate-400">
                  Input → Baseline QC → Isolation Forest → LSTM Autoencoder → Physical Consistency → Evidence Fusion → Recovery → Sensor Health
                </div>
              </div>
              <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 text-xs text-slate-300">
                <div className="font-bold text-cyan-300">Spatial Validation</div>
                <div className="mt-2 leading-relaxed text-slate-400">
                  Executed dynamically when neighboring station observations are available. Single-station data is preserved without false spatial claims.
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      <div className="flex flex-wrap gap-3 text-xs pt-2">
        <button
          onClick={() => onNavigateTab?.('stations')}
          className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 font-semibold text-slate-200 hover:border-cyan-500/50 hover:text-cyan-300 transition shadow-sm"
        >
          View Station Details
        </button>
        <button
          onClick={() => onNavigateTab?.('alerts')}
          className="rounded-lg border border-slate-700 bg-slate-900 px-4 py-2.5 font-semibold text-slate-200 hover:border-cyan-500/50 hover:text-cyan-300 transition shadow-sm"
        >
          Open Alert Work Queue
        </button>
        <button
          onClick={() => onNavigateTab?.('data-replay')}
          className="rounded-lg bg-cyan-600 hover:bg-cyan-500 text-slate-950 px-4 py-2.5 font-extrabold transition shadow-lg shadow-cyan-950/50"
        >
          Run Data Replay
        </button>
      </div>
    </div>
  );
}
