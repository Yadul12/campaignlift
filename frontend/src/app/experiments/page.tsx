"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Calculator, ExternalLink, Search } from "lucide-react";
import { useFilters } from "@/context/FilterContext";
import { apiGet, apiPost, buildFilterQueryString } from "@/lib/api";
import { fmtCurrency, fmtDecimal, fmtInt, fmtPct, fmtPValue, fmtSignedPP } from "@/lib/format";
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

interface ExpListItem {
  campaign_id: number;
  campaign_code: string;
  campaign_name: string;
  campaign_type: string;
  experiment_type: string;
  channel_name: string;
  target_segment_name: string;
  start_date: string;
  n_treatment: number;
  n_control: number;
  srm_passed: boolean | null;
  max_covariate_smd: number | null;
  conversion_lift_abs: number;
  conversion_p_value: number | null;
  incremental_contribution: number | null;
  is_statistically_significant: boolean;
  recommendation_status: string;
}

interface ExpDetail {
  campaign: Record<string, any>;
  diagnostics: {
    is_rct: boolean;
    methodology: string;
    n_treatment: number;
    n_control: number;
    reached_treatment: number;
    exposure_compliance_rate: number;
    cace_approx_conv_lift: number | null;
    srm_chi2: number | null;
    srm_p_value: number | null;
    srm_passed: boolean | null;
    max_covariate_smd: number | null;
    covariate_balance: {
      covariate: string;
      treatment_mean: number;
      control_mean: number;
      smd: number;
      status: string;
    }[];
    selection_bias_warning: string | null;
    ipw_sensitivity: {
      ipw_conversion_lift_abs: number | null;
      ipw_contrib_lift_per_cust: number | null;
      overlap_pct: number | null;
    } | null;
  };
  incremental_summary: {
    causal_claim_allowed: boolean;
    marketing_spend: number;
    incremental_bookings: number | null;
    incremental_revenue: number | null;
    incremental_contribution: number | null;
    cost_per_incremental_booking: number | null;
    recommendation_status: string;
  };
  metrics_table: {
    metric_key: string;
    metric_name: string;
    unit: string;
    is_conditional: boolean;
    control_value: number | null;
    treatment_value: number | null;
    lift_abs: number | null;
    lift_rel: number | null;
    ci_low: number | null;
    ci_high: number | null;
    test_stat: number | null;
    test_stat_label: string;
    secondary_stat?: number | null;
    secondary_stat_label?: string;
    secondary_p_value?: number | null;
    p_value: number | null;
    power: number | null;
    significant: boolean;
    primary_test: string;
    rationale: string;
  }[];
  subgroup_hte: {
    segment_name: string;
    n_treatment: number;
    n_control: number;
    control_conv: number;
    treatment_conv: number;
    conv_lift_pp: number;
    conv_ci_low_pp: number;
    conv_ci_high_pp: number;
    conv_p_value: number;
    contrib_lift_per_cust: number;
    contrib_ci_low: number;
    contrib_ci_high: number;
    contrib_p_value: number;
  }[];
}

interface SampleSizeResult {
  baseline_rate: number;
  target_treatment_rate: number;
  mde_abs: number;
  mde_rel: number;
  cohen_h: number;
  required_n_control: number;
  required_n_treatment: number;
  required_n_total: number;
  power_curve: { total_sample: number; control_sample: number; treatment_sample: number; power: number }[];
  mde_sensitivity: { mde_abs_pp: number; mde_rel_pct: number; n_control: number; n_treatment: number; n_total: number }[];
}

function ExperimentationLabContent() {
  const searchParams = useSearchParams();
  const { filters, resetFilters } = useFilters();
  const [listData, setListData] = useState<{ summary: Record<string, number>; experiments: ExpListItem[] } | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const [detail, setDetail] = useState<ExpDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Sample Size Calculator State
  const [baselinePct, setBaselinePct] = useState(7.5);
  const [mdePP, setMdePP] = useState(1.5);
  const [alpha, setAlpha] = useState(0.05);
  const [power, setPower] = useState(0.8);
  const [splitPct, setSplitPct] = useState(50);
  const [ssResult, setSsResult] = useState<SampleSizeResult | null>(null);

  const loadList = useCallback(() => {
    const controller = new AbortController();
    setListLoading(true);
    setListError(null);
    const qs = buildFilterQueryString(filters);
    apiGet<{ summary: Record<string, number>; experiments: ExpListItem[] }>(`/experiments${qs}`, controller.signal)
      .then((res) => {
        setListData(res);
        const paramId = searchParams.get("campaign_id");
        if (paramId && res.experiments.some((e) => e.campaign_id === Number(paramId))) {
          setSelectedId(Number(paramId));
        } else if (filters.campaign_id && res.experiments.some((e) => e.campaign_id === Number(filters.campaign_id))) {
          setSelectedId(Number(filters.campaign_id));
        } else if (res.experiments.length > 0) {
          setSelectedId((prev) =>
            prev && res.experiments.some((e) => e.campaign_id === prev) ? prev : res.experiments[0].campaign_id
          );
        } else {
          setSelectedId(null);
        }
      })
      .catch((err) => {
        if (err.name !== "AbortError") setListError(err.message);
      })
      .finally(() => setListLoading(false));
    return () => controller.abort();
  }, [filters, searchParams]);

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
    apiGet<ExpDetail>(`/experiments/${selectedId}`, controller.signal)
      .then((res) => setDetail(res))
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
    return () => controller.abort();
  }, [selectedId]);

  useEffect(() => {
    const controller = new AbortController();
    apiPost<SampleSizeResult>(
      "/experiments/sample-size",
      {
        baseline_rate: baselinePct / 100,
        mde_abs: mdePP / 100,
        alpha,
        power,
        treatment_split: splitPct / 100,
      },
      controller.signal
    )
      .then((res) => setSsResult(res))
      .catch(() => {});
    return () => controller.abort();
  }, [baselinePct, mdePP, alpha, power, splitPct]);

  const filteredList = useMemo(() => {
    if (!listData) return [];
    const q = searchTerm.trim().toLowerCase();
    if (!q) return listData.experiments;
    return listData.experiments.filter(
      (e) =>
        e.campaign_name.toLowerCase().includes(q) ||
        e.campaign_code.toLowerCase().includes(q) ||
        e.experiment_type.toLowerCase().includes(q) ||
        e.channel_name.toLowerCase().includes(q)
    );
  }, [listData, searchTerm]);

  const forestChartData = useMemo(() => {
    if (!detail || detail.subgroup_hte.length === 0) return [];
    const sorted = [...detail.subgroup_hte].sort((a, b) => a.conv_lift_pp - b.conv_lift_pp);
    return [
      {
        type: "scatter",
        mode: "markers",
        name: "Conversion Lift (pp) ± 95% CI",
        y: sorted.map((s) => s.segment_name),
        x: sorted.map((s) => s.conv_lift_pp),
        error_x: {
          type: "data",
          symmetric: false,
          array: sorted.map((s) => s.conv_ci_high_pp - s.conv_lift_pp),
          arrayminus: sorted.map((s) => s.conv_lift_pp - s.conv_ci_low_pp),
          color: CHART_COLORS.navy,
          thickness: 1.5,
          width: 4,
        },
        marker: {
          size: 8,
          color: sorted.map((s) =>
            s.conv_ci_low_pp > 0 ? CHART_COLORS.teal : s.conv_ci_high_pp < 0 ? CHART_COLORS.crimson : CHART_COLORS.steel
          ),
        },
        hovertemplate: "<b>%{y}</b><br>Lift: %{x:+.2f} pp<extra></extra>",
      },
    ];
  }, [detail]);

  const smdChartData = useMemo(() => {
    if (!detail) return [];
    const bal = detail.diagnostics.covariate_balance;
    return [
      {
        type: "bar",
        orientation: "h",
        y: bal.map((b) => b.covariate),
        x: bal.map((b) => Math.abs(b.smd)),
        marker: {
          color: bal.map((b) =>
            Math.abs(b.smd) < 0.1 ? CHART_COLORS.teal : Math.abs(b.smd) < 0.2 ? CHART_COLORS.amber : CHART_COLORS.crimson
          ),
        },
        text: bal.map((b) => `${b.smd >= 0 ? "+" : ""}${b.smd.toFixed(3)}`),
        textposition: "outside",
        cliponaxis: false,
        textfont: { size: 10.5, family: "IBM Plex Mono, monospace", color: "#0F1E2E" },
        hovertemplate: "<b>%{y}</b><br>|SMD|: %{x:.3f}<extra></extra>",
      },
    ];
  }, [detail]);

  const powerCurveData = useMemo(() => {
    if (!ssResult) return [];
    return [
      {
        type: "scatter",
        mode: "lines+markers",
        name: "Statistical Power",
        x: ssResult.power_curve.map((p) => p.total_sample),
        y: ssResult.power_curve.map((p) => p.power * 100),
        line: { color: CHART_COLORS.navy, width: 2.2 },
        marker: { size: 5, color: CHART_COLORS.cobalt },
        hovertemplate: "Total N: %{x:,}<br>Power: %{y:.1f}%<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines",
        name: `Target Power (${(power * 100).toFixed(0)}%)`,
        x: [ssResult.power_curve[0]?.total_sample || 0, ssResult.power_curve[ssResult.power_curve.length - 1]?.total_sample || 0],
        y: [power * 100, power * 100],
        line: { color: CHART_COLORS.teal, width: 1.5, dash: "dash" },
        hoverinfo: "skip",
      },
    ];
  }, [ssResult, power]);

  if (listLoading && !listData) return <LoadingPanel lines={8} />;
  if (listError) return <ErrorPanel message={listError} onRetry={loadList} />;
  if (!listData || listData.experiments.length === 0) return <EmptyPanel onReset={resetFilters} />;

  const formatMetricVal = (val: number | null, unit: string) => {
    if (val === null || val === undefined) return "—";
    if (unit === "percent") return fmtPct(val, 2);
    if (unit === "currency") return fmtCurrency(val);
    return val.toFixed(4);
  };

  const formatLift = (val: number | null, unit: string) => {
    if (val === null || val === undefined) return "—";
    if (unit === "percent") return fmtSignedPP(val);
    if (unit === "currency") return `${val >= 0 ? "+" : ""}${fmtCurrency(val)}`;
    return `${val >= 0 ? "+" : ""}${val.toFixed(4)}`;
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Causal Inference & Statistical Testing"
        title="Experimentation Lab"
        description="Intention-to-Treat (ITT) evaluation for randomized campaigns, SRM & covariate balance diagnostics, observational selection-bias auditing, and experimental power planning."
      />

      <MetricStrip
        columns={5}
        items={[
          { label: "Experiments in Scope", value: fmtInt(listData.summary.total), sublabel: `${listData.summary.rct_count} RCT · ${listData.summary.observational_count} Observational`, tone: "navy" },
          { label: "RCT SRM Integrity", value: `${listData.summary.srm_passed_count} / ${listData.summary.rct_count}`, sublabel: "Chi-square goodness-of-fit (p >= 0.001)", tone: "positive" },
          { label: "Stat. Significant RCTs", value: fmtInt(listData.summary.statistically_significant_count), sublabel: "Two-proportion z-test (alpha = 0.05)", tone: "navy" },
          { label: "Observational Audits", value: fmtInt(listData.summary.observational_count), sublabel: "Flagged for selection bias (no causal claim)", tone: "warning" },
          {
            label: "Selected Study Design",
            value: detail?.campaign.experiment_type || "—",
            sublabel: detail?.diagnostics.is_rct ? "ITT Validated" : "Non-Randomized",
            tone: detail?.diagnostics.is_rct ? "positive" : "warning",
          },
        ]}
      />

      {/* Workbench Split: Experiment Selector (left 4 cols) + Inference Workbench (right 8 cols) */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5 items-start">
        <Panel
          className="xl:col-span-4"
          title="Select Campaign Experiment"
          subtitle="RCTs listed first; select an Observational campaign to audit selection bias"
          noPadding
        >
          <div className="p-2.5 border-b border-[#EEF1F5]">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-[#64748B] absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Filter by code, name, RCT, Obs..."
                className="w-full h-[28px] pl-8 pr-2 text-[11.5px] bg-[#FAFBFD] border border-[#CBD5E1] rounded-[4px] focus:outline-none focus:border-[#1E5B94]"
              />
            </div>
          </div>
          <div className="max-h-[640px] overflow-y-auto divide-y divide-[#EEF1F5]">
            {filteredList.map((e) => {
              const active = e.campaign_id === selectedId;
              return (
                <button
                  key={e.campaign_id}
                  type="button"
                  onClick={() => setSelectedId(e.campaign_id)}
                  className={`w-full text-left px-3.5 py-2.5 transition-colors cursor-pointer ${
                    active ? "bg-[#EFF6FF] border-l-[3px] border-[#0F2942]" : "hover:bg-[#F8FAFC]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono-num text-[11px] font-semibold text-[#1E5B94]">{e.campaign_code}</span>
                    <div className="flex items-center gap-1.5">
                      <StatusBadge label={e.experiment_type} variant={e.experiment_type === "RCT" ? "cobalt" : "warning"} />
                      {e.experiment_type === "RCT" && (
                        <span className={`font-mono-num text-[11px] font-semibold ${(e.incremental_contribution || 0) >= 0 ? "text-[#0F766E]" : "text-[#B91C1C]"}`}>
                          {fmtCurrency(e.incremental_contribution, true)}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-[12px] font-medium text-[#0F1E2E] truncate mt-0.5">{e.campaign_name}</div>
                  <div className="flex items-center justify-between text-[10.5px] text-[#64748B] mt-0.5">
                    <span>{e.channel_name} · {e.target_segment_name}</span>
                    <span className="font-mono-num">
                      N={fmtInt(e.n_treatment + e.n_control)}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </Panel>

        <div className="xl:col-span-8 space-y-5">
          {detailLoading || !detail ? (
            <LoadingPanel lines={10} />
          ) : (
            <>
              <Panel
                title={`${detail.campaign.campaign_code}: ${detail.campaign.campaign_name}`}
                subtitle={`${detail.campaign.campaign_type} · ${detail.campaign.channel_name} · ${detail.campaign.start_date} to ${detail.campaign.end_date} (+${detail.campaign.booking_window_days}d window) · Offer: ${
                  detail.campaign.discount_pct > 0 ? `${detail.campaign.discount_pct}% Off` : ""
                }${detail.campaign.discount_pct > 0 && detail.campaign.bonus_miles_offer > 0 ? " + " : ""}${
                  detail.campaign.bonus_miles_offer > 0 ? `${fmtInt(detail.campaign.bonus_miles_offer)} Bonus Miles` : ""
                }`}
                action={
                  <div className="flex items-center gap-2">
                    <StatusBadge
                      label={detail.incremental_summary.recommendation_status}
                      variant={recommendationVariant(detail.incremental_summary.recommendation_status)}
                    />
                    <Link
                      href={`/reports?campaign_id=${detail.campaign.campaign_id}`}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-[11.5px] font-medium bg-[#0F2942] text-white rounded-[4px] hover:bg-[#1E5B94]"
                    >
                      Report <ExternalLink className="w-3 h-3" />
                    </Link>
                  </div>
                }
              >
                <div className="space-y-3">
                  <div className="text-[12px] text-[#334155]">
                    <span className="font-semibold text-[#0F2942]">Experimental Hypothesis: </span>
                    {detail.campaign.hypothesis}
                  </div>

                  {/* Experiment Health Diagnostics Strip */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
                    <div className="bg-[#FAFBFD] border border-[#E2E6EC] rounded-[4px] p-2.5">
                      <div className="text-[10px] uppercase font-semibold text-[#64748B]">Assigned Arms (ITT)</div>
                      <div className="font-mono-num text-[12.5px] font-semibold text-[#0F2942] mt-0.5 whitespace-nowrap">
                        T: {fmtInt(detail.diagnostics.n_treatment)} / C: {fmtInt(detail.diagnostics.n_control)}
                      </div>
                      <div className="text-[10.5px] text-[#64748B]">
                        {detail.diagnostics.is_rct
                          ? `Target split ${fmtPct(detail.campaign.treatment_split_target, 0)}`
                          : "Non-random pool"}
                      </div>
                    </div>

                    <div className="bg-[#FAFBFD] border border-[#E2E6EC] rounded-[4px] p-2.5">
                      <div className="text-[10px] uppercase font-semibold text-[#64748B]">SRM Goodness-of-Fit</div>
                      <div className="font-mono-num text-[14px] font-semibold mt-0.5">
                        {detail.diagnostics.is_rct ? (
                          <span className={detail.diagnostics.srm_passed ? "text-[#0F766E]" : "text-[#B91C1C]"}>
                            {detail.diagnostics.srm_passed ? "PASS" : "FAIL"} (p={fmtPValue(detail.diagnostics.srm_p_value)})
                          </span>
                        ) : (
                          <span className="text-[#B45309]">N/A (Obs)</span>
                        )}
                      </div>
                      <div className="text-[10.5px] text-[#64748B]">Chi-square split audit</div>
                    </div>

                    <div className="bg-[#FAFBFD] border border-[#E2E6EC] rounded-[4px] p-2.5">
                      <div className="text-[10px] uppercase font-semibold text-[#64748B]">Pre-Period Max |SMD|</div>
                      <div
                        className={`font-mono-num text-[14px] font-semibold mt-0.5 ${
                          (detail.diagnostics.max_covariate_smd || 0) < 0.1
                            ? "text-[#0F766E]"
                            : (detail.diagnostics.max_covariate_smd || 0) < 0.2
                            ? "text-[#B45309]"
                            : "text-[#B91C1C]"
                        }`}
                      >
                        {fmtDecimal(detail.diagnostics.max_covariate_smd, 3)}
                      </div>
                      <div className="text-[10.5px] text-[#64748B]">Threshold &lt; 0.10 balanced</div>
                    </div>

                    <div className="bg-[#FAFBFD] border border-[#E2E6EC] rounded-[4px] p-2.5">
                      <div className="text-[10px] uppercase font-semibold text-[#64748B]">Exposure Compliance</div>
                      <div className="font-mono-num text-[14px] font-semibold text-[#0F2942] mt-0.5">
                        {fmtPct(detail.diagnostics.exposure_compliance_rate, 1)}
                      </div>
                      <div className="text-[10.5px] text-[#64748B]">
                        {fmtInt(detail.diagnostics.reached_treatment)} of {fmtInt(detail.diagnostics.n_treatment)} reached
                      </div>
                    </div>
                  </div>

                  {/* Conditional Banner: Causal RCT Impact OR Observational Selection Bias Warning */}
                  {detail.diagnostics.is_rct ? (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
                      <div className="bg-[#F8FAFC] border border-[#CBD5E1] rounded-[4px] p-2.5">
                        <div className="text-[10px] uppercase font-semibold text-[#475569]">Causal Inc. Bookings</div>
                        <div className="font-mono-num text-[16px] font-semibold text-[#0F2942] mt-0.5">
                          {fmtDecimal(detail.incremental_summary.incremental_bookings, 1)}
                        </div>
                      </div>
                      <div className="bg-[#F8FAFC] border border-[#CBD5E1] rounded-[4px] p-2.5">
                        <div className="text-[10px] uppercase font-semibold text-[#475569]">Causal Inc. Revenue</div>
                        <div className="font-mono-num text-[16px] font-semibold text-[#0F2942] mt-0.5">
                          {fmtCurrency(detail.incremental_summary.incremental_revenue)}
                        </div>
                      </div>
                      <div className="bg-[#F8FAFC] border border-[#CBD5E1] rounded-[4px] p-2.5">
                        <div className="text-[10px] uppercase font-semibold text-[#475569]">Net Inc. Contribution</div>
                        <div
                          className={`font-mono-num text-[16px] font-semibold mt-0.5 ${
                            (detail.incremental_summary.incremental_contribution || 0) >= 0
                              ? "text-[#0F766E]"
                              : "text-[#B91C1C]"
                          }`}
                        >
                          {fmtCurrency(detail.incremental_summary.incremental_contribution)}
                        </div>
                      </div>
                      <div className="bg-[#F8FAFC] border border-[#CBD5E1] rounded-[4px] p-2.5">
                        <div className="text-[10px] uppercase font-semibold text-[#475569]">Cost / Inc. Booking</div>
                        <div className="font-mono-num text-[16px] font-semibold text-[#0F2942] mt-0.5">
                          {detail.incremental_summary.cost_per_incremental_booking !== null
                            ? fmtCurrency(detail.incremental_summary.cost_per_incremental_booking)
                            : "N/A"}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <MethodNote title="Observational Study — Causal Lift Withheld Due to Selection Bias" tone="danger">
                      <p>{detail.diagnostics.selection_bias_warning}</p>
                      {detail.diagnostics.ipw_sensitivity && (
                        <div className="mt-2 pt-2 border-t border-[#FECACA] flex flex-wrap gap-5 font-mono-num text-[11.5px]">
                          <span>
                            <strong>IPW Sensitivity Conv Diff:</strong>{" "}
                            {fmtSignedPP(detail.diagnostics.ipw_sensitivity.ipw_conversion_lift_abs)}
                          </span>
                          <span>
                            <strong>IPW Sensitivity Contrib/Cust:</strong>{" "}
                            {fmtCurrency(detail.diagnostics.ipw_sensitivity.ipw_contrib_lift_per_cust)}
                          </span>
                          <span>
                            <strong>Propensity Overlap:</strong>{" "}
                            {fmtPct(detail.diagnostics.ipw_sensitivity.overlap_pct, 1)}
                          </span>
                        </div>
                      )}
                    </MethodNote>
                  )}
                </div>
              </Panel>

              {/* Statistical Hypothesis Tests Table */}
              <Panel
                title={
                  detail.diagnostics.is_rct
                    ? "Intention-to-Treat (ITT) Hypothesis Tests & 95% Confidence Intervals"
                    : "Unadjusted Observational Comparison (Confounded — Reference Only)"
                }
                subtitle="Includes exact test statistic, p-value, 95% confidence interval, achieved power, and methodological test rationale"
                noPadding
              >
                <div className="overflow-x-auto">
                  <table className="cl-table table-fixed w-full">
                    <thead>
                      <tr>
                        <th className="w-[27%]">Metric</th>
                        <th className="w-[10%] text-right">Control</th>
                        <th className="w-[10%] text-right">Treat</th>
                        <th className="w-[11%] text-right">Lift</th>
                        <th className="w-[17%] text-right">95% CI</th>
                        <th className="w-[18%] text-right">Stat &amp; p</th>
                        <th className="w-[7%] text-right">Pwr</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.metrics_table.map((m) => (
                        <React.Fragment key={m.metric_key}>
                          <tr>
                            <td className="break-words">
                              <div className="font-semibold text-[#0F2942] flex flex-wrap items-center gap-1 leading-snug">
                                <span>{m.metric_name}</span>
                                {m.is_conditional && <StatusBadge label="Cond." variant="warning" />}
                              </div>
                              <div className="text-[10px] text-[#1E5B94] font-medium leading-snug mt-0.5">{m.primary_test}</div>
                            </td>
                            <td className="text-right font-mono-num text-[11.5px] whitespace-nowrap">{formatMetricVal(m.control_value, m.unit)}</td>
                            <td className="text-right font-mono-num text-[11.5px] font-medium whitespace-nowrap">{formatMetricVal(m.treatment_value, m.unit)}</td>
                            <td
                              className={`text-right font-mono-num text-[11.5px] font-semibold whitespace-nowrap ${
                                !detail.diagnostics.is_rct
                                  ? "text-[#64748B]"
                                  : (m.lift_abs || 0) > 0
                                  ? "text-[#0F766E]"
                                  : (m.lift_abs || 0) < 0
                                  ? "text-[#B91C1C]"
                                  : "text-[#475569]"
                              }`}
                            >
                              {formatLift(m.lift_abs, m.unit)}
                            </td>
                            <td className="text-right font-mono-num text-[10.5px] text-[#475569] leading-tight">
                              [{formatLift(m.ci_low, m.unit)}, {formatLift(m.ci_high, m.unit)}]
                            </td>
                            <td className="text-right font-mono-num text-[10.5px] leading-tight">
                              <div>
                                {m.test_stat_label}={fmtDecimal(m.test_stat, 2)} ·{" "}
                                <span className={m.significant ? "font-semibold text-[#0F766E]" : "text-[#475569]"}>
                                  p={fmtPValue(m.p_value)}
                                </span>
                              </div>
                              {m.secondary_stat !== undefined && m.secondary_stat !== null && (
                                <div className="text-[10px] text-[#64748B]">
                                  {m.secondary_stat_label}={fmtDecimal(m.secondary_stat, 2)} (p={fmtPValue(m.secondary_p_value)})
                                </div>
                              )}
                            </td>
                            <td className="text-right font-mono-num text-[11.5px] whitespace-nowrap">{fmtPct(m.power, 0)}</td>
                          </tr>
                          <tr className="bg-[#FAFBFD]">
                            <td colSpan={7} className="text-[11px] text-[#475569] py-1.5 px-3 whitespace-normal break-words">
                              <strong className="text-[#0F2942]">Why this test: </strong>
                              {m.rationale}
                            </td>
                          </tr>
                        </React.Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>

              {/* Covariate Balance + HTE Forest Plot */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                <Panel
                  title="Pre-Period Covariate Balance Audit (|SMD|)"
                  subtitle="Values < 0.10 verify unbiased randomization; values > 0.20 prove selection bias"
                >
                  <PlotlyChart
                    data={smdChartData}
                    height={245}
                    layout={{
                      margin: { t: 10, r: 58, b: 44, l: 155 },
                      xaxis: {
                        title: "Absolute SMD (|SMD|)",
                        automargin: true,
                        range: [0, Math.max(0.18, (detail.diagnostics.max_covariate_smd || 0.1) * 1.32)],
                      },
                      shapes: [
                        {
                          type: "line",
                          layer: "below",
                          x0: 0.1,
                          x1: 0.1,
                          y0: -0.5,
                          y1: 4.5,
                          line: { color: CHART_COLORS.amber, width: 1.5, dash: "dash" },
                        },
                      ],
                    }}
                  />
                </Panel>

                <Panel
                  title="Subgroup Treatment Effects (Forest Plot · 95% CI)"
                  subtitle="Segment-level conversion lift heterogeneity (percentage points)"
                >
                  {forestChartData.length > 0 ? (
                    <PlotlyChart
                      data={forestChartData}
                      height={235}
                      layout={{
                        margin: { t: 10, r: 20, b: 36, l: 170 },
                        xaxis: { title: "Conversion Lift (pp)", zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#475569" },
                      }}
                    />
                  ) : (
                    <div className="py-12 text-center text-[12px] text-[#64748B]">
                      Single-segment targeted campaign (no multi-segment HTE split).
                    </div>
                  )}
                </Panel>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Interactive Power & Sample Size Calculator */}
      <Panel
        title="Experimental Power & Sample-Size Calculator"
        subtitle="Plan future Meridian Air A/B promotional tests using exact two-proportion normal-approximation power analysis (statsmodels NormalIndPower)"
        action={
          <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-[#1E5B94]">
            <Calculator className="w-3.5 h-3.5" /> Live Server-Computed
          </span>
        }
      >
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
          <div className="xl:col-span-4 space-y-3.5">
            <div>
              <div className="flex justify-between text-[12px] mb-1">
                <label className="font-medium text-[#0F1E2E]">Baseline Conversion Rate</label>
                <span className="font-mono-num font-semibold text-[#0F2942]">{baselinePct.toFixed(1)}%</span>
              </div>
              <input type="range" min={1} max={25} step={0.5} value={baselinePct} onChange={(e) => setBaselinePct(Number(e.target.value))} className="cl-slider" />
            </div>

            <div>
              <div className="flex justify-between text-[12px] mb-1">
                <label className="font-medium text-[#0F1E2E]">Minimum Detectable Effect (MDE)</label>
                <span className="font-mono-num font-semibold text-[#0F2942]">+{mdePP.toFixed(2)} pp</span>
              </div>
              <input type="range" min={0.25} max={6.0} step={0.25} value={mdePP} onChange={(e) => setMdePP(Number(e.target.value))} className="cl-slider" />
            </div>

            <div className="grid grid-cols-3 gap-2.5">
              <div>
                <label className="block text-[11px] font-medium text-[#475569] mb-1">Alpha (α)</label>
                <select
                  value={alpha}
                  onChange={(e) => setAlpha(Number(e.target.value))}
                  className="w-full h-[30px] px-2 text-[12px] font-mono-num border border-[#CBD5E1] rounded-[4px]"
                >
                  <option value={0.01}>0.01</option>
                  <option value={0.05}>0.05</option>
                  <option value={0.1}>0.10</option>
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-medium text-[#475569] mb-1">Power (1-β)</label>
                <select
                  value={power}
                  onChange={(e) => setPower(Number(e.target.value))}
                  className="w-full h-[30px] px-2 text-[12px] font-mono-num border border-[#CBD5E1] rounded-[4px]"
                >
                  <option value={0.75}>75%</option>
                  <option value={0.8}>80%</option>
                  <option value={0.85}>85%</option>
                  <option value={0.9}>90%</option>
                </select>
              </div>
              <div>
                <label className="block text-[11px] font-medium text-[#475569] mb-1">Treat Split</label>
                <select
                  value={splitPct}
                  onChange={(e) => setSplitPct(Number(e.target.value))}
                  className="w-full h-[30px] px-2 text-[12px] font-mono-num border border-[#CBD5E1] rounded-[4px]"
                >
                  <option value={50}>50 / 50</option>
                  <option value={60}>60 / 40</option>
                  <option value={70}>70 / 30</option>
                  <option value={80}>80 / 20</option>
                </select>
              </div>
            </div>

            {ssResult && (
              <div className="bg-[#F8FAFC] border border-[#CBD5E1] rounded-[4px] p-3 grid grid-cols-3 gap-2 text-center">
                <div>
                  <div className="text-[10px] uppercase font-semibold text-[#64748B]">Control N</div>
                  <div className="font-mono-num text-[15px] font-semibold text-[#0F2942]">{fmtInt(ssResult.required_n_control)}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase font-semibold text-[#64748B]">Treatment N</div>
                  <div className="font-mono-num text-[15px] font-semibold text-[#1E5B94]">{fmtInt(ssResult.required_n_treatment)}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase font-semibold text-[#64748B]">Total Required</div>
                  <div className="font-mono-num text-[15px] font-semibold text-[#0F766E]">{fmtInt(ssResult.required_n_total)}</div>
                </div>
              </div>
            )}
          </div>

          <div className="xl:col-span-4">
            <PlotlyChart
              data={powerCurveData}
              height={235}
              layout={{
                margin: { t: 24, r: 12, b: 40, l: 48 },
                xaxis: { title: "Total Experiment Sample Size (N)" },
                yaxis: { title: "Power (%)", range: [0, 102], ticksuffix: "%" },
              }}
            />
          </div>

          <div className="xl:col-span-4 overflow-x-auto">
            <div className="text-[11.5px] font-semibold text-[#0F2942] mb-1.5">MDE Sample-Size Sensitivity</div>
            <table className="cl-table border border-[#E2E6EC]">
              <thead>
                <tr>
                  <th className="text-right">MDE (pp)</th>
                  <th className="text-right">Rel Lift</th>
                  <th className="text-right">Control N</th>
                  <th className="text-right">Treat N</th>
                  <th className="text-right">Total N</th>
                </tr>
              </thead>
              <tbody>
                {ssResult?.mde_sensitivity.map((r) => (
                  <tr key={r.mde_abs_pp} className={Math.abs(r.mde_abs_pp - mdePP) < 0.01 ? "bg-[#EFF6FF] font-semibold" : ""}>
                    <td className="text-right font-mono-num">+{r.mde_abs_pp.toFixed(2)}</td>
                    <td className="text-right font-mono-num">+{r.mde_rel_pct.toFixed(1)}%</td>
                    <td className="text-right font-mono-num">{fmtInt(r.n_control)}</td>
                    <td className="text-right font-mono-num">{fmtInt(r.n_treatment)}</td>
                    <td className="text-right font-mono-num text-[#0F2942]">{fmtInt(r.n_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Panel>
    </div>
  );
}

export default function ExperimentationLabPage() {
  return (
    <React.Suspense fallback={<LoadingPanel lines={8} />}>
      <ExperimentationLabContent />
    </React.Suspense>
  );
}
