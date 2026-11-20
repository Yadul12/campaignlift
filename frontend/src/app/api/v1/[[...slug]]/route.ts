import { NextRequest, NextResponse } from "next/server";
import {
  computeCampaignsFromSnapshot,
  computeEconomicsFromSnapshot,
  computeExperimentsListFromSnapshot,
  computeFunnelFromSnapshot,
  computeOverviewFromSnapshot,
  computeSampleSizeTS,
  computeSimulationTS,
  getSnapshot,
  parseFiltersFromSearchParams,
} from "@/lib/snapshotEngine";

async function tryProxyToBackend(req: NextRequest, slug: string[]): Promise<Response | null> {
  const internalUrl = process.env.API_INTERNAL_URL;
  if (!internalUrl) return null;
  try {
    const targetUrl = `${internalUrl.replace(/\/$/, "")}/api/v1/${slug.join("/")}${req.nextUrl.search}`;
    const init: RequestInit = {
      method: req.method,
      headers: { Accept: req.headers.get("accept") || "application/json" },
      cache: "no-store",
    };
    if (req.method === "POST") {
      init.headers = { ...init.headers, "Content-Type": "application/json" };
      init.body = await req.clone().text();
    }
    const resp = await fetch(targetUrl, init);
    const buf = await resp.arrayBuffer();
    const outHeaders = new Headers();
    const ct = resp.headers.get("content-type");
    const cd = resp.headers.get("content-disposition");
    if (ct) outHeaders.set("Content-Type", ct);
    if (cd) outHeaders.set("Content-Disposition", cd);
    return new Response(buf, { status: resp.status, headers: outHeaders });
  } catch {
    return null;
  }
}

function toCsv(rows: Record<string, any>[], cols: string[]): string {
  const esc = (v: any) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return s.includes(",") || s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export async function GET(req: NextRequest, context: { params: Promise<{ slug?: string[] }> }) {
  const { slug = [] } = await context.params;
  const proxied = await tryProxyToBackend(req, slug);
  if (proxied) return proxied;

  const snap = getSnapshot();
  const sp = req.nextUrl.searchParams;
  const f = parseFiltersFromSearchParams(sp);
  const pathKey = slug.join("/");

  if (pathKey === "health") {
    return NextResponse.json({
      status: "ok",
      version: "1.0.0",
      dataset_label: snap.filters.dataset_label,
      campaigns_loaded: snap.campaigns.length,
    });
  }

  if (pathKey === "filters") {
    return NextResponse.json(snap.filters);
  }

  if (pathKey === "overview") {
    return NextResponse.json(computeOverviewFromSnapshot(f));
  }

  if (pathKey === "campaigns") {
    return NextResponse.json(
      computeCampaignsFromSnapshot(
        f,
        sp.get("search"),
        sp.get("sort_by") || "incremental_contribution",
        sp.get("sort_dir") || "desc"
      )
    );
  }

  if (pathKey === "campaigns/export/csv") {
    const data = computeCampaignsFromSnapshot(f, sp.get("search"), "incremental_contribution", "desc");
    const cols = [
      "campaign_code", "campaign_name", "campaign_type", "experiment_type", "start_date", "end_date",
      "channel_name", "target_segment_name", "target_route_code", "discount_pct", "bonus_miles_offer",
      "marketing_spend", "customers_targeted", "customers_reached", "attributed_bookings",
      "gross_booking_revenue", "discount_cost", "loyalty_reward_cost", "contribution_after_promo",
      "incremental_bookings", "incremental_revenue", "incremental_contribution",
      "cost_per_incremental_booking", "conversion_p_value", "recommendation_status",
    ];
    return new Response(toCsv(data.campaigns, cols), {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": 'attachment; filename="campaignlift_campaigns.csv"',
      },
    });
  }

  if (pathKey === "campaigns/export/excel") {
    const firstKey = Object.keys(snap.report_xlsxs_b64 || {})[0];
    if (firstKey) {
      const buf = Buffer.from(snap.report_xlsxs_b64[firstKey], "base64");
      return new Response(buf, {
        headers: {
          "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "Content-Disposition": 'attachment; filename="campaignlift_campaigns.xlsx"',
        },
      });
    }
  }

  if (slug[0] === "campaigns" && slug.length === 2) {
    const det = snap.campaign_details[slug[1]];
    if (!det) return NextResponse.json({ detail: "Not found" }, { status: 404 });
    return NextResponse.json(det);
  }

  if (pathKey === "funnel") {
    return NextResponse.json(computeFunnelFromSnapshot(f));
  }

  if (pathKey === "experiments") {
    return NextResponse.json(computeExperimentsListFromSnapshot(f));
  }

  if (slug[0] === "experiments" && slug.length === 2) {
    const det = snap.experiment_details[slug[1]];
    if (!det) return NextResponse.json({ detail: "Not found" }, { status: 404 });
    return NextResponse.json(det);
  }

  if (pathKey === "economics") {
    return NextResponse.json(computeEconomicsFromSnapshot(f));
  }

  if (pathKey === "customers") {
    const base =
      f.segment_id !== null && snap.customers_by_segment[String(f.segment_id)]
        ? snap.customers_by_segment[String(f.segment_id)]
        : snap.customers_all;
    const arch = sp.get("archetype");
    if (arch && arch.trim()) {
      return NextResponse.json({
        ...base,
        customer_cohort_sample: base.customer_cohort_sample.filter(
          (c: any) => c.response_archetype === arch.trim()
        ),
      });
    }
    return NextResponse.json(base);
  }

  if (pathKey === "simulator/defaults") {
    return NextResponse.json(snap.simulator_defaults);
  }

  if (pathKey === "sql-analytics/queries") {
    return NextResponse.json({ queries: snap.sql_queries });
  }

  if (slug[0] === "sql-analytics" && slug[1] === "queries" && slug[3] === "run") {
    const res = snap.sql_results[slug[2]];
    if (!res) return NextResponse.json({ detail: "Query not found" }, { status: 404 });
    return NextResponse.json(res);
  }

  if (slug[0] === "sql-analytics" && slug[1] === "queries" && slug[3] === "csv") {
    const res = snap.sql_results[slug[2]];
    if (!res) return NextResponse.json({ detail: "Query not found" }, { status: 404 });
    return new Response(toCsv(res.rows, res.columns), {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="campaignlift_sql_${slug[2]}.csv"`,
      },
    });
  }

  if (pathKey === "sql-analytics/audit") {
    return NextResponse.json(snap.audit_summary);
  }

  if (slug[0] === "reports" && slug[1] === "campaign" && slug.length === 3) {
    const rep = snap.executive_reports[slug[2]];
    if (!rep) return NextResponse.json({ detail: "Campaign not found" }, { status: 404 });
    return NextResponse.json(rep);
  }

  if (slug[0] === "reports" && slug[1] === "campaign" && slug[3] === "pdf") {
    const b64 = snap.report_pdfs_b64?.[slug[2]] || Object.values(snap.report_pdfs_b64 || {})[0];
    if (b64) {
      return new Response(Buffer.from(String(b64), "base64"), {
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": `attachment; filename="campaignlift_report_${slug[2]}.pdf"`,
        },
      });
    }
  }

  if (slug[0] === "reports" && slug[1] === "campaign" && slug[3] === "excel") {
    const b64 = snap.report_xlsxs_b64?.[slug[2]] || Object.values(snap.report_xlsxs_b64 || {})[0];
    if (b64) {
      return new Response(Buffer.from(String(b64), "base64"), {
        headers: {
          "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "Content-Disposition": `attachment; filename="campaignlift_report_${slug[2]}.xlsx"`,
        },
      });
    }
  }

  return NextResponse.json({ detail: `Unknown endpoint /api/v1/${pathKey}` }, { status: 404 });
}

export async function POST(req: NextRequest, context: { params: Promise<{ slug?: string[] }> }) {
  const { slug = [] } = await context.params;
  const proxied = await tryProxyToBackend(req, slug);
  if (proxied) return proxied;

  const snap = getSnapshot();
  const pathKey = slug.join("/");
  const body = await req.json();

  if (pathKey === "experiments/sample-size") {
    return NextResponse.json(computeSampleSizeTS(body));
  }

  if (pathKey === "compare") {
    const ids: number[] = Array.from(new Set((body.campaign_ids || []).map(Number)));
    const campaigns = ids
      .map((id) => {
        const c = snap.campaigns.find((x: any) => Number(x.campaign_id) === id);
        if (!c) return null;
        const spend = Number(c.marketing_spend || 0);
        const inc_c = c.incremental_contribution !== null ? Number(c.incremental_contribution) : null;
        return {
          ...c,
          incremental_roi: inc_c !== null && spend > 0 ? Number((inc_c / spend).toFixed(2)) : null,
        };
      })
      .filter(Boolean);

    const segment_matrix: any[] = [];
    for (const c of campaigns) {
      const det = snap.experiment_details[String(c.campaign_id)];
      if (det?.subgroup_hte) {
        for (const h of det.subgroup_hte) {
          segment_matrix.push({
            campaign_id: c.campaign_id,
            campaign_code: c.campaign_code,
            segment_name: h.segment_name,
            n_targeted: h.n_treatment,
            treatment_conv: h.treatment_conv,
            control_conv: h.control_conv,
            lift_pp: h.conv_lift_pp,
          });
        }
      }
    }

    const idSet = new Set(ids);
    const route_overlap = snap.route_cube
      .filter((rc: any) => idSet.has(Number(rc.campaign_id)))
      .map((rc: any) => ({
        market_code: rc.market_code,
        market_region: rc.market_region,
        haul_type: rc.haul_type,
        campaign_id: rc.campaign_id,
        campaign_code: rc.campaign_code,
        bookings: rc.attributed_bookings,
        net_revenue: rc.net_revenue,
      }))
      .sort((a: any, b: any) => b.net_revenue - a.net_revenue)
      .slice(0, 40);

    return NextResponse.json({ campaigns, segment_matrix, route_overlap });
  }

  if (pathKey === "simulator/run") {
    return NextResponse.json(computeSimulationTS(body));
  }

  return NextResponse.json({ detail: `Unknown POST endpoint /api/v1/${pathKey}` }, { status: 404 });
}
