"use client";

import React, { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Database, Download, FileSpreadsheet, FileText, Play } from "lucide-react";
import { useFilters } from "@/context/FilterContext";
import { apiGet, triggerFileDownload } from "@/lib/api";
import { fmtCurrency, fmtDecimal, fmtInt, fmtPct, fmtPValue } from "@/lib/format";
import {
  ErrorPanel,
  LoadingPanel,
  MethodNote,
  PageHeader,
  Panel,
  recommendationVariant,
  StatusBadge,
} from "@/components/ui/Primitives";

interface SQLQueryMeta {
  id: string;
  title: string;
  category: string;
  techniques: string[];
  indexes: string[];
  business_decision: string;
  sql: string;
}

interface SQLRunResult {
  query: SQLQueryMeta;
  columns: string[];
  row_count: number;
  rows: Record<string, any>[];
  explain_plan: string[];
}

interface AuditData {
  dataset_label: string;
  metadata: Record<string, string>;
  table_counts: { table_name: string; row_count: number }[];
  experiment_audit: {
    experiment_type: string;
    campaigns: number;
    srm_passed: number;
    avg_max_smd: number;
    sig_campaigns: number;
  }[];
  migrations: { version: string; applied_at: string }[];
}

function ReportsAndSQLContent() {
  const searchParams = useSearchParams();
  const { options, filters } = useFilters();
  const [activeTab, setActiveTab] = useState<"report" | "sql" | "audit">("report");

  // Executive Report state
  const [reportCampaignId, setReportCampaignId] = useState<number | null>(null);
  const [report, setReport] = useState<Record<string, any> | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  // SQL Analytics state
  const [sqlQueries, setSqlQueries] = useState<SQLQueryMeta[]>([]);
  const [selectedQueryId, setSelectedQueryId] = useState<string>("");
  const [sqlResult, setSqlResult] = useState<SQLRunResult | null>(null);
  const [sqlLoading, setSqlLoading] = useState(false);
  const [showExplain, setShowExplain] = useState(false);

  // Audit state
  const [audit, setAudit] = useState<AuditData | null>(null);

  useEffect(() => {
    if (!options) return;
    const qp = searchParams.get("campaign_id");
    if (qp) {
      setReportCampaignId(Number(qp));
    } else if (filters.campaign_id) {
      setReportCampaignId(Number(filters.campaign_id));
    } else if (!reportCampaignId && options.campaigns.length > 0) {
      const firstRct = options.campaigns.find((c) => c.experiment_type === "RCT") || options.campaigns[0];
      setReportCampaignId(firstRct.campaign_id);
    }
  }, [options, searchParams, filters.campaign_id, reportCampaignId]);

  useEffect(() => {
    if (!reportCampaignId) return;
    const controller = new AbortController();
    setReportLoading(true);
    setReportError(null);
    apiGet<Record<string, any>>(`/reports/campaign/${reportCampaignId}`, controller.signal)
      .then((res) => setReport(res))
      .catch((err) => {
        if (err.name !== "AbortError") setReportError(err.message);
      })
      .finally(() => setReportLoading(false));
    return () => controller.abort();
  }, [reportCampaignId]);

  useEffect(() => {
    apiGet<{ queries: SQLQueryMeta[] }>("/sql-analytics/queries")
      .then((res) => {
        setSqlQueries(res.queries);
        if (res.queries.length > 0) setSelectedQueryId(res.queries[0].id);
      })
      .catch(() => {});

    apiGet<AuditData>("/sql-analytics/audit")
      .then((res) => setAudit(res))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!selectedQueryId) return;
    const controller = new AbortController();
    setSqlLoading(true);
    apiGet<SQLRunResult>(`/sql-analytics/queries/${selectedQueryId}/run?include_explain=true`, controller.signal)
      .then((res) => setSqlResult(res))
      .catch(() => setSqlResult(null))
      .finally(() => setSqlLoading(false));
    return () => controller.abort();
  }, [selectedQueryId]);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Executive Decision Support & Data Engineering"
        title="Executive Reports, SQL Analytics Library & Data Audit"
        description="Board-ready downloadable campaign memos (PDF & multi-sheet Excel using identical dashboard math), live production PostgreSQL analytical queries with EXPLAIN plans, and synthetic data lineage."
      />

      {/* Top Section Switcher */}
      <div className="inline-flex rounded-[4px] border border-[#CBD5E1] bg-white overflow-hidden text-[12.5px]">
        {[
          { id: "report" as const, label: "Executive Campaign Report", icon: FileText },
          { id: "sql" as const, label: `SQL Analytics Library (${sqlQueries.length})`, icon: Database },
          { id: "audit" as const, label: "Data & Experiment Audit", icon: FileSpreadsheet },
        ].map((t) => {
          const Icon = t.icon;
          const active = activeTab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setActiveTab(t.id)}
              className={`px-4 py-2 inline-flex items-center gap-2 font-medium border-r last:border-r-0 border-[#CBD5E1] cursor-pointer ${
                active ? "bg-[#0F2942] text-white" : "text-[#475569] hover:bg-[#F8FAFC]"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {t.label}
            </button>
          );
        })}
      </div>

      {/* TAB 1: EXECUTIVE CAMPAIGN REPORT */}
      {activeTab === "report" && (
        <div className="space-y-4">
          <Panel>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2.5 flex-1 min-w-[280px]">
                <label className="text-[11.5px] font-semibold uppercase tracking-[0.04em] text-[#475569] whitespace-nowrap">
                  Report Campaign:
                </label>
                <select
                  value={reportCampaignId ? String(reportCampaignId) : ""}
                  onChange={(e) => setReportCampaignId(Number(e.target.value))}
                  className="h-[32px] px-2.5 text-[12px] bg-white border border-[#CBD5E1] rounded-[4px] flex-1 max-w-[520px]"
                >
                  {options?.campaigns.map((c) => (
                    <option key={c.campaign_id} value={String(c.campaign_id)}>
                      {c.campaign_code} ({c.experiment_type}) · {c.campaign_name}
                    </option>
                  ))}
                </select>
              </div>
              {reportCampaignId && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => triggerFileDownload(`/reports/campaign/${reportCampaignId}/pdf`)}
                    className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[12px] font-medium bg-[#0F2942] text-white rounded-[4px] hover:bg-[#1E5B94] cursor-pointer"
                  >
                    <Download className="w-3.5 h-3.5" /> Download PDF Report
                  </button>
                  <button
                    type="button"
                    onClick={() => triggerFileDownload(`/reports/campaign/${reportCampaignId}/excel`)}
                    className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[12px] font-medium bg-white border border-[#CBD5E1] text-[#0F1E2E] rounded-[4px] hover:bg-[#F8FAFC] cursor-pointer"
                  >
                    <FileSpreadsheet className="w-3.5 h-3.5" /> Download Excel (.xlsx)
                  </button>
                </div>
              )}
            </div>
          </Panel>

          {reportLoading && <LoadingPanel lines={12} />}
          {reportError && <ErrorPanel message={reportError} />}

          {report && !reportLoading && (
            <article className="bg-white border border-[#CBD5E1] rounded-[5px] p-6 md:p-8 space-y-6 max-w-[1160px]">
              {/* Report Masthead */}
              <div className="pb-4 border-b-2 border-[#0F2942] flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="text-[10.5px] font-semibold uppercase tracking-[0.09em] text-[#1E5B94]">
                    Meridian Air Commercial Analytics · Executive Campaign Evaluation Memo
                  </div>
                  <h2 className="text-[20px] font-semibold text-[#0F2942] mt-1">
                    {report.campaign.campaign_code}: {report.campaign.campaign_name}
                  </h2>
                  <div className="text-[11.5px] text-[#64748B] mt-1 font-mono-num">
                    {report.campaign.campaign_type} · {report.campaign.channel_name} · {report.campaign.start_date} to {report.campaign.end_date} (+{report.campaign.booking_window_days}d window) · {report.dataset_label}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge
                    label={report.campaign.experiment_type}
                    variant={report.campaign.experiment_type === "RCT" ? "cobalt" : "warning"}
                  />
                  <StatusBadge
                    label={report.recommended_action.status}
                    variant={recommendationVariant(report.recommended_action.status)}
                  />
                </div>
              </div>

              {/* 1. Business Question */}
              <section>
                <h3 className="text-[12.5px] font-semibold uppercase tracking-[0.05em] text-[#0F2942] mb-1.5">
                  1. Business Question
                </h3>
                <p className="text-[13px] text-[#1E293B] leading-relaxed">{report.business_question}</p>
              </section>

              {/* 2. Campaign Overview */}
              <section>
                <h3 className="text-[12.5px] font-semibold uppercase tracking-[0.05em] text-[#0F2942] mb-2">
                  2. Campaign Overview
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px]">
                  <div className="bg-[#FAFBFD] border border-[#E2E6EC] p-2.5 rounded-[4px]">
                    <div className="text-[10px] uppercase text-[#64748B] font-semibold">Target Segment</div>
                    <div className="font-semibold text-[#0F2942] mt-0.5">{report.campaign.target_segment_name}</div>
                  </div>
                  <div className="bg-[#FAFBFD] border border-[#E2E6EC] p-2.5 rounded-[4px]">
                    <div className="text-[10px] uppercase text-[#64748B] font-semibold">Route Market</div>
                    <div className="font-mono-num font-semibold text-[#0F2942] mt-0.5">{report.campaign.target_route_code}</div>
                  </div>
                  <div className="bg-[#FAFBFD] border border-[#E2E6EC] p-2.5 rounded-[4px]">
                    <div className="text-[10px] uppercase text-[#64748B] font-semibold">Offer Incentive</div>
                    <div className="font-mono-num font-semibold text-[#0F2942] mt-0.5">
                      {report.campaign.discount_pct.toFixed(1)}% Off · {fmtInt(report.campaign.bonus_miles_offer)} mi
                    </div>
                  </div>
                  <div className="bg-[#FAFBFD] border border-[#E2E6EC] p-2.5 rounded-[4px]">
                    <div className="text-[10px] uppercase text-[#64748B] font-semibold">Media &amp; Promo Spend</div>
                    <div className="font-mono-num font-semibold text-[#0F2942] mt-0.5">
                      {fmtCurrency(report.incremental_impact.marketing_spend)}
                    </div>
                  </div>
                </div>
              </section>

              {/* 3. Methodology */}
              <section>
                <h3 className="text-[12.5px] font-semibold uppercase tracking-[0.05em] text-[#0F2942] mb-1.5">
                  3. Methodology &amp; Randomization Audit
                </h3>
                <p className="text-[12.5px] text-[#334155] leading-relaxed">{report.methodology}</p>
              </section>

              {/* 4. Control & Treatment Results */}
              <section>
                <h3 className="text-[12.5px] font-semibold uppercase tracking-[0.05em] text-[#0F2942] mb-2">
                  4. Control vs. Treatment Results
                </h3>
                <div className="overflow-x-auto border border-[#E2E6EC] rounded-[4px]">
                  <table className="cl-table">
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th className="text-right">Control</th>
                        <th className="text-right">Treatment</th>
                        <th className="text-right">Abs Lift</th>
                        <th className="text-right">p-value</th>
                        <th className="text-right">Power</th>
                        <th>Test Method</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.metrics_table.map((m: any) => (
                        <tr key={m.metric_key}>
                          <td className="font-medium text-[#0F2942]">{m.metric_name}</td>
                          <td className="text-right font-mono-num">
                            {m.unit === "percent" ? fmtPct(m.control_value, 2) : m.unit === "currency" ? fmtCurrency(m.control_value) : fmtDecimal(m.control_value, 4)}
                          </td>
                          <td className="text-right font-mono-num">
                            {m.unit === "percent" ? fmtPct(m.treatment_value, 2) : m.unit === "currency" ? fmtCurrency(m.treatment_value) : fmtDecimal(m.treatment_value, 4)}
                          </td>
                          <td className="text-right font-mono-num font-semibold">
                            {m.unit === "percent"
                              ? `${(m.lift_abs * 100) >= 0 ? "+" : ""}${(m.lift_abs * 100).toFixed(2)} pp`
                              : m.unit === "currency"
                              ? fmtCurrency(m.lift_abs)
                              : fmtDecimal(m.lift_abs, 4)}
                          </td>
                          <td className="text-right font-mono-num">{fmtPValue(m.p_value)}</td>
                          <td className="text-right font-mono-num">{fmtPct(m.power, 0)}</td>
                          <td className="text-[11.5px] text-[#475569]">{m.primary_test}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              {/* 5 & 6. Incremental & Financial Impact */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <section className="bg-[#FAFBFD] border border-[#E2E6EC] rounded-[4px] p-4">
                  <h3 className="text-[12px] font-semibold uppercase tracking-[0.05em] text-[#0F2942] mb-1.5">
                    5. Incremental Impact
                  </h3>
                  <p className="text-[12.5px] text-[#334155] leading-relaxed">{report.incremental_impact.summary}</p>
                </section>
                <section className="bg-[#FAFBFD] border border-[#E2E6EC] rounded-[4px] p-4">
                  <h3 className="text-[12px] font-semibold uppercase tracking-[0.05em] text-[#0F2942] mb-1.5">
                    6. Financial Impact &amp; Margin P&amp;L
                  </h3>
                  <p className="text-[12.5px] text-[#334155] leading-relaxed">{report.financial_impact.summary}</p>
                </section>
              </div>

              {/* 7. Statistical Confidence & Risks */}
              <section>
                <h3 className="text-[12.5px] font-semibold uppercase tracking-[0.05em] text-[#0F2942] mb-1.5">
                  7. Statistical Confidence, Risks &amp; Limitations
                </h3>
                <ul className="list-disc pl-5 space-y-1 text-[12.5px] text-[#334155]">
                  {report.risks_and_limitations.map((r: string, i: number) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </section>

              {/* 8. Recommended Action */}
              <MethodNote
                title={`8. Recommended Commercial Action — ${report.recommended_action.status}`}
                tone={
                  report.recommended_action.status.includes("Scale")
                    ? "info"
                    : report.recommended_action.status.includes("Pause")
                    ? "danger"
                    : "warning"
                }
              >
                <span className="font-medium">{report.recommended_action.narrative}</span>
              </MethodNote>
            </article>
          )}
        </div>
      )}

      {/* TAB 2: SQL ANALYTICS LIBRARY */}
      {activeTab === "sql" && (
        <div className="space-y-5">
          <Panel
            title="Production SQL Analytics Library"
            subtitle="Select any reusable PostgreSQL query to inspect its commercial rationale, index optimization strategy, EXPLAIN plan, and live results"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2.5">
              {sqlQueries.map((q) => {
                const active = q.id === selectedQueryId;
                return (
                  <button
                    key={q.id}
                    type="button"
                    onClick={() => setSelectedQueryId(q.id)}
                    className={`text-left p-3 rounded-[4px] border transition-colors cursor-pointer ${
                      active
                        ? "bg-[#EFF6FF] border-[#0F2942] ring-1 ring-[#0F2942]"
                        : "bg-white border-[#E2E6EC] hover:bg-[#F8FAFC]"
                    }`}
                  >
                    <div className="text-[9.5px] font-semibold uppercase tracking-[0.06em] text-[#1E5B94]">
                      {q.category}
                    </div>
                    <div className="text-[12px] font-semibold text-[#0F1E2E] mt-0.5 leading-snug">{q.title}</div>
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {q.techniques.slice(0, 2).map((t) => (
                        <span
                          key={t}
                          className="text-[9.5px] px-1.5 py-0.5 bg-[#F1F5F9] text-[#475569] rounded-[3px]"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </button>
                );
              })}
            </div>
          </Panel>

          <div className="space-y-4">
            {sqlLoading && <LoadingPanel lines={10} />}
            {!sqlLoading && sqlResult && (
              <>
                <Panel
                  title={sqlResult.query.title}
                  subtitle={sqlResult.query.business_decision}
                  action={
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setShowExplain((s) => !s)}
                        className="px-2.5 py-1 text-[11.5px] font-medium bg-white border border-[#CBD5E1] text-[#0F1E2E] rounded-[4px] hover:bg-[#F8FAFC] cursor-pointer"
                      >
                        {showExplain ? "Hide EXPLAIN" : "Show EXPLAIN ANALYZE"}
                      </button>
                      <button
                        type="button"
                        onClick={() => triggerFileDownload(`/sql-analytics/queries/${sqlResult.query.id}/csv`)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 text-[11.5px] font-medium bg-[#0F2942] text-white rounded-[4px] hover:bg-[#1E5B94] cursor-pointer"
                      >
                        <Download className="w-3 h-3" /> CSV
                      </button>
                    </div>
                  }
                >
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2 text-[11px]">
                      <span className="font-semibold text-[#475569]">Indexes leveraged:</span>
                      {sqlResult.query.indexes.map((ix) => (
                        <code
                          key={ix}
                          className="font-mono-num px-1.5 py-0.5 bg-[#EFF4F9] text-[#0F2942] rounded-[3px]"
                        >
                          {ix}
                        </code>
                      ))}
                    </div>

                    <pre className="p-3.5 bg-[#0F1E2E] text-[#E2E8F0] rounded-[4px] text-[11.5px] font-mono-num overflow-x-auto max-h-[280px] leading-relaxed">
                      {sqlResult.query.sql}
                    </pre>

                    {showExplain && (
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.04em] text-[#475569] mb-1">
                          PostgreSQL EXPLAIN (ANALYZE) Plan
                        </div>
                        <pre className="p-3 bg-[#F8FAFC] border border-[#CBD5E1] text-[#1E293B] rounded-[4px] text-[11px] font-mono-num overflow-x-auto max-h-[210px]">
                          {sqlResult.explain_plan.join("\n")}
                        </pre>
                      </div>
                    )}
                  </div>
                </Panel>

                <Panel
                  title={`Live Query Output (${sqlResult.row_count} rows)`}
                  subtitle="Executed read-only directly against PostgreSQL 16"
                  action={
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-[#0F766E]">
                      <Play className="w-3 h-3" /> Live PostgreSQL Result
                    </span>
                  }
                  noPadding
                >
                  <div className="overflow-x-auto">
                    <table className="cl-table">
                      <thead>
                        <tr>
                          {sqlResult.columns.map((col) => (
                            <th key={col}>{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sqlResult.rows.map((row, rIdx) => (
                          <tr key={rIdx}>
                            {sqlResult.columns.map((col) => {
                              const v = row[col];
                              const isNum = typeof v === "number";
                              return (
                                <td key={col} className={isNum ? "font-mono-num whitespace-nowrap" : "max-w-[240px] truncate"}>
                                  {v === null || v === undefined ? "—" : isNum ? v.toLocaleString("en-US") : String(v)}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              </>
            )}
          </div>
        </div>
      )}

      {/* TAB 3: DATA & EXPERIMENT AUDIT */}
      {activeTab === "audit" && audit && (
        <div className="space-y-5">
          <MethodNote title="Synthetic Data & Reproducibility Disclosure" tone="info">
            {audit.dataset_label}. Generated deterministically with seed{" "}
            <strong className="font-mono-num">{audit.metadata.generation_seed}</strong> for Meridian Air (fictional international carrier).
            All experiment statistics, financial ledgers, and machine learning evaluations are computed directly from these PostgreSQL tables with zero hard-coded outcomes.
          </MethodNote>

          <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
            <Panel
              className="xl:col-span-6"
              title="PostgreSQL Relational Schema Row Counts (15 Core + 3 Analytics Tables)"
              noPadding
            >
              <table className="cl-table">
                <thead>
                  <tr>
                    <th>Table Name</th>
                    <th className="text-right">Row Count</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.table_counts.map((t) => (
                    <tr key={t.table_name}>
                      <td className="font-mono-num font-medium text-[#0F2942]">{t.table_name}</td>
                      <td className="text-right font-mono-num font-semibold">{fmtInt(t.row_count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            <div className="xl:col-span-6 space-y-5">
              <Panel title="Experiment Integrity & Randomization Audit" noPadding>
                <table className="cl-table">
                  <thead>
                    <tr>
                      <th>Study Type</th>
                      <th className="text-right">Campaigns</th>
                      <th className="text-right">SRM Passed</th>
                      <th className="text-right">Avg Max |SMD|</th>
                      <th className="text-right">Sig. Campaigns</th>
                    </tr>
                  </thead>
                  <tbody>
                    {audit.experiment_audit.map((ea) => (
                      <tr key={ea.experiment_type}>
                        <td className="font-semibold text-[#0F2942]">{ea.experiment_type}</td>
                        <td className="text-right font-mono-num">{ea.campaigns}</td>
                        <td className="text-right font-mono-num">{ea.srm_passed}</td>
                        <td className="text-right font-mono-num">{ea.avg_max_smd.toFixed(4)}</td>
                        <td className="text-right font-mono-num">{ea.sig_campaigns}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>

              <Panel title="Applied SQL Schema Migrations" noPadding>
                <table className="cl-table">
                  <thead>
                    <tr>
                      <th>Migration File</th>
                      <th className="text-right">Applied At</th>
                    </tr>
                  </thead>
                  <tbody>
                    {audit.migrations.map((m) => (
                      <tr key={m.version}>
                        <td className="font-mono-num text-[#0F2942]">{m.version}</td>
                        <td className="text-right font-mono-num text-[11.5px] text-[#64748B]">{m.applied_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ReportsAndSQLPage() {
  return (
    <React.Suspense fallback={<LoadingPanel lines={10} />}>
      <ReportsAndSQLContent />
    </React.Suspense>
  );
}
