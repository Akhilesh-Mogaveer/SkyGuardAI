import React from 'react';
import { RefreshCw, Wifi, WifiOff, Activity } from 'lucide-react';

export default function Header({ isWsConnected, replayStatus, onToggleReplay }) {
  return (
    <header className="sticky top-0 z-50 flex items-center justify-between border-b border-slate-800 bg-[#090e1a]/90 backdrop-blur-md px-6 py-3.5 shadow-md">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.2)]">
          <Activity className="h-5 w-5" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-extrabold tracking-tight text-white uppercase">SkyGuard <span className="text-cyan-400">AI</span></h1>
            <span className="rounded bg-cyan-950/80 border border-cyan-500/30 px-2 py-0.5 text-[10px] font-bold text-cyan-300 tracking-wider">
              WEATHER INTELLIGENCE
            </span>
          </div>
          <p className="text-[11px] text-slate-400 font-medium">Automatic Weather Station Monitoring & Fault Detection</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleReplay}
          className={`inline-flex items-center gap-2 rounded-lg border px-3.5 py-1.5 text-xs font-semibold transition-all shadow-sm ${
            replayStatus?.is_running
              ? 'border-amber-500/40 bg-amber-950/40 text-amber-300 hover:bg-amber-900/50'
              : 'border-slate-700 bg-slate-900/80 text-slate-200 hover:border-cyan-500/50 hover:text-cyan-300 hover:bg-slate-800'
          }`}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${replayStatus?.is_running ? 'animate-spin text-amber-400' : 'text-cyan-400'}`} />
          {replayStatus?.is_running ? `Replay ${replayStatus.speed_multiplier}x` : 'Start Replay'}
        </button>
        <div
          className={`inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-semibold ${
            isWsConnected
              ? 'border-emerald-500/40 bg-emerald-950/50 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.15)]'
              : 'border-slate-800 bg-slate-900 text-slate-400'
          }`}
        >
          {isWsConnected ? <Wifi className="h-3.5 w-3.5 text-emerald-400" /> : <WifiOff className="h-3.5 w-3.5" />}
          {isWsConnected ? 'Stream Active' : 'Offline'}
        </div>
      </div>
    </header>
  );
}
