"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useFilters } from "@/context/FilterContext";
import { apiGet, buildFilterQueryString } from "@/lib/api";
import { fmtCurrency, fmtInt, fmtPct } from "@/lib/format";
import { CHART_COLORS, PlotlyChart } from "@/components/charts/PlotlyChart";
import {
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
  MethodNote,
  MetricStrip,
  PageHeader,
  Panel,
  recommendationVariant,
  StatusBadge,
} from "@/components/ui/Primitives";

interface EconomicsData {
  summary: {
    campaign_count: number;
    rct_campaign_count: number;
    gross_revenue: number;
    discount_cost: number;
    variable_cost: number;
    contribution_before_promo: number;
    bonus_miles_cost: number;
    other_promo_cost: number;
    contribution_after_promo: number;
    margin_erosion_pct: number;
    rct_incremental_bookings: number;
    rct_incremental_revenue: number;
    rct_incremental_contribution: number;
    rct_deadweight_subsidy: number;
    rct_subsidy_waste_share: number;
  };
  waterfall: { label: string; value: number; measure: string }[];
  by_campaign_type: {
    campaign_type: string;
    campaigns: number;
    rct_campaigns: number;
    gross_revenue: number;
    discount_cost: number;
    bonus_miles_cost: number;
    other_promo_cost: number;
    contribution_before_promo: number;
    contribution_after_promo: number;
    incremental_contribution: number;
    deadweight_subsidy: number;
    margin_erosion_pct: number;
  }[];
  campaigns: {
    campaign_id: number;
    campaign_code: string;
    campaign_name: string;
    campaign_type: string;
    experiment_type: string;
    channel_name: string;
    target_segment_name: string;
    discount_pct: number;
    bonus_miles_offer: number;
    attributed_bookings: number;
    gross_revenue: number;
    discount_cost: number;
    variable_cost: number;
    contribution_before_promo: number;
    bonus_miles_cost: number;
    other_promo_cost: number;
    contribution_after_promo: number;
    incremental_bookings: number | null;
    incremental_revenue: number | null;
    incremental_contribution: number | null;
    deadweight_subsidy: number | null;
    incremental_share_of_attributed: number | null;
    margin_erosion_pct: number;
    recommendation_status: string;
  }[];
  formulas: { metric: string; formula: string; note: string }[];
}

export default function PromotionEconomicsPage() {
  const { filters, resetFilters } = useFilters();
  const [data, setData] = useState<EconomicsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadEconomics = useCallback(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const qs = buildFilterQueryString(filters);
    apiGet<EconomicsData>(`/economics${qs}`, controller.signal)
      .then((res) => setData(res))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [filters]);

  useEffect(() => {
    const cancel = loadEconomics();
    return cancel;
  }, [loadEconomics]);

  const waterfallData = useMemo(() => {
    if (!data) return [];
    const shortLabels: Record<string, string> = {
      "Gross Booking Revenue": "Gross<br>Revenue",
      "Fare Discounts": "Fare<br>Discounts",
      "Estimated Variable Costs": "Variable<br>Costs",
      "Bonus Loyalty Miles Cost": "Bonus<br>Miles",
      "Media & Other Promo Cost": "Media &<br>Exec Spend",
      "Contribution After Promo": "Contrib<br>After Promo",
    };
    return [
      {
        type: "waterfall",
        orientation: "v",
        measure: data.waterfall.map((w) => w.measure),
        x: data.waterfall.map((w) => shortLabels[w.label] || w.label),
        y: data.waterfall.map((w) => w.value),
        connector: { line: { color: "#CBD5E1", width: 1 } },
        increasing: { marker: { color: CHART_COLORS.navy } },
        decreasing: { marker: { color: CHART_COLORS.crimson } },
        totals: { marker: { color: CHART_COLORS.teal } },
        textposition: "outside",
        cliponaxis: false,
        text: data.waterfall.map((w) => fmtCurrency(w.value, true)),
        textfont: { size: 10.5, family: "IBM Plex Mono, monospace", color: "#0F1E2E" },
        hovertemplate: "<b>%{x}</b><br>%{y:$,.0f}<extra></extra>",
      },
    ];
  }, [data]);

  const revVsProfitData = useMemo(() => {
    if (!data) return [];
    const rcts = data.campaigns.filter((c) => c.experiment_type === "RCT" && c.incremental_contribution !== null);
    const pos = rcts.filter((c) => (c.incremental_contribution || 0) >= 0);
    const neg = rcts.filter((c) => (c.incremental_contribution || 0) < 0);
    return [
      {
        type: "scatter",
        mode: "markers",
        name: "Positive Incremental Profit",
        x: pos.map((c) => c.gross_revenue),
        y: pos.map((c) => c.incremental_contribution),
        customdata: pos.map((c) => [c.campaign_code, c.campaign_name, c.discount_pct, c.margin_erosion_pct * 100]),
        marker: { color: CHART_COLORS.teal, size: 9, opacity: 0.85, line: { color: "#FFFFFF", width: 1 } },
        hovertemplate:
          "<b>%{customdata[0]}</b>: %{customdata[1]}<br>Gross Rev: $%{x:,.0f}<br>Inc. Contrib: $%{y:,.0f}<br>Discount: %{customdata[2]:.1f}% · Erosion: %{customdata[3]:.1f}%<extra></extra>",
      },
      {
        type: "scatter",
        mode: "markers",
        name: "Revenue Positive / Profit Destroying",
        x: neg.map((c) => c.gross_revenue),
        y: neg.map((c) => c.incremental_contribution),
        customdata: neg.map((c) => [c.campaign_code, c.campaign_name, c.discount_pct, c.margin_erosion_pct * 100]),
        marker: { color: CHART_COLORS.crimson, size: 10, symbol: "diamond", opacity: 0.9, line: { color: "#FFFFFF", width: 1 } },
        hovertemplate:
          "<b>%{customdata[0]}</b>: %{customdata[1]}<br>Gross Rev: $%{x:,.0f}<br>Inc. Contrib: $%{y:,.0f}<br>Discount: %{customdata[2]:.1f}% · Erosion: %{customdata[3]:.1f}%<extra></extra>",
      },
    ];
  }, [data]);

  if (loading && !data) return <LoadingPanel lines={8} />;
  if (error) return <ErrorPanel message={error} onRetry={loadEconomics} />;
  if (!data || data.summary.campaign_count === 0) return <EmptyPanel onReset={resetFilters} />;

  const s = data.summary;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Unit Economics & Margin Governance"
        title="Promotion Economics & Cannibalization P&L"
        description="Full contribution accounting separating top-line gross booking revenue from variable operating costs, fare discounts, loyalty miles liabilities, and deadweight subsidy to organic bookers."
      />

      <MetricStrip
        columns={6}
        items={[
          { label: "Gross Booking Revenue", value: fmtCurrency(s.gross_revenue, true), sublabel: "Undiscounted ticket + ancillary", tone: "navy" },
          { label: "Fare Discounts", value: fmtCurrency(-s.discount_cost, true), sublabel: "Direct ticket yield dilution", tone: "negative" },
          { label: "Bonus Miles Liability", value: fmtCurrency(-s.bonus_miles_cost, true), sublabel: "$0.0094/mile breakage-adjusted", tone: "warning" },
          { label: "Media & Exec Spend", value: fmtCurrency(-s.other_promo_cost, true), sublabel: "Channel + creative + ops" },
          { label: "Contrib After Promo", value: fmtCurrency(s.contribution_after_promo, true), sublabel: `Before promo: ${fmtCurrency(s.contribution_before_promo, true)}` },
          {
            label: "RCT Causal Inc. Contrib",
            value: fmtCurrency(s.rct_incremental_contribution, true),
            sublabel: `Deadweight subsidy: ${fmtCurrency(s.rct_deadweight_subsidy, true)}`,
            tone: s.rct_incremental_contribution >= 0 ? "positive" : "negative",
          },
        ]}
      />

      <MethodNote title="Revenue Is Not Profit — Baseline Subsidy Decomposition" tone="warning">
        Across {s.rct_campaign_count} randomized experiments, an estimated{" "}
        <strong>{fmtCurrency(s.rct_deadweight_subsidy)} ({fmtPct(s.rct_subsidy_waste_share, 1)} of total promo discounts &amp; miles)</strong>{" "}
        was absorbed by baseline customers who would have booked without a promotion. Campaign types relying on broad cash fare cuts suffer heavy margin erosion, whereas targeted bonus miles and reactivation offers preserve contribution margin.
      </MethodNote>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
        <Panel
          className="xl:col-span-6"
          title="Portfolio Promotion P&L Bridge (Attributed Bookings)"
          subtitle="Step-down from gross booking revenue to net contribution after all promotional liabilities"
        >
          <PlotlyChart
            data={waterfallData}
            height={325}
            layout={{
              margin: { t: 40, r: 22, b: 54, l: 64 },
              yaxis: {
                title: "USD ($)",
                tickprefix: "$",
                range: [0, Math.max(1000, s.gross_revenue * 1.18)],
              },
              xaxis: { tickangle: 0, automargin: true },
            }}
          />
        </Panel>

        <Panel
          className="xl:col-span-6"
          title="Why Revenue ≠ Profit: Gross Revenue vs. Causal Incremental Contribution"
          subtitle="Red diamonds represent campaigns that generated strong top-line revenue while destroying incremental profit (RCT scope)"
        >
          <PlotlyChart
            data={revVsProfitData}
            height={320}
            layout={{
              xaxis: { title: "Attributed Gross Booking Revenue ($)", tickprefix: "$" },
              yaxis: { title: "Causal Incremental Contribution ($)", tickprefix: "$", zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#475569" },
            }}
          />
        </Panel>
      </div>

      {/* Promotion Type Economic Comparison */}
      <Panel
        title="Economics & Subsidy Audit by Promotion Type"
        subtitle="Compares cash discount erosion against lower-cost loyalty miles liabilities"
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="cl-table">
            <thead>
              <tr>
                <th>Promotion Type</th>
                <th className="text-right">Campaigns</th>
                <th className="text-right">Gross Revenue</th>
                <th className="text-right">Fare Discounts</th>
                <th className="text-right">Bonus Miles</th>
                <th className="text-right">Media Spend</th>
                <th className="text-right">Contrib After Promo</th>
                <th className="text-right">Margin Erosion</th>
                <th className="text-right">RCT Deadweight Subsidy</th>
                <th className="text-right">RCT Inc. Contrib</th>
              </tr>
            </thead>
            <tbody>
              {data.by_campaign_type.map((t) => (
                <tr key={t.campaign_type}>
                  <td className="font-semibold text-[#0F2942]">{t.campaign_type}</td>
                  <td className="text-right font-mono-num">{t.campaigns} ({t.rct_campaigns} RCT)</td>
                  <td className="text-right font-mono-num">{fmtCurrency(t.gross_revenue, true)}</td>
                  <td className="text-right font-mono-num text-[#B91C1C]">{fmtCurrency(t.discount_cost, true)}</td>
                  <td className="text-right font-mono-num text-[#B45309]">{fmtCurrency(t.bonus_miles_cost, true)}</td>
                  <td className="text-right font-mono-num">{fmtCurrency(t.other_promo_cost, true)}</td>
                  <td className="text-right font-mono-num">{fmtCurrency(t.contribution_after_promo, true)}</td>
                  <td className="text-right font-mono-num">{fmtPct(t.margin_erosion_pct, 1)}</td>
                  <td className="text-right font-mono-num text-[#B45309]">{fmtCurrency(t.deadweight_subsidy, true)}</td>
                  <td
                    className={`text-right font-mono-num font-semibold ${
                      t.incremental_contribution >= 0 ? "text-[#0F766E]" : "text-[#B91C1C]"
                    }`}
                  >
                    {fmtCurrency(t.incremental_contribution, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Campaign-Level Economics Ledger */}
      <Panel
        title="Campaign-Level P&L & Baseline Subsidy Ledger"
        subtitle="Sorted by RCT incremental contribution; observational studies omit causal subsidy claims"
        noPadding
      >
        <div className="overflow-x-auto max-h-[460px]">
          <table className="cl-table">
            <thead className="sticky top-0 z-10">
              <tr>
                <th>Campaign</th>
                <th>Design</th>
                <th className="text-right">Gross Rev</th>
                <th className="text-right">Discounts</th>
                <th className="text-right">Var. Costs</th>
                <th className="text-right">Miles Cost</th>
                <th className="text-right">Media</th>
                <th className="text-right">Contrib Before</th>
                <th className="text-right">Contrib After</th>
                <th className="text-right">Deadweight</th>
                <th className="text-right">Inc. Contrib</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.campaigns.map((c) => (
                <tr key={c.campaign_id}>
                  <td className="max-w-[230px] truncate">
                    <Link
                      href={`/experiments?campaign_id=${c.campaign_id}`}
                      className="font-medium text-[#0F2942] hover:text-[#1E5B94] hover:underline"
                    >
                      <span className="font-mono-num text-[11px] text-[#64748B] mr-1">{c.campaign_code}</span>
                      {c.campaign_name}
                    </Link>
                  </td>
                  <td>
                    <StatusBadge label={c.experiment_type} variant={c.experiment_type === "RCT" ? "cobalt" : "warning"} />
                  </td>
                  <td className="text-right font-mono-num">{fmtCurrency(c.gross_revenue, true)}</td>
                  <td className="text-right font-mono-num text-[#B91C1C]">{fmtCurrency(c.discount_cost, true)}</td>
                  <td className="text-right font-mono-num text-[#475569]">{fmtCurrency(c.variable_cost, true)}</td>
                  <td className="text-right font-mono-num text-[#B45309]">{fmtCurrency(c.bonus_miles_cost, true)}</td>
                  <td className="text-right font-mono-num">{fmtCurrency(c.other_promo_cost, true)}</td>
                  <td className="text-right font-mono-num">{fmtCurrency(c.contribution_before_promo, true)}</td>
                  <td className="text-right font-mono-num">{fmtCurrency(c.contribution_after_promo, true)}</td>
                  <td className="text-right font-mono-num text-[#B45309]">
                    {c.deadweight_subsidy !== null ? fmtCurrency(c.deadweight_subsidy, true) : "—"}
                  </td>
                  <td
                    className={`text-right font-mono-num font-semibold ${
                      c.incremental_contribution === null
                        ? "text-[#94A3B8]"
                        : c.incremental_contribution >= 0
                        ? "text-[#0F766E]"
                        : "text-[#B91C1C]"
                    }`}
                  >
                    {c.incremental_contribution !== null ? fmtCurrency(c.incremental_contribution) : "Non-Causal"}
                  </td>
                  <td>
                    <StatusBadge label={c.recommendation_status} variant={recommendationVariant(c.recommendation_status)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Transparent Metric Accounting Documentation */}
      <Panel
        title="Financial Accounting & Metric Calculation Methodology"
        subtitle="Exact commercial formulas applied uniformly across PostgreSQL queries, dashboard views, and PDF/Excel reports"
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="cl-table">
            <thead>
              <tr>
                <th className="w-[240px]">Metric</th>
                <th>Exact Formula</th>
                <th>Commercial Interpretation</th>
              </tr>
            </thead>
            <tbody>
              {data.formulas.map((f) => (
                <tr key={f.metric}>
                  <td className="font-semibold text-[#0F2942]">{f.metric}</td>
                  <td className="font-mono-num text-[11.5px] text-[#1E5B94]">{f.formula}</td>
                  <td className="text-[12px] text-[#475569]">{f.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
