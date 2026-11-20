"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Download } from "lucide-react";
import { useFilters } from "@/context/FilterContext";
import { apiGet, buildFilterQueryString, triggerFileDownload } from "@/lib/api";
import { fmtCurrency, fmtDecimal, fmtInt, fmtPct, fmtPValue } from "@/lib/format";
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

interface OverviewData {
  kpis: {
    total_campaigns: number;
    rct_campaigns: number;
    obs_campaigns: number;
    total_spend: number;
    rct_spend: number;
    customers_targeted: number;
    customers_reached: number;
    reach_rate: number;
    campaign_conversion_rate: number;
    booking_conversion_rate: number;
    total_attributed_bookings: number;
    gross_booking_revenue: number;
    discount_cost: number;
    loyalty_reward_cost: number;
    contribution_margin: number;
    margin_erosion_pct: number;
    incremental_bookings: number;
    incremental_revenue: number;
    incremental_contribution: number;
    cost_per_incremental_booking: number | null;
    incremental_roas: number | null;
    incremental_roi: number | null;
    rct_attributed_bookings: number;
    rct_attributed_contribution: number;
    attribution_overstatement_ratio: number | null;
    rct_significant_count: number;
    rct_value_creating_count: number;
    rct_value_destroying_count: number;
  };
  monthly_trend: {
    month: string;
    campaigns: number;
    rct_campaigns: number;
    total_spend: number;
    gross_revenue: number;
    promo_incentive_cost: number;
    rct_attributed_contrib: number;
    rct_incremental_contrib: number;
    rct_incremental_bookings: number;
  }[];
  portfolio_scatter: {
    campaign_id: number;
    campaign_code: string;
    campaign_name: string;
    campaign_type: string;
    experiment_type: string;
    channel_name: string;
    target_segment_name: string;
    discount_pct: number;
    bonus_miles_offer: number;
    marketing_spend: number;
    attributed_bookings: number;
    incremental_bookings: number | null;
    incremental_revenue: number | null;
    incremental_contribution: number | null;
    cost_per_incremental_booking: number | null;
    conversion_lift_abs: number | null;
    conversion_p_value: number | null;
    is_statistically_significant: boolean;
    recommendation_status: string;
  }[];
  by_channel: {
    channel_id: number;
    channel_name: string;
    campaigns: number;
    rct_campaigns: number;
    spend: number;
    rct_spend: number;
    targeted: number;
    reached: number;
    reach_rate: number;
    attributed_bookings: number;
    gross_revenue: number;
    incentive_cost: number;
    incremental_bookings: number;
    incremental_revenue: number;
    incremental_contribution: number;
    cost_per_incremental_booking: number | null;
  }[];
  by_segment: {
    segment_id: number;
    segment_name: string;
    campaigns: number;
    rct_campaigns: number;
    spend: number;
    rct_spend: number;
    attributed_bookings: number;
    discount_cost: number;
    miles_cost: number;
    incremental_bookings: number;
    incremental_revenue: number;
    incremental_contribution: number;
    cost_per_incremental_booking: number | null;
  }[];
  by_campaign_type: {
    campaign_type: string;
    campaigns: number;
    rct_campaigns: number;
    rct_spend: number;
    rct_attributed_bookings: number;
    rct_incremental_bookings: number;
    rct_attributed_contrib: number;
    rct_incremental_contrib: number;
    avg_discount_pct: number;
  }[];
  decision_queue: {
    scale_winners: OverviewData["portfolio_scatter"];
    margin_dilutive: OverviewData["portfolio_scatter"];
  };
}

export default function ExecutiveOverviewPage() {
  const { filters, setFilter, resetFilters } = useFilters();
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const qs = buildFilterQueryString(filters);
    apiGet<OverviewData>(`/overview${qs}`, controller.signal)
      .then((res) => setData(res))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [filters]);

  useEffect(() => {
    const cancel = loadData();
    return cancel;
  }, [loadData]);

  const k = data?.kpis;

  const trendChartData = useMemo(() => {
    if (!data) return [];
    const months = data.monthly_trend.map((m) => m.month);
    return [
      {
        type: "bar",
        name: "Marketing Media Spend",
        x: months,
        y: data.monthly_trend.map((m) => m.total_spend),
        marker: { color: "#CBD5E1" },
        yaxis: "y",
        hovertemplate: "<b>%{x}</b><br>Media Spend: $%{y:,.0f}<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines+markers",
        name: "RCT Attributed Contribution",
        x: months,
        y: data.monthly_trend.map((m) => m.rct_attributed_contrib),
        line: { color: CHART_COLORS.steel, width: 1.75, dash: "dot" },
        marker: { size: 4 },
        yaxis: "y",
        hovertemplate: "<b>%{x}</b><br>RCT Attributed Contrib: $%{y:,.0f}<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines+markers",
        name: "RCT Causal Incremental Contribution",
        x: months,
        y: data.monthly_trend.map((m) => m.rct_incremental_contrib),
        line: { color: CHART_COLORS.navy, width: 2.5 },
        marker: { size: 5.5, color: CHART_COLORS.navy },
        yaxis: "y",
        hovertemplate: "<b>%{x}</b><br>Causal Inc. Contrib: $%{y:,.0f}<extra></extra>",
      },
    ];
  }, [data]);

  const typeBridgeData = useMemo(() => {
    if (!data) return [];
    const sorted = [...data.by_campaign_type].reverse();
    const labels = sorted.map((t) => t.campaign_type);
    return [
      {
        type: "bar",
        orientation: "h",
        name: "Attributed Contribution (RCTs)",
        y: labels,
        x: sorted.map((t) => t.rct_attributed_contrib),
        marker: { color: "#CBD5E1" },
        hovertemplate: "<b>%{y}</b><br>Attributed Contrib: $%{x:,.0f}<extra></extra>",
      },
      {
        type: "bar",
        orientation: "h",
        name: "Causal Incremental Contribution",
        y: labels,
        x: sorted.map((t) => t.rct_incremental_contrib),
        marker: {
          color: sorted.map((t) =>
            t.rct_incremental_contrib >= 0 ? CHART_COLORS.cobalt : CHART_COLORS.crimson
          ),
        },
        hovertemplate: "<b>%{y}</b><br>Causal Inc. Contrib: $%{x:,.0f}<extra></extra>",
      },
    ];
  }, [data]);

  const scatterData = useMemo(() => {
    if (!data) return [];
    const rcts = data.portfolio_scatter.filter(
      (c) => c.experiment_type === "RCT" && c.incremental_bookings !== null && c.incremental_contribution !== null
    );
    const winners = rcts.filter((c) => (c.incremental_contribution || 0) > 0 && c.is_statistically_significant);
    const dilutive = rcts.filter((c) => (c.incremental_contribution || 0) <= 0);
    const inconc = rcts.filter((c) => (c.incremental_contribution || 0) > 0 && !c.is_statistically_significant);

    const makeTrace = (name: string, list: typeof rcts, color: string) => ({
      type: "scatter",
      mode: "markers",
      name,
      x: list.map((c) => c.incremental_bookings),
      y: list.map((c) => c.incremental_contribution),
      customdata: list.map((c) => [c.campaign_id, c.campaign_code, c.campaign_name, c.marketing_spend, c.recommendation_status]),
      marker: {
        size: list.map((c) => Math.max(7, Math.min(20, Math.sqrt(c.marketing_spend / 180)))),
        color,
        opacity: 0.85,
        line: { width: 1, color: "#FFFFFF" },
      },
      hovertemplate:
        "<b>%{customdata[1]}</b>: %{customdata[2]}<br>Inc. Bookings: %{x:,.1f}<br>Inc. Contrib: $%{y:,.0f}<br>Media Spend: $%{customdata[3]:,.0f}<br>Action: %{customdata[4]}<extra></extra>",
    });

    return [
      makeTrace("Significant Value Creators", winners, CHART_COLORS.teal),
      makeTrace("Positive / Inconclusive", inconc, CHART_COLORS.steel),
      makeTrace("Margin-Dilutive (Inc. Contrib <= 0)", dilutive, CHART_COLORS.crimson),
    ];
  }, [data]);

  if (loading && !data) return <LoadingPanel lines={8} />;
  if (error) return <ErrorPanel message={error} onRetry={loadData} />;
  if (!data || !k || k.total_campaigns === 0) {
    return <EmptyPanel onReset={resetFilters} />;
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Executive Commercial Portfolio"
        title="Promotional Incrementality & Contribution Overview"
        description="Separates randomized causal incremental profit from attributed top-line bookings across Meridian Air's promotional portfolio."
        actions={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => triggerFileDownload(`/campaigns/export/csv${buildFilterQueryString(filters)}`)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium bg-white border border-[#CBD5E1] text-[#0F1E2E] rounded-[4px] hover:bg-[#F8FAFC] cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" /> Export CSV
            </button>
            <button
              type="button"
              onClick={() => triggerFileDownload(`/campaigns/export/excel${buildFilterQueryString(filters)}`)}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium bg-[#0F2942] text-white rounded-[4px] hover:bg-[#1E5B94] cursor-pointer"
            >
              <Download className="w-3.5 h-3.5" /> Export Excel
            </button>
          </div>
        }
      />

      {/* Primary Causal & Financial KPI Strip */}
      <MetricStrip
        columns={6}
        items={[
          {
            label: "Total Marketing Spend",
            value: fmtCurrency(k.total_spend, true),
            sublabel: `${k.total_campaigns} campaigns (${k.rct_campaigns} RCT · ${k.obs_campaigns} Obs)`,
            tone: "navy",
          },
          {
            label: "Causal Inc. Bookings (RCT)",
            value: fmtDecimal(k.incremental_bookings, 0),
            sublabel: `vs. ${fmtInt(k.rct_attributed_bookings)} RCT attributed`,
            tone: k.incremental_bookings >= 0 ? "navy" : "negative",
          },
          {
            label: "Causal Inc. Revenue (RCT)",
            value: fmtCurrency(k.incremental_revenue, true),
            sublabel: k.incremental_roas !== null ? `iROAS ${k.incremental_roas.toFixed(2)}x on RCT spend` : "No RCT spend",
            tone: "navy",
          },
          {
            label: "Causal Inc. Contribution",
            value: fmtCurrency(k.incremental_contribution, true),
            sublabel: `${k.rct_value_creating_count} value-creating · ${k.rct_value_destroying_count} dilutive`,
            tone: k.incremental_contribution >= 0 ? "positive" : "negative",
          },
          {
            label: "Cost / Inc. Booking (iCPA)",
            value: k.cost_per_incremental_booking !== null ? fmtCurrency(k.cost_per_incremental_booking) : "N/A",
            sublabel: `Reach ${fmtPct(k.reach_rate, 1)} · Conv ${fmtPct(k.booking_conversion_rate, 2)}`,
          },
          {
            label: "Promo Margin Erosion",
            value: fmtPct(k.margin_erosion_pct, 1),
            sublabel: `Disc ${fmtCurrency(k.discount_cost, true)} + Miles ${fmtCurrency(k.loyalty_reward_cost, true)}`,
            tone: k.margin_erosion_pct > 0.25 ? "warning" : "default",
          },
        ]}
      />

      {/* Methodological Guardrail Callout */}
      <MethodNote title="Attribution vs. Causality Discipline" tone="info">
        <span className="font-medium text-[#0F2942]">
          {k.attribution_overstatement_ratio !== null
            ? `Last-touch attribution overstates true RCT incremental bookings by ${k.attribution_overstatement_ratio.toFixed(2)}x `
            : "Randomized controlled trials isolate true incremental lift "}
        </span>
        ({fmtInt(k.rct_attributed_bookings)} attributed vs. {fmtDecimal(k.incremental_bookings, 0)} causal incremental bookings across {k.rct_campaigns} RCTs).
        {" "}Observational campaigns ({k.obs_campaigns}) are excluded from causal incrementality sums to avoid selection-bias distortion.
        {" "}Total attributed gross revenue ({fmtCurrency(k.gross_booking_revenue, true)}) is never substituted for net incremental contribution ({fmtCurrency(k.incremental_contribution, true)}).
      </MethodNote>

      {/* Row 1 Visuals: Monthly Time Trajectory + Campaign Type Attribution vs Causal Bridge */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
        <Panel
          className="xl:col-span-7"
          title="Monthly Trajectory: Media Spend vs. Attributed & Causal Contribution"
          subtitle="Tracks gap between attributed campaign contribution and true RCT net incremental profit by launch month"
        >
          <PlotlyChart
            data={trendChartData}
            height={305}
            layout={{
              barmode: "overlay",
              yaxis: { title: "USD ($)", tickprefix: "$", separatethousands: true },
              xaxis: { title: "" },
            }}
          />
        </Panel>

        <Panel
          className="xl:col-span-5"
          title="Attributed vs. Causal Contribution by Promotion Type"
          subtitle="Reveals which promotional mechanics create profit vs. subsidize organic demand (RCT scope)"
        >
          <PlotlyChart
            data={typeBridgeData}
            height={305}
            layout={{
              barmode: "group",
              margin: { l: 145, r: 16, t: 28, b: 36 },
              xaxis: { title: "USD ($)", tickprefix: "$", zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#64748B" },
              yaxis: { automargin: true },
            }}
          />
        </Panel>
      </div>

      {/* Row 2 Visuals: Portfolio Efficiency Scatter + Decision Queue */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
        <Panel
          className="xl:col-span-6"
          title="RCT Portfolio Efficiency Map (Incremental Bookings vs. Incremental Contribution)"
          subtitle="Bubble area reflects media spend. Click any point to scope global filters to that campaign."
        >
          <PlotlyChart
            data={scatterData}
            height={330}
            onPointClick={(pt) => {
              const cd = pt.customdata as [number] | undefined;
              if (cd && cd[0]) setFilter("campaign_id", String(cd[0]));
            }}
            layout={{
              xaxis: { title: "Causal Incremental Bookings (ITT)", zeroline: true, zerolinecolor: "#94A3B8" },
              yaxis: { title: "Net Incremental Contribution ($)", tickprefix: "$", zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#475569" },
            }}
          />
        </Panel>

        <Panel
          className="xl:col-span-6"
          title="Commercial Investment Decision Queue (RCT Evidence)"
          subtitle="Top incremental profit generators to scale vs. margin-dilutive promotions requiring discount reduction or pause"
          noPadding
        >
          <div className="divide-y divide-[#EEF1F5]">
            <div className="px-4 py-2 bg-[#F8FAFC] flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-[#0F766E]">
                Scale Priority — Highest Causal Incremental Contribution
              </span>
              <Link href="/experiments" className="text-[11px] text-[#1E5B94] hover:underline inline-flex items-center gap-0.5">
                Experiment Lab <ArrowUpRight className="w-3 h-3" />
              </Link>
            </div>
            <div className="overflow-x-auto">
              <table className="cl-table table-fixed w-full">
                <thead>
                  <tr>
                    <th className="w-[41%]">Campaign</th>
                    <th className="w-[17%]">Channel</th>
                    <th className="w-[13%] text-right">Inc. Bk</th>
                    <th className="w-[15%] text-right">Inc. Contrib</th>
                    <th className="w-[14%] text-right">Conv p</th>
                  </tr>
                </thead>
                <tbody>
                  {data.decision_queue.scale_winners.slice(0, 4).map((c) => (
                    <tr key={c.campaign_id}>
                      <td className="truncate">
                        <Link
                          href={`/experiments?campaign_id=${c.campaign_id}`}
                          className="font-medium text-[#0F2942] hover:text-[#1E5B94] hover:underline"
                          title={`${c.campaign_code}: ${c.campaign_name}`}
                        >
                          <span className="font-mono-num text-[10.5px] text-[#64748B] mr-1">{c.campaign_code}</span>
                          {c.campaign_name}
                        </Link>
                      </td>
                      <td className="text-[#475569] truncate">{c.channel_name}</td>
                      <td className="text-right font-mono-num whitespace-nowrap">{fmtDecimal(c.incremental_bookings, 1)}</td>
                      <td className="text-right font-mono-num font-semibold text-[#0F766E] whitespace-nowrap">
                        {fmtCurrency(c.incremental_contribution, true)}
                      </td>
                      <td className="text-right font-mono-num text-[11px] text-[#475569] whitespace-nowrap">{fmtPValue(c.conversion_p_value)}</td>
                    </tr>
                  ))}
                  {data.decision_queue.scale_winners.length === 0 && (
                    <tr>
                      <td colSpan={5} className="text-center text-[#64748B] py-4">No RCT scale winners in current filter slice.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="px-4 py-2 bg-[#FEF2F2]/60 flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-[#B91C1C]">
                Margin-Dilutive Alerts — Negative Net Incremental Contribution
              </span>
              <Link href="/economics" className="text-[11px] text-[#1E5B94] hover:underline inline-flex items-center gap-0.5">
                Economics P&amp;L <ArrowUpRight className="w-3 h-3" />
              </Link>
            </div>
            <div className="overflow-x-auto">
              <table className="cl-table table-fixed w-full">
                <thead>
                  <tr>
                    <th className="w-[37%]">Campaign</th>
                    <th className="w-[13%]">Offer</th>
                    <th className="w-[12%] text-right">Inc. Bk</th>
                    <th className="w-[15%] text-right">Inc. Contrib</th>
                    <th className="w-[23%]">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data.decision_queue.margin_dilutive.slice(0, 4).map((c) => (
                    <tr key={c.campaign_id}>
                      <td className="truncate">
                        <Link
                          href={`/experiments?campaign_id=${c.campaign_id}`}
                          className="font-medium text-[#0F2942] hover:text-[#1E5B94] hover:underline"
                          title={`${c.campaign_code}: ${c.campaign_name}`}
                        >
                          <span className="font-mono-num text-[10.5px] text-[#64748B] mr-1">{c.campaign_code}</span>
                          {c.campaign_name}
                        </Link>
                      </td>
                      <td className="font-mono-num text-[11px] text-[#475569] whitespace-nowrap">
                        {c.discount_pct > 0 ? `${c.discount_pct.toFixed(0)}% Off` : `${fmtInt(c.bonus_miles_offer)} mi`}
                      </td>
                      <td className="text-right font-mono-num whitespace-nowrap">{fmtDecimal(c.incremental_bookings, 1)}</td>
                      <td className="text-right font-mono-num font-semibold text-[#B91C1C] whitespace-nowrap">
                        {fmtCurrency(c.incremental_contribution, true)}
                      </td>
                      <td>
                        <StatusBadge
                          label={c.recommendation_status.replace("Reduce Discount / ", "Reduce ").replace("Inconclusive — ", "")}
                          variant={recommendationVariant(c.recommendation_status)}
                        />
                      </td>
                    </tr>
                  ))}
                  {data.decision_queue.margin_dilutive.length === 0 && (
                    <tr>
                      <td colSpan={5} className="text-center text-[#64748B] py-4">No margin-dilutive RCTs in current filter slice.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </Panel>
      </div>

      {/* Row 3: Channel & Segment Cross-Filter Comparison Matrices */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Panel
          title="Marketing Channel Incremental Scorecard"
          subtitle="Click a channel row to apply global channel cross-filter"
          noPadding
        >
          <div className="overflow-x-auto">
            <table className="cl-table">
              <thead>
                <tr>
                  <th>Channel</th>
                  <th className="text-right">RCT</th>
                  <th className="text-right">Reach</th>
                  <th className="text-right">Spend</th>
                  <th className="text-right">Inc. Bk</th>
                  <th className="text-right">Inc. Contrib</th>
                  <th className="text-right">iCPA</th>
                </tr>
              </thead>
              <tbody>
                {data.by_channel.map((ch) => (
                  <tr
                    key={ch.channel_id}
                    onClick={() => setFilter("channel_id", String(ch.channel_id))}
                    className="cursor-pointer"
                  >
                    <td className="font-medium text-[#0F2942]">{ch.channel_name}</td>
                    <td className="text-right font-mono-num">{ch.rct_campaigns}</td>
                    <td className="text-right font-mono-num">{fmtPct(ch.reach_rate, 1)}</td>
                    <td className="text-right font-mono-num">{fmtCurrency(ch.rct_spend, true)}</td>
                    <td className="text-right font-mono-num">{fmtDecimal(ch.incremental_bookings, 1)}</td>
                    <td
                      className={`text-right font-mono-num font-semibold ${
                        ch.incremental_contribution >= 0 ? "text-[#0F766E]" : "text-[#B91C1C]"
                      }`}
                    >
                      {fmtCurrency(ch.incremental_contribution, true)}
                    </td>
                    <td className="text-right font-mono-num">
                      {ch.cost_per_incremental_booking !== null ? fmtCurrency(ch.cost_per_incremental_booking) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel
          title="Target Customer Segment Incremental Scorecard"
          subtitle="Click a segment row to filter the workspace to that commercial segment"
          noPadding
        >
          <div className="overflow-x-auto">
            <table className="cl-table">
              <thead>
                <tr>
                  <th>Target Segment</th>
                  <th className="text-right">RCT</th>
                  <th className="text-right">Disc</th>
                  <th className="text-right">Miles</th>
                  <th className="text-right">Inc. Bk</th>
                  <th className="text-right">Inc. Contrib</th>
                  <th className="text-right">iCPA</th>
                </tr>
              </thead>
              <tbody>
                {data.by_segment.map((seg) => (
                  <tr
                    key={seg.segment_name}
                    onClick={() => seg.segment_id > 0 && setFilter("segment_id", String(seg.segment_id))}
                    className={seg.segment_id > 0 ? "cursor-pointer" : ""}
                  >
                    <td className="font-medium text-[#0F2942]">{seg.segment_name}</td>
                    <td className="text-right font-mono-num">{seg.rct_campaigns}</td>
                    <td className="text-right font-mono-num">{fmtCurrency(seg.discount_cost, true)}</td>
                    <td className="text-right font-mono-num">{fmtCurrency(seg.miles_cost, true)}</td>
                    <td className="text-right font-mono-num">{fmtDecimal(seg.incremental_bookings, 1)}</td>
                    <td
                      className={`text-right font-mono-num font-semibold ${
                        seg.incremental_contribution >= 0 ? "text-[#0F766E]" : "text-[#B91C1C]"
                      }`}
                    >
                      {fmtCurrency(seg.incremental_contribution, true)}
                    </td>
                    <td className="text-right font-mono-num">
                      {seg.cost_per_incremental_booking !== null ? fmtCurrency(seg.cost_per_incremental_booking) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
