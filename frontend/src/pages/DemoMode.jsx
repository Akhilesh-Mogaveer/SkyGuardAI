import React, { useState, useEffect, useRef } from 'react';
import {
  Play,
  Pause,
  SkipForward,
  RotateCcw,
  Zap,
  ShieldCheck,
  Cpu,
  Network,
  Layers,
  FileText,
  Activity,
  AlertOctagon,
  Radio,
  Loader2,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react';
import { fetchDemoPresets, evaluateDemoStep } from '../services/api';

const DEFAULT_PRESETS = [
  {
    case_id: 'temp_spike_2016_09_09',
    title: '2016-09-09 17:00 (+41.6°C Extreme Jump)',
    timestamp: '2016-09-09 17:00:00+00:00',
    temperature: 41.6,
    pressure: 946.7,
    humidity: 100.0,
    category: 'SENSOR_FAULT_BENCHMARK',
    description:
      'Known Antarctic sensor fault where temperature jumped +63.8°C in 1 hour (from -22.2°C to +41.6°C). Demonstrates multi-pillar fault detection.',
  },
  {
    case_id: 'normal_polar_diurnal',
    title: '2016-06-15 12:00 (Pristine Polar Winter)',
    timestamp: '2016-06-15 12:00:00+00:00',
    temperature: -9.0,
    pressure: 967.8,
    humidity: 76.0,
    category: 'NORMAL_BASELINE',
    description: 'Uncontaminated, smooth polar winter diurnal temperature and pressure trace.',
  },
  {
    case_id: 'imd_bharati_2015_11_06',
    title: '2015-11-06 15:00 (IMD Bharati validation case)',
    timestamp: '2015-11-06 15:00:00+00:00',
    temperature: -5.42,
    pressure: 965.08,
    humidity: 44.42,
    category: 'VALIDATION_CASE',
    description: 'Deterministic IMD Bharati observation processed by the live pipeline using the supplied values.',
  },
  {
    case_id: 'pressure_gradient_storm',
    title: '2016-07-22 08:00 (Barometric Pressure Fall)',
    timestamp: '2016-07-22 08:00:00+00:00',
    temperature: -22.3,
    pressure: 965.5,
    humidity: 39.0,
    category: 'WEATHER_EVENT_BENCHMARK',
    description: 'Rapid barometric pressure fall during an Antarctic coastal cyclone.',
  },
  {
    case_id: 'sensor_flatline',
    title: '2016-04-10 06:00 (Humidity Flatline Persistence)',
    timestamp: '2016-04-10 06:00:00+00:00',
    temperature: -15.7,
    pressure: 956.1,
    humidity: 46.0,
    category: 'FLATLINE_BENCHMARK',
    description:
      'Multiple consecutive hours of unvarying identical relative humidity reading indicating sensor freezing.',
  },
];

export default function DemoMode() {
  const [presets, setPresets] = useState(DEFAULT_PRESETS);
  const [selectedPresetId, setSelectedPresetId] = useState('temp_spike_2016_09_09');

  // Cache for already computed demo results: { [case_id]: stepResult }
  const [demoResultCache, setDemoResultCache] = useState({});
  const [activeStepData, setActiveStepData] = useState(null);

  const [activeStage, setActiveStage] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speedMultiplier, setSpeedMultiplier] = useState(1);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const timerRef = useRef(null);

  // Fetch presets metadata on mount (lightweight GET request, no ML execution)
  useEffect(() => {
    fetchDemoPresets()
      .then((data) => {
        if (data && Array.isArray(data) && data.length > 0) {
          setPresets(data);
        }
      })
      .catch((err) => console.error('Failed to load demo presets:', err));
  }, []);

  const currentPreset = presets.find((p) => p.case_id === selectedPresetId) || presets[0];

  const handleSelectPreset = (caseId) => {
    if (isLoading) return;
    setSelectedPresetId(caseId);
    setIsPlaying(false);
    setActiveStage(1);
    setError(null);

    // Check if result is already in cache
    if (demoResultCache[caseId]) {
      setActiveStepData(demoResultCache[caseId]);
    } else {
      setActiveStepData(null);
    }
  };

  const runDemoInference = async (preset) => {
    if (!preset) return null;
    if (isLoading) return null;

    // Check cache first
    if (demoResultCache[preset.case_id]) {
      const cached = demoResultCache[preset.case_id];
      setActiveStepData(cached);
      return cached;
    }

    setIsLoading(true);
    setError(null);
    try {
      const stepResult = await evaluateDemoStep(preset.timestamp, 24, {
        temperature: preset.temperature,
        pressure: preset.pressure,
        humidity: preset.humidity,
      });
      if (stepResult && !stepResult.detail) {
        setDemoResultCache((prev) => ({
          ...prev,
          [preset.case_id]: stepResult,
        }));
        setActiveStepData(stepResult);
        return stepResult;
      } else {
        throw new Error(stepResult?.detail || 'Failed to evaluate demo step');
      }
    } catch (err) {
      console.error('Error evaluating demo step:', err);
      setError('Unable to run demo inference.');
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isPlaying) {
      const delayMs = speedMultiplier === 1 ? 1200 : speedMultiplier === 10 ? 400 : 100;
      timerRef.current = setTimeout(() => {
        setActiveStage((prev) => {
          if (prev >= 8) {
            setIsPlaying(false);
            return 8;
          }
          return prev + 1;
        });
      }, delayMs);
    }

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [isPlaying, activeStage, speedMultiplier]);

  const handlePlayPause = async () => {
    if (isLoading) return;

    if (isPlaying) {
      setIsPlaying(false);
      return;
    }

    // Lazy load inference on explicit Play Flow click
    let data = activeStepData;
    if (!data || data.target_timestamp !== currentPreset.timestamp) {
      data = await runDemoInference(currentPreset);
      if (!data) return; // Inference failed
    }

    if (activeStage >= 8) {
      setActiveStage(1);
    }
    setIsPlaying(true);
  };

  const handleStepForward = async () => {
    if (isLoading) return;

    let data = activeStepData;
    if (!data || data.target_timestamp !== currentPreset.timestamp) {
      data = await runDemoInference(currentPreset);
      if (!data) return;
    }

    setIsPlaying(false);
    if (activeStage < 8) {
      setActiveStage((prev) => prev + 1);
    }
  };

  const handleReset = () => {
    setIsPlaying(false);
    setActiveStage(1);
    setError(null);
  };

  const stages = [
    { id: 1, title: 'Incoming Observation', icon: Radio },
    { id: 2, title: 'Rule QC Check', icon: ShieldCheck },
    { id: 3, title: 'Isolation Forest', icon: Cpu },
    { id: 4, title: 'LSTM Autoencoder', icon: Network },
    { id: 5, title: 'Evidence Validation', icon: Layers },
    { id: 6, title: 'Final Classification', icon: AlertOctagon },
    { id: 7, title: 'Explanation & Action', icon: FileText },
    { id: 8, title: 'Sensor Health Update', icon: Activity },
  ];

  const getClassificationBadge = (cls) => {
    switch (cls) {
      case 'NORMAL':
        return { label: 'NORMAL', bg: 'bg-emerald-50 text-emerald-700 border-emerald-200' };
      case 'LIKELY_GENUINE_WEATHER_EVENT':
        return { label: 'GENUINE WEATHER EVENT', bg: 'bg-amber-50 text-amber-700 border-amber-200' };
      case 'LIKELY_SENSOR_DATA_FAULT':
        return { label: 'SENSOR DATA FAULT', bg: 'bg-red-50 text-red-700 border-red-200' };
      case 'UNCERTAIN':
      default:
        return { label: 'UNCERTAIN', bg: 'bg-purple-50 text-purple-700 border-purple-200' };
    }
  };

  const s1 = activeStepData?.stage_1_incoming || {
    timestamp: currentPreset?.timestamp,
    temperature: currentPreset?.temperature,
    pressure: currentPreset?.pressure,
    humidity: currentPreset?.humidity,
  };
  const s2 = activeStepData?.stage_2_qc;
  const s3 = activeStepData?.stage_3_iforest;
  const s4 = activeStepData?.stage_4_lstm;
  const s5 = activeStepData?.stage_5_evidence_validation;
  const s6 = activeStepData?.stage_6_classification;
  const s7 = activeStepData?.stage_7_explanation;
  const s8 = activeStepData?.stage_8_sensor_health_update;

  return (
    <div className="space-y-5">
      {/* Top Banner */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-2">
        <div className="flex items-center space-x-2">
          <Zap className="w-5 h-5 text-amber-500" />
          <h2 className="text-xl font-bold text-slate-900">
            SkyGuard AI Interactive Pipeline Flow Studio
          </h2>
          <span className="bg-amber-50 text-amber-700 text-xs font-mono font-bold px-2.5 py-0.5 rounded border border-amber-200">
            Live Pipeline Engine
          </span>
        </div>
        <p className="text-xs text-slate-500">
          Interactive 8-stage observation playback through the active production pipeline with real IMD Maitri AWS data.
        </p>
      </div>

      {/* Loading & Error Status Messages */}
      {isLoading && (
        <div className="bg-sky-50 border border-sky-200 rounded-xl p-3.5 text-xs text-sky-700 flex items-center space-x-2 shadow-xs animate-pulse">
          <Loader2 className="w-4 h-4 text-sky-600 animate-spin" />
          <span className="font-semibold">Preparing observation assessment...</span>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-3.5 text-xs text-red-700 flex items-center justify-between shadow-xs">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-red-600 shrink-0" />
            <span className="font-medium">{error}</span>
          </div>
          <button
            onClick={() => runDemoInference(currentPreset)}
            className="bg-red-600 text-white px-3 py-1.5 rounded-lg text-xs font-bold hover:bg-red-700 flex items-center space-x-1 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Toolbar: Case Jump & Playback Controls */}
      <div className="bg-white border border-slate-200 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs text-xs">
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2">
          <span className="font-semibold text-slate-500">Benchmark Case:</span>
          <select
            value={selectedPresetId}
            onChange={(e) => handleSelectPreset(e.target.value)}
            disabled={isLoading}
            className="bg-slate-50 border border-slate-200 text-slate-800 text-xs rounded-lg px-3 py-1.5 focus:outline-none focus:border-sky-500 font-medium disabled:opacity-60"
          >
            {presets.map((p) => (
              <option key={p.case_id} value={p.case_id}>
                {p.title}
              </option>
            ))}
          </select>

          <button
            onClick={() => handleSelectPreset('temp_spike_2016_09_09')}
            disabled={isLoading}
            className="bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 px-3 py-1.5 rounded-lg font-bold transition-colors flex items-center space-x-1 disabled:opacity-60"
          >
            <Zap className="w-3.5 h-3.5 text-red-600" />
            <span>Jump to +41.6°C Spike</span>
          </button>
        </div>

        <div className="flex items-center space-x-2">
          <div className="flex items-center space-x-1 bg-slate-50 p-1 rounded-lg border border-slate-200 font-mono text-xs">
            {[1, 10, 100].map((spd) => (
              <button
                key={spd}
                onClick={() => setSpeedMultiplier(spd)}
                className={`px-2 py-0.5 rounded font-bold transition-colors ${
                  speedMultiplier === spd ? 'bg-sky-600 text-white' : 'text-slate-500 hover:text-slate-900'
                }`}
              >
                {spd}x
              </button>
            ))}
          </div>

          <div className="flex items-center space-x-1.5">
            <button
              onClick={handlePlayPause}
              disabled={isLoading}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors flex items-center space-x-1 disabled:opacity-75 ${
                isPlaying
                  ? 'bg-amber-600 text-white hover:bg-amber-700'
                  : 'bg-emerald-600 text-white hover:bg-emerald-700'
              }`}
            >
              {isLoading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : isPlaying ? (
                <Pause className="w-3.5 h-3.5 fill-current" />
              ) : (
                <Play className="w-3.5 h-3.5 fill-current" />
              )}
              <span>{isLoading ? 'Preparing...' : isPlaying ? 'Pause' : 'Play Flow'}</span>
            </button>

            <button
              onClick={handleStepForward}
              disabled={isLoading || activeStage >= 8}
              className="p-1.5 bg-slate-50 hover:bg-slate-100 text-slate-700 rounded-lg border border-slate-200 disabled:opacity-40"
              title="Step Forward"
            >
              <SkipForward className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={handleReset}
              disabled={isLoading}
              className="p-1.5 bg-slate-50 hover:bg-slate-100 text-slate-700 rounded-lg border border-slate-200"
              title="Reset Flow"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Case Description Card */}
      {currentPreset && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 text-xs space-y-1">
          <div className="font-bold text-slate-900 flex items-center space-x-2">
            <span className="text-slate-500">Case Context:</span>
            <span className="text-sky-700 font-mono">{currentPreset.title}</span>
          </div>
          <p className="text-slate-600 leading-relaxed">{currentPreset.description}</p>
        </div>
      )}

      {/* 8-Stage Grid */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 space-y-5 shadow-xs">
        <div className="flex items-center justify-between border-b border-slate-200 pb-3">
          <h3 className="text-sm font-bold text-slate-900 flex items-center space-x-2">
            <Activity className="w-4 h-4 text-sky-600" />
            <span>8-Stage Multi-Pillar Evidence Execution Flow</span>
          </h3>
          <span className="text-xs text-sky-700 font-mono font-bold bg-sky-50 px-2.5 py-0.5 rounded-md border border-sky-200">
            Step {activeStage} of 8 Active
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 text-xs">
          {stages.map((stg) => {
            const Icon = stg.icon;
            const isCurrent = activeStage === stg.id;
            const isCompleted = activeStage > stg.id;

            return (
              <div
                key={stg.id}
                onClick={() => setActiveStage(stg.id)}
                className={`cursor-pointer p-2.5 rounded-lg border text-center space-y-1.5 transition-colors ${
                  isCurrent
                    ? 'bg-sky-600 text-white font-bold border-sky-600 shadow-xs'
                    : isCompleted
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    : 'bg-slate-50 text-slate-500 border-slate-200 hover:bg-slate-100 hover:text-slate-800'
                }`}
              >
                <div className="flex justify-center">
                  <Icon className="w-4 h-4" />
                </div>
                <span className="text-[10px] block font-semibold leading-tight">{stg.title}</span>
              </div>
            );
          })}
        </div>

        {/* Stage Execution Details */}
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 space-y-4 text-xs font-sans">
          {activeStage >= 1 && s1 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between font-bold text-slate-900 border-b border-slate-200 pb-2">
                <span>Stage 1: Raw Observation Ingestion</span>
                <span className="font-mono text-sky-700">{s1.timestamp}</span>
              </div>
              <div className="grid grid-cols-3 gap-3 font-mono">
                <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                  <span className="text-[10px] text-slate-500 block">Temperature</span>
                  <span className="font-bold text-sky-700">{s1.temperature}°C</span>
                </div>
                <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                  <span className="text-[10px] text-slate-500 block">Pressure</span>
                  <span className="font-bold text-slate-900">{s1.pressure} hPa</span>
                </div>
                <div className="bg-white p-2.5 rounded-lg border border-slate-200">
                  <span className="text-[10px] text-slate-500 block">Humidity</span>
                  <span className="font-bold text-slate-900">{s1.humidity}%</span>
                </div>
              </div>
            </div>
          )}

          {activeStage >= 2 && (
            s2 ? (
              <div className="space-y-2 border-t border-slate-200 pt-3">
                <div className="flex items-center justify-between font-bold text-slate-900">
                  <span>Stage 2: WMO Quality Control Check</span>
                  <span
                    className={`px-2 py-0.5 rounded-md text-[10px] border font-bold ${
                      s2.qc_flag ? 'bg-red-50 text-red-700 border-red-200' : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    }`}
                  >
                    {s2.qc_flag ? 'QC FLAGGED' : 'QC PASSED'}
                  </span>
                </div>
                {s2.qc_reasons && s2.qc_reasons.length > 0 && (
                  <p className="text-red-700 font-mono text-[11px] bg-red-50 p-2.5 rounded-lg border border-red-200">
                    Violations: {s2.qc_reasons.join(', ')}
                  </p>
                )}
              </div>
            ) : (
              <div className="space-y-1 border-t border-slate-200 pt-3 text-slate-500 italic">
                <span>Stage 2: WMO Quality Control Check</span>
                <p className="text-[11px] font-mono">Pipeline evaluation pending — click "Play Flow" to evaluate.</p>
              </div>
            )
          )}

          {activeStage >= 3 && (
            s3 ? (
              <div className="space-y-2 border-t border-slate-200 pt-3">
                <div className="flex items-center justify-between font-bold text-slate-900">
                  <span>Stage 3: Isolation Forest Evaluator</span>
                  <span className="font-mono text-slate-700">
                    Raw Anomaly Score: {s3.anomaly_score !== null && s3.anomaly_score !== undefined ? s3.anomaly_score.toFixed(4) : 'N/A'}
                  </span>
                </div>
              </div>
            ) : (
              <div className="space-y-1 border-t border-slate-200 pt-3 text-slate-500 italic">
                <span>Stage 3: Isolation Forest Evaluator</span>
                <p className="text-[11px] font-mono">Pipeline evaluation pending — click "Play Flow" to evaluate.</p>
              </div>
            )
          )}

          {activeStage >= 4 && (
            s4 ? (
              <div className="space-y-2 border-t border-slate-200 pt-3">
                <div className="flex items-center justify-between font-bold text-slate-900">
                  <span>Stage 4: TensorFlow/Keras LSTM Autoencoder</span>
                  {s4.reconstruction_error_mse !== null && s4.reconstruction_error_mse !== undefined ? (
                    <span className="font-mono text-slate-700">
                      Reconstruction MSE: {s4.reconstruction_error_mse.toFixed(4)}
                    </span>
                  ) : (
                    <span className="font-mono text-amber-700 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-200">
                      LSTM Unavailable
                    </span>
                  )}
                </div>
                {s4.reconstruction_error_mse !== null && s4.reconstruction_error_mse !== undefined && (
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 font-mono text-[11px] text-slate-800">
                    <div className="bg-white p-2 rounded-lg border border-slate-200">
                      <span className="text-slate-500 block text-[10px]">Prediction</span>
                      <span className={`font-bold ${s4.is_anomaly ? 'text-red-600' : 'text-emerald-600'}`}>
                        {s4.is_anomaly ? 'ANOMALOUS SEQUENCE' : 'NORMAL SEQUENCE'}
                      </span>
                    </div>
                    <div className="bg-white p-2 rounded-lg border border-slate-200">
                      <span className="text-slate-500 block text-[10px]">Threshold</span>
                      <span className="font-bold text-slate-900">
                        {s4.anomaly_threshold !== null && s4.anomaly_threshold !== undefined ? s4.anomaly_threshold.toFixed(4) : 'N/A'}
                      </span>
                    </div>
                    <div className="bg-white p-2 rounded-lg border border-slate-200">
                      <span className="text-slate-500 block text-[10px]">Evidence Score</span>
                      <span className="font-bold text-slate-900">
                        {s4.calibrated_evidence !== null && s4.calibrated_evidence !== undefined
                          ? (s4.calibrated_evidence * 100).toFixed(1) + '%'
                          : '0%'}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-1 border-t border-slate-200 pt-3 text-slate-500 italic">
                <span>Stage 4: TensorFlow/Keras LSTM Autoencoder</span>
                <p className="text-[11px] font-mono">Pipeline evaluation pending — click "Play Flow" to evaluate.</p>
              </div>
            )
          )}

          {activeStage >= 5 && (
            s5 ? (
              <div className="space-y-2 border-t border-slate-200 pt-3">
                <div className="flex items-center justify-between font-bold text-slate-900">
                  <span>Stage 5: Dew Point & Spatial Validation</span>
                  <span className="font-mono text-sky-700">
                    Dew Point: {s5.dew_point !== null && s5.dew_point !== undefined ? `${s5.dew_point}°C` : 'N/A'}
                  </span>
                </div>
              </div>
            ) : (
              <div className="space-y-1 border-t border-slate-200 pt-3 text-slate-500 italic">
                <span>Stage 5: Dew Point & Spatial Validation</span>
                <p className="text-[11px] font-mono">Pipeline evaluation pending — click "Play Flow" to evaluate.</p>
              </div>
            )
          )}

          {activeStage >= 6 && (
            s6 ? (
              <div className="space-y-2 border-t border-slate-200 pt-3">
                <div className="flex items-center justify-between font-bold text-slate-900">
                  <span>Stage 6: Consensus Assessment</span>
                  <span className={`px-2.5 py-0.5 rounded-md text-xs font-bold border ${getClassificationBadge(s6.primary_classification).bg}`}>
                    {getClassificationBadge(s6.primary_classification).label}
                  </span>
                </div>
              </div>
            ) : (
              <div className="space-y-1 border-t border-slate-200 pt-3 text-slate-500 italic">
                <span>Stage 6: Consensus Assessment</span>
                <p className="text-[11px] font-mono">Pipeline evaluation pending — click "Play Flow" to evaluate.</p>
              </div>
            )
          )}

          {activeStage >= 7 && (
            s7 ? (
              <div className="space-y-2 border-t border-slate-200 pt-3">
                <div className="font-bold text-slate-900">Stage 7: Explanation & Recommended Action</div>
                <p className="text-slate-800 bg-white p-2.5 rounded-lg border border-slate-200 font-mono text-[11px]">
                  {s7.probable_cause}
                </p>
                <p className="text-amber-800 bg-amber-50 p-2.5 rounded-lg border border-amber-200 font-mono text-[11px]">
                  Recommended Action: {s7.recommended_operator_action}
                </p>
              </div>
            ) : (
              <div className="space-y-1 border-t border-slate-200 pt-3 text-slate-500 italic">
                <span>Stage 7: Explanation & Recommended Action</span>
                <p className="text-[11px] font-mono">Pipeline evaluation pending — click "Play Flow" to evaluate.</p>
              </div>
            )
          )}

          {activeStage >= 8 && (
            s8 ? (
              <div className="space-y-2 border-t border-slate-200 pt-3 font-mono">
                <div className="flex items-center justify-between font-bold text-slate-900">
                  <span>Stage 8: Sensor Health Update</span>
                  <span className="text-emerald-700">Overall: {s8.overall_status}</span>
                </div>
              </div>
            ) : (
              <div className="space-y-1 border-t border-slate-200 pt-3 text-slate-500 italic">
                <span>Stage 8: Sensor Health Update</span>
                <p className="text-[11px] font-mono">Pipeline evaluation pending — click "Play Flow" to evaluate.</p>
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}
