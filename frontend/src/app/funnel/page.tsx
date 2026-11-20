"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useFilters } from "@/context/FilterContext";
import { apiGet, buildFilterQueryString } from "@/lib/api";
import { fmtInt, fmtPct } from "@/lib/format";
import { CHART_COLORS, PlotlyChart } from "@/components/charts/PlotlyChart";
import {
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
  MethodNote,
  MetricStrip,
  PageHeader,
  Panel,
} from "@/components/ui/Primitives";

interface FunnelStage {
  stage_key: string;
  stage_label: string;
  count: number;
  step_conversion_rate: number;
  dropoff_count: number;
  dropoff_rate: number;
  cumulative_from_assigned: number;
  description: string;
}

interface FunnelData {
  campaign_count: number;
  stages: FunnelStage[];
  assigned_vs_exposed_gap: {
    assigned_targeted: number;
    reached: number;
    unreached: number;
    reach_rate: number;
  };
  bottleneck: {
    from_stage: string;
    to_stage: string;
    dropoff_count: number;
    dropoff_rate: number;
    step_conversion_rate: number;
  } | null;
  treatment_vs_control: {
    rct_campaign_count: number;
    treatment: {
      assigned: number;
      reached: number;
      reach_rate: number;
      booked_itt: number;
      booking_rate_itt: number;
      completed_itt: number;
      completion_rate_itt: number;
    };
    control: {
      assigned: number;
      reached: number;
      reach_rate: number;
      booked_itt: number;
      booking_rate_itt: number;
      completed_itt: number;
      completion_rate_itt: number;
    };
  } | null;
  by_channel: {
    channel_name: string;
    assigned: number;
    reached: number;
    engaged: number;
    booked: number;
    completed: number;
    reach_rate: number;
    engage_rate: number;
    book_of_engaged: number;
    end_to_end_rate: number;
  }[];
  by_segment: {
    segment_name: string;
    assigned: number;
    reached: number;
    engaged: number;
    booked: number;
    completed: number;
    reach_rate: number;
    engage_rate: number;
    book_of_engaged: number;
    end_to_end_rate: number;
  }[];
}

export default function CampaignFunnelPage() {
  const { filters, resetFilters } = useFilters();
  const [data, setData] = useState<FunnelData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sliceTab, setSliceTab] = useState<"channel" | "segment">("channel");

  const loadFunnel = useCallback(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const qs = buildFilterQueryString(filters);
    apiGet<FunnelData>(`/funnel${qs}`, controller.signal)
      .then((res) => setData(res))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [filters]);

  useEffect(() => {
    const cancel = loadFunnel();
    return cancel;
  }, [loadFunnel]);

  const funnelChartData = useMemo(() => {
    if (!data?.stages.length) return [];
    // Show post-eligibility operational funnel clearly on bar scale + include Eligible in ledger
    const opStages = data.stages.slice(1);
    return [
      {
        type: "funnel",
        y: opStages.map((s) => s.stage_label),
        x: opStages.map((s) => s.count),
        textinfo: "value+percent previous",
        textposition: "auto",
        insidetextfont: { size: 11, family: "IBM Plex Mono, monospace", color: "#FFFFFF" },
        outsidetextfont: { size: 11, family: "IBM Plex Mono, monospace", color: "#0F1E2E" },
        cliponaxis: false,
        marker: {
          color: ["#0F2942", "#1B4670", "#1E5B94", "#0F766E", "#115E59"],
          line: { width: 1, color: "#FFFFFF" },
        },
        connector: { line: { color: "#DCE3EC", width: 1 } },
        hovertemplate: "<b>%{y}</b><br>Customers: %{x:,}<br>Step Conv: %{percentPrevious:.1%}<extra></extra>",
      },
    ];
  }, [data]);

  const tvcChartData = useMemo(() => {
    const tvc = data?.treatment_vs_control;
    if (!tvc) return [];
    return [
      {
        type: "bar",
        name: "RCT Treatment (ITT)",
        x: ["Reached / Exposed", "Booked in Window", "Completed Travel"],
        y: [tvc.treatment.reach_rate * 100, tvc.treatment.booking_rate_itt * 100, tvc.treatment.completion_rate_itt * 100],
        marker: { color: CHART_COLORS.cobalt },
        text: [
          `${(tvc.treatment.reach_rate * 100).toFixed(1)}%`,
          `${(tvc.treatment.booking_rate_itt * 100).toFixed(2)}%`,
          `${(tvc.treatment.completion_rate_itt * 100).toFixed(2)}%`,
        ],
        textposition: "outside",
        hovertemplate: "<b>Treatment</b> — %{x}: %{y:.2f}%<extra></extra>",
      },
      {
        type: "bar",
        name: "RCT Control (Holdout)",
        x: ["Reached / Exposed", "Booked in Window", "Completed Travel"],
        y: [0, tvc.control.booking_rate_itt * 100, tvc.control.completion_rate_itt * 100],
        marker: { color: CHART_COLORS.steelLight },
        text: [
          "0.0%",
          `${(tvc.control.booking_rate_itt * 100).toFixed(2)}%`,
          `${(tvc.control.completion_rate_itt * 100).toFixed(2)}%`,
        ],
        textposition: "outside",
        hovertemplate: "<b>Control</b> — %{x}: %{y:.2f}%<extra></extra>",
      },
    ];
  }, [data]);

  if (loading && !data) return <LoadingPanel lines={7} />;
  if (error) return <ErrorPanel message={error} onRetry={loadFunnel} />;
  if (!data || data.stages.length === 0) return <EmptyPanel onReset={resetFilters} />;

  const gap = data.assigned_vs_exposed_gap;
  const bookedStage = data.stages.find((s) => s.stage_key === "booked");
  const compStage = data.stages.find((s) => s.stage_key === "completed");

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Conversion Funnel & Reach Diagnostics"
        title="6-Stage Promotional Customer Funnel"
        description="Traces airline customers from CRM eligibility through assignment, verified exposure, offer engagement, booking, and flown travel completion."
      />

      <MetricStrip
        columns={5}
        items={[
          {
            label: "Assigned (Targeted)",
            value: fmtInt(gap.assigned_targeted),
            sublabel: `${data.campaign_count} filtered campaigns`,
            tone: "navy",
          },
          {
            label: "Verified Reached / Exposed",
            value: fmtInt(gap.reached),
            sublabel: `Reach rate ${fmtPct(gap.reach_rate, 1)}`,
            tone: "navy",
          },
          {
            label: "Assigned But Unreached",
            value: fmtInt(gap.unreached),
            sublabel: "Bounced / suppressed — zero exposure",
            tone: "warning",
          },
          {
            label: "Attributed Booked Customers",
            value: fmtInt(bookedStage?.count),
            sublabel: `${fmtPct(bookedStage?.cumulative_from_assigned, 2)} of targeted`,
          },
          {
            label: "Primary Drop-Off Bottleneck",
            value: data.bottleneck ? fmtPct(data.bottleneck.dropoff_rate, 1) : "—",
            sublabel: data.bottleneck ? `${data.bottleneck.from_stage} → ${data.bottleneck.to_stage}` : "",
            tone: "negative",
          },
        ]}
      />

      <MethodNote title="Assigned vs. Reached / Exposed Separation (Intention-to-Treat Compliance)" tone="warning">
        <strong>{fmtInt(gap.unreached)} targeted customers ({fmtPct(1 - gap.reach_rate, 1)})</strong> were assigned to a campaign but never received a verified exposure due to email bounces, push suppression, or channel delivery gaps.
        {" "}Causal RCT evaluation MUST retain all assigned customers in the denominator (Intention-to-Treat); restricting analysis solely to reached or engaged users introduces severe post-treatment compliance bias.
      </MethodNote>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
        <Panel
          className="xl:col-span-7"
          title="Operational Conversion Funnel (Assigned → Completed Travel)"
          subtitle="Stage volumes and step-to-step conversion rates across filtered scope"
        >
          <PlotlyChart
            data={funnelChartData}
            height={325}
            layout={{ margin: { t: 12, r: 96, b: 14, l: 195 } }}
          />
        </Panel>

        <Panel
          className="xl:col-span-5"
          title="RCT Treatment vs. Holdout Control Progression (% of Assigned)"
          subtitle={
            data.treatment_vs_control
              ? `Intention-to-Treat window outcomes across ${data.treatment_vs_control.rct_campaign_count} RCTs (Control receives 0% exposures)`
              : "No RCT campaigns in current filter slice"
          }
        >
          {data.treatment_vs_control ? (
            <PlotlyChart
              data={tvcChartData}
              height={325}
              layout={{
                barmode: "group",
                yaxis: { title: "% of Assigned Customers", ticksuffix: "%" },
                margin: { t: 30, r: 16, b: 40, l: 54 },
              }}
            />
          ) : (
            <div className="py-16 text-center text-[12px] text-[#64748B]">
              Select RCT campaigns to compare Treatment vs. Control progression.
            </div>
          )}
        </Panel>
      </div>

      {/* Stage-by-Stage Funnel Ledger */}
      <Panel
        title="Stage-by-Stage Conversion & Drop-Off Audit"
        subtitle="Full 6-stage monotonic progression including pre-assignment CRM eligibility pool"
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="cl-table">
            <thead>
              <tr>
                <th>Stage</th>
                <th className="text-right">Customers</th>
                <th className="text-right">Step Conv %</th>
                <th className="text-right">Stage Drop-Off</th>
                <th className="text-right">Drop-Off %</th>
                <th className="text-right">Cum. vs. Assigned</th>
                <th>Operational Definition</th>
              </tr>
            </thead>
            <tbody>
              {data.stages.map((st, idx) => (
                <tr key={st.stage_key}>
                  <td className="font-semibold text-[#0F2942]">
                    <span className="font-mono-num text-[11px] text-[#64748B] mr-2">0{idx + 1}</span>
                    {st.stage_label}
                  </td>
                  <td className="text-right font-mono-num font-semibold">{fmtInt(st.count)}</td>
                  <td className="text-right font-mono-num">
                    {idx === 0 ? "—" : fmtPct(st.step_conversion_rate, 1)}
                  </td>
                  <td className="text-right font-mono-num text-[#64748B]">
                    {idx === 0 ? "—" : fmtInt(st.dropoff_count)}
                  </td>
                  <td
                    className={`text-right font-mono-num ${
                      idx >= 2 && st.dropoff_rate > 0.7 ? "text-[#B91C1C] font-semibold" : "text-[#475569]"
                    }`}
                  >
                    {idx === 0 ? "—" : fmtPct(st.dropoff_rate, 1)}
                  </td>
                  <td className="text-right font-mono-num">
                    {idx === 0 ? "Baseline Pool" : fmtPct(st.cumulative_from_assigned, 2)}
                  </td>
                  <td className="text-[11.5px] text-[#475569] max-w-[340px]">{st.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Channel / Segment Funnel Diagnostics */}
      <Panel
        title="Funnel Drop-Off Diagnostics by Channel & Customer Segment"
        subtitle="Pinpoints whether leakage occurs at delivery/reach, offer engagement, or checkout booking"
        action={
          <div className="inline-flex rounded-[4px] border border-[#CBD5E1] overflow-hidden text-[11.5px]">
            <button
              type="button"
              onClick={() => setSliceTab("channel")}
              className={`px-2.5 py-1 font-medium cursor-pointer ${
                sliceTab === "channel" ? "bg-[#0F2942] text-white" : "bg-white text-[#475569]"
              }`}
            >
              By Channel
            </button>
            <button
              type="button"
              onClick={() => setSliceTab("segment")}
              className={`px-2.5 py-1 font-medium cursor-pointer border-l border-[#CBD5E1] ${
                sliceTab === "segment" ? "bg-[#0F2942] text-white" : "bg-white text-[#475569]"
              }`}
            >
              By Segment
            </button>
          </div>
        }
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="cl-table">
            <thead>
              <tr>
                <th>{sliceTab === "channel" ? "Marketing Channel" : "Customer Segment"}</th>
                <th className="text-right">Assigned</th>
                <th className="text-right">Reached</th>
                <th className="text-right">Reach %</th>
                <th className="text-right">Engaged</th>
                <th className="text-right">Engage / Reach</th>
                <th className="text-right">Booked</th>
                <th className="text-right">Book / Engaged</th>
                <th className="text-right">Completed</th>
                <th className="text-right">End-to-End %</th>
              </tr>
            </thead>
            <tbody>
              {(sliceTab === "channel" ? data.by_channel : data.by_segment).map((row: any) => (
                <tr key={row.channel_name || row.segment_name}>
                  <td className="font-medium text-[#0F2942]">{row.channel_name || row.segment_name}</td>
                  <td className="text-right font-mono-num">{fmtInt(row.assigned)}</td>
                  <td className="text-right font-mono-num">{fmtInt(row.reached)}</td>
                  <td className="text-right font-mono-num">{fmtPct(row.reach_rate, 1)}</td>
                  <td className="text-right font-mono-num">{fmtInt(row.engaged)}</td>
                  <td className="text-right font-mono-num">{fmtPct(row.engage_rate, 1)}</td>
                  <td className="text-right font-mono-num">{fmtInt(row.booked)}</td>
                  <td className="text-right font-mono-num">{fmtPct(row.book_of_engaged, 1)}</td>
                  <td className="text-right font-mono-num">{fmtInt(row.completed)}</td>
                  <td className="text-right font-mono-num font-semibold text-[#0F2942]">
                    {fmtPct(row.end_to_end_rate, 2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
