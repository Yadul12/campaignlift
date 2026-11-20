"use client";

import React, { useEffect, useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { fmtCurrency, fmtDecimal, fmtInt, fmtPct } from "@/lib/format";
import { CHART_COLORS, PlotlyChart } from "@/components/charts/PlotlyChart";
import {
  ErrorPanel,
  LoadingPanel,
  MethodNote,
  MetricStrip,
  PageHeader,
  Panel,
} from "@/components/ui/Primitives";

interface SimDefaults {
  channels: {
    channel_id: number;
    channel_name: string;
    cost_model: string;
    unit_reach_cost: number;
    avg_deliverability_rate: number;
    historical_share_pct: number;
    historical_icpa: number | null;
    rct_inc_contrib: number;
  }[];
  segments: {
    segment_id: number;
    segment_name: string;
    incentive_affinity: string;
    avg_baseline_prob: number;
    avg_discount_uplift: number;
    avg_miles_uplift: number;
    sure_things_share: number;
  }[];
  routes: {
    route_market_id: number;
    market_code: string;
    market_region: string;
    haul_type: string;
    avg_base_fare: number;
    load_factor_baseline: number;
  }[];
  rct_campaigns: {
    campaign_id: number;
    campaign_code: string;
    campaign_name: string;
    channel_id: number;
    segment_id: number | null;
    route_market_id: number | null;
    discount_pct: number;
    bonus_miles_offer: number;
    marketing_spend: number;
    incremental_contribution: number | null;
  }[];
}

interface SimResult {
  disclaimer: string;
  scope: {
    baseline_reference: string;
    target_segment: string;
    exclude_sure_things: boolean;
    route_market: string;
  };
  baseline: {
    spend: number;
    targeted_customers: number;
    discount_pct: number;
    bonus_miles_offer: number;
    incremental_bookings: number;
    incremental_revenue: number;
    incremental_contribution: number;
    cost_per_incremental_booking: number | null;
  };
  simulated: {
    spend: number;
    targeted_customers: number;
    reached_customers: number;
    discount_pct: number;
    bonus_miles_offer: number;
    projected_itt_lift_pp: number;
    incremental_bookings: number;
    incremental_revenue: number;
    incremental_contribution: number;
    total_discount_cost: number;
    total_miles_cost: number;
    deadweight_subsidy: number;
    cost_per_incremental_booking: number | null;
    incremental_roi: number | null;
  };
  deltas: {
    spend_delta: number;
    incremental_bookings_delta: number;
    incremental_revenue_delta: number;
    incremental_contribution_delta: number;
  };
  uncertainty_bands: {
    conservative: { incremental_bookings: number; incremental_revenue: number; incremental_contribution: number };
    base: { incremental_bookings: number; incremental_revenue: number; incremental_contribution: number };
    upside: { incremental_bookings: number; incremental_revenue: number; incremental_contribution: number };
  };
  channel_allocation_plan: {
    channel_id: number;
    channel_name: string;
    share_pct: number;
    allocated_spend: number;
    empirical_lift_index: number;
    deliverability_rate: number;
  }[];
  discount_frontier: {
    discount_pct: number;
    projected_incremental_bookings: number;
    projected_incremental_contribution: number;
    projected_deadweight_subsidy: number;
  }[];
  assumptions: string[];
}

export default function BudgetSimulatorPage() {
  const [defaults, setDefaults] = useState<SimDefaults | null>(null);
  const [defLoading, setDefLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Scenario Controls
  const [baseCampaignId, setBaseCampaignId] = useState<string>("");
  const [budgetMultiplier, setBudgetMultiplier] = useState<number>(1.25);
  const [discountPct, setDiscountPct] = useState<number>(10);
  const [bonusMiles, setBonusMiles] = useState<number>(4000);
  const [targetSegmentId, setTargetSegmentId] = useState<string>("");
  const [excludeSureThings, setExcludeSureThings] = useState<boolean>(true);
  const [routeMarketId, setRouteMarketId] = useState<string>("");
  const [channelWeights, setChannelWeights] = useState<Record<number, number>>({});

  const [result, setResult] = useState<SimResult | null>(null);

  useEffect(() => {
    apiGet<SimDefaults>("/simulator/defaults")
      .then((res) => {
        setDefaults(res);
        // Initialize balanced realistic channel mix across top channels
        const init: Record<number, number> = {};
        res.channels.forEach((c) => {
          init[c.channel_id] = Math.round(c.historical_share_pct);
        });
        setChannelWeights(init);
      })
      .catch((err) => setError(err.message))
      .finally(() => setDefLoading(false));
  }, []);

  // Sync preset inputs when user selects a specific base RCT campaign
  const handleSelectBaseCampaign = (val: string) => {
    setBaseCampaignId(val);
    if (!val || !defaults) return;
    const found = defaults.rct_campaigns.find((c) => c.campaign_id === Number(val));
    if (found) {
      setDiscountPct(Math.round(found.discount_pct));
      setBonusMiles(found.bonus_miles_offer);
      setTargetSegmentId(found.segment_id ? String(found.segment_id) : "");
      setRouteMarketId(found.route_market_id ? String(found.route_market_id) : "");
    }
  };

  useEffect(() => {
    if (!defaults) return;
    const controller = new AbortController();
    const allocList = Object.entries(channelWeights)
      .filter(([, w]) => w > 0)
      .map(([cid, w]) => ({ channel_id: Number(cid), share_pct: w }));

    apiPost<SimResult>(
      "/simulator/run",
      {
        base_campaign_id: baseCampaignId ? Number(baseCampaignId) : null,
        budget_multiplier: budgetMultiplier,
        discount_pct: discountPct,
        bonus_miles_offer: bonusMiles,
        target_segment_id: targetSegmentId ? Number(targetSegmentId) : null,
        exclude_sure_things: excludeSureThings,
        route_market_id: routeMarketId ? Number(routeMarketId) : null,
        channel_allocations: allocList.length > 0 ? allocList : null,
      },
      controller.signal
    )
      .then((res) => setResult(res))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      });
    return () => controller.abort();
  }, [defaults, baseCampaignId, budgetMultiplier, discountPct, bonusMiles, targetSegmentId, excludeSureThings, routeMarketId, channelWeights]);

  const resetScenario = () => {
    setBaseCampaignId("");
    setBudgetMultiplier(1.0);
    setDiscountPct(10);
    setBonusMiles(4000);
    setTargetSegmentId("");
    setExcludeSureThings(false);
    setRouteMarketId("");
    if (defaults) {
      const init: Record<number, number> = {};
      defaults.channels.forEach((c) => {
        init[c.channel_id] = Math.round(c.historical_share_pct);
      });
      setChannelWeights(init);
    }
  };

  const frontierChart = useMemo(() => {
    if (!result) return [];
    const xs = result.discount_frontier.map((d) => `${d.discount_pct}%`);
    return [
      {
        type: "scatter",
        mode: "lines+markers",
        name: "Projected Net Inc. Contribution ($)",
        x: xs,
        y: result.discount_frontier.map((d) => d.projected_incremental_contribution),
        line: { color: CHART_COLORS.navy, width: 2.5 },
        marker: {
          size: 7,
          color: result.discount_frontier.map((d) =>
            d.projected_incremental_contribution >= 0 ? CHART_COLORS.teal : CHART_COLORS.crimson
          ),
        },
        hovertemplate: "<b>Discount %{x}</b><br>Inc. Contrib: $%{y:,.0f}<extra></extra>",
      },
      {
        type: "bar",
        name: "Deadweight Baseline Subsidy ($)",
        x: xs,
        y: result.discount_frontier.map((d) => d.projected_deadweight_subsidy),
        marker: { color: "#FDE68A", line: { color: "#B45309", width: 1 } },
        opacity: 0.7,
        hovertemplate: "<b>Discount %{x}</b><br>Baseline Subsidy: $%{y:,.0f}<extra></extra>",
      },
    ];
  }, [result]);

  const bandChart = useMemo(() => {
    if (!result) return [];
    const b = result.uncertainty_bands;
    return [
      {
        type: "bar",
        x: ["Conservative<br>(-18%)", "Base<br>Estimate", "Upside<br>(+18%)", "Baseline<br>Benchmark"],
        y: [
          b.conservative.incremental_contribution,
          b.base.incremental_contribution,
          b.upside.incremental_contribution,
          result.baseline.incremental_contribution,
        ],
        marker: {
          color: [CHART_COLORS.steel, CHART_COLORS.navy, CHART_COLORS.teal, "#CBD5E1"],
        },
        text: [
          fmtCurrency(b.conservative.incremental_contribution, true),
          fmtCurrency(b.base.incremental_contribution, true),
          fmtCurrency(b.upside.incremental_contribution, true),
          fmtCurrency(result.baseline.incremental_contribution, true),
        ],
        textposition: "outside",
        cliponaxis: false,
        textfont: { size: 10.5, family: "IBM Plex Mono, monospace", color: "#0F1E2E" },
        hovertemplate: "<b>%{x}</b><br>Inc. Contrib: $%{y:,.0f}<extra></extra>",
      },
    ];
  }, [result]);

  if (defLoading) return <LoadingPanel lines={10} />;
  if (error && !defaults) return <ErrorPanel message={error} />;

  const totalWeight = Object.values(channelWeights).reduce((acc, v) => acc + v, 0) || 1;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Commercial Decision Support & What-If Modeling"
        title="Budget Allocation & Promotional Scenario Simulator"
        description="Simulate budget scaling, fare discount depth, bonus miles awards, channel reallocation, audience suppression, and route targeting using elasticities calibrated from Meridian Air's RCT data."
        actions={
          <button
            type="button"
            onClick={resetScenario}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium bg-white border border-[#CBD5E1] text-[#0F1E2E] rounded-[4px] hover:bg-[#F8FAFC] cursor-pointer"
          >
            <RotateCcw className="w-3.5 h-3.5" /> Reset Scenario
          </button>
        }
      />

      {result && (
        <MethodNote title="Directional Scenario Estimate — Not a Guaranteed Outcome" tone="warning">
          {result.disclaimer}
        </MethodNote>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-start">
        {/* Left Control Panel (4 cols) */}
        <Panel
          className="xl:col-span-4"
          title="Scenario Controls & Levers"
          subtitle="All inputs recompute projections live on the server"
        >
          <div className="space-y-4">
            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-[0.04em] text-[#475569] mb-1">
                Base Campaign / Benchmark
              </label>
              <select
                value={baseCampaignId}
                onChange={(e) => handleSelectBaseCampaign(e.target.value)}
                className="w-full h-[32px] px-2.5 text-[12px] border border-[#CBD5E1] rounded-[4px]"
              >
                <option value="">Portfolio Average RCT Benchmark</option>
                {defaults?.rct_campaigns.map((c) => (
                  <option key={c.campaign_id} value={String(c.campaign_id)}>
                    {c.campaign_code} · {c.campaign_name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div className="flex justify-between text-[12px] mb-1">
                <label className="font-medium text-[#0F1E2E]">Budget Scale Multiplier</label>
                <span className="font-mono-num font-semibold text-[#0F2942]">{budgetMultiplier.toFixed(2)}x ({Math.round((budgetMultiplier - 1) * 100) >= 0 ? "+" : ""}{Math.round((budgetMultiplier - 1) * 100)}%)</span>
              </div>
              <input
                type="range"
                min={0.5}
                max={2.5}
                step={0.05}
                value={budgetMultiplier}
                onChange={(e) => setBudgetMultiplier(Number(e.target.value))}
                className="cl-slider"
              />
            </div>

            <div>
              <div className="flex justify-between text-[12px] mb-1">
                <label className="font-medium text-[#0F1E2E]">Fare Discount Percentage</label>
                <span className="font-mono-num font-semibold text-[#0F2942]">{discountPct}% Off</span>
              </div>
              <input
                type="range"
                min={0}
                max={32}
                step={1}
                value={discountPct}
                onChange={(e) => setDiscountPct(Number(e.target.value))}
                className="cl-slider"
              />
            </div>

            <div>
              <div className="flex justify-between text-[12px] mb-1">
                <label className="font-medium text-[#0F1E2E]">Bonus Loyalty Miles Offer</label>
                <span className="font-mono-num font-semibold text-[#0F766E]">{fmtInt(bonusMiles)} miles</span>
              </div>
              <input
                type="range"
                min={0}
                max={15000}
                step={500}
                value={bonusMiles}
                onChange={(e) => setBonusMiles(Number(e.target.value))}
                className="cl-slider"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-[0.04em] text-[#475569] mb-1">
                Target Customer Segment
              </label>
              <select
                value={targetSegmentId}
                onChange={(e) => setTargetSegmentId(e.target.value)}
                className="w-full h-[32px] px-2.5 text-[12px] border border-[#CBD5E1] rounded-[4px]"
              >
                <option value="">All Segments (Portfolio Mix)</option>
                {defaults?.segments.map((s) => (
                  <option key={s.segment_id} value={String(s.segment_id)}>
                    {s.segment_name} (Base {fmtPct(s.avg_baseline_prob, 1)})
                  </option>
                ))}
              </select>
            </div>

            <label className="flex items-start gap-2.5 p-2.5 bg-[#F8FAFC] border border-[#E2E6EC] rounded-[4px] cursor-pointer">
              <input
                type="checkbox"
                checked={excludeSureThings}
                onChange={(e) => setExcludeSureThings(e.target.checked)}
                className="mt-0.5 accent-[#0F2942]"
              />
              <div>
                <div className="text-[12px] font-semibold text-[#0F2942]">Suppress &ldquo;Sure Things&rdquo; Baseline Bookers</div>
                <div className="text-[11px] text-[#64748B]">
                  Excludes high-baseline organic bookers identified by the T-Learner uplift model to curb discount cannibalization.
                </div>
              </div>
            </label>

            <div>
              <label className="block text-[11px] font-semibold uppercase tracking-[0.04em] text-[#475569] mb-1">
                Target Route Market Focus
              </label>
              <select
                value={routeMarketId}
                onChange={(e) => setRouteMarketId(e.target.value)}
                className="w-full h-[32px] px-2.5 text-[12px] border border-[#CBD5E1] rounded-[4px]"
              >
                <option value="">Network-Wide Route Mix</option>
                {defaults?.routes.map((r) => (
                  <option key={r.route_market_id} value={String(r.route_market_id)}>
                    {r.market_code} · {r.market_region} (LF {fmtPct(r.load_factor_baseline, 0)} · ${r.avg_base_fare.toFixed(0)})
                  </option>
                ))}
              </select>
            </div>

            <div className="pt-2 border-t border-[#EEF1F5]">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-semibold uppercase tracking-[0.04em] text-[#475569]">
                  Channel Budget Reallocation
                </span>
                <span className="text-[10.5px] text-[#64748B]">Auto-normalized to 100%</span>
              </div>
              <div className="space-y-2">
                {defaults?.channels.map((ch) => {
                  const rawW = channelWeights[ch.channel_id] ?? 0;
                  const normPct = (rawW / totalWeight) * 100;
                  return (
                    <div key={ch.channel_id}>
                      <div className="flex justify-between text-[11.5px] mb-0.5">
                        <span className="text-[#334155]">{ch.channel_name}</span>
                        <span className="font-mono-num text-[#0F2942]">{normPct.toFixed(0)}%</span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={60}
                        step={2}
                        value={rawW}
                        onChange={(e) =>
                          setChannelWeights((prev) => ({ ...prev, [ch.channel_id]: Number(e.target.value) }))
                        }
                        className="cl-slider"
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </Panel>

        {/* Right Output Panel (8 cols) */}
        <div className="xl:col-span-8 space-y-5">
          {!result ? (
            <LoadingPanel lines={10} />
          ) : (
            <>
              <MetricStrip
                columns={5}
                items={[
                  {
                    label: "Simulated Spend",
                    value: fmtCurrency(result.simulated.spend),
                    sublabel: `Delta ${result.deltas.spend_delta >= 0 ? "+" : ""}${fmtCurrency(result.deltas.spend_delta)}`,
                    tone: "navy",
                  },
                  {
                    label: "Inc. Bookings",
                    value: fmtDecimal(result.simulated.incremental_bookings, 1),
                    sublabel: `ITT lift +${result.simulated.projected_itt_lift_pp.toFixed(2)} pp`,
                    tone: "navy",
                  },
                  {
                    label: "Inc. Revenue",
                    value: fmtCurrency(result.simulated.incremental_revenue, true),
                    sublabel: `vs. Base ${fmtCurrency(result.baseline.incremental_revenue, true)}`,
                  },
                  {
                    label: "Inc. Contribution",
                    value: fmtCurrency(result.simulated.incremental_contribution),
                    sublabel: `Delta ${result.deltas.incremental_contribution_delta >= 0 ? "+" : ""}${fmtCurrency(result.deltas.incremental_contribution_delta)}`,
                    tone: result.simulated.incremental_contribution >= 0 ? "positive" : "negative",
                  },
                  {
                    label: "Baseline Subsidy",
                    value: fmtCurrency(result.simulated.deadweight_subsidy),
                    sublabel: `iCPA ${result.simulated.cost_per_incremental_booking !== null ? fmtCurrency(result.simulated.cost_per_incremental_booking) : "N/A"}`,
                    tone: "warning",
                  },
                ]}
              />

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                <Panel
                  title="Discount Depth Frontier (0% – 30% Off)"
                  subtitle="Shows profit inflection where incremental bookings are overtaken by organic discount cannibalization"
                >
                  <PlotlyChart
                    data={frontierChart}
                    height={295}
                    layout={{
                      yaxis: { title: "USD ($)", tickprefix: "$", zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#475569" },
                      xaxis: { title: "Simulated Fare Discount %" },
                    }}
                  />
                </Panel>

                <Panel
                  title="Empirical Uncertainty Range vs. Baseline Benchmark"
                  subtitle="±18% empirical lift band reflecting finite-sample RCT uncertainty"
                >
                  <PlotlyChart
                    data={bandChart}
                    height={295}
                    layout={{
                      yaxis: {
                        title: "Net Inc. Contribution ($)",
                        tickprefix: "$",
                        zeroline: true,
                        zerolinecolor: "#475569",
                        automargin: true,
                        range: [
                          Math.min(0, result.uncertainty_bands.conservative.incremental_contribution, result.baseline.incremental_contribution) * 1.18,
                          Math.max(1000, result.uncertainty_bands.upside.incremental_contribution, result.baseline.incremental_contribution) * 1.22,
                        ],
                      },
                      xaxis: { tickangle: 0, automargin: true },
                      margin: { t: 38, r: 16, b: 56, l: 62 },
                    }}
                  />
                </Panel>
              </div>

              <Panel
                title="Simulated Channel Budget Plan & Empirical Efficiency"
                subtitle={`Scope: ${result.scope.target_segment} · ${result.scope.route_market}`}
                noPadding
              >
                <div className="overflow-x-auto">
                  <table className="cl-table">
                    <thead>
                      <tr>
                        <th>Marketing Channel</th>
                        <th className="text-right">Budget Share</th>
                        <th className="text-right">Allocated Spend</th>
                        <th className="text-right">Empirical Lift Index</th>
                        <th className="text-right">Avg Deliverability</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.channel_allocation_plan.map((ch) => (
                        <tr key={ch.channel_id}>
                          <td className="font-medium text-[#0F2942]">{ch.channel_name}</td>
                          <td className="text-right font-mono-num">{ch.share_pct.toFixed(1)}%</td>
                          <td className="text-right font-mono-num font-semibold">{fmtCurrency(ch.allocated_spend)}</td>
                          <td className="text-right font-mono-num">{ch.empirical_lift_index.toFixed(2)}x</td>
                          <td className="text-right font-mono-num">{fmtPct(ch.deliverability_rate, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>

              <Panel title="Explicit Modeling Assumptions & Parameters">
                <ul className="list-disc pl-5 space-y-1.5 text-[12px] text-[#334155]">
                  {result.assumptions.map((a, idx) => (
                    <li key={idx}>{a}</li>
                  ))}
                </ul>
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
