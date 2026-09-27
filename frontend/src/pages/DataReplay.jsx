import React, { useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { Play, Pause, Square, FastForward, Send, RefreshCw, AlertTriangle, ShieldCheck, ChevronDown, ChevronUp } from 'lucide-react';
import { startReplay, stopReplay, processObservation } from '../services/api';

function assessmentTone(classification) {
  const value = String(classification || '').toUpperCase();
  if (value === 'LIKELY_SENSOR_DATA_FAULT') return 'bg-red-950/80 text-red-300 border-red-500/40';
  if (value === 'LIKELY_GENUINE_WEATHER_EVENT') return 'bg-amber-950/80 text-amber-300 border-amber-500/40';
  if (value === 'UNCERTAIN') return 'bg-yellow-950/80 text-yellow-300 border-yellow-500/40';
  return 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40';
}

function severityTone(severity) {
  const value = String(severity || '').toUpperCase();
  if (value === 'CRITICAL') return 'bg-red-950/80 text-red-300 border-red-500/40';
  if (value === 'HIGH') return 'bg-orange-950/80 text-orange-300 border-orange-500/40';
  if (value === 'MEDIUM') return 'bg-amber-950/80 text-amber-300 border-amber-500/40';
  if (value === 'LOW') return 'bg-blue-950/80 text-blue-300 border-blue-500/40';
  return 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40';
}

function formatConfidence(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) return '—';
  const percentage = numericValue <= 1 ? numericValue * 100 : numericValue;
  return `${percentage.toFixed(1)}%`;
}

export default function DataReplay({ observations, replayStatus, onStartReplay, onStopReplay, onObservationProcessed }) {
  const [speed, setSpeed] = useState(10);
  const [dataset, setDataset] = useState('IMD_Maitri_Antarctic_2016.csv');
  const [isPaused, setIsPaused] = useState(false);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

  // Test form state for known 2016-09-09 17:00 observation
  const [testForm, setTestForm] = useState({
    timestamp: '2016-09-09 17:00',
    temperature: 41.6,
    pressure: 946.7,
    relative_humidity: 100.0,
  });
  const [backendInferenceResult, setBackendInferenceResult] = useState(null);
  const [isProcessing, setIsProcessing] = useState(false);

  const activeStream = Array.isArray(observations) ? observations : [];

  const handleStartReplay = async () => {
    setIsPaused(false);
    if (onStartReplay) {
      await onStartReplay(speed);
    } else {
      await startReplay(speed);
    }
  };

  const handlePauseReplay = async () => {
    setIsPaused(true);
    await stopReplay();
  };

  const handleStopReplay = async () => {
    setIsPaused(false);
    if (onStopReplay) {
      await onStopReplay();
    } else {
      await stopReplay();
    }
  };

  // Run actual backend pipeline inference for custom or preset observation
  const handleTestBackendInference = async (e) => {
    if (e) e.preventDefault();
    setIsProcessing(true);
    setBackendInferenceResult(null); // Clear previous inference result to prevent stale state leak
    try {
      const res = await processObservation({
        timestamp: testForm.timestamp,
        temperature: parseFloat(testForm.temperature),
        pressure: parseFloat(testForm.pressure),
        relative_humidity: parseFloat(testForm.relative_humidity),
      });
      setBackendInferenceResult(res);
      if (onObservationProcessed) {
        onObservationProcessed(res);
      }
    } catch (err) {
      console.error('Backend processObservation error:', err);
    } finally {
      setIsProcessing(false);
    }
  };

  const applyPresetForm = (ts, temp, press, hum) => {
    setTestForm({
      timestamp: ts,
      temperature: temp,
      pressure: press,
      relative_humidity: hum,
    });
    setBackendInferenceResult(null);
  };

  const chartData = activeStream.slice(-30).map((item) => {
    const dec = item.decision || {};
    const cls = dec.primary_classification || dec.classification || item.classification;
    return {
      timestamp: item.timestamp?.includes(' ') ? item.timestamp.split(' ')[1] : item.timestamp,
      fullTs: item.timestamp,
      temperature: item.temperature,
      pressure: item.pressure,
      humidity: item.humidity || item.relative_humidity,
      isFault: cls === 'LIKELY_SENSOR_DATA_FAULT',
    };
  });

  const currentObs = activeStream[0] || {};
  const currentDec = currentObs.decision || {};

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-100">Historical Replay & Backend Demonstration</h2>
        <p className="text-xs text-slate-400 mt-0.5">
          Execute real-time dataset playback and run inference against the FastAPI backend pipeline.
        </p>
      </div>

      {/* CSV Dataset Replay Controls Toolbar */}
      <div className="bg-[#090e1a]/80 border border-slate-800 rounded-xl p-5 shadow-md space-y-4 backdrop-blur-md">
        <h3 className="font-bold text-slate-300 text-xs uppercase tracking-wider">Historical Dataset Replay Controls</h3>

        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
          <div>
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">Dataset</label>
            <select
              value={dataset}
              onChange={(e) => setDataset(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 font-mono text-slate-200 focus:border-cyan-500 focus:outline-none"
            >
              <option value="IMD_Maitri_Antarctic_2016.csv">IMD_Maitri_Antarctic_2016.csv</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">Replay Speed</label>
            <select
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 font-mono text-slate-200 focus:border-cyan-500 focus:outline-none"
            >
              <option value={1}>1x</option>
              <option value={5}>5x</option>
              <option value={10}>10x</option>
              <option value={50}>50x</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">Date / Time Status</label>
            <div className="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 font-mono text-cyan-300 font-bold">
              {currentObs.timestamp || '—'}
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">Replay Status</label>
            <div className="flex items-center space-x-2">
              {replayStatus?.is_running && !isPaused ? (
                <button
                  onClick={handlePauseReplay}
                  className="flex-1 bg-amber-600 hover:bg-amber-500 text-white font-semibold py-1.5 px-3 rounded-lg flex items-center justify-center space-x-1 shadow-sm transition"
                >
                  <Pause className="w-3.5 h-3.5 fill-current" />
                  <span>Pause</span>
                </button>
              ) : (
                <button
                  onClick={handleStartReplay}
                  className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold py-1.5 px-3 rounded-lg flex items-center justify-center space-x-1 shadow-sm transition"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Start</span>
                </button>
              )}

              <button
                onClick={handleStopReplay}
                className="bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-semibold py-1.5 px-3 rounded-lg flex items-center justify-center space-x-1 transition"
              >
                <Square className="w-3.5 h-3.5 fill-current" />
                <span>Stop</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Current Observation Readout */}
      <div className="bg-[#090e1a]/80 border border-slate-800 rounded-xl p-5 shadow-md space-y-3 backdrop-blur-md">
        <h3 className="font-bold text-slate-300 text-xs uppercase tracking-wider">Current Replay Observation Readout</h3>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
          <div className="bg-slate-900/90 p-3 rounded-lg border border-slate-800">
            <span className="text-slate-400 block text-[10px] font-sans font-semibold">Timestamp</span>
            <span className="font-bold text-slate-100">{currentObs.timestamp || '—'}</span>
          </div>

          <div className="bg-slate-900/90 p-3 rounded-lg border border-slate-800">
            <span className="text-slate-400 block text-[10px] font-sans font-semibold">Temperature</span>
            <span className="font-bold text-cyan-300">{currentObs.temperature !== undefined ? `${currentObs.temperature}°C` : '—'}</span>
          </div>

          <div className="bg-slate-900/90 p-3 rounded-lg border border-slate-800">
            <span className="text-slate-400 block text-[10px] font-sans font-semibold">Pressure</span>
            <span className="font-bold text-slate-100">{currentObs.pressure !== undefined ? `${currentObs.pressure} hPa` : '—'}</span>
          </div>

          <div className="bg-slate-900/90 p-3 rounded-lg border border-slate-800">
            <span className="text-slate-400 block text-[10px] font-sans font-semibold">Humidity</span>
            <span className="font-bold text-slate-100">{(currentObs.humidity ?? currentObs.relative_humidity) !== undefined ? `${currentObs.humidity ?? currentObs.relative_humidity}%` : '—'}</span>
          </div>
        </div>
      </div>

      {/* Manual Observation Backend Pipeline Evaluator */}
      <div className="bg-[#090e1a]/80 border border-slate-800 rounded-xl p-5 shadow-md space-y-4 backdrop-blur-md">
        <div>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <h3 className="font-bold text-slate-100 text-sm">Manual Observation Backend Inference Evaluator</h3>
            <div className="flex items-center gap-1.5 flex-wrap text-[11px]">
              <span className="text-slate-400 font-semibold">Test Presets:</span>
              <button
                type="button"
                onClick={() => applyPresetForm('2016-09-09 17:00', 41.6, 946.7, 100)}
                className="px-2 py-1 rounded-md bg-red-950/60 text-red-300 border border-red-500/40 hover:bg-red-900/60 font-semibold transition"
              >
                Known Maitri 41.6°C Spike
              </button>
              <button
                type="button"
                onClick={() => applyPresetForm('2016-09-09 17:00', 15, 600, 100)}
                className="px-2 py-1 rounded-md bg-purple-950/60 text-purple-300 border border-purple-500/40 hover:bg-purple-900/60 font-semibold transition"
              >
                600 hPa Pressure Violation
              </button>
              <button
                type="button"
                onClick={() => applyPresetForm('2016-09-09 17:00', 15, 946.7, 50)}
                className="px-2 py-1 rounded-md bg-emerald-950/60 text-emerald-300 border border-emerald-500/40 hover:bg-emerald-900/60 font-semibold transition"
              >
                Normal Baseline (15°C/946.7hPa)
              </button>
            </div>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Test any custom observation values against the live FastAPI backend pipeline. Inputs are evaluated independently without hardcoded defaults.
          </p>
        </div>

        <form onSubmit={handleTestBackendInference} className="grid grid-cols-1 sm:grid-cols-5 gap-3 text-xs">
          <div>
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">Time</label>
            <input
              type="text"
              value={testForm.timestamp}
              onChange={(e) => setTestForm({ ...testForm, timestamp: e.target.value })}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 font-mono text-slate-200 focus:border-cyan-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">Temp (°C)</label>
            <input
              type="number"
              step="0.1"
              value={testForm.temperature}
              onChange={(e) => setTestForm({ ...testForm, temperature: e.target.value })}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 font-mono text-slate-200 focus:border-cyan-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">Pressure (hPa)</label>
            <input
              type="number"
              step="0.1"
              value={testForm.pressure}
              onChange={(e) => setTestForm({ ...testForm, pressure: e.target.value })}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 font-mono text-slate-200 focus:border-cyan-500 focus:outline-none"
            />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-slate-400 mb-1">Humidity (%)</label>
            <input
              type="number"
              step="0.1"
              value={testForm.relative_humidity}
              onChange={(e) => setTestForm({ ...testForm, relative_humidity: e.target.value })}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 font-mono text-slate-200 focus:border-cyan-500 focus:outline-none"
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={isProcessing}
              className="w-full bg-cyan-600 hover:bg-cyan-500 text-white font-bold py-1.5 px-3 rounded-lg transition-colors disabled:opacity-50 shadow-lg shadow-cyan-900/30"
            >
              {isProcessing ? 'Running...' : 'Run Backend Inference'}
            </button>
          </div>
        </form>

        {/* Dynamic Backend Inference Output */}
        {backendInferenceResult && (
          <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 text-xs font-mono space-y-3">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2 font-sans font-bold">
              <span className="text-slate-100">ACTUAL BACKEND INFERENCE RESULT:</span>
              <span className={`px-2 py-0.5 rounded border font-mono text-[11px] ${
                (backendInferenceResult.decision?.classification || backendInferenceResult.assessment?.classification) === 'LIKELY_SENSOR_DATA_FAULT'
                  ? 'bg-red-950/80 text-red-300 border-red-500/40 font-bold'
                  : (backendInferenceResult.decision?.classification || backendInferenceResult.assessment?.classification) === 'LIKELY_GENUINE_WEATHER_EVENT'
                  ? 'bg-amber-950/80 text-amber-300 border-amber-500/40 font-bold'
                  : 'bg-emerald-950/80 text-emerald-300 border-emerald-500/40 font-semibold'
              }`}>
                {backendInferenceResult.assessment?.classification || backendInferenceResult.decision?.primary_classification || backendInferenceResult.decision?.classification}
              </span>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 pt-1 font-sans text-slate-300">
              <div>
                <strong className="block text-[10px] text-slate-400 uppercase">Assessment</strong>
                <span className={`inline-block mt-1 rounded border px-2 py-0.5 text-xs font-bold ${assessmentTone(backendInferenceResult.assessment?.classification || backendInferenceResult.decision?.classification)}`}>
                  {backendInferenceResult.assessment?.classification || backendInferenceResult.decision?.classification || 'NORMAL'}
                </span>
              </div>
              <div>
                <strong className="block text-[10px] text-slate-400 uppercase">Severity</strong>
                <span className={`inline-block mt-1 rounded border px-2 py-0.5 text-xs font-bold ${severityTone(backendInferenceResult.assessment?.severity || backendInferenceResult.decision?.severity || 'NONE')}`}>
                  {backendInferenceResult.assessment?.severity || backendInferenceResult.decision?.severity || 'NONE'}
                </span>
              </div>
              <div>
                <strong className="block text-[10px] text-slate-400 uppercase">Primary Parameter</strong>
                <span className="font-bold text-slate-100">
                  {backendInferenceResult.decision?.primary_parameter || '—'}
                </span>
              </div>
              <div>
                <strong className="block text-[10px] text-slate-400 uppercase">Affected Parameters</strong>
                <span className="font-bold text-slate-100">
                  {(backendInferenceResult.affected_parameters || backendInferenceResult.decision?.affected_parameters || []).join(', ') || '—'}
                </span>
              </div>
              <div>
                <strong className="block text-[10px] text-slate-400 uppercase">Calibrated Confidence</strong>
                <span className="font-bold text-slate-100 font-mono">
                  {backendInferenceResult.assessment?.evidence_confidence != null
                    ? formatConfidence(backendInferenceResult.assessment.evidence_confidence)
                    : formatConfidence(backendInferenceResult.decision?.calibrated_confidence)}
                </span>
              </div>
            </div>

            <div className="pt-1 font-sans text-slate-200">
              <strong className="block text-[10px] text-slate-400 uppercase">Primary Root Cause</strong>
              <p className="mt-0.5 text-xs font-semibold text-slate-100">
                {backendInferenceResult.assessment?.primary_root_cause || backendInferenceResult.decision?.probable_cause || '—'}
              </p>
            </div>

            {/* Recovery Estimation Block */}
            <div className="pt-2 border-t border-slate-800 font-sans">
              <strong className="block text-[10px] text-slate-400 uppercase mb-1">Data Recovery Estimation</strong>
              {Object.entries(backendInferenceResult.recovery_results || {}).some(([, result]) => result.available) ? (
                <div className="bg-emerald-950/30 border border-emerald-500/30 p-2.5 rounded-lg text-xs space-y-2">
                  {Object.entries(backendInferenceResult.recovery_results || {}).map(([parameter, result]) => (
                    <div key={parameter} className="border-b border-emerald-500/20 pb-2 last:border-0 last:pb-0">
                      <div className="flex justify-between font-mono font-bold text-emerald-300">
                        <span>Estimated {parameter}:</span>
                        <span>{result.available ? result.estimated_value : 'Unavailable'}</span>
                      </div>
                      <div className="text-[11px] text-emerald-400/80">
                        {result.available ? `${result.recovery_method} (${result.previous_observation_timestamp} & ${result.next_observation_timestamp})` : result.message}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="bg-slate-950/60 border border-slate-800 p-2.5 rounded-lg text-xs text-slate-400 italic">
                  {backendInferenceResult.recovery?.message || backendInferenceResult.recovery_message || 'Recovery not applicable — valid temporal neighbors are unavailable for this test observation.'}
                </div>
              )}
            </div>

            {/* Expandable Technical Details */}
            <div className="border border-slate-800 rounded-lg mt-3 overflow-hidden">
              <button
                type="button"
                onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
                className="w-full bg-slate-900/90 px-3 py-1.5 flex items-center justify-between text-xs font-semibold text-slate-300 hover:bg-slate-800"
              >
                <span>Technical Detector Details</span>
                {showTechnicalDetails ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </button>

              {showTechnicalDetails && (
                <div className="p-3 bg-slate-950 text-slate-200 border-t border-slate-800 text-[11px] space-y-1 font-mono">
                  <div>Isolation Forest raw score: {backendInferenceResult.iforest_score ?? backendInferenceResult.decision?.evidence_scores?.iforest ?? '—'}</div>
                  <div>TensorFlow/Keras LSTM MSE: {backendInferenceResult.lstm_mse ?? backendInferenceResult.decision?.evidence_scores?.lstm_autoencoder ?? '—'}</div>
                  <div>Physical Consistency Status: {backendInferenceResult.decision?.physical_result?.status ?? '—'}</div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
