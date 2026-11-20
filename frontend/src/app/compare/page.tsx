"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { useFilters } from "@/context/FilterContext";
import { apiPost } from "@/lib/api";
import { fmtCurrency, fmtDecimal, fmtInt, fmtPct, fmtPValue, fmtSignedPP } from "@/lib/format";
import { CHART_COLORS, PlotlyChart } from "@/components/charts/PlotlyChart";
import {
  ErrorPanel,
  LoadingPanel,
  PageHeader,
  Panel,
  recommendationVariant,
  StatusBadge,
} from "@/components/ui/Primitives";

interface ComparedCampaign {
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
  target_route_region: string;
  discount_pct: number;
  bonus_miles_offer: number;
  marketing_spend: number;
  customers_targeted: number;
  customers_reached: number;
  reach_rate: number;
  booking_conversion_rate: number;
  attributed_bookings: number;
  gross_booking_revenue: number;
  discount_cost: number;
  loyalty_reward_cost: number;
  contribution_after_promo: number;
  margin_erosion_pct: number;
  conversion_control: number;
  conversion_treatment: number;
  conversion_lift_abs: number;
  conversion_p_value: number | null;
  incremental_bookings: number | null;
  incremental_revenue: number | null;
  incremental_contribution: number | null;
  cost_per_incremental_booking: number | null;
  incremental_roi: number | null;
  is_statistically_significant: boolean;
  recommendation_status: string;
}

interface CompareResponse {
  campaigns: ComparedCampaign[];
  segment_matrix: {
    campaign_id: number;
    campaign_code: string;
    segment_name: string;
    n_targeted: number;
    treatment_conv: number | null;
    control_conv: number | null;
    lift_pp: number | null;
  }[];
  route_overlap: {
    market_code: string;
    market_region: string;
    haul_type: string;
    campaign_id: number;
    campaign_code: string;
    bookings: number;
    net_revenue: number;
  }[];
}

export default function CampaignComparisonPage() {
  const { options } = useFilters();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [pickerId, setPickerId] = useState<string>("");
  const [data, setData] = useState<CompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pre-select 3 diverse RCT campaigns once options arrive
  useEffect(() => {
    if (!options || selectedIds.length > 0) return;
    const rcts = options.campaigns.filter((c) => c.experiment_type === "RCT");
    const pickTypes = ["Bonus Loyalty Miles", "Customer Reactivation", "Discounted Ticket"];
    const defaults: number[] = [];
    for (const pt of pickTypes) {
      const found = rcts.find((c) => c.campaign_type === pt && !defaults.includes(c.campaign_id));
      if (found) defaults.push(found.campaign_id);
    }
    while (defaults.length < 3 && rcts.length > defaults.length) {
      const next = rcts.find((c) => !defaults.includes(c.campaign_id));
      if (next) defaults.push(next.campaign_id);
      else break;
    }
    if (defaults.length >= 2) setSelectedIds(defaults);
  }, [options, selectedIds.length]);

  useEffect(() => {
    if (selectedIds.length < 2) {
      setData(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    apiPost<CompareResponse>("/compare", { campaign_ids: selectedIds }, controller.signal)
      .then((res) => setData(res))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [selectedIds]);

  const addCampaign = () => {
    const id = Number(pickerId);
    if (!id || selectedIds.includes(id) || selectedIds.length >= 5) return;
    setSelectedIds((prev) => [...prev, id]);
    setPickerId("");
  };

  const removeCampaign = (id: number) => {
    setSelectedIds((prev) => prev.filter((x) => x !== id));
  };

  const barCompareData = useMemo(() => {
    if (!data) return [];
    const labels = data.campaigns.map((c) => c.campaign_code);
    return [
      {
        type: "bar",
        name: "Marketing Spend ($)",
        x: labels,
        y: data.campaigns.map((c) => c.marketing_spend),
        marker: { color: "#CBD5E1" },
      },
      {
        type: "bar",
        name: "Causal Inc. Revenue ($)",
        x: labels,
        y: data.campaigns.map((c) => c.incremental_revenue ?? 0),
        marker: { color: CHART_COLORS.cobalt },
      },
      {
        type: "bar",
        name: "Causal Inc. Contribution ($)",
        x: labels,
        y: data.campaigns.map((c) => c.incremental_contribution ?? 0),
        marker: {
          color: data.campaigns.map((c) =>
            (c.incremental_contribution ?? 0) >= 0 ? CHART_COLORS.teal : CHART_COLORS.crimson
          ),
        },
      },
    ];
  }, [data]);

  const heatmapData = useMemo(() => {
    if (!data || data.segment_matrix.length === 0) return [];
    const segs = Array.from(new Set(data.segment_matrix.map((m) => m.segment_name)));
    const camps = data.campaigns.map((c) => c.campaign_code);
    const z = segs.map((seg) =>
      camps.map((code) => {
        const hit = data.segment_matrix.find((m) => m.segment_name === seg && m.campaign_code === code);
        return hit?.lift_pp ?? null;
      })
    );
    return [
      {
        type: "heatmap",
        x: camps,
        y: segs,
        z,
        colorscale: [
          [0, "#B91C1C"],
          [0.5, "#F8FAFC"],
          [1, "#0F766E"],
        ],
        zmid: 0,
        hovertemplate: "<b>%{y}</b> · %{x}<br>Conv Lift: %{z:+.2f} pp<extra></extra>",
        colorbar: { title: "Lift (pp)", thickness: 12 },
      },
    ];
  }, [data]);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Side-by-Side Portfolio Benchmarking"
        title="Campaign Comparison Workbench"
        description="Compare 2 to 5 campaigns head-to-head across spend, conversion lift, incremental contribution, cost per incremental booking, channel, segment, and route market."
      />

      {/* Campaign Picker Bar */}
      <Panel title="Selected Campaigns (2 to 5)" subtitle="Add or remove campaigns to update the comparative matrix and heatmaps">
        <div className="flex flex-wrap items-center gap-2.5">
          {selectedIds.map((id) => {
            const info = options?.campaigns.find((c) => c.campaign_id === id);
            return (
              <div
                key={id}
                className="inline-flex items-center gap-2 px-2.5 py-1.5 bg-[#EFF4F9] border border-[#BFDBFE] rounded-[4px] text-[12px]"
              >
                <span className="font-mono-num font-semibold text-[#0F2942]">{info?.campaign_code || `#${id}`}</span>
                <span className="text-[#334155] max-w-[200px] truncate">{info?.campaign_name}</span>
                <button
                  type="button"
                  onClick={() => removeCampaign(id)}
                  className="text-[#64748B] hover:text-[#B91C1C] cursor-pointer"
                  aria-label="Remove campaign"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })}

          {selectedIds.length < 5 && (
            <div className="flex items-center gap-1.5">
              <select
                value={pickerId}
                onChange={(e) => setPickerId(e.target.value)}
                className="h-[32px] px-2.5 text-[12px] bg-white border border-[#CBD5E1] rounded-[4px] max-w-[320px]"
              >
                <option value="">Add campaign to compare...</option>
                {options?.campaigns
                  .filter((c) => !selectedIds.includes(c.campaign_id))
                  .map((c) => (
                    <option key={c.campaign_id} value={String(c.campaign_id)}>
                      {c.campaign_code} ({c.experiment_type}) · {c.campaign_name}
                    </option>
                  ))}
              </select>
              <button
                type="button"
                onClick={addCampaign}
                disabled={!pickerId}
                className="h-[32px] px-3 inline-flex items-center gap-1 text-[12px] font-medium bg-[#0F2942] text-white rounded-[4px] hover:bg-[#1E5B94] disabled:opacity-40 cursor-pointer"
              >
                <Plus className="w-3.5 h-3.5" /> Add
              </button>
            </div>
          )}
        </div>
      </Panel>

      {selectedIds.length < 2 && (
        <Panel>
          <p className="text-[12.5px] text-[#64748B] py-4 text-center">
            Select at least two campaigns above to render side-by-side metrics.
          </p>
        </Panel>
      )}

      {loading && <LoadingPanel lines={8} />}
      {error && <ErrorPanel message={error} />}

      {data && data.campaigns.length >= 2 && (
        <>
          {/* Side-by-Side Structured Comparison Matrix */}
          <Panel title="Head-to-Head Commercial & Statistical Comparison Matrix" noPadding>
            <div className="overflow-x-auto">
              <table className="cl-table">
                <thead>
                  <tr>
                    <th className="w-[210px]">Dimension / Metric</th>
                    {data.campaigns.map((c) => (
                      <th key={c.campaign_id} className="min-w-[190px]">
                        <div className="font-mono-num text-[#0F2942]">{c.campaign_code}</div>
                        <div className="font-normal normal-case tracking-normal text-[11.5px] text-[#334155] truncate max-w-[210px]">
                          {c.campaign_name}
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[
                    { label: "Study Design", render: (c: ComparedCampaign) => <StatusBadge label={c.experiment_type} variant={c.experiment_type === "RCT" ? "cobalt" : "warning"} /> },
                    { label: "Promotion Type", render: (c: ComparedCampaign) => c.campaign_type },
                    { label: "Channel", render: (c: ComparedCampaign) => c.channel_name },
                    { label: "Target Segment", render: (c: ComparedCampaign) => c.target_segment_name },
                    { label: "Target Route Market", render: (c: ComparedCampaign) => `${c.target_route_code} (${c.target_route_region})` },
                    { label: "Offer Structure", render: (c: ComparedCampaign) => `${c.discount_pct.toFixed(1)}% Off · ${fmtInt(c.bonus_miles_offer)} Miles` },
                    { label: "Marketing Spend", render: (c: ComparedCampaign) => <span className="font-mono-num">{fmtCurrency(c.marketing_spend)}</span> },
                    { label: "Targeted / Reached", render: (c: ComparedCampaign) => <span className="font-mono-num">{fmtInt(c.customers_targeted)} / {fmtInt(c.customers_reached)} ({fmtPct(c.reach_rate, 1)})</span> },
                    { label: "Booking Conversion Rate", render: (c: ComparedCampaign) => <span className="font-mono-num">{fmtPct(c.booking_conversion_rate, 2)}</span> },
                    { label: "ITT Conv Lift (T vs C)", render: (c: ComparedCampaign) => <span className="font-mono-num">{c.experiment_type === "RCT" ? `${fmtSignedPP(c.conversion_lift_abs)} (p=${fmtPValue(c.conversion_p_value)})` : "Non-Causal (Obs)"}</span> },
                    { label: "Incremental Bookings (RCT)", render: (c: ComparedCampaign) => <span className="font-mono-num font-semibold">{c.incremental_bookings !== null ? fmtDecimal(c.incremental_bookings, 1) : "Non-Causal"}</span> },
                    { label: "Incremental Revenue (RCT)", render: (c: ComparedCampaign) => <span className="font-mono-num">{c.incremental_revenue !== null ? fmtCurrency(c.incremental_revenue) : "Non-Causal"}</span> },
                    {
                      label: "Incremental Contribution",
                      render: (c: ComparedCampaign) => (
                        <span className={`font-mono-num font-semibold ${c.incremental_contribution === null ? "text-[#94A3B8]" : c.incremental_contribution >= 0 ? "text-[#0F766E]" : "text-[#B91C1C]"}`}>
                          {c.incremental_contribution !== null ? fmtCurrency(c.incremental_contribution) : "Non-Causal"}
                        </span>
                      ),
                    },
                    { label: "Cost / Inc. Booking (iCPA)", render: (c: ComparedCampaign) => <span className="font-mono-num">{c.cost_per_incremental_booking !== null ? fmtCurrency(c.cost_per_incremental_booking) : "—"}</span> },
                    { label: "Discount + Miles Cost", render: (c: ComparedCampaign) => <span className="font-mono-num">{fmtCurrency(c.discount_cost + c.loyalty_reward_cost)} ({fmtPct(c.margin_erosion_pct, 1)} erosion)</span> },
                    { label: "Recommended Action", render: (c: ComparedCampaign) => <StatusBadge label={c.recommendation_status} variant={recommendationVariant(c.recommendation_status)} /> },
                  ].map((row) => (
                    <tr key={row.label}>
                      <td className="font-semibold text-[#0F2942] bg-[#FAFBFD]">{row.label}</td>
                      {data.campaigns.map((c) => (
                        <td key={`${row.label}-${c.campaign_id}`}>{row.render(c)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {/* Comparative Visuals */}
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
            <Panel
              className="xl:col-span-6"
              title="Spend vs. Causal Incremental Revenue & Contribution"
              subtitle="Direct comparison of investment return across selected campaigns"
            >
              <PlotlyChart
                data={barCompareData}
                height={300}
                layout={{
                  barmode: "group",
                  yaxis: { title: "USD ($)", tickprefix: "$", zeroline: true, zerolinecolor: "#475569" },
                }}
              />
            </Panel>

            <Panel
              className="xl:col-span-6"
              title="Customer Segment Conversion Lift Heatmap (pp)"
              subtitle="Treatment minus Control conversion lift by segment across compared campaigns"
            >
              {heatmapData.length > 0 ? (
                <PlotlyChart
                  data={heatmapData}
                  height={310}
                  layout={{
                    margin: { t: 16, r: 24, b: 56, l: 175 },
                    xaxis: { tickangle: 0, automargin: true },
                  }}
                />
              ) : (
                <div className="py-12 text-center text-[12px] text-[#64748B]">No overlapping segment cells.</div>
              )}
            </Panel>
          </div>

          {/* Route Market Overlap */}
          {data.route_overlap.length > 0 && (
            <Panel
              title="Top Redeemed Route Markets Across Selected Campaigns"
              subtitle="Identifies route concentration and overlapping market exposure"
              noPadding
            >
              <div className="overflow-x-auto max-h-[300px]">
                <table className="cl-table">
                  <thead className="sticky top-0 z-10">
                    <tr>
                      <th>Campaign</th>
                      <th>Route Market</th>
                      <th>Region</th>
                      <th>Haul</th>
                      <th className="text-right">Attributed Bookings</th>
                      <th className="text-right">Net Ticket Revenue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.route_overlap.slice(0, 20).map((r, i) => (
                      <tr key={`${r.campaign_id}-${r.market_code}-${i}`}>
                        <td className="font-mono-num font-semibold text-[#1E5B94]">{r.campaign_code}</td>
                        <td className="font-mono-num font-semibold text-[#0F2942]">{r.market_code}</td>
                        <td>{r.market_region}</td>
                        <td className="text-[#475569]">{r.haul_type}</td>
                        <td className="text-right font-mono-num">{fmtInt(r.bookings)}</td>
                        <td className="text-right font-mono-num">{fmtCurrency(r.net_revenue)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
