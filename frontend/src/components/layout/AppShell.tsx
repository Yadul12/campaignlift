"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  FileSpreadsheet,
  Filter,
  FlaskConical,
  GitCompareArrows,
  Layers,
  LayoutDashboard,
  RotateCcw,
  SlidersHorizontal,
  Users,
  Wallet,
} from "lucide-react";
import { useFilters } from "@/context/FilterContext";

const NAV_GROUPS = [
  {
    heading: "Commercial Portfolio",
    items: [
      { href: "/", label: "Executive Overview", icon: LayoutDashboard },
      { href: "/campaigns", label: "Campaign Performance", icon: BarChart3 },
      { href: "/funnel", label: "Campaign Funnel", icon: Layers },
    ],
  },
  {
    heading: "Causal & Unit Economics",
    items: [
      { href: "/experiments", label: "Experimentation Lab", icon: FlaskConical },
      { href: "/economics", label: "Promotion Economics", icon: Wallet },
      { href: "/customers", label: "Customer Response", icon: Users },
    ],
  },
  {
    heading: "Investment Decisions",
    items: [
      { href: "/compare", label: "Campaign Comparison", icon: GitCompareArrows },
      { href: "/simulator", label: "Budget Simulator", icon: SlidersHorizontal },
      { href: "/reports", label: "Reports & SQL", icon: FileSpreadsheet },
    ],
  },
];

function MeridianMark() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0">
      <rect x="1" y="1" width="22" height="22" rx="4" fill="#0F2942" />
      <path d="M5 16.5L12 6.5L19 16.5" stroke="#FFFFFF" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8.5 16.5L12 11.2L15.5 16.5" stroke="#7FB3E6" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="5" y1="18.8" x2="19" y2="18.8" stroke="#94A3B8" strokeWidth="1.1" />
    </svg>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { filters, options, setFilter, setMultipleFilters, resetFilters, activeFilterCount } = useFilters();

  const applyDatePreset = (preset: string) => {
    if (preset === "all") {
      setMultipleFilters({ start_date: "", end_date: "" });
    } else if (preset === "2026") {
      setMultipleFilters({ start_date: "2026-01-01", end_date: "2026-12-31" });
    } else if (preset === "2025") {
      setMultipleFilters({ start_date: "2025-01-01", end_date: "2025-12-31" });
    } else if (preset === "2024") {
      setMultipleFilters({ start_date: "2024-01-01", end_date: "2024-12-31" });
    } else if (preset === "last12m") {
      setMultipleFilters({ start_date: "2025-09-01", end_date: "2026-09-30" });
    }
  };

  return (
    <div className="min-h-screen flex bg-[#F6F7F9] text-[#0F1E2E]">
      {/* Fixed Left Enterprise Rail */}
      <aside className="w-[210px] shrink-0 bg-white border-r border-[#E2E6EC] flex flex-col sticky top-0 h-screen">
        <div className="px-4 py-3.5 border-b border-[#EEF1F5] flex items-center gap-2.5">
          <MeridianMark />
          <div className="min-w-0">
            <div className="text-[14px] font-semibold tracking-[-0.02em] text-[#0F2942] leading-none">
              CampaignLift
            </div>
            <div className="text-[10px] font-medium uppercase tracking-[0.06em] text-[#64748B] mt-1">
              Meridian Air Commercial
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-2.5 py-3 space-y-4">
          {NAV_GROUPS.map((group) => (
            <div key={group.heading}>
              <div className="px-2.5 mb-1.5 text-[10px] font-semibold uppercase tracking-[0.07em] text-[#64748B]">
                {group.heading}
              </div>
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = pathname === item.href;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className={`flex items-center gap-2.5 px-2.5 py-2 rounded-[4px] text-[12.5px] transition-colors ${
                          active
                            ? "bg-[#EFF4F9] text-[#0F2942] font-semibold border-l-[3px] border-[#0F2942] pl-[7px]"
                            : "text-[#475569] hover:bg-[#F8FAFC] hover:text-[#0F1E2E]"
                        }`}
                      >
                        <Icon className={`w-4 h-4 shrink-0 ${active ? "text-[#0F2942]" : "text-[#64748B]"}`} />
                        <span className="truncate">{item.label}</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className="px-3.5 py-3 border-t border-[#EEF1F5] bg-[#FAFBFD] text-[10.5px] text-[#64748B] space-y-1">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-[#0F2942]">SIMULATED DATA</span>
            <span className="font-mono-num text-[10px] px-1.5 py-0.5 bg-[#EFF4F9] text-[#1E5B94] rounded-[3px]">
              Seed 20260401
            </span>
          </div>
          <p className="leading-snug text-[10px]">
            Synthetic airline CRM &amp; randomized experiment dataset. All metrics computed live from PostgreSQL.
          </p>
        </div>
      </aside>

      {/* Main Content Workspace */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Global Analytical Filter Bar */}
        <header className="sticky top-0 z-20 bg-white border-b border-[#E2E6EC] px-4 py-2">
          <div className="flex flex-wrap xl:flex-nowrap items-center gap-1.5">
            <div className="flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-[0.05em] text-[#475569] mr-0.5 shrink-0">
              <Filter className="w-3 h-3 text-[#1E5B94]" />
              <span>Scope</span>
            </div>

            {/* Quick Period Presets */}
            <div className="inline-flex rounded-[4px] border border-[#CBD5E1] overflow-hidden text-[10.5px] shrink-0">
              {[
                { id: "all", label: "All" },
                { id: "2024", label: "2024" },
                { id: "2025", label: "2025" },
                { id: "2026", label: "2026" },
                { id: "last12m", label: "L12M" },
              ].map((p) => {
                const isActive =
                  (p.id === "all" && !filters.start_date && !filters.end_date) ||
                  (p.id === "2024" && filters.start_date === "2024-01-01" && filters.end_date === "2024-12-31") ||
                  (p.id === "2025" && filters.start_date === "2025-01-01" && filters.end_date === "2025-12-31") ||
                  (p.id === "2026" && filters.start_date === "2026-01-01" && filters.end_date === "2026-12-31") ||
                  (p.id === "last12m" && filters.start_date === "2025-09-01" && filters.end_date === "2026-09-30");
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => applyDatePreset(p.id)}
                    className={`px-1.5 py-1 font-medium cursor-pointer border-r last:border-r-0 border-[#CBD5E1] ${
                      isActive ? "bg-[#0F2942] text-white" : "bg-white text-[#475569] hover:bg-[#F8FAFC]"
                    }`}
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>

            {/* Date Inputs */}
            <input
              type="date"
              aria-label="Start date"
              value={filters.start_date}
              onChange={(e) => setFilter("start_date", e.target.value)}
              className="h-[27px] w-[112px] px-1.5 text-[11px] font-mono-num bg-white border border-[#CBD5E1] rounded-[4px] text-[#0F1E2E] focus:outline-none focus:border-[#1E5B94] shrink-0"
            />
            <span className="text-[10px] text-[#94A3B8] shrink-0">–</span>
            <input
              type="date"
              aria-label="End date"
              value={filters.end_date}
              onChange={(e) => setFilter("end_date", e.target.value)}
              className="h-[27px] w-[112px] px-1.5 text-[11px] font-mono-num bg-white border border-[#CBD5E1] rounded-[4px] text-[#0F1E2E] focus:outline-none focus:border-[#1E5B94] shrink-0"
            />

            {/* Study Design */}
            <select
              aria-label="Study design"
              value={filters.experiment_type}
              onChange={(e) => setFilter("experiment_type", e.target.value)}
              className="h-[27px] px-1.5 text-[11px] bg-white border border-[#CBD5E1] rounded-[4px] text-[#0F1E2E] focus:outline-none focus:border-[#1E5B94] max-w-[118px] min-w-0"
            >
              <option value="">All Studies</option>
              <option value="RCT">RCT Only</option>
              <option value="Observational">Observational</option>
            </select>

            {/* Channel */}
            <select
              aria-label="Marketing channel"
              value={filters.channel_id}
              onChange={(e) => setFilter("channel_id", e.target.value)}
              className="h-[27px] px-1.5 text-[11px] bg-white border border-[#CBD5E1] rounded-[4px] text-[#0F1E2E] focus:outline-none focus:border-[#1E5B94] max-w-[116px] min-w-0"
            >
              <option value="">All Channels</option>
              {options?.channels.map((c) => (
                <option key={c.channel_id} value={String(c.channel_id)}>
                  {c.channel_name}
                </option>
              ))}
            </select>

            {/* Customer Segment */}
            <select
              aria-label="Customer segment"
              value={filters.segment_id}
              onChange={(e) => setFilter("segment_id", e.target.value)}
              className="h-[27px] px-1.5 text-[11px] bg-white border border-[#CBD5E1] rounded-[4px] text-[#0F1E2E] focus:outline-none focus:border-[#1E5B94] max-w-[132px] min-w-0"
            >
              <option value="">All Segments</option>
              {options?.segments.map((s) => (
                <option key={s.segment_id} value={String(s.segment_id)}>
                  {s.segment_name}
                </option>
              ))}
            </select>

            {/* Route Market */}
            <select
              aria-label="Route market"
              value={filters.route_market_id}
              onChange={(e) => setFilter("route_market_id", e.target.value)}
              className="h-[27px] px-1.5 text-[11px] bg-white border border-[#CBD5E1] rounded-[4px] text-[#0F1E2E] focus:outline-none focus:border-[#1E5B94] max-w-[122px] min-w-0"
            >
              <option value="">All Routes</option>
              {options?.routes.map((r) => (
                <option key={r.route_market_id} value={String(r.route_market_id)}>
                  {r.market_code} · {r.market_region}
                </option>
              ))}
            </select>

            {/* Campaign Selector */}
            <select
              aria-label="Campaign"
              value={filters.campaign_id}
              onChange={(e) => setFilter("campaign_id", e.target.value)}
              className="h-[27px] px-1.5 text-[11px] bg-white border border-[#CBD5E1] rounded-[4px] text-[#0F1E2E] focus:outline-none focus:border-[#1E5B94] flex-1 min-w-[125px] max-w-[180px]"
            >
              <option value="">All Campaigns ({options?.campaigns.length || 108})</option>
              {options?.campaigns.map((c) => (
                <option key={c.campaign_id} value={String(c.campaign_id)}>
                  {c.campaign_code} ({c.experiment_type}) · {c.campaign_name}
                </option>
              ))}
            </select>

            {activeFilterCount > 0 && (
              <button
                type="button"
                onClick={resetFilters}
                className="h-[27px] px-2 inline-flex items-center gap-1 text-[11px] font-medium text-[#1E5B94] bg-[#EFF6FF] border border-[#BFDBFE] rounded-[4px] hover:bg-[#DBEAFE] cursor-pointer shrink-0"
              >
                <RotateCcw className="w-3 h-3" />
                Reset ({activeFilterCount})
              </button>
            )}
          </div>
        </header>

        <main className="flex-1 px-6 py-5 max-w-[1620px] w-full mx-auto space-y-5">{children}</main>
      </div>
    </div>
  );
}
