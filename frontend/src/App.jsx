import React, { useState, useEffect, useRef } from 'react';
import Header from './components/Header';
import Sidebar from './components/Sidebar';

// Pages
import Dashboard from './pages/Dashboard';
import DemoMode from './pages/DemoMode';
import Stations from './pages/Stations';
import Alerts from './pages/Alerts';
import DataReplay from './pages/DataReplay';

import { getAlertUniqueId } from './utils/observation';

// API Services
import {
  fetchHealth,
  fetchStations,
  fetchSensorHealth,
  fetchObservations,
  fetchAnomalies,
  fetchStatistics,
  fetchReplayStatus,
  startReplay,
  stopReplay,
} from './services/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [isWsConnected, setIsWsConnected] = useState(false);
  const [systemHealth, setSystemHealth] = useState(null);
  const [stations, setStations] = useState([]);
  const [sensorHealth, setSensorHealth] = useState(null);
  const [observations, setObservations] = useState([]);
  const [anomalies, setAnomalies] = useState([]);
  const [latestAlertEvent, setLatestAlertEvent] = useState(null);
  const [statistics, setStatistics] = useState(null);
  const [replayStatus, setReplayStatus] = useState(null);

  const wsRef = useRef(null);

  // Initial Data Fetching
  const loadInitialData = async (forceReset = false) => {
    try {
      const [hRes, stRes, shRes, obsRes, anomRes, statsRes, repRes] = await Promise.all([
        fetchHealth().catch(() => null),
        fetchStations().catch(() => []),
        fetchSensorHealth().catch(() => null),
        fetchObservations(1000).catch(() => []),
        fetchAnomalies(10).catch(() => []),
        fetchStatistics().catch(() => null),
        fetchReplayStatus().catch(() => null),
      ]);

      if (hRes) setSystemHealth(hRes);
      if (stRes) setStations(Array.isArray(stRes) ? stRes : (stRes?.stations || []));
      if (shRes) setSensorHealth(shRes);

      if (obsRes) {
        const fetchedObs = Array.isArray(obsRes) ? obsRes : (obsRes?.observations || []);
        if (forceReset) {
          setObservations(fetchedObs);
        } else {
          setObservations((prev) => {
            const map = new Map();
            prev.forEach((o) => {
              const key = o.db_id ? `db_${o.db_id}` : o._instance_id || JSON.stringify(o);
              map.set(key, o);
            });
            fetchedObs.forEach((o) => {
              const key = o.db_id ? `db_${o.db_id}` : o._instance_id || JSON.stringify(o);
              map.set(key, o);
            });
            return Array.from(map.values());
          });
        }
      } else if (forceReset) {
        setObservations([]);
      }

      if (anomRes) {
        const fetchedAnom = Array.isArray(anomRes) ? anomRes : (anomRes?.anomalies || []);
        if (forceReset) {
          setAnomalies(fetchedAnom);
        } else {
          setAnomalies((prev) => {
            const map = new Map();
            prev.forEach((a) => {
              const key = a.db_id ? `db_${a.db_id}` : a._instance_id || JSON.stringify(a);
              map.set(key, a);
            });
            fetchedAnom.forEach((a) => {
              const key = a.db_id ? `db_${a.db_id}` : a._instance_id || JSON.stringify(a);
              map.set(key, a);
            });
            return Array.from(map.values());
          });
        }
      } else if (forceReset) {
        setAnomalies([]);
      }

      if (statsRes) setStatistics(statsRes);
      if (repRes) setReplayStatus(repRes);
    } catch (err) {
      console.error('Failed to load initial backend state:', err);
    }
  };

  // Clear all alerts and observations from both backend DB and React memory
  const handleClearAlerts = async () => {
    try {
      await fetch('/api/anomalies/clear', { method: 'POST' });
    } catch (err) {
      console.error('Failed to clear backend anomalies:', err);
    }
    setObservations([]);
    setAnomalies([]);
    await loadInitialData(true);
  };

  const getObsKey = (o) => {
    return getAlertUniqueId(o);
  };

  // Helper to ingest single observation into memory state without dropping historical records
  const handleObservationProcessed = (obs) => {
    if (!obs) return;
    const key = getObsKey(obs);

    const classification =
      obs.final_classification ||
      obs.FINAL_CLASSIFICATION ||
      obs.decision?.primary_classification ||
      obs.decision?.classification ||
      obs.classification;

    setObservations((prev) => {
      const exists = prev.some((o) => getObsKey(o) === key);
      if (exists) return prev;
      return [{ ...obs, _instance_id: key }, ...prev];
    });

    if (classification && classification !== 'NORMAL') {
      setLatestAlertEvent(obs);
      setAnomalies((prev) => {
        const exists = prev.some((a) => getObsKey(a) === key);
        if (exists) return prev;
        return [{ ...obs, _instance_id: key }, ...prev];
      });
    }

    fetchStatistics().then(setStatistics).catch(() => {});
  };

  useEffect(() => {
    loadInitialData();

    // Setup WebSocket for real-time observation streaming
    const protocol =
    window.location.protocol === 'https:' ? 'wss:' : 'ws:';

    const wsUrl =
    `${protocol}//${window.location.host}/ws/observations`;

    const ws = new WebSocket(wsUrl);
    let socket;

    const connectWs = () => {
      try {
        socket = new WebSocket(wsUrl);
        wsRef.current = socket;

        socket.onopen = () => {
          setIsWsConnected(true);
          console.log('Connected to SkyGuard Live WebSocket');
        };

        socket.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (
              data.type === 'NEW_OBSERVATION' ||
              data.event_type === 'SINGLE_OBSERVATION_PROCESSED' ||
              data.event_type === 'NEW_OBSERVATION' ||
              data.observation ||
              data.data
            ) {
              const obs = data.data || data.observation || data;
              if (obs && (obs.timestamp || obs.station_id)) {
                handleObservationProcessed(obs);
              }
            }
          } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
          }
        };

        socket.onclose = () => {
          setIsWsConnected(false);
          setTimeout(connectWs, 3000);
        };

        socket.onerror = () => {
          setIsWsConnected(false);
        };
      } catch (err) {
        setIsWsConnected(false);
      }
    };

    connectWs();

    return () => {
      if (socket) socket.close();
    };
  }, []);

  // Replay Toggle
  const handleToggleReplay = async () => {
    try {
      if (replayStatus?.is_running) {
        await stopReplay();
      } else {
        await startReplay(10, 0);
      }
      const updatedStatus = await fetchReplayStatus();
      setReplayStatus(updatedStatus);
    } catch (err) {
      console.error('Replay toggle failed:', err);
    }
  };

  return (
    <div className="min-h-screen bg-[#0b1329] text-slate-100 flex flex-col font-sans antialiased selection:bg-cyan-500 selection:text-slate-950">
      {/* Top Sticky Header */}
      <Header
        isWsConnected={isWsConnected}
        systemHealth={systemHealth}
        replayStatus={replayStatus}
        onToggleReplay={handleToggleReplay}
      />

      <div className="flex flex-1 relative">
        {/* Left Sidebar Navigation */}
        <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

        {/* Main Content View Container */}
        <main className="flex-1 p-6 overflow-y-auto max-w-7xl mx-auto w-full">
          {activeTab === 'dashboard' && (
            <Dashboard
              statistics={statistics}
              sensorHealth={sensorHealth}
              stations={stations}
              observations={observations}
              onNavigateTab={setActiveTab}
            />
          )}

          {activeTab === 'demo' && (
            <DemoMode />
          )}

          {activeTab === 'stations' && (
            <Stations
              observations={observations}
              sensorHealth={sensorHealth}
              stations={stations}
            />
          )}

          {activeTab === 'alerts' && (
            <Alerts
              anomalies={anomalies}
              observations={observations}
              stations={stations}
              latestAlertEvent={latestAlertEvent}
              onRefresh={loadInitialData}
              onClearAlerts={handleClearAlerts}
              onNavigateTab={setActiveTab}
              onStartReplay={async () => {
                setActiveTab('data-replay');
                if (!replayStatus?.is_running) {
                  await startReplay(10, 0);
                  const s = await fetchReplayStatus();
                  setReplayStatus(s);
                }
              }}
              replayStatus={replayStatus}
            />
          )}

          {activeTab === 'data-replay' && (
            <DataReplay
              observations={observations}
              replayStatus={replayStatus}
              onObservationProcessed={handleObservationProcessed}
              onStartReplay={async (speed) => {
                await startReplay(speed, 0);
                const s = await fetchReplayStatus();
                setReplayStatus(s);
              }}
              onStopReplay={async () => {
                await stopReplay();
                const s = await fetchReplayStatus();
                setReplayStatus(s);
              }}
            />
          )}
        </main>
      </div>
    </div>
  );
}
