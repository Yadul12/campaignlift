"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useFilters } from "@/context/FilterContext";
import { apiGet, buildFilterQueryString } from "@/lib/api";
import { fmtCurrency, fmtDecimal, fmtInt, fmtPct, fmtSignedPP } from "@/lib/format";
import { CHART_COLORS, PlotlyChart } from "@/components/charts/PlotlyChart";
import {
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
  MethodNote,
  PageHeader,
  Panel,
  StatusBadge,
} from "@/components/ui/Primitives";

interface ModelRun {
  run_id: number;
  model_name: string;
  model_role: string;
  train_period: string;
  val_period: string;
  test_period: string;
  n_train: number;
  n_val: number;
  n_test: number;
  roc_auc: number;
  roc_auc_ci_low: number;
  roc_auc_ci_high: number;
  pr_auc: number;
  pr_auc_ci_low: number;
  pr_auc_ci_high: number;
  brier_score: number;
  log_loss_val: number;
  f1_score_val: number;
  precision_top_20: number;
  lift_top_decile: number;
  qini_auc: number | null;
  training_seconds: number;
  confusion_matrix: { tn: number; fp: number; fn: number; tp: number; threshold: number } | null;
  calibration: { bin: number; mean_predicted: number; observed_rate: number }[] | null;
  feature_importance: { feature: string; importance: number }[] | null;
  slice_metrics: { segment: string; n_test: number; actual_rate: number; predicted_rate: number; roc_auc: number; pr_auc: number; brier: number }[] | null;
  uplift_deciles: {
    decile: number;
    n_customers: number;
    predicted_uplift_pp: number;
    observed_treatment_rate_pct: number;
    observed_control_rate_pct: number;
    observed_uplift_pp: number;
    cumulative_incremental_bookings: number;
  }[] | null;
  limitations: string[] | null;
}

interface CustomerResponseData {
  total_customers_scored: number;
  archetypes: {
    response_archetype: string;
    recommended_incentive: string;
    customer_count: number;
    share_pct: number;
    avg_trips_12m: number;
    avg_spend_12m: number;
    avg_miles_balance: number;
    avg_baseline_prob: number;
    avg_promo_prob: number;
    avg_predicted_uplift: number;
    avg_discount_uplift: number;
    avg_miles_uplift: number;
  }[];
  segment_incentive_matrix: {
    segment_id: number;
    segment_name: string;
    incentive_affinity: string;
    customers: number;
    baseline_prob: number;
    discount_uplift: number;
    miles_uplift: number;
    avg_spend_12m: number;
    sure_things_cnt: number;
    persuadable_cnt: number;
  }[];
  model_runs: ModelRun[];
  customer_cohort_sample: {
    customer_code: string;
    segment_name: string;
    loyalty_tier: string;
    home_airport: string;
    historical_trips_12m: number;
    historical_spend_12m: number;
    miles_balance: number;
    baseline_booking_prob: number;
    predicted_uplift: number;
    discount_uplift_score: number;
    miles_uplift_score: number;
    uplift_decile: number;
    response_archetype: string;
    recommended_incentive: string;
  }[];
}

export default function CustomerResponsePage() {
  const { filters, resetFilters } = useFilters();
  const [selectedArchetype, setSelectedArchetype] = useState<string>("");
  const [activeModelRole, setActiveModelRole] = useState<string>("advanced_gbdt");
  const [data, setData] = useState<CustomerResponseData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const qs = buildFilterQueryString(filters, { archetype: selectedArchetype || undefined, limit: 40 });
    apiGet<CustomerResponseData>(`/customers${qs}`, controller.signal)
      .then((res) => setData(res))
      .catch((err) => {
        if (err.name !== "AbortError") setError(err.message);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [filters, selectedArchetype]);

  useEffect(() => {
    const cancel = loadData();
    return cancel;
  }, [loadData]);

  const activeModel = useMemo(
    () => data?.model_runs.find((m) => m.model_role === activeModelRole) || data?.model_runs[2] || null,
    [data, activeModelRole]
  );

  const upliftModel = useMemo(
    () => data?.model_runs.find((m) => m.model_role === "causal_uplift_tlearner") || null,
    [data]
  );

  const segIncentiveChart = useMemo(() => {
    if (!data) return [];
    const segs = data.segment_incentive_matrix.map((s) => s.segment_name);
    return [
      {
        type: "bar",
        name: "15% Fare Discount Uplift (pp)",
        x: segs,
        y: data.segment_incentive_matrix.map((s) => s.discount_uplift * 100),
        marker: { color: CHART_COLORS.navy },
        hovertemplate: "<b>%{x}</b><br>Discount Uplift: +%{y:.2f} pp<extra></extra>",
      },
      {
        type: "bar",
        name: "6,000 Bonus Miles Uplift (pp)",
        x: segs,
        y: data.segment_incentive_matrix.map((s) => s.miles_uplift * 100),
        marker: { color: CHART_COLORS.teal },
        hovertemplate: "<b>%{x}</b><br>Bonus Miles Uplift: +%{y:.2f} pp<extra></extra>",
      },
    ];
  }, [data]);

  const upliftDecileChart = useMemo(() => {
    const decs = upliftModel?.uplift_deciles;
    if (!decs) return [];
    return [
      {
        type: "bar",
        name: "Observed Out-of-Time RCT Lift (pp)",
        x: decs.map((d) => `D${d.decile}`),
        y: decs.map((d) => d.observed_uplift_pp),
        marker: {
          color: decs.map((d) => (d.observed_uplift_pp >= 0 ? CHART_COLORS.cobalt : CHART_COLORS.crimson)),
        },
        hovertemplate: "<b>Decile %{x}</b><br>Observed RCT Lift: %{y:+.2f} pp<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines+markers",
        name: "Predicted T-Learner Uplift (pp)",
        x: decs.map((d) => `D${d.decile}`),
        y: decs.map((d) => d.predicted_uplift_pp),
        line: { color: CHART_COLORS.navy, width: 2 },
        marker: { size: 5 },
        hovertemplate: "<b>Decile %{x}</b><br>Predicted Uplift: %{y:+.2f} pp<extra></extra>",
      },
    ];
  }, [upliftModel]);

  const calibrationChart = useMemo(() => {
    if (!data) return [];
    const lr = data.model_runs.find((m) => m.model_role === "linear_baseline");
    const gb = data.model_runs.find((m) => m.model_role === "advanced_gbdt");
    const traces: Record<string, unknown>[] = [
      {
        type: "scatter",
        mode: "lines",
        name: "Perfect Calibration",
        x: [0, 0.4],
        y: [0, 0.4],
        line: { color: "#94A3B8", width: 1.2, dash: "dash" },
        hoverinfo: "skip",
      },
    ];
    if (lr?.calibration) {
      traces.push({
        type: "scatter",
        mode: "lines+markers",
        name: "Logistic Regression (Baseline)",
        x: lr.calibration.map((c) => c.mean_predicted),
        y: lr.calibration.map((c) => c.observed_rate),
        line: { color: CHART_COLORS.steel, width: 1.8 },
        marker: { size: 5 },
      });
    }
    if (gb?.calibration) {
      traces.push({
        type: "scatter",
        mode: "lines+markers",
        name: "HistGradientBoosting (Advanced)",
        x: gb.calibration.map((c) => c.mean_predicted),
        y: gb.calibration.map((c) => c.observed_rate),
        line: { color: CHART_COLORS.navy, width: 2.3 },
        marker: { size: 6 },
      });
    }
    return traces;
  }, [data]);

  const featureImpChart = useMemo(() => {
    const fi = activeModel?.feature_importance?.slice(0, 10);
    if (!fi || fi.length === 0) return [];
    const rev = [...fi].reverse();
    return [
      {
        type: "bar",
        orientation: "h",
        y: rev.map((f) => f.feature),
        x: rev.map((f) => f.importance),
        marker: { color: CHART_COLORS.cobalt },
        hovertemplate: "<b>%{y}</b><br>Permutation ROC-AUC Drop: %{x:.4f}<extra></extra>",
      },
    ];
  }, [activeModel]);

  if (loading && !data) return <LoadingPanel lines={8} />;
  if (error) return <ErrorPanel message={error} onRetry={loadData} />;
  if (!data) return <EmptyPanel onReset={resetFilters} />;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Customer Targeting & Predictive Modeling"
        title="Customer Response Archetypes & Causal Uplift Modeling"
        description="Separates genuinely persuadable customers from organic 'Sure Things' baseline bookers and contrasts fare-discount elasticity vs. loyalty-miles responsiveness using leakage-free out-of-time models."
      />

      {/* Behavioral Archetypes Matrix */}
      <Panel
        title={`Customer Behavioral Response Archetypes (${fmtInt(data.total_customers_scored)} Scored Customers)`}
        subtitle="Click any archetype row to filter the customer cohort explorer below"
        action={
          selectedArchetype && (
            <button
              type="button"
              onClick={() => setSelectedArchetype("")}
              className="text-[11.5px] font-medium text-[#1E5B94] hover:underline cursor-pointer"
            >
              Clear Archetype Filter
            </button>
          )
        }
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="cl-table">
            <thead>
              <tr>
                <th>Response Archetype</th>
                <th className="text-right">Customers</th>
                <th className="text-right">Share</th>
                <th className="text-right">Avg 12m Spend</th>
                <th className="text-right">Baseline Prob</th>
                <th className="text-right">Discount Uplift</th>
                <th className="text-right">Miles Uplift</th>
                <th>Recommended Action</th>
              </tr>
            </thead>
            <tbody>
              {data.archetypes.map((a) => {
                const isSelected = selectedArchetype === a.response_archetype;
                const badgeVar = a.response_archetype.includes("Sure Things")
                  ? "warning"
                  : a.response_archetype.includes("Non-Responders")
                  ? "neutral"
                  : a.response_archetype.includes("Loyalty") || a.response_archetype.includes("Persuadables")
                  ? "positive"
                  : "cobalt";
                return (
                  <tr
                    key={`${a.response_archetype}-${a.recommended_incentive}`}
                    onClick={() => setSelectedArchetype(isSelected ? "" : a.response_archetype)}
                    className={`cursor-pointer ${isSelected ? "bg-[#EFF6FF]" : ""}`}
                  >
                    <td className="font-semibold text-[#0F2942]">{a.response_archetype}</td>
                    <td className="text-right font-mono-num">{fmtInt(a.customer_count)}</td>
                    <td className="text-right font-mono-num">{fmtPct(a.share_pct, 1)}</td>
                    <td className="text-right font-mono-num">{fmtCurrency(a.avg_spend_12m)}</td>
                    <td className="text-right font-mono-num">{fmtPct(a.avg_baseline_prob, 2)}</td>
                    <td className="text-right font-mono-num text-[#0F2942]">{fmtSignedPP(a.avg_discount_uplift)}</td>
                    <td className="text-right font-mono-num text-[#0F766E]">{fmtSignedPP(a.avg_miles_uplift)}</td>
                    <td>
                      <StatusBadge label={a.recommended_incentive} variant={badgeVar} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Segment x Incentive Preference & Out-of-Time T-Learner Uplift */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
        <Panel
          className="xl:col-span-6"
          title="Fare Discount vs. Bonus Loyalty Miles Elasticity by Segment"
          subtitle="Counterfactual T-Learner predicted uplift (15% Fare Discount vs. 6,000 Bonus Miles)"
        >
          <PlotlyChart
            data={segIncentiveChart}
            height={295}
            layout={{
              barmode: "group",
              margin: { t: 28, r: 16, b: 78, l: 52 },
              xaxis: { tickangle: -18 },
              yaxis: { title: "Predicted Uplift (pp)", ticksuffix: " pp" },
            }}
          />
        </Panel>

        <Panel
          className="xl:col-span-6"
          title="Causal T-Learner Validation: Observed vs. Predicted RCT Lift by Decile"
          subtitle={`Held-out chronological RCT test set (${upliftModel?.test_period || ""}) · Normalized Qini Gain: ${
            upliftModel?.qini_auc !== null && upliftModel?.qini_auc !== undefined ? `+${upliftModel.qini_auc.toFixed(4)}` : "—"
          }`}
        >
          <PlotlyChart
            data={upliftDecileChart}
            height={295}
            layout={{
              xaxis: { title: "Predicted Uplift Decile (D1 = Top 10% Most Persuadable)" },
              yaxis: { title: "Incremental Conversion Lift (pp)", zeroline: true, zerolinecolor: "#475569" },
            }}
          />
        </Panel>
      </div>

      {/* Predictive Model Comparison Table */}
      <Panel
        title="Predictive & Causal Model Evaluation (Strict Chronological Holdout — Zero Leakage)"
        subtitle="All metrics computed from out-of-time test predictions (2025-12 to 2026-08) using strictly pre-campaign CRM & offer features; preprocessing fitted on training fold only"
        noPadding
      >
        <div className="overflow-x-auto">
          <table className="cl-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Test Period</th>
                <th className="text-right">Test N</th>
                <th className="text-right">ROC-AUC (95% CI)</th>
                <th className="text-right">PR-AUC (95% CI)</th>
                <th className="text-right">Brier</th>
                <th className="text-right">F1</th>
                <th className="text-right">Prec@20%</th>
                <th className="text-right">Lift@Top10%</th>
                <th className="text-right">Train (s)</th>
              </tr>
            </thead>
            <tbody>
              {data.model_runs.map((m) => (
                <tr
                  key={m.run_id}
                  onClick={() => m.model_role !== "naive_baseline" && setActiveModelRole(m.model_role)}
                  className={`cursor-pointer ${activeModel?.run_id === m.run_id ? "bg-[#EFF6FF]" : ""}`}
                >
                  <td>
                    <div className="font-semibold text-[#0F2942]">{m.model_name}</div>
                    <div className="text-[10.5px] text-[#64748B] font-mono-num">{m.model_role}</div>
                  </td>
                  <td className="text-[11.5px] text-[#475569]">{m.test_period}</td>
                  <td className="text-right font-mono-num">{fmtInt(m.n_test)}</td>
                  <td className="text-right font-mono-num font-semibold text-[#0F2942]">
                    {m.roc_auc.toFixed(4)}{" "}
                    <span className="text-[10.5px] font-normal text-[#64748B]">
                      [{m.roc_auc_ci_low.toFixed(3)}, {m.roc_auc_ci_high.toFixed(3)}]
                    </span>
                  </td>
                  <td className="text-right font-mono-num font-semibold text-[#1E5B94]">
                    {m.pr_auc.toFixed(4)}{" "}
                    <span className="text-[10.5px] font-normal text-[#64748B]">
                      [{m.pr_auc_ci_low.toFixed(3)}, {m.pr_auc_ci_high.toFixed(3)}]
                    </span>
                  </td>
                  <td className="text-right font-mono-num">{m.brier_score.toFixed(4)}</td>
                  <td className="text-right font-mono-num">{m.f1_score_val.toFixed(3)}</td>
                  <td className="text-right font-mono-num">{fmtPct(m.precision_top_20, 1)}</td>
                  <td className="text-right font-mono-num font-semibold text-[#0F766E]">{m.lift_top_decile.toFixed(2)}x</td>
                  <td className="text-right font-mono-num text-[#64748B]">{m.training_seconds.toFixed(2)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Model Diagnostics: Calibration, Feature Importance, Confusion Matrix & Segment Slice Errors */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
        <Panel
          className="xl:col-span-4"
          title="Probability Calibration Curve"
          subtitle="Observed vs. predicted conversion probability across deciles"
        >
          <PlotlyChart
            data={calibrationChart}
            height={250}
            layout={{
              margin: { t: 24, r: 12, b: 42, l: 48 },
              xaxis: { title: "Mean Predicted Probability", range: [0, 0.4] },
              yaxis: { title: "Observed Conversion Rate", range: [0, 0.4] },
            }}
          />
        </Panel>

        <Panel
          className="xl:col-span-4"
          title={`Permutation Feature Importance (${activeModel?.model_name || ""})`}
          subtitle="ROC-AUC decrease on validation holdout when permuting each pre-campaign feature"
        >
          <PlotlyChart
            data={featureImpChart}
            height={250}
            layout={{
              margin: { t: 10, r: 18, b: 36, l: 138 },
              xaxis: { title: "ROC-AUC Drop" },
            }}
          />
        </Panel>

        <Panel
          className="xl:col-span-4"
          title="Confusion Matrix & Slice Error Audit"
          subtitle={activeModel ? `Validation-tuned threshold = ${activeModel.confusion_matrix?.threshold.toFixed(3)}` : ""}
        >
          {activeModel?.confusion_matrix && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2 text-center font-mono-num text-[12px]">
                <div className="bg-[#F8FAFC] border border-[#E2E6EC] rounded-[4px] p-2">
                  <div className="text-[10px] text-[#64748B] uppercase">True Negative</div>
                  <div className="text-[15px] font-semibold text-[#0F1E2E]">{fmtInt(activeModel.confusion_matrix.tn)}</div>
                </div>
                <div className="bg-[#FFFBEB] border border-[#FDE68A] rounded-[4px] p-2">
                  <div className="text-[10px] text-[#B45309] uppercase">False Positive</div>
                  <div className="text-[15px] font-semibold text-[#B45309]">{fmtInt(activeModel.confusion_matrix.fp)}</div>
                </div>
                <div className="bg-[#FEF2F2] border border-[#FECACA] rounded-[4px] p-2">
                  <div className="text-[10px] text-[#B91C1C] uppercase">False Negative</div>
                  <div className="text-[15px] font-semibold text-[#B91C1C]">{fmtInt(activeModel.confusion_matrix.fn)}</div>
                </div>
                <div className="bg-[#ECFDF5] border border-[#A7F3D0] rounded-[4px] p-2">
                  <div className="text-[10px] text-[#0F766E] uppercase">True Positive</div>
                  <div className="text-[15px] font-semibold text-[#0F766E]">{fmtInt(activeModel.confusion_matrix.tp)}</div>
                </div>
              </div>

              {activeModel.slice_metrics && (
                <div className="overflow-x-auto max-h-[168px]">
                  <table className="w-full border-collapse text-[10.5px]">
                    <thead>
                      <tr className="border-b border-[#D8DFE8] bg-[#F8FAFC] text-[#475569] uppercase">
                        <th className="text-left py-1.5 px-1.5 font-semibold">Segment Slice</th>
                        <th className="text-right py-1.5 px-1.5 font-semibold">AUC</th>
                        <th className="text-right py-1.5 px-1.5 font-semibold">Actual</th>
                        <th className="text-right py-1.5 px-1.5 font-semibold">Pred</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeModel.slice_metrics.map((sl) => (
                        <tr key={sl.segment} className="border-b border-[#EEF1F5]">
                          <td className="py-1 px-1.5 text-[#0F1E2E] truncate max-w-[140px]" title={sl.segment}>
                            {sl.segment.replace(" Travelers", "").replace(" Flyers", "").replace(" Warriors", "")}
                          </td>
                          <td className="text-right py-1 px-1.5 font-mono-num">{sl.roc_auc.toFixed(3)}</td>
                          <td className="text-right py-1 px-1.5 font-mono-num">{fmtPct(sl.actual_rate, 1)}</td>
                          <td className="text-right py-1 px-1.5 font-mono-num">{fmtPct(sl.predicted_rate, 1)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </Panel>
      </div>

      {/* Model Limitations & Leakage Safeguards */}
      {activeModel?.limitations && (
        <MethodNote title="Modeling Governance, Leakage Safeguards & Limitations" tone="info">
          <ul className="list-disc pl-4 space-y-1">
            {activeModel.limitations.map((lim, i) => (
              <li key={i}>{lim}</li>
            ))}
          </ul>
        </MethodNote>
      )}

      {/* Scored Customer Cohort Explorer */}
      <Panel
        title={`Scored Customer Targeting Explorer${selectedArchetype ? ` — ${selectedArchetype}` : ""}`}
        subtitle="Top 40 customers by predicted incremental promotional uplift within active filter scope"
        noPadding
      >
        <div className="overflow-x-auto max-h-[360px]">
          <table className="cl-table">
            <thead className="sticky top-0 z-10">
              <tr>
                <th>Customer</th>
                <th>Segment</th>
                <th>Tier / Hub</th>
                <th className="text-right">12m Trips</th>
                <th className="text-right">12m Spend</th>
                <th className="text-right">Baseline Prob</th>
                <th className="text-right">Discount Lift</th>
                <th className="text-right">Miles Lift</th>
                <th className="text-right">Decile</th>
                <th>Archetype &amp; Action</th>
              </tr>
            </thead>
            <tbody>
              {data.customer_cohort_sample.map((cu) => (
                <tr key={cu.customer_code}>
                  <td className="font-mono-num font-semibold text-[#0F2942] whitespace-nowrap">{cu.customer_code}</td>
                  <td className="whitespace-nowrap">{cu.segment_name}</td>
                  <td className="text-[#475569] whitespace-nowrap">
                    {cu.loyalty_tier} · <span className="font-mono-num">{cu.home_airport}</span>
                  </td>
                  <td className="text-right font-mono-num whitespace-nowrap">{cu.historical_trips_12m}</td>
                  <td className="text-right font-mono-num whitespace-nowrap">{fmtCurrency(cu.historical_spend_12m)}</td>
                  <td className="text-right font-mono-num whitespace-nowrap">{fmtPct(cu.baseline_booking_prob, 2)}</td>
                  <td className="text-right font-mono-num whitespace-nowrap">{fmtSignedPP(cu.discount_uplift_score)}</td>
                  <td className="text-right font-mono-num text-[#0F766E] whitespace-nowrap">{fmtSignedPP(cu.miles_uplift_score)}</td>
                  <td className="text-right font-mono-num font-semibold whitespace-nowrap">D{cu.uplift_decile}</td>
                  <td className="whitespace-nowrap">
                    <div className="text-[11.5px] font-medium text-[#0F1E2E]">{cu.response_archetype}</div>
                    <div className="text-[10.5px] text-[#1E5B94]">{cu.recommended_incentive}</div>
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
