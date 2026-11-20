"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, Download, ExternalLink, Search, X } from "lucide-react";
import { useFilters } from "@/context/FilterContext";
import { apiGet, buildFilterQueryString, triggerFileDownload } from "@/lib/api";
import { fmtCurrency, fmtDecimal, fmtInt, fmtPct, fmtPValue } from "@/lib/format";
import { CHART_COLORS, PlotlyChart } from "@/components/charts/PlotlyChart";
import {
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
  PageHeader,
  Panel,
  recommendationVariant,
  StatusBadge,
} from "@/components/ui/Primitives";

interface CampaignRow {
  campaign_id: number;
  campaign_code: string;
  campaign_name: string;
  campaign_type: string;
  experiment_type: string;
  start_date: string;
  end_date: string;
  channel_name: string;
  target_segment_name: string;
  target_route_code: string;
  discount_pct: number;
  bonus_miles_offer: number;
  customers_targeted: number;
  customers_reached: number;
  reach_rate: number;
  attributed_bookings: number;
  marketing_spend: number;
  gross_booking_revenue: number;
  discount_cost: number;
  loyalty_reward_cost: number;
  contribution_after_promo: number;
  margin_erosion_pct: number;
  incremental_bookings: number | null;
  incremental_revenue: number | null;
  incremental_contribution: number | null;
  cost_per_incremental_booking: number | null;
  conversion_p_value: number | null;
  is_statistically_significant: boolean;
  recommendation_status: string;
}

interface RouteRow {
  route_market_id: number;
  market_code: string;
  market_region: string;
  haul_type: string;
  load_factor_baseline: number;
  attributed_bookings: number;
  gross_revenue: number;
  discount_cost: number;
  net_contribution: number;
}

interface CampaignDetailResponse {
  campaign: Record<string, any>;
  cost_breakdown: { cost_category: string; amount_usd: number }[];
  daily_bookings: { booking_date: string; attributed_bookings: number; gross_revenue: number; discount_cost: number }[];
  segment_mix: { segment_name: string; targeted: number; control: number; attributed_bookings: number; net_revenue: number }[];
  top_routes: { market_code: string; market_region: string; bookings: number; gross_revenue: number; discount_cost: number }[];
}

export default function CampaignPerformancePage() {
  const { filters, resetFilters } = useFilters();
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState("incremental_contribution");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [activeTab, setActiveTab] = useState<"campaigns" | "routes">("campaigns");

  const [rows, setRows] = useState<CampaignRow[]>([]);
  const [routes, setRoutes] = useState<RouteRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CampaignDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const loadList = useCallback(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const qs = buildFilterQueryString(filters, { search, sort_by: sortBy, sort_dir: sortDir });
    apiGet<{ count: number; campaigns: CampaignRow[]; route_breakdown: RouteRow[] }>(`/campaigns${qs}`, controller.signal)
      .then((res) => {
        setRows(res.campaigns);
        setRoutes(res.route_breakdown);
      })
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [filters, search, sortBy, sortDir]);

  useEffect(() => {
    const cancel = loadList();
    return cancel;
  }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    apiGet<CampaignDetailResponse>(`/campaigns/${selectedId}`, controller.signal)
      .then((res) => setDetail(res))
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
    return () => controller.abort();
  }, [selectedId]);

  const toggleSort = (col: string) => {
    if (sortBy === col) {
      setSortDir((d) => (d === "desc" ? "asc" : "desc"));
    } else {
      setSortBy(col);
      setSortDir("desc");
    }
  };

  const SortHeader = ({ col, label, align = "right" }: { col: string; label: string; align?: "left" | "right" }) => (
    <th
      onClick={() => toggleSort(col)}
      className={`cursor-pointer select-none hover:text-[#0F2942] ${align === "right" ? "text-right" : "text-left"}`}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {sortBy === col && (sortDir === "desc" ? <ArrowDown className="w-3 h-3" /> : <ArrowUp className="w-3 h-3" />)}
      </span>
    </th>
  );

  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow="Commercial Campaign Ledger"
        title="Campaign Performance & Route Breakdown"
        description="Searchable, sortable ledger across all promotional campaigns. Click any campaign row to inspect granular cost composition, daily trajectory, segment mix, and report actions."
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => triggerFileDownload(`/campaigns/export/csv${buildFilterQueryString(filters, { search })}`)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium bg-white border border-[#CBD5E1] text-[#0F1E2E] rounded-[4px] hover:bg-[#F8FAFC] cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" /> CSV
            </button>
            <button
              type="button"
              onClick={() => triggerFileDownload(`/campaigns/export/excel${buildFilterQueryString(filters, { search })}`)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium bg-[#0F2942] text-white rounded-[4px] hover:bg-[#1E5B94] cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" /> Excel (.xlsx)
            </button>
          </div>
        }
      />

      {/* Toolbar: Tabs + Live Search */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-white border border-[#E2E6EC] rounded-[5px] px-4 py-2.5">
        <div className="inline-flex rounded-[4px] border border-[#CBD5E1] overflow-hidden text-[12px]">
          <button
            type="button"
            onClick={() => setActiveTab("campaigns")}
            className={`px-3 py-1.5 font-medium cursor-pointer ${
              activeTab === "campaigns" ? "bg-[#0F2942] text-white" : "bg-white text-[#475569] hover:bg-[#F8FAFC]"
            }`}
          >
            Campaign Ledger ({rows.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("routes")}
            className={`px-3 py-1.5 font-medium cursor-pointer border-l border-[#CBD5E1] ${
              activeTab === "routes" ? "bg-[#0F2942] text-white" : "bg-white text-[#475569] hover:bg-[#F8FAFC]"
            }`}
          >
            Route Market Performance ({routes.length})
          </button>
        </div>

        <div className="relative w-full sm:w-[320px]">
          <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search campaign code, name, type, route..."
            className="w-full h-[30px] pl-8 pr-3 text-[12px] bg-[#FAFBFD] border border-[#CBD5E1] rounded-[4px] focus:outline-none focus:border-[#1E5B94]"
          />
        </div>
      </div>

      {loading && rows.length === 0 && <LoadingPanel lines={10} />}
      {error && <ErrorPanel message={error} onRetry={loadList} />}
      {!loading && !error && rows.length === 0 && <EmptyPanel onReset={resetFilters} />}

      {!error && rows.length > 0 && activeTab === "campaigns" && (
        <Panel noPadding>
          <div className="overflow-x-auto max-h-[680px]">
            <table className="cl-table">
              <thead className="sticky top-0 z-10">
                <tr>
                  <SortHeader col="campaign_name" label="Campaign" align="left" />
                  <th>Design</th>
                  <th>Channel / Segment</th>
                  <th>Offer</th>
                  <SortHeader col="marketing_spend" label="Spend" />
                  <SortHeader col="attributed_bookings" label="Attr. Book" />
                  <SortHeader col="gross_booking_revenue" label="Gross Rev" />
                  <SortHeader col="discount_cost" label="Disc + Miles" />
                  <SortHeader col="incremental_bookings" label="Inc. Book (RCT)" />
                  <SortHeader col="incremental_contribution" label="Inc. Contrib" />
                  <SortHeader col="cost_per_incremental_booking" label="iCPA" />
                  <SortHeader col="conversion_p_value" label="Conv p" />
                  <th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.campaign_id}
                    onClick={() => setSelectedId(r.campaign_id)}
                    className={`cursor-pointer ${selectedId === r.campaign_id ? "bg-[#EFF6FF]" : ""}`}
                  >
                    <td className="max-w-[260px]">
                      <div className="font-medium text-[#0F2942] truncate" title={r.campaign_name}>
                        {r.campaign_name}
                      </div>
                      <div className="text-[11px] text-[#64748B] font-mono-num">
                        {r.campaign_code} · {r.start_date} · {r.target_route_code}
                      </div>
                    </td>
                    <td>
                      <StatusBadge
                        label={r.experiment_type}
                        variant={r.experiment_type === "RCT" ? "cobalt" : "warning"}
                      />
                    </td>
                    <td className="max-w-[175px]">
                      <div className="text-[#0F1E2E] truncate">{r.channel_name}</div>
                      <div className="text-[11px] text-[#64748B] truncate">{r.target_segment_name}</div>
                    </td>
                    <td className="font-mono-num text-[11.5px] whitespace-nowrap text-[#334155]">
                      {r.discount_pct > 0 ? `${r.discount_pct.toFixed(0)}% Off` : ""}
                      {r.discount_pct > 0 && r.bonus_miles_offer > 0 ? " + " : ""}
                      {r.bonus_miles_offer > 0 ? `${fmtInt(r.bonus_miles_offer)} mi` : ""}
                      {r.discount_pct === 0 && r.bonus_miles_offer === 0 ? "Msg Only" : ""}
                    </td>
                    <td className="text-right font-mono-num">{fmtCurrency(r.marketing_spend)}</td>
                    <td className="text-right font-mono-num">{fmtInt(r.attributed_bookings)}</td>
                    <td className="text-right font-mono-num">{fmtCurrency(r.gross_booking_revenue, true)}</td>
                    <td className="text-right font-mono-num text-[#475569]">
                      {fmtCurrency(r.discount_cost + r.loyalty_reward_cost, true)}
                    </td>
                    <td className="text-right font-mono-num font-medium">
                      {r.experiment_type === "RCT" ? fmtDecimal(r.incremental_bookings, 1) : <span className="text-[#94A3B8]">Obs</span>}
                    </td>
                    <td
                      className={`text-right font-mono-num font-semibold ${
                        r.experiment_type !== "RCT"
                          ? "text-[#94A3B8]"
                          : (r.incremental_contribution || 0) >= 0
                          ? "text-[#0F766E]"
                          : "text-[#B91C1C]"
                      }`}
                    >
                      {r.experiment_type === "RCT" ? fmtCurrency(r.incremental_contribution) : "Non-Causal"}
                    </td>
                    <td className="text-right font-mono-num">
                      {r.cost_per_incremental_booking !== null ? fmtCurrency(r.cost_per_incremental_booking) : "—"}
                    </td>
                    <td className="text-right font-mono-num text-[#475569]">
                      {r.experiment_type === "RCT" ? fmtPValue(r.conversion_p_value) : "—"}
                    </td>
                    <td>
                      <StatusBadge
                        label={r.recommendation_status}
                        variant={recommendationVariant(r.recommendation_status)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {!error && activeTab === "routes" && (
        <Panel
          title="Promotional Performance by Origin-Destination Route Market"
          subtitle="Attributed bookings, discounting cost, and net route contribution across active filter scope"
          noPadding
        >
          <div className="overflow-x-auto">
            <table className="cl-table">
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Region</th>
                  <th>Haul Type</th>
                  <th className="text-right">Baseline LF</th>
                  <th className="text-right">Attr. Bookings</th>
                  <th className="text-right">Gross Revenue</th>
                  <th className="text-right">Discounts</th>
                  <th className="text-right">Net Route Contrib</th>
                </tr>
              </thead>
              <tbody>
                {routes.map((rt) => (
                  <tr key={rt.route_market_id}>
                    <td className="font-mono-num font-semibold text-[#0F2942]">{rt.market_code}</td>
                    <td>{rt.market_region}</td>
                    <td className="text-[#475569]">{rt.haul_type}</td>
                    <td className="text-right font-mono-num">{fmtPct(rt.load_factor_baseline, 1)}</td>
                    <td className="text-right font-mono-num">{fmtInt(rt.attributed_bookings)}</td>
                    <td className="text-right font-mono-num">{fmtCurrency(rt.gross_revenue)}</td>
                    <td className="text-right font-mono-num text-[#B45309]">{fmtCurrency(rt.discount_cost)}</td>
                    <td className="text-right font-mono-num font-semibold text-[#0F766E]">
                      {fmtCurrency(rt.net_contribution)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {/* Slide-Over Campaign Inspector Drawer */}
      {selectedId !== null && (
        <div className="fixed inset-0 z-40 flex justify-end bg-[#0F1E2E]/25">
          <div className="w-full max-w-[600px] bg-white h-full border-l border-[#CBD5E1] flex flex-col overflow-hidden">
            <div className="px-5 py-3.5 border-b border-[#E2E6EC] flex items-start justify-between gap-3 bg-[#FAFBFD]">
              <div className="min-w-0">
                <div className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-[#1E5B94]">
                  Campaign Inspector
                </div>
                <div className="text-[15px] font-semibold text-[#0F2942] truncate">
                  {detail?.campaign?.campaign_code} — {detail?.campaign?.campaign_name || "Loading..."}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                className="p-1 text-[#64748B] hover:text-[#0F1E2E] cursor-pointer"
                aria-label="Close inspector"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {detailLoading || !detail ? (
                <LoadingPanel lines={6} />
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge
                      label={detail.campaign.experiment_type}
                      variant={detail.campaign.experiment_type === "RCT" ? "cobalt" : "warning"}
                    />
                    <StatusBadge
                      label={detail.campaign.recommendation_status}
                      variant={recommendationVariant(detail.campaign.recommendation_status)}
                    />
                    <Link
                      href={`/experiments?campaign_id=${detail.campaign.campaign_id}`}
                      className="ml-auto inline-flex items-center gap-1 text-[11.5px] font-medium text-[#1E5B94] hover:underline"
                    >
                      Open in Experiment Lab <ExternalLink className="w-3 h-3" />
                    </Link>
                    <Link
                      href={`/reports?campaign_id=${detail.campaign.campaign_id}`}
                      className="inline-flex items-center gap-1 text-[11.5px] font-medium text-[#0F2942] hover:underline"
                    >
                      Executive Report <ExternalLink className="w-3 h-3" />
                    </Link>
                  </div>

                  <div className="text-[12px] bg-[#F8FAFC] border border-[#E2E6EC] rounded-[4px] p-3 space-y-1.5">
                    <div>
                      <span className="font-semibold text-[#0F2942]">Hypothesis: </span>
                      <span className="text-[#334155]">{detail.campaign.hypothesis}</span>
                    </div>
                    <div>
                      <span className="font-semibold text-[#0F2942]">Eligibility: </span>
                      <span className="text-[#475569]">{detail.campaign.eligibility_criteria}</span>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2.5">
                    <div className="border border-[#E2E6EC] rounded-[4px] p-2.5">
                      <div className="text-[10px] uppercase text-[#64748B] font-semibold">Marketing Spend</div>
                      <div className="font-mono-num text-[15px] font-semibold text-[#0F2942] mt-0.5">
                        {fmtCurrency(detail.campaign.marketing_spend)}
                      </div>
                    </div>
                    <div className="border border-[#E2E6EC] rounded-[4px] p-2.5">
                      <div className="text-[10px] uppercase text-[#64748B] font-semibold">Inc. Bookings</div>
                      <div className="font-mono-num text-[15px] font-semibold text-[#0F2942] mt-0.5">
                        {detail.campaign.experiment_type === "RCT"
                          ? fmtDecimal(detail.campaign.incremental_bookings, 1)
                          : "Non-Causal"}
                      </div>
                    </div>
                    <div className="border border-[#E2E6EC] rounded-[4px] p-2.5">
                      <div className="text-[10px] uppercase text-[#64748B] font-semibold">Inc. Contribution</div>
                      <div
                        className={`font-mono-num text-[15px] font-semibold mt-0.5 ${
                          (detail.campaign.incremental_contribution || 0) >= 0 ? "text-[#0F766E]" : "text-[#B91C1C]"
                        }`}
                      >
                        {detail.campaign.experiment_type === "RCT"
                          ? fmtCurrency(detail.campaign.incremental_contribution)
                          : "Non-Causal"}
                      </div>
                    </div>
                  </div>

                  {detail.daily_bookings.length > 0 && (
                    <div className="border border-[#E2E6EC] rounded-[4px] p-3">
                      <div className="text-[11.5px] font-semibold text-[#0F2942] mb-1">
                        Daily Attributed Bookings Trajectory
                      </div>
                      <PlotlyChart
                        height={180}
                        data={[
                          {
                            type: "bar",
                            x: detail.daily_bookings.map((d) => d.booking_date),
                            y: detail.daily_bookings.map((d) => d.attributed_bookings),
                            marker: { color: CHART_COLORS.cobalt },
                            hovertemplate: "%{x}: %{y} bookings<extra></extra>",
                          },
                        ]}
                        layout={{ margin: { t: 8, r: 10, b: 32, l: 36 }, yaxis: { title: "Bookings" } }}
                      />
                    </div>
                  )}

                  <div>
                    <div className="text-[11.5px] font-semibold text-[#0F2942] mb-1.5">Marketing Cost Composition</div>
                    <table className="cl-table border border-[#E2E6EC]">
                      <thead>
                        <tr>
                          <th>Cost Category</th>
                          <th className="text-right">Amount (USD)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.cost_breakdown.map((cb) => (
                          <tr key={cb.cost_category}>
                            <td>{cb.cost_category}</td>
                            <td className="text-right font-mono-num">{fmtCurrency(cb.amount_usd)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div>
                    <div className="text-[11.5px] font-semibold text-[#0F2942] mb-1.5">Assigned Segment Composition</div>
                    <table className="cl-table border border-[#E2E6EC]">
                      <thead>
                        <tr>
                          <th>Segment</th>
                          <th className="text-right">Targeted</th>
                          <th className="text-right">Control</th>
                          <th className="text-right">Attr. Bookings</th>
                        </tr>
                      </thead>
                      <tbody>
                        {detail.segment_mix.map((sm) => (
                          <tr key={sm.segment_name}>
                            <td>{sm.segment_name}</td>
                            <td className="text-right font-mono-num">{fmtInt(sm.targeted)}</td>
                            <td className="text-right font-mono-num">{fmtInt(sm.control)}</td>
                            <td className="text-right font-mono-num">{fmtInt(sm.attributed_bookings)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  {detail.top_routes.length > 0 && (
                    <div>
                      <div className="text-[11.5px] font-semibold text-[#0F2942] mb-1.5">Top Redeemed Route Markets</div>
                      <table className="cl-table border border-[#E2E6EC]">
                        <thead>
                          <tr>
                            <th>Market</th>
                            <th>Region</th>
                            <th className="text-right">Bookings</th>
                            <th className="text-right">Gross Rev</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.top_routes.map((tr) => (
                            <tr key={tr.market_code}>
                              <td className="font-mono-num font-semibold text-[#0F2942]">{tr.market_code}</td>
                              <td className="text-[#475569]">{tr.market_region}</td>
                              <td className="text-right font-mono-num">{fmtInt(tr.bookings)}</td>
                              <td className="text-right font-mono-num">{fmtCurrency(tr.gross_revenue)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
