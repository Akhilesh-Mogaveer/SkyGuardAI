import React, { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, GeoJSON, useMap } from 'react-leaflet';
import { MapPinned, Layers3, Info, Maximize2 } from 'lucide-react';

const NETWORKS = {
  current: {
    label: 'Current IMD AWS network',
    total: 1008,
    sourceLabel: 'IMD AWS network · 2026',
    counts: {
      'Andhra Pradesh': 24, 'Arunachal Pradesh': 51, Assam: 55, Bihar: 35,
      Chhattisgarh: 21, Goa: 5, Gujarat: 41, Haryana: 30, 'Himachal Pradesh': 24,
      Jharkhand: 22, Karnataka: 31, Kerala: 109, 'Madhya Pradesh': 51, Maharashtra: 65,
      Manipur: 19, Meghalaya: 11, Mizoram: 6, Nagaland: 9, Odisha: 35, Punjab: 30,
      Rajasthan: 35, Sikkim: 5, 'Tamil Nadu': 51, Telangana: 24, Tripura: 11,
      Uttarakhand: 25, 'Uttar Pradesh': 65, 'West Bengal': 47,
      'Andaman and Nicobar': 12, Chandigarh: 3, 'Dadra and Nagar Haveli': 1,
      'Daman and Diu': 2, Delhi: 19, 'Jammu and Kashmir': 17, Ladakh: 12,
      Lakshadweep: 2, Puducherry: 3,
    },
  },
  proposed: {
    label: 'Proposed Agro AWS · 2026',
    total: 200,
    sourceLabel: 'Mission Mausam Phase-II · proposed 2026',
    counts: {
      'Andhra Pradesh': 0, 'Arunachal Pradesh': 4, Assam: 13, Bihar: 21,
      Chhattisgarh: 14, Goa: 0, Gujarat: 2, Haryana: 8, 'Himachal Pradesh': 0,
      Jharkhand: 0, Karnataka: 8, Kerala: 5, 'Madhya Pradesh': 17, Maharashtra: 11,
      Manipur: 2, Meghalaya: 2, Mizoram: 2, Nagaland: 2, Odisha: 0, Punjab: 4,
      Rajasthan: 10, Sikkim: 2, 'Tamil Nadu': 13, Telangana: 9, Tripura: 2,
      Uttarakhand: 3, 'Uttar Pradesh': 36, 'West Bengal': 8,
      'Andaman and Nicobar': 0, Chandigarh: 0, 'Dadra and Nagar Haveli': 0,
      'Daman and Diu': 0, Delhi: 1, 'Jammu and Kashmir': 1, Ladakh: 0,
      Lakshadweep: 0, Puducherry: 0,
    },
  },
};

const INDIA_STATES_GEOJSON_URL = 'https://raw.githubusercontent.com/geohacker/india/master/state/india_state.geojson';

function getStateName(feature) {
  const properties = feature?.properties || {};
  const name = properties.NAME_1 || properties.ST_NM || properties.st_nm || properties.name || properties.NAME || '';
  return {
    'NCT of Delhi': 'Delhi',
    'Jammu & Kashmir': 'Jammu and Kashmir',
    'Andaman & Nicobar': 'Andaman and Nicobar',
  }[name] || name;
}

function fillColor(count, maxCount) {
  if (!count) return '#1e293b';
  const intensity = Math.min(0.95, 0.25 + (count / maxCount) * 0.7);
  const r = Math.round(8 + intensity * 15);
  const g = Math.round(50 + intensity * 135);
  const b = Math.round(80 + intensity * 145);
  return `rgb(${r} ${g} ${b})`;
}

function FitIndia() {
  const map = useMap();
  React.useEffect(() => {
    map.setView([22.5, 79.0], 4.5, { animate: false });
  }, [map]);
  return null;
}

export default function AwsNetworkMap() {
  const [mode, setMode] = useState('current');
  const [selectedState, setSelectedState] = useState(null);
  const [stateGeoJson, setStateGeoJson] = useState(null);
  const [geoJsonError, setGeoJsonError] = useState(false);
  const network = NETWORKS[mode];
  const proposedNetwork = NETWORKS.proposed;

  useEffect(() => {
    const controller = new AbortController();
    fetch(INDIA_STATES_GEOJSON_URL, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`GeoJSON request failed: ${response.status}`);
        return response.json();
      })
      .then((data) => setStateGeoJson(data))
      .catch((error) => {
        if (error.name !== 'AbortError') setGeoJsonError(true);
      });
    return () => controller.abort();
  }, []);

  const ranked = useMemo(() => Object.entries(network.counts)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]), [network]);

  return (
    <section className="rounded-xl border border-slate-800 bg-[#090e1a]/80 shadow-md overflow-hidden backdrop-blur-md">
      <div className="px-5 py-4 border-b border-slate-800 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3 bg-slate-900/60">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-cyan-950/80 p-2 text-cyan-400 border border-cyan-500/30"><MapPinned className="h-5 w-5" /></div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold text-slate-100">India AWS Network</h3>
              <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-cyan-400 border border-slate-700">Network view</span>
            </div>
            <p className="mt-1 text-xs text-slate-400">{network.sourceLabel} · state/UT level coverage</p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-1">
            <button onClick={() => setMode('current')} className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${mode === 'current' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}>Current 1,008</button>
            <button onClick={() => setMode('proposed')} className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${mode === 'proposed' ? 'bg-cyan-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'}`}>Proposed 200</button>
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-slate-400"><Info className="h-3.5 w-3.5 text-cyan-400" /> State totals, not exact station coordinates</div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_290px]">
        <div className="relative h-[540px]">
          <MapContainer center={[22.5, 79]} zoom={4.5} minZoom={3.8} maxZoom={7} scrollWheelZoom className="h-full w-full">
            <FitIndia />
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {stateGeoJson && (
              <GeoJSON
                key={mode}
                data={stateGeoJson}
                style={(feature) => {
                  const state = getStateName(feature);
                  const count = NETWORKS.current.counts[state] || 0;
                  return {
                    color: selectedState === state ? '#38bdf8' : '#334155',
                    weight: selectedState === state ? 2.5 : 0.8,
                    fillColor: fillColor(count, Math.max(...Object.values(NETWORKS.current.counts))),
                    fillOpacity: selectedState === state ? 0.88 : 0.68,
                  };
                }}
                onEachFeature={(feature, layer) => {
                  const state = getStateName(feature);
                  const currentCount = NETWORKS.current.counts[state] || 0;
                  const proposedCount = proposedNetwork.counts[state];
                  layer.on({ click: () => setSelectedState(state) });
                  layer.bindPopup(`
                    <div class="min-w-[190px] font-sans">
                      <div class="text-sm font-bold text-slate-100">${state || 'State / UT'}</div>
                      <div class="mt-2 flex items-center justify-between gap-4"><span class="text-xs text-slate-400">Current AWS</span><strong class="text-base text-cyan-400 font-mono">${currentCount}</strong></div>
                      <div class="mt-1 flex items-center justify-between gap-4"><span class="text-xs text-slate-400">Proposed Agro AWS</span><strong class="text-base text-emerald-400 font-mono">${proposedCount ?? 'N/A'}</strong></div>
                    </div>
                  `);
                }}
              />
            )}
          </MapContainer>

          {geoJsonError && (
            <div className="absolute left-4 bottom-4 z-[1000] rounded-lg border border-amber-500/40 bg-amber-950/90 px-3 py-2 text-[10px] text-amber-300 shadow-md">
              State boundaries could not be loaded. Check your network connection.
            </div>
          )}

          <div className="absolute right-4 top-4 z-[1000] rounded-xl border border-slate-800 bg-[#090e1a]/90 px-3.5 py-2.5 shadow-md backdrop-blur-md">
            <div className="flex items-center gap-2 text-xs font-bold text-slate-100"><Layers3 className="h-4 w-4 text-cyan-400" /> {network.total.toLocaleString()} AWS stations</div>
            <div className="mt-0.5 text-[10px] text-slate-400">Darker cyan shading means more AWS stations</div>
          </div>
        </div>

        <aside className="border-t xl:border-t-0 xl:border-l border-slate-800 bg-slate-900/60">
          <div className="px-4 py-4 border-b border-slate-800">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Network summary</div>
            <div className="mt-1 text-2xl font-bold text-cyan-300 font-mono">{network.total.toLocaleString()}</div>
            <div className="text-xs text-slate-400">AWS stations in source network</div>
          </div>
          <div className="max-h-[470px] overflow-y-auto divide-y divide-slate-800/80">
            {ranked.map(([state, count], index) => (
              <button key={state} onClick={() => setSelectedState(state)} className={`w-full px-4 py-3 text-left flex items-center justify-between transition hover:bg-slate-800/80 ${selectedState === state ? 'bg-cyan-950/60 border-l-2 border-cyan-400' : ''}`}>
                <div className="flex items-center gap-3 min-w-0">
                  <span className="w-5 text-[10px] font-bold text-slate-400 font-mono">{index + 1}</span>
                  <span className="text-xs font-semibold text-slate-200 truncate">{state}</span>
                </div>
                <span className="text-sm font-bold text-cyan-400 font-mono">{count}</span>
              </button>
            ))}
          </div>
        </aside>
      </div>

      <div className="px-5 py-3 border-t border-slate-800 bg-slate-900/80 flex items-start gap-2 text-[11px] text-slate-400">
        <Info className="h-3.5 w-3.5 mt-0.5 shrink-0 text-cyan-400" />
        <p>The uploaded PIB release reports AWS totals by state/UT. It does not provide individual station latitude/longitude, so markers represent the state/UT network count rather than exact station locations.</p>
      </div>
    </section>
  );
}
