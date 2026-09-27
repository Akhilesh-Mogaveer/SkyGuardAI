import React, { useState, useMemo, useEffect } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  CircleAlert,
  Clock,
  Filter,
  RefreshCw,
  RotateCcw,
  SlidersHorizontal,
  X,
  Radio,
  Thermometer,
  Gauge,
  Droplets,
  Wrench,
  ChevronRight,
  Info,
  ShieldAlert,
  Activity,
  Check,
} from 'lucide-react';
import {
  formatClassification,
  getClassification,
  getSeverity,
  getRootCause,
  getMaintenanceStatus,
  getMaintenanceAction,
  getRecoveryMeta,
  getRecoveryMethod,
  getRecoveryStatus,
  getPreviousObservationTimestamp,
  getNextObservationTimestamp,
  getHumidity,
  getTemperature,
  getPressure,
  getStationName,
  getAffectedParameter,
  getCalibratedDecisionConfidence,
  analyzeEvidence,
  isAnomaly,
  getObservedValueForParameter,
  getAlertUniqueId,
} from '../utils/observation';
import { fetchAlertDetails, fetchAlertsPage } from '../services/api';

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

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined || value === '') return '—';
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : '—';
}

function severityBadge(severity) {
  const value = String(severity || '').toUpperCase();
  if (value === 'CRITICAL') {
    return 'bg-red-950/70 text-red-300 border-red-500/40 font-bold shadow-[0_0_8px_rgba(239,68,68,0.2)]';
  }
  if (value === 'HIGH') {
    return 'bg-orange-950/70 text-orange-300 border-orange-500/40 font-bold';
  }
  if (value === 'MEDIUM') {
    return 'bg-amber-950/70 text-amber-300 border-amber-500/40 font-semibold';
  }
  if (value === 'LOW') {
    return 'bg-slate-900 text-slate-300 border-slate-700 font-medium';
  }
  return 'bg-emerald-950/70 text-emerald-300 border-emerald-500/40 font-medium';
}

function assessmentTextTone(classification) {
  const value = String(classification || '').toUpperCase();
  if (value === 'LIKELY_SENSOR_DATA_FAULT') return 'text-red-400';
  if (value === 'LIKELY_GENUINE_WEATHER_EVENT') return 'text-cyan-400';
  if (value === 'UNCERTAIN') return 'text-amber-400';
  return 'text-emerald-400';
}

export default function Alerts({
  stations = [],
  onNavigateTab,
  onStartReplay,
  anomalies = [],
  latestAlertEvent = null,
}) {
  const [selectedAlert, setSelectedAlert] = useState(null);
  const [alertPage, setAlertPage] = useState({ items: [], page: 1, page_size: 10, total: 0, total_pages: 0, counts: {} });
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [page, setPage] = useState(1);

  // Filters State
  const [filterSeverity, setFilterSeverity] = useState('ALL');
  const [filterAssessment, setFilterAssessment] = useState('ALL');
  const [filterStation, setFilterStation] = useState('ALL');
  const [filterParameter, setFilterParameter] = useState('ALL');
  const [filterTime, setFilterTime] = useState('ALL');

  const allAlerts = alertPage.items || [];

  const loadAlerts = async (silent = false) => {
    if (!silent) setIsLoading(true);
    try {
      const result = await fetchAlertsPage({
        page,
        pageSize: 10,
        severity: filterSeverity,
        classification: filterAssessment,
        stationId: filterStation,
        parameter: filterParameter,
        timeRange: filterTime,
      });

      setAlertPage((prev) => {
        const fetchedItems = result.items || [];
        if (silent && prev.items.length > 0) {
          const map = new Map();
          fetchedItems.forEach((item) => {
            const k = getAlertUniqueId(item);
            if (k) map.set(k, item);
          });
          prev.items.forEach((item) => {
            const k = getAlertUniqueId(item);
            if (k && !map.has(k)) {
              map.set(k, item);
            }
          });
          const merged = Array.from(map.values());
          return {
            ...result,
            items: merged,
            total: Math.max(result.total || 0, merged.length),
            counts: result.counts || prev.counts || {},
          };
        }

        // Deduplicate fetched items defensively
        const map = new Map();
        fetchedItems.forEach((item) => {
          const k = getAlertUniqueId(item);
          if (k) map.set(k, item);
        });
        return {
          ...result,
          items: Array.from(map.values()),
        };
      });
    } catch (err) {
      if (!silent) {
        console.error('Failed to load alert history:', err);
        setAlertPage((previous) => ({ ...previous, items: [], total: 0, total_pages: 0 }));
      }
    } finally {
      if (!silent) setIsLoading(false);
    }
  };

  const ingestAlertRecord = (rawAlert) => {
    if (!rawAlert) return;
    const cls = getClassification(rawAlert);
    if (cls === 'NORMAL') return;

    const key = getAlertUniqueId(rawAlert);
    if (!key) return;

    setAlertPage((prev) => {
      const items = prev.items || [];
      const existingIdx = items.findIndex((item) => getAlertUniqueId(item) === key);

      let updatedItems;
      let newTotal = prev.total || 0;
      const counts = { ...(prev.counts || { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 }) };

      if (existingIdx >= 0) {
        updatedItems = [...items];
        updatedItems[existingIdx] = { ...items[existingIdx], ...rawAlert, alert_key: key };
      } else {
        updatedItems = [{ ...rawAlert, alert_key: key }, ...items];
        newTotal += 1;
        const sev = getSeverity(rawAlert);
        if (counts[sev] !== undefined) {
          counts[sev] += 1;
        }
      }

      return {
        ...prev,
        items: updatedItems,
        total: newTotal,
        counts,
      };
    });
  };

  // Process incoming prop alert events
  useEffect(() => {
    if (latestAlertEvent) {
      ingestAlertRecord(latestAlertEvent);
    }
  }, [latestAlertEvent]);

  // Initial load and periodic silent polling background sync
  useEffect(() => {
    loadAlerts(false);
    const interval = setInterval(() => {
      loadAlerts(true);
    }, 5000);
    return () => clearInterval(interval);
  }, [page, filterSeverity, filterAssessment, filterStation, filterParameter, filterTime]);

  // Direct WebSocket stream listener for real-time alert updates in Alerts tab
  useEffect(() => {
    const wsUrl = 'ws://127.0.0.1:8000/ws/observations';
    let socket;
    try {
      socket = new WebSocket(wsUrl);
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const obs = data.data || data.observation || (data.timestamp ? data : null);
          if (obs) {
            ingestAlertRecord(obs);
          }
        } catch (e) {}
      };
    } catch (e) {}

    return () => {
      if (socket) socket.close();
    };
  }, []);

  // Handle Refresh Click
  const handleRefresh = async () => {
    if (!isRefreshing) {
      setIsRefreshing(true);
      try {
        await loadAlerts();
      } catch (err) {
        console.error('Failed to refresh alerts:', err);
      } finally {
        setTimeout(() => setIsRefreshing(false), 500);
      }
    }
  };

  const counts = alertPage.counts || {};

  // Unique Stations for filter dropdown
  const stationOptions = useMemo(() => {
    return stations.map((station) => ({ id: station.station_id, name: station.name || station.station_name || station.station_id }));
  }, [stations]);

  // Reset Filters Function
  const handleResetFilters = () => {
    setFilterSeverity('ALL');
    setFilterAssessment('ALL');
    setFilterStation('ALL');
    setFilterParameter('ALL');
    setFilterTime('ALL');
    setPage(1);
  };

  const setFilter = (setter, value) => {
    setter(value);
    setPage(1);
  };

  const handleSelectAlert = async (alert) => {
    setSelectedAlert(alert);
    if (alert.db_id) {
      try {
        setSelectedAlert(await fetchAlertDetails(alert.db_id));
      } catch (err) {
        console.error('Failed to load alert details:', err);
      }
    }
  };

  // Latest Timestamp for Page Header
  const lastUpdatedTs = allAlerts[0]?.timestamp || allAlerts[0]?.TIMESTAMP || null;
  const hasActiveFilters = [filterSeverity, filterAssessment, filterStation, filterParameter, filterTime].some((value) => value !== 'ALL');

  return (
    <div className="space-y-6">
      {/* 1. Page Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-slate-800 bg-[#090e1a]/80 backdrop-blur-md p-6 shadow-md">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">ALERTS</h1>
            <span className="rounded-md bg-red-950/70 border border-red-500/40 px-2.5 py-0.5 text-xs font-bold text-red-300">
              Work Queue
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-400">
            Operational alert work queue generated by SkyGuard AI.
          </p>
          {lastUpdatedTs && (
            <div className="mt-2 text-xs text-slate-400 flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-cyan-400" />
              <span>Last updated: {formatTime(lastUpdatedTs)}</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/80 px-4 py-2 text-sm font-semibold text-slate-200 hover:bg-slate-800 hover:border-cyan-500/50 active:bg-slate-700 disabled:opacity-50 transition shadow-sm"
          >
            <RefreshCw className={`h-4 w-4 text-cyan-400 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* 2. Summary Cards (CRITICAL, HIGH, MEDIUM, LOW) */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-4 shadow-sm backdrop-blur-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-red-400">CRITICAL</div>
          <div className="mt-2 text-3xl font-extrabold text-red-300">{counts.CRITICAL || 0}</div>
          <div className="mt-1 text-xs text-red-400/80 font-medium">Immediate fault & data risk</div>
        </div>

        <div className="rounded-xl border border-orange-500/30 bg-orange-950/20 p-4 shadow-sm backdrop-blur-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-orange-400">HIGH</div>
          <div className="mt-2 text-3xl font-extrabold text-orange-300">{counts.HIGH || 0}</div>
          <div className="mt-1 text-xs text-orange-400/80 font-medium">Corroborated sensor failure</div>
        </div>

        <div className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-4 shadow-sm backdrop-blur-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-amber-400">MEDIUM</div>
          <div className="mt-2 text-3xl font-extrabold text-amber-300">{counts.MEDIUM || 0}</div>
          <div className="mt-1 text-xs text-amber-400/80 font-medium">Weather event or threshold alert</div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-[#090e1a]/80 p-4 shadow-sm backdrop-blur-md">
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">LOW</div>
          <div className="mt-2 text-3xl font-extrabold text-slate-200">{counts.LOW || 0}</div>
          <div className="mt-1 text-xs text-slate-400 font-medium">Single-indicator / low severity</div>
        </div>
      </div>

      {/* 3. Filter Bar */}
      <div className="rounded-xl border border-slate-800 bg-[#090e1a]/80 p-4 shadow-sm space-y-3 backdrop-blur-md">
        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-400 border-b border-slate-800 pb-2">
          <SlidersHorizontal className="h-4 w-4 text-cyan-400" />
          <span>Filter Alert Queue</span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
          {/* Severity Filter */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Severity</label>
            <select
              value={filterSeverity}
              onChange={(e) => setFilter(setFilterSeverity, e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-200 focus:border-cyan-500 focus:outline-none"
            >
              <option value="ALL">All Severities</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </select>
          </div>

          {/* Assessment Filter */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Assessment</label>
            <select
              value={filterAssessment}
              onChange={(e) => setFilter(setFilterAssessment, e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-200 focus:border-cyan-500 focus:outline-none"
            >
              <option value="ALL">All Assessments</option>
              <option value="LIKELY_SENSOR_DATA_FAULT">Likely Sensor/Data Fault</option>
              <option value="LIKELY_GENUINE_WEATHER_EVENT">Genuine Weather Event</option>
              <option value="UNCERTAIN">Uncertain</option>
            </select>
          </div>

          {/* Station Filter */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Station</label>
            <select
              value={filterStation}
              onChange={(e) => setFilter(setFilterStation, e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-200 focus:border-cyan-500 focus:outline-none"
            >
              <option value="ALL">All Stations</option>
              {stationOptions.map((st) => (
                <option key={st.id} value={st.id}>
                  {st.name}
                </option>
              ))}
            </select>
          </div>

          {/* Parameter Filter */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Parameter</label>
            <select
              value={filterParameter}
              onChange={(e) => setFilter(setFilterParameter, e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-200 focus:border-cyan-500 focus:outline-none"
            >
              <option value="ALL">All Parameters</option>
              <option value="Temperature">Temperature</option>
              <option value="Pressure">Pressure</option>
              <option value="Relative Humidity">Relative Humidity</option>
              <option value="Multiple">Multiple</option>
              <option value="Data Quality">Data Quality</option>
            </select>
          </div>

          {/* Time Filter */}
          <div>
            <label className="block text-[11px] font-medium text-slate-400 mb-1">Time Range</label>
            <select
              value={filterTime}
              onChange={(e) => setFilter(setFilterTime, e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-slate-200 focus:border-cyan-500 focus:outline-none"
            >
              <option value="ALL">All Time</option>
              <option value="24H">Last 24 Hours</option>
              <option value="7D">Last 7 Days</option>
            </select>
          </div>
        </div>

        {/* Reset Filters Button */}
        {(filterSeverity !== 'ALL' ||
          filterAssessment !== 'ALL' ||
          filterStation !== 'ALL' ||
          filterParameter !== 'ALL' ||
          filterTime !== 'ALL') && (
          <div className="flex justify-end pt-1">
            <button
              onClick={handleResetFilters}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-cyan-400 hover:text-cyan-300"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Reset Filters</span>
            </button>
          </div>
        )}
      </div>

      {/* 4. Alert Table or Empty States */}
      {isLoading ? (
        <div className="rounded-xl border border-slate-800 bg-[#090e1a]/80 p-12 text-center shadow-sm text-sm text-slate-400">Loading alert history...</div>
      ) : alertPage.total === 0 ? (
        /* Empty State: No active alerts in current data window */
        <div className="rounded-xl border border-slate-800 bg-[#090e1a]/80 p-12 text-center shadow-sm backdrop-blur-md">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-950/60 text-emerald-400 border border-emerald-500/30">
            <CheckCircle2 className="h-8 w-8" />
          </div>
          <h3 className="mt-4 text-xl font-bold text-slate-100">{hasActiveFilters ? 'No alerts match the selected filters.' : 'No alerts found'}</h3>
          <p className="mt-2 max-w-md mx-auto text-sm text-slate-400 leading-relaxed">
            {hasActiveFilters ? 'Try changing the filters or reset them to view the full alert history.' : 'SkyGuard has not detected any observations requiring operational attention in the current data window.'}
          </p>
          {hasActiveFilters ? (
            <button onClick={handleResetFilters} className="mt-6 inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800">
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Reset Filters</span>
            </button>
          ) : (
            <div className="mt-6 flex justify-center gap-3">
              <button
                onClick={async () => {
                  if (onNavigateTab) onNavigateTab('data-replay');
                  if (onStartReplay) await onStartReplay();
                }}
                className="inline-flex items-center gap-2 rounded-lg bg-cyan-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-cyan-500 transition shadow-lg shadow-cyan-900/30"
              >
                <RefreshCw className="h-4 w-4" />
                <span>Run Data Replay</span>
              </button>
            </div>
          )}
        </div>
      ) : (
        /* Operational Alert Table */
        <div className="rounded-xl border border-slate-800 bg-[#090e1a]/80 shadow-md overflow-hidden backdrop-blur-md">
          <div className="px-5 py-3.5 border-b border-slate-800 bg-slate-900/80 flex items-center justify-between">
            <div className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Active Operational Queue
              <span className="ml-2 text-cyan-400 font-mono">{alertPage.total} alerts</span>
            </div>
            <div className="text-[11px] text-slate-400">
              Showing {(alertPage.page - 1) * alertPage.page_size + 1}–{Math.min(alertPage.page * alertPage.page_size, alertPage.total)} of {alertPage.total} alerts
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-slate-800 bg-slate-900/90 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  <th className="py-3 px-4">Severity</th>
                  <th className="py-3 px-4">Station</th>
                  <th className="py-3 px-4">Time</th>
                  <th className="py-3 px-4">Parameter</th>
                  <th className="py-3 px-4">Observed</th>
                  <th className="py-3 px-4">Assessment</th>
                  <th className="py-3 px-4">Evidence</th>
                  <th className="py-3 px-4">Confidence</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80 font-medium text-slate-200">
                {allAlerts.map((obs, idx) => {
                  const severity = getSeverity(obs);
                  const stationName = getStationName(obs, stations);
                  const timeStr = formatTime(obs.timestamp || obs.TIMESTAMP);
                  const param = getAffectedParameter(obs);
                  const classification = getClassification(obs);
                  const formattedClass = formatClassification(classification);

                  // Observed values
                  const temp = getTemperature(obs);
                  const press = getPressure(obs);
                  const hum = getHumidity(obs);
                  let observedText = '—';
                  if (param === 'Temperature' && temp != null) observedText = `${temp} °C`;
                  else if (param === 'Pressure' && press != null) observedText = `${press} hPa`;
                  else if (param === 'Relative Humidity' && hum != null) observedText = `${hum} %`;
                  else {
                    const parts = [];
                    if (temp != null) parts.push(`${temp}°C`);
                    if (press != null) parts.push(`${press}hPa`);
                    if (hum != null) parts.push(`${hum}%`);
                    observedText = parts.length > 0 ? parts.join(' | ') : '—';
                  }

                  // Evidence analysis
                  const ev = analyzeEvidence(obs);
                  const conf = getCalibratedDecisionConfidence(obs);
                  const actionStatus = getMaintenanceStatus(obs);

                  return (
                    <tr
                      key={getAlertUniqueId(obs) || (obs.db_id ? `db_${obs.db_id}` : `idx_${idx}`)}
                      onClick={() => handleSelectAlert(obs)}
                      className="hover:bg-slate-800/50 cursor-pointer transition"
                    >
                      {/* Severity */}
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <span className={`inline-block rounded-md border px-2.5 py-1 text-[10px] uppercase tracking-wider ${severityBadge(severity)}`}>
                          {severity}
                        </span>
                      </td>

                      {/* Station */}
                      <td className="py-3.5 px-4 whitespace-nowrap font-bold text-slate-100">
                        {stationName}
                      </td>

                      {/* Time */}
                      <td className="py-3.5 px-4 whitespace-nowrap text-slate-400">
                        {timeStr}
                      </td>

                      {/* Parameter */}
                      <td className="py-3.5 px-4 whitespace-nowrap font-medium text-slate-300">
                        {param}
                      </td>

                      {/* Observed */}
                      <td className="py-3.5 px-4 whitespace-nowrap font-mono text-xs font-semibold text-cyan-300">
                        {observedText}
                      </td>

                      {/* Assessment */}
                      <td className={`py-3.5 px-4 whitespace-nowrap font-bold ${assessmentTextTone(classification)}`}>
                        {formattedClass}
                      </td>

                      {/* Evidence */}
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        <div className="font-bold text-slate-100">
                          {ev.flaggedCount} / {ev.totalAvailable}
                        </div>
                        <div className="text-[10px] text-slate-400 font-normal">
                          {ev.agreementPercentage}% agreement
                        </div>
                      </td>

                      {/* Confidence */}
                      <td className="py-3.5 px-4 whitespace-nowrap">
                        {conf != null ? (
                          <span className="font-bold text-slate-100">{conf}%</span>
                        ) : (
                          <span className="text-[11px] text-slate-400 italic">Not calibrated</span>
                        )}
                      </td>

                      {/* Action */}
                      <td className="py-3.5 px-4 whitespace-nowrap text-right">
                        <span className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-semibold text-cyan-400 hover:bg-slate-800 hover:border-cyan-500/40">
                          <span>Details</span>
                          <ChevronRight className="h-3.5 w-3.5 text-cyan-400" />
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="flex flex-col gap-3 border-t border-slate-800 px-5 py-3 text-xs text-slate-400 sm:flex-row sm:items-center sm:justify-between bg-slate-900/60">
            <span>Showing {(alertPage.page - 1) * alertPage.page_size + 1}–{Math.min(alertPage.page * alertPage.page_size, alertPage.total)} of {alertPage.total} alerts</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 font-semibold text-slate-200 disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-800"
              >
                Previous
              </button>
              <span className="font-semibold text-slate-300">{page} / {Math.max(1, alertPage.total_pages)}</span>
              <button
                type="button"
                disabled={page >= alertPage.total_pages}
                onClick={() => setPage((current) => Math.min(alertPage.total_pages, current + 1))}
                className="rounded border border-slate-700 bg-slate-900 px-3 py-1.5 font-semibold text-slate-200 disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-800"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 5. ALERT DETAILS RIGHT-SIDE DRAWER */}
      {selectedAlert && (
        <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/80 backdrop-blur-xs transition-opacity animate-fade-in">
          {/* Backdrop click to close */}
          <div className="flex-1" onClick={() => setSelectedAlert(null)} />

          {/* Drawer Content */}
          <div className="w-full max-w-2xl bg-[#090e1a] h-full shadow-2xl overflow-y-auto border-l border-slate-800 flex flex-col">
            {/* Drawer Header */}
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-800 bg-slate-900 px-6 py-4 text-white">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold uppercase tracking-wider text-cyan-400">ALERT DETAILS</span>
                  <span className={`rounded px-2 py-0.5 text-[9px] font-bold uppercase ${severityBadge(getSeverity(selectedAlert))}`}>
                    {getSeverity(selectedAlert)}
                  </span>
                </div>
                <h2 className="mt-1 text-lg font-bold text-slate-100">
                  {getStationName(selectedAlert, stations)}
                </h2>
                <div className="text-xs text-slate-400 flex items-center gap-1 mt-0.5">
                  <Clock className="h-3 w-3 text-slate-400" />
                  <span>{formatTime(selectedAlert.timestamp || selectedAlert.TIMESTAMP)}</span>
                </div>
              </div>

              <button
                onClick={() => setSelectedAlert(null)}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Drawer Body */}
            <div className="p-6 space-y-6 flex-1 text-slate-200">
              {/* SECTION A: OBSERVATION */}
              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
                  <Activity className="h-4 w-4 text-cyan-400" />
                  <span>OBSERVATION</span>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1">
                      <Thermometer className="h-3.5 w-3.5 text-slate-400" />
                      Temperature
                    </div>
                    <div className="mt-1.5 text-lg font-bold text-slate-100">
                      {getTemperature(selectedAlert) != null ? `${getTemperature(selectedAlert)} °C` : '—'}
                    </div>
                  </div>

                  <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1">
                      <Gauge className="h-3.5 w-3.5 text-slate-400" />
                      Pressure
                    </div>
                    <div className="mt-1.5 text-lg font-bold text-slate-100">
                      {getPressure(selectedAlert) != null ? `${getPressure(selectedAlert)} hPa` : '—'}
                    </div>
                  </div>

                  <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                    <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1">
                      <Droplets className="h-3.5 w-3.5 text-slate-400" />
                      Relative Humidity
                    </div>
                    <div className="mt-1.5 text-lg font-bold text-slate-100">
                      {getHumidity(selectedAlert) != null ? `${getHumidity(selectedAlert)} %` : '—'}
                    </div>
                  </div>
                </div>

                <div className="mt-2 text-[11px] text-slate-500 italic">
                  * Raw telemetry values preserved without modification.
                </div>
              </div>

              {/* SECTION B: ASSESSMENT SUMMARY */}
              {(() => {
                const ev = analyzeEvidence(selectedAlert);
                const conf = getCalibratedDecisionConfidence(selectedAlert);
                const cls = getClassification(selectedAlert);
                const sev = getSeverity(selectedAlert);
                const rootCause = getRootCause(selectedAlert);
                const maintenance = getMaintenanceStatus(selectedAlert);

                return (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-4">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                      <ShieldAlert className="h-4 w-4 text-cyan-400" />
                      <span>ASSESSMENT</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-lg bg-slate-900 p-3 border border-slate-800">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Final Classification</div>
                        <div className={`mt-1 text-base font-bold ${assessmentTextTone(cls)}`}>
                          {formatClassification(cls)}
                        </div>
                      </div>

                      <div className="rounded-lg bg-slate-900 p-3 border border-slate-800">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Severity</div>
                        <div className="mt-1">
                          <span className={`inline-block rounded border px-2 py-0.5 text-xs font-bold ${severityBadge(sev)}`}>
                            {sev}
                          </span>
                        </div>
                      </div>

                      <div className="rounded-lg bg-slate-900 p-3 border border-slate-800">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Evidence Agreement</div>
                        <div className="mt-1 text-lg font-bold text-slate-100">
                          {ev.flaggedCount} / {ev.totalAvailable}
                        </div>
                        <div className="text-[11px] text-slate-400 font-medium">
                          {ev.agreementPercentage}% detector agreement
                        </div>
                      </div>

                      <div className="rounded-lg bg-slate-900 p-3 border border-slate-800">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Decision Confidence</div>
                        <div className="mt-1 text-lg font-bold text-slate-100">
                          {conf != null ? `${conf}%` : 'Not calibrated'}
                        </div>
                        <div className="text-[10px] text-slate-400 leading-tight mt-0.5">
                          {conf != null
                            ? 'Decision-engine confidence; not a calibrated probability unless explicitly provided by the backend.'
                            : 'Not calibrated by decision engine.'}
                        </div>
                      </div>
                    </div>

                    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Primary Root Cause</div>
                      <div className="mt-1 text-xs font-bold text-slate-200">{rootCause}</div>
                    </div>

                    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                      <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Maintenance Status</div>
                      <div className="mt-1 text-xs font-bold text-slate-200">{maintenance}</div>
                    </div>
                  </div>
                );
              })()}

              {/* SECTION C: DETECTOR EVIDENCE DETAILED BREAKDOWN */}
              {(() => {
                const ev = analyzeEvidence(selectedAlert);
                const { qc, iforest, lstm, physical, spatial } = ev.detectors;

                return (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-4">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5 border-b border-slate-800 pb-2">
                      <Info className="h-4 w-4 text-cyan-400" />
                      <span>DETECTOR EVIDENCE</span>
                    </div>

                    {/* 1. Rule-Based Quality Control */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3.5 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                          1 · RULE-BASED QUALITY CONTROL
                        </span>
                        {qc.flagged ? (
                          <span className="inline-flex items-center gap-1 rounded bg-red-950/80 border border-red-500/40 px-2 py-0.5 text-xs font-bold text-red-300">
                            <CircleAlert className="h-3.5 w-3.5" /> Flagged
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-emerald-950/80 border border-emerald-500/40 px-2 py-0.5 text-xs font-bold text-emerald-300">
                            <CheckCircle2 className="h-3.5 w-3.5" /> Clear
                          </span>
                        )}
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-xs pt-1">
                        <div className="flex justify-between border-b border-slate-800 pb-1">
                          <span className="text-slate-400">Range violation:</span>
                          <span className="font-semibold text-slate-200">{qc.rangeViolation ? 'Yes' : 'No'}</span>
                        </div>
                        <div className="flex justify-between border-b border-slate-800 pb-1">
                          <span className="text-slate-400">Rate-of-change:</span>
                          <span className="font-semibold text-slate-200">{qc.rateOfChangeViolation ? 'Yes' : 'No'}</span>
                        </div>
                        <div className="flex justify-between border-b border-slate-800 pb-1">
                          <span className="text-slate-400">Flatline:</span>
                          <span className="font-semibold text-slate-200">{qc.flatlineViolation ? 'Yes' : 'No'}</span>
                        </div>
                        <div className="flex justify-between border-b border-slate-800 pb-1">
                          <span className="text-slate-400">Communication gap:</span>
                          <span className="font-semibold text-slate-200">{qc.commGapViolation ? 'Yes' : 'No'}</span>
                        </div>
                      </div>

                      <div className="text-[11px] text-slate-400 pt-1">
                        <span className="font-semibold text-slate-300">QC Result:</span> {qc.flagStr}
                        {qc.reasons.length > 0 && (
                          <div className="mt-1 text-[11px] text-red-300 bg-red-950/40 p-2 rounded border border-red-500/30 font-mono">
                            {qc.reasons.join('; ')}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* 2. Isolation Forest */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3.5 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                          2 · ISOLATION FOREST
                        </span>
                        {iforest.flagged ? (
                          <span className="inline-flex items-center gap-1 rounded bg-red-950/80 border border-red-500/40 px-2 py-0.5 text-xs font-bold text-red-300">
                            <CircleAlert className="h-3.5 w-3.5" /> Flagged
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-emerald-950/80 border border-emerald-500/40 px-2 py-0.5 text-xs font-bold text-emerald-300">
                            <CheckCircle2 className="h-3.5 w-3.5" /> Clear
                          </span>
                        )}
                      </div>

                      <div className="grid grid-cols-3 gap-2 text-xs pt-1">
                        <div>
                          <div className="text-[10px] text-slate-400">Raw Anomaly Score</div>
                          <div className="font-mono font-bold text-slate-200">{formatNumber(iforest.rawScore, 4)}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400">Prediction</div>
                          <div className="font-semibold text-slate-200">{iforest.flagged ? 'Anomaly' : 'Normal'}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400">Evidence Score</div>
                          <div className="font-mono font-bold text-slate-200">{formatNumber(iforest.evidenceScore, 3)}</div>
                        </div>
                      </div>
                    </div>

                    {/* 3. LSTM Autoencoder */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3.5 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                          3 · LSTM AUTOENCODER
                        </span>
                        {!lstm.available ? (
                          <span className="inline-flex items-center gap-1 rounded bg-slate-800 border border-slate-700 px-2 py-0.5 text-xs font-bold text-slate-400">
                            <Info className="h-3.5 w-3.5 text-slate-400" /> Unavailable
                          </span>
                        ) : lstm.flagged ? (
                          <span className="inline-flex items-center gap-1 rounded bg-red-950/80 border border-red-500/40 px-2 py-0.5 text-xs font-bold text-red-300">
                            <CircleAlert className="h-3.5 w-3.5" /> Flagged
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-emerald-950/80 border border-emerald-500/40 px-2 py-0.5 text-xs font-bold text-emerald-300">
                            <CheckCircle2 className="h-3.5 w-3.5" /> Clear
                          </span>
                        )}
                      </div>

                      <div className="grid grid-cols-4 gap-2 text-xs pt-1">
                        <div>
                          <div className="text-[10px] text-slate-400">Reconstruction MSE</div>
                          <div className="font-mono font-bold text-slate-200">
                            {lstm.available ? formatNumber(lstm.mse, 4) : '—'}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400">Threshold</div>
                          <div className="font-mono font-bold text-slate-400">{formatNumber(lstm.threshold, 4)}</div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400">Prediction</div>
                          <div className="font-semibold text-slate-200">
                            {!lstm.available ? 'Unavailable' : (lstm.flagged ? 'Anomaly' : 'Normal')}
                          </div>
                        </div>
                        <div>
                          <div className="text-[10px] text-slate-400">Evidence Score</div>
                          <div className="font-mono font-bold text-slate-200">
                            {lstm.available ? formatNumber(lstm.evidenceScore, 3) : '—'}
                          </div>
                        </div>
                      </div>

                      {!lstm.available && (
                        <div className="text-[11px] text-slate-400 bg-slate-950/60 p-2 rounded border border-slate-800 italic mt-1">
                          Insufficient valid observations for 24-step sequence.
                        </div>
                      )}
                    </div>

                    {/* 4. Physical / Multivariate Consistency */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3.5 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                          4 · PHYSICAL / MULTIVARIATE CONSISTENCY
                        </span>
                        {physical.flagged ? (
                          <span className="inline-flex items-center gap-1 rounded bg-red-950/80 border border-red-500/40 px-2 py-0.5 text-xs font-bold text-red-300">
                            <CircleAlert className="h-3.5 w-3.5" /> Flagged
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-emerald-950/80 border border-emerald-500/40 px-2 py-0.5 text-xs font-bold text-emerald-300">
                            <CheckCircle2 className="h-3.5 w-3.5" /> Clear
                          </span>
                        )}
                      </div>

                      <div className="text-xs space-y-1 pt-1">
                        <div className="flex justify-between">
                          <span className="text-slate-400">Physical consistency score:</span>
                          <span className="font-mono font-bold text-slate-200">{formatNumber(physical.score, 3)}</span>
                        </div>
                        {physical.dewPoint != null && (
                          <div className="flex justify-between text-slate-400">
                            <span>Calculated Dew Point:</span>
                            <span className="font-mono text-cyan-300">{physical.dewPoint.toFixed(1)} °C</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* 5. Spatial Validation */}
                    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3.5 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                          5 · SPATIAL VALIDATION
                        </span>
                        {spatial.available ? (
                          spatial.flagged ? (
                            <span className="inline-flex items-center gap-1 rounded bg-red-950/80 border border-red-500/40 px-2 py-0.5 text-xs font-bold text-red-300">
                              <CircleAlert className="h-3.5 w-3.5" /> Flagged
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded bg-emerald-950/80 border border-emerald-500/40 px-2 py-0.5 text-xs font-bold text-emerald-300">
                              <CheckCircle2 className="h-3.5 w-3.5" /> Clear
                            </span>
                          )
                        ) : (
                          <span className="inline-flex items-center gap-1 rounded bg-slate-800 border border-slate-700 px-2 py-0.5 text-xs font-semibold text-slate-400">
                            Unavailable
                          </span>
                        )}
                      </div>

                      {spatial.available ? (
                        <div className="text-xs space-y-1">
                          <div className="flex justify-between">
                            <span className="text-slate-400">Status:</span>
                            <span className="font-semibold text-slate-200">{spatial.status}</span>
                          </div>
                          {spatial.buddyStation && (
                            <div className="flex justify-between">
                              <span className="text-slate-400">Buddy station:</span>
                              <span className="font-semibold text-slate-200">{spatial.buddyStation}</span>
                            </div>
                          )}
                          <div className="flex justify-between">
                            <span className="text-slate-400">Spatial evidence score:</span>
                            <span className="font-mono font-bold text-slate-200">{formatNumber(spatial.score, 3)}</span>
                          </div>
                        </div>
                      ) : (
                        <div className="text-xs text-slate-400 space-y-1 pt-1">
                          <p className="font-medium text-slate-300">
                            Unavailable — single-station observation; no buddy data supplied
                          </p>
                          <p className="text-[11px] text-slate-400 leading-tight">
                            Spatial validation is not included in evidence agreement when neighboring station data is missing.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()}

              {/* SECTION D: WHY WAS THIS ALERT GENERATED? */}
              <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2">
                  WHY WAS THIS ALERT GENERATED?
                </div>
                <div className="text-xs font-semibold text-slate-200 leading-relaxed bg-slate-900 p-3 rounded-lg border border-slate-800">
                  {getRootCause(selectedAlert)}
                </div>
              </div>

              {/* SECTION E: RECOVERY / ESTIMATION */}
              {(() => {
                const recovery = getRecoveryMeta(selectedAlert);
                const recMethod = getRecoveryMethod(selectedAlert);
                const recStatus = getRecoveryStatus(selectedAlert);
                const prevTs = getPreviousObservationTimestamp(selectedAlert) || recovery.previousTimestamp;
                const nextTs = getNextObservationTimestamp(selectedAlert) || recovery.nextTimestamp;
                const rawValue = getObservedValueForParameter(selectedAlert, recovery.parameter);

                return (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-3">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span>RECOVERY / ESTIMATION</span>
                        <span className={`rounded px-2 py-0.5 text-[9px] font-bold uppercase ${recStatus === 'AVAILABLE' ? 'bg-cyan-950/80 text-cyan-300 border border-cyan-500/40' : 'bg-slate-800 text-slate-400 border border-slate-700'}`}>
                          {recStatus}
                        </span>
                      </div>
                      <Wrench className="h-4 w-4 text-slate-400" />
                    </div>

                    {recovery.estimatedValue != null ? (
                      <div className="space-y-3">
                        <div className="grid grid-cols-2 gap-3">
                          <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
                            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Observed Value</div>
                            <div className="mt-1 text-base font-bold text-slate-100">
                              {rawValue != null ? `${rawValue} ${recovery.unit}` : '—'}
                            </div>
                          </div>

                          <div className="rounded-lg border border-cyan-500/30 bg-cyan-950/30 p-3">
                            <div className="text-[10px] font-bold uppercase tracking-wider text-cyan-400">{recovery.label}</div>
                            <div className="mt-1 text-base font-bold text-cyan-200">
                              {recovery.estimatedValue.toFixed(1)} {recovery.unit}
                            </div>
                            <div className="mt-0.5 text-[10px] text-cyan-400/80">{recMethod || 'Temporal neighbor interpolation'}</div>
                          </div>
                        </div>

                        {(prevTs || nextTs) && (
                          <div className="rounded-lg border border-slate-800 bg-slate-900 p-2.5 text-xs text-slate-400 space-y-1">
                            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Chronological Neighbors Used</div>
                            <div className="grid grid-cols-2 gap-2 text-[11px]">
                              <div><span className="text-slate-400">Previous:</span> <span className="font-mono text-slate-200">{prevTs || 'N/A'}</span></div>
                              <div><span className="text-slate-400">Next:</span> <span className="font-mono text-slate-200">{nextTs || 'N/A'}</span></div>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="rounded-lg bg-slate-900 p-3 text-xs text-slate-400 border border-slate-800">
                        <div className="flex items-center justify-between">
                          <span className="text-slate-400">Estimated value:</span>
                          <span className="font-bold text-slate-200">—</span>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-400">
                          Recovery unavailable for this observation (requires chronologically adjacent valid station observations).
                        </p>
                      </div>
                    )}

                    <div className="text-[11px] text-slate-400 bg-slate-950/60 p-2.5 rounded border border-slate-800">
                      <span className="font-semibold text-slate-300">Data policy:</span> Raw observation values are strictly preserved without overwrite. Estimated values are stored in separate channels.
                    </div>
                  </div>
                );
              })()}

              {/* SECTION F: MAINTENANCE ACTION */}
              {(() => {
                const actionStatus = getMaintenanceStatus(selectedAlert);
                const recAction = getMaintenanceAction(selectedAlert);

                return (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-2">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                      MAINTENANCE ACTION
                    </div>
                    <div className="flex items-start gap-3 bg-amber-950/30 border border-amber-500/40 p-3 rounded-lg">
                      <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
                      <div>
                        <div className="text-sm font-bold text-amber-300">{actionStatus}</div>
                        {recAction && (
                          <div className="mt-1 text-xs text-amber-200/80 leading-relaxed">{recAction}</div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* SECTION G: ALERT STATUS / WORKFLOW */}
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 text-xs text-slate-400">
                <div className="font-bold text-slate-300 mb-1">ALERT WORKFLOW STATE</div>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Backend alert state unavailable (SkyGuard processes telemetry deterministically in real time; persistent alert acknowledge/resolve states are not saved in backend database).
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
