import React from 'react';
import { LayoutDashboard, Radio, AlertOctagon, RefreshCw, Zap } from 'lucide-react';

export default function Sidebar({ activeTab, setActiveTab }) {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'stations', label: 'Stations', icon: Radio },
    { id: 'alerts', label: 'Alerts', icon: AlertOctagon },
    { id: 'data-replay', label: 'Data / Replay', icon: RefreshCw },
    { id: 'demo', label: 'Demo Mode', icon: Zap, highlight: true },
  ];

  return (
    <aside className="w-56 shrink-0 border-r border-slate-800 bg-[#0b192c] flex flex-col justify-between shadow-md">
      <div className="p-4">
        <div className="mb-3 px-3 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Operations</div>
        <nav className="space-y-1.5">
          {navItems.map(({ id, label, icon: Icon, highlight }) => {
            const active = activeTab === id;
            return (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`flex w-full items-center gap-3 rounded-lg px-3.5 py-2.5 text-sm font-semibold transition-all duration-150 ${
                  active
                    ? 'bg-sky-500/15 text-sky-400 border-l-4 border-sky-400 font-bold shadow-xs'
                    : 'text-slate-300 hover:bg-slate-800/80 hover:text-white'
                }`}
              >
                <Icon
                  className={`h-4 w-4 ${
                    active ? 'text-sky-400' : highlight ? 'text-amber-400' : 'text-slate-400'
                  }`}
                />
                <span>{label}</span>
                {highlight && (
                  <span
                    className={`ml-auto rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${
                      active
                        ? 'bg-amber-400/20 text-amber-300 border border-amber-400/40'
                        : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
                    }`}
                  >
                    SIH
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>
      <div className="border-t border-slate-800/80 p-4 text-[11px] leading-5 text-slate-400 font-medium">
        Operator-first view. Multi-pillar evidence engine continuously active.
      </div>
    </aside>
  );
}

