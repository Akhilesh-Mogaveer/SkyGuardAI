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
  clearAnomalies,
} from './services/api';


/* =========================================================
   BACKEND CONFIGURATION
   ========================================================= */

// WebSocket backend URL
//
// For local frontend:
// localhost:3000
//
// WebSocket connects directly to Render backend.
const WS_BACKEND_URL =
  import.meta.env.VITE_WS_URL ||
  'https://skyguard-backend-kmko.onrender.com';

const WS_URL =
  WS_BACKEND_URL.replace(/^http:/, 'ws:')
               .replace(/^https:/, 'wss:') +
  '/ws/observations';


export default function App() {

  /* =======================================================
     STATE
     ======================================================= */

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


  /* =======================================================
     REFS
     ======================================================= */

  const wsRef = useRef(null);

  const reconnectTimeoutRef = useRef(null);

  const isUnmountedRef = useRef(false);


  /* =======================================================
     INITIAL DATA FETCHING
     ======================================================= */

  const loadInitialData = async (forceReset = false) => {

    try {

      const [
        hRes,
        stRes,
        shRes,
        obsRes,
        anomRes,
        statsRes,
        repRes,
      ] = await Promise.all([

        fetchHealth().catch(() => null),

        fetchStations().catch(() => []),

        fetchSensorHealth().catch(() => null),

        fetchObservations(1000).catch(() => []),

        fetchAnomalies(10).catch(() => []),

        fetchStatistics().catch(() => null),

        fetchReplayStatus().catch(() => null),

      ]);


      /* ---------------- HEALTH ---------------- */

      if (hRes) {
        setSystemHealth(hRes);
      }


      /* ---------------- STATIONS ---------------- */

      if (stRes) {

        setStations(
          Array.isArray(stRes)
            ? stRes
            : stRes?.stations || []
        );

      }


      /* ---------------- SENSOR HEALTH ---------------- */

      if (shRes) {
        setSensorHealth(shRes);
      }


      /* ---------------- OBSERVATIONS ---------------- */

      if (obsRes) {

        const fetchedObs =
          Array.isArray(obsRes)
            ? obsRes
            : obsRes?.observations || [];


        if (forceReset) {

          setObservations(fetchedObs);

        } else {

          setObservations((prev) => {

            const map = new Map();


            prev.forEach((o) => {

              const key =
                o.db_id
                  ? `db_${o.db_id}`
                  : o._instance_id ||
                    JSON.stringify(o);

              map.set(key, o);

            });


            fetchedObs.forEach((o) => {

              const key =
                o.db_id
                  ? `db_${o.db_id}`
                  : o._instance_id ||
                    JSON.stringify(o);

              map.set(key, o);

            });


            return Array.from(map.values());

          });

        }

      } else if (forceReset) {

        setObservations([]);

      }


      /* ---------------- ANOMALIES ---------------- */

      if (anomRes) {

        const fetchedAnom =
          Array.isArray(anomRes)
            ? anomRes
            : anomRes?.anomalies || [];


        if (forceReset) {

          setAnomalies(fetchedAnom);

        } else {

          setAnomalies((prev) => {

            const map = new Map();


            prev.forEach((a) => {

              const key =
                a.db_id
                  ? `db_${a.db_id}`
                  : a._instance_id ||
                    JSON.stringify(a);

              map.set(key, a);

            });


            fetchedAnom.forEach((a) => {

              const key =
                a.db_id
                  ? `db_${a.db_id}`
                  : a._instance_id ||
                    JSON.stringify(a);

              map.set(key, a);

            });


            return Array.from(map.values());

          });

        }

      } else if (forceReset) {

        setAnomalies([]);

      }


      /* ---------------- STATISTICS ---------------- */

      if (statsRes) {
        setStatistics(statsRes);
      }


      /* ---------------- REPLAY ---------------- */

      if (repRes) {
        setReplayStatus(repRes);
      }

    } catch (error) {

      console.error(
        'Failed to load initial backend state:',
        error
      );

    }

  };


  /* =======================================================
     CLEAR ALERTS
     ======================================================= */

  const handleClearAlerts = async () => {
  try {
    await clearAnomalies();
  } catch (err) {
    console.error('Failed to clear backend anomalies:', err);
  }

  setObservations([]);
  setAnomalies([]);

  await loadInitialData(true);
};


  /* =======================================================
     OBSERVATION UNIQUE KEY
     ======================================================= */

  const getObsKey = (observation) => {

    return getAlertUniqueId(observation);

  };


  /* =======================================================
     HANDLE NEW OBSERVATION
     ======================================================= */

  const handleObservationProcessed = (obs) => {

    if (!obs) return;


    const key = getObsKey(obs);


    /* -----------------------------------------------------
       Determine classification
       ----------------------------------------------------- */

    const classification =
      obs.final_classification ||
      obs.FINAL_CLASSIFICATION ||
      obs.decision?.primary_classification ||
      obs.decision?.classification ||
      obs.classification;


    /* -----------------------------------------------------
       Add observation
       ----------------------------------------------------- */

    setObservations((prev) => {

      const exists = prev.some(
        (o) => getObsKey(o) === key
      );


      if (exists) {
        return prev;
      }


      return [
        {
          ...obs,
          _instance_id: key,
        },
        ...prev,
      ];

    });


    /* -----------------------------------------------------
       Add anomaly if not NORMAL
       ----------------------------------------------------- */

    if (
      classification &&
      classification !== 'NORMAL'
    ) {

      setLatestAlertEvent(obs);


      setAnomalies((prev) => {

        const exists = prev.some(
          (a) => getObsKey(a) === key
        );


        if (exists) {
          return prev;
        }


        return [
          {
            ...obs,
            _instance_id: key,
          },
          ...prev,
        ];

      });

    }


    /* -----------------------------------------------------
       Refresh statistics
       ----------------------------------------------------- */

    fetchStatistics()
      .then((data) => {

        if (data) {
          setStatistics(data);
        }

      })
      .catch(() => {});

  };


  /* =======================================================
     WEBSOCKET CONNECTION
     ======================================================= */

  useEffect(() => {

    isUnmountedRef.current = false;


    // Initial REST API data
    loadInitialData();


    let reconnectAttempts = 0;


    const connectWebSocket = () => {

      if (isUnmountedRef.current) {
        return;
      }


      // Prevent duplicate connections
      if (
        wsRef.current &&
        (
          wsRef.current.readyState === WebSocket.OPEN ||
          wsRef.current.readyState === WebSocket.CONNECTING
        )
      ) {

        return;

      }


      console.log(
        'SkyGuard WebSocket:',
        WS_URL
      );


      console.log(
        'Connecting to SkyGuard WebSocket...'
      );


      try {

        const socket = new WebSocket(WS_URL);


        wsRef.current = socket;


        /* -------------------------------------------------
           CONNECTED
           ------------------------------------------------- */

        socket.onopen = () => {

          console.log(
            'Connected to SkyGuard Live WebSocket'
          );


          reconnectAttempts = 0;

          setIsWsConnected(true);

        };


        /* -------------------------------------------------
           MESSAGE
           ------------------------------------------------- */

        socket.onmessage = (event) => {

          try {

            const data = JSON.parse(
              event.data
            );


            console.log(
              'SkyGuard WebSocket message:',
              data
            );


            if (
              data.type === 'NEW_OBSERVATION' ||
              data.event_type ===
                'SINGLE_OBSERVATION_PROCESSED' ||
              data.event_type ===
                'NEW_OBSERVATION' ||
              data.observation ||
              data.data
            ) {

              const obs =
                data.data ||
                data.observation ||
                data;


              if (
                obs &&
                (
                  obs.timestamp ||
                  obs.station_id
                )
              ) {

                handleObservationProcessed(
                  obs
                );

              }

            }

          } catch (error) {

            console.error(
              'Failed to parse WebSocket message:',
              error
            );

          }

        };


        /* -------------------------------------------------
           ERROR
           ------------------------------------------------- */

        socket.onerror = (error) => {

          console.warn(
            'SkyGuard WebSocket error:',
            error
          );


          setIsWsConnected(false);

        };


        /* -------------------------------------------------
           CLOSED
           ------------------------------------------------- */

        socket.onclose = (event) => {

          console.warn(
            'SkyGuard WebSocket closed.',
            {
              code: event.code,
              reason: event.reason,
            }
          );


          setIsWsConnected(false);


          wsRef.current = null;


          if (
            isUnmountedRef.current
          ) {

            return;

          }


          reconnectAttempts += 1;


          // Maximum delay = 30 seconds
          const delay = Math.min(
            3000 * reconnectAttempts,
            30000
          );


          console.log(
            `Reconnecting WebSocket in ${
              delay / 1000
            } seconds...`
          );


          reconnectTimeoutRef.current =
            setTimeout(
              connectWebSocket,
              delay
            );

        };


      } catch (error) {

        console.error(
          'Failed to create WebSocket:',
          error
        );


        setIsWsConnected(false);

      }

    };


    /* -----------------------------------------------------
       Start WebSocket
       ----------------------------------------------------- */

    connectWebSocket();


    /* =====================================================
       FALLBACK POLLING

       Even if WebSocket is unavailable, the dashboard
       will continue receiving backend data.
       ===================================================== */

    const pollingInterval =
      setInterval(() => {

        if (!isUnmountedRef.current) {

          loadInitialData(false);

        }

      }, 10000);


    /* =====================================================
       CLEANUP
       ===================================================== */

    return () => {

      isUnmountedRef.current = true;


      if (
        reconnectTimeoutRef.current
      ) {

        clearTimeout(
          reconnectTimeoutRef.current
        );

      }


      clearInterval(
        pollingInterval
      );


      if (wsRef.current) {

        wsRef.current.onopen = null;

        wsRef.current.onmessage = null;

        wsRef.current.onerror = null;

        wsRef.current.onclose = null;


        wsRef.current.close();

        wsRef.current = null;

      }

    };

  }, []);


  /* =======================================================
     REPLAY TOGGLE
     ======================================================= */

  const handleToggleReplay = async () => {

    try {

      if (
        replayStatus?.is_running
      ) {

        await stopReplay();

      } else {

        await startReplay(
          10,
          0
        );

      }


      const updatedStatus =
        await fetchReplayStatus();


      setReplayStatus(
        updatedStatus
      );

    } catch (error) {

      console.error(
        'Replay toggle failed:',
        error
      );

    }

  };


  /* =======================================================
     START REPLAY FROM ALERTS
     ======================================================= */

  const handleStartReplayFromAlerts =
    async () => {

      setActiveTab(
        'data-replay'
      );


      try {

        if (
          !replayStatus?.is_running
        ) {

          await startReplay(
            10,
            0
          );


          const status =
            await fetchReplayStatus();


          setReplayStatus(
            status
          );

        }

      } catch (error) {

        console.error(
          'Failed to start replay:',
          error
        );

      }

    };


  /* =======================================================
     RENDER
     ======================================================= */

  return (

    <div
      className="
        min-h-screen
        bg-slate-50
        text-slate-900
        flex
        flex-col
        font-sans
        antialiased
        selection:bg-sky-500
        selection:text-white
      "
    >

      {/* =================================================
          HEADER
          ================================================= */}

      <Header
        isWsConnected={isWsConnected}
        systemHealth={systemHealth}
        replayStatus={replayStatus}
        onToggleReplay={
          handleToggleReplay
        }
      />


      <div className="flex flex-1 relative">


        {/* =================================================
            SIDEBAR
            ================================================= */}

        <Sidebar
          activeTab={activeTab}
          setActiveTab={setActiveTab}
        />


        {/* =================================================
            MAIN CONTENT
            ================================================= */}

        <main
          className="
            flex-1
            p-6
            overflow-y-auto
            max-w-7xl
            mx-auto
            w-full
          "
        >


          {/* =================================================
              DASHBOARD
              ================================================= */}

          {activeTab === 'dashboard' && (

            <Dashboard
              statistics={statistics}
              sensorHealth={sensorHealth}
              stations={stations}
              observations={observations}
              onNavigateTab={
                setActiveTab
              }
            />

          )}


          {/* =================================================
              DEMO MODE
              ================================================= */}

          {activeTab === 'demo' && (

            <DemoMode />

          )}


          {/* =================================================
              STATIONS
              ================================================= */}

          {activeTab === 'stations' && (

            <Stations
              observations={observations}
              sensorHealth={sensorHealth}
              stations={stations}
            />

          )}


          {/* =================================================
              ALERTS
              ================================================= */}

          {activeTab === 'alerts' && (

            <Alerts
              anomalies={anomalies}
              observations={observations}
              stations={stations}
              latestAlertEvent={
                latestAlertEvent
              }
              onRefresh={
                loadInitialData
              }
              onClearAlerts={
                handleClearAlerts
              }
              onNavigateTab={
                setActiveTab
              }
              onStartReplay={
                handleStartReplayFromAlerts
              }
              replayStatus={
                replayStatus
              }
            />

          )}


          {/* =================================================
              DATA REPLAY
              ================================================= */}

          {activeTab === 'data-replay' && (

            <DataReplay
              observations={
                observations
              }
              replayStatus={
                replayStatus
              }
              onObservationProcessed={
                handleObservationProcessed
              }


              onStartReplay={
                async (speed) => {

                  try {

                    await startReplay(
                      speed,
                      0
                    );


                    const status =
                      await fetchReplayStatus();


                    setReplayStatus(
                      status
                    );

                  } catch (error) {

                    console.error(
                      'Failed to start replay:',
                      error
                    );

                  }

                }
              }


              onStopReplay={
                async () => {

                  try {

                    await stopReplay();


                    const status =
                      await fetchReplayStatus();


                    setReplayStatus(
                      status
                    );

                  } catch (error) {

                    console.error(
                      'Failed to stop replay:',
                      error
                    );

                  }

                }
              }

            />

          )}

        </main>

      </div>

    </div>

  );

}