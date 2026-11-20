import fs from "fs";
import path from "path";

let cachedSnapshot: any = null;

export function getSnapshot(): any {
  if (!cachedSnapshot) {
    const filePath = path.join(process.cwd(), "src", "data", "snapshot", "campaignlift_snapshot.json");
    const raw = fs.readFileSync(filePath, "utf-8");
    cachedSnapshot = JSON.parse(raw);
  }
  return cachedSnapshot;
}

export interface ParsedFilters {
  start_date: string | null;
  end_date: string | null;
  campaign_id: number | null;
  channel_id: number | null;
  segment_id: number | null;
  route_market_id: number | null;
  experiment_type: string | null;
  campaign_type: string | null;
}

export function parseFiltersFromSearchParams(sp: URLSearchParams): ParsedFilters {
  const num = (k: string) => {
    const v = sp.get(k);
    if (!v || !v.trim()) return null;
    const n = Number(v);
    return Number.isFinite(n) && n >= 1 ? n : null;
  };
  const str = (k: string) => {
    const v = sp.get(k);
    return v && v.trim() ? v.trim() : null;
  };
  return {
    start_date: str("start_date"),
    end_date: str("end_date"),
    campaign_id: num("campaign_id"),
    channel_id: num("channel_id"),
    segment_id: num("segment_id"),
    route_market_id: num("route_market_id"),
    experiment_type: str("experiment_type"),
    campaign_type: str("campaign_type"),
  };
}

export function filterCampaignRows(f: ParsedFilters): any[] {
  const snap = getSnapshot();
  const routeCampSet =
    f.route_market_id !== null
      ? new Set<number>(
          snap.route_cube
            .filter((rc: any) => rc.route_market_id === f.route_market_id)
            .map((rc: any) => Number(rc.campaign_id))
        )
      : null;

  const segCampSet =
    f.segment_id !== null
      ? new Set<number>(
          snap.funnel_cube
            .filter((fc: any) => fc.segment_id === f.segment_id)
            .map((fc: any) => Number(fc.campaign_id))
        )
      : null;

  return snap.campaigns.filter((c: any) => {
    if (f.start_date && c.end_date < f.start_date) return false;
    if (f.end_date && c.start_date > f.end_date) return false;
    if (f.campaign_id !== null && Number(c.campaign_id) !== f.campaign_id) return false;
    if (f.channel_id !== null && Number(c.channel_id) !== f.channel_id) return false;
    if (f.experiment_type && c.experiment_type !== f.experiment_type) return false;
    if (f.campaign_type && c.campaign_type !== f.campaign_type) return false;
    if (f.segment_id !== null) {
      const matchDirect = Number(c.segment_id) === f.segment_id;
      const matchBroad = (c.segment_id === null || c.segment_id === 0) && segCampSet?.has(Number(c.campaign_id));
      if (!matchDirect && !matchBroad) return false;
    }
    if (f.route_market_id !== null) {
      const matchDirect = Number(c.route_market_id) === f.route_market_id;
      const matchBooked = routeCampSet?.has(Number(c.campaign_id));
      if (!matchDirect && !matchBooked) return false;
    }
    return true;
  });
}

export function computeOverviewFromSnapshot(f: ParsedFilters): any {
  const camps = filterCampaignRows(f);
  const rcts = camps.filter((c) => c.experiment_type === "RCT");
  const obs = camps.filter((c) => c.experiment_type === "Observational");

  const sum = (arr: any[], key: string) => arr.reduce((a, r) => a + Number(r[key] || 0), 0);

  const total_spend = sum(camps, "marketing_spend");
  const rct_spend = sum(rcts, "marketing_spend");
  const targeted = sum(camps, "customers_targeted");
  const reached = sum(camps, "customers_reached");
  const bookers = sum(camps, "attributed_bookers");
  const attr_bookings = sum(camps, "attributed_bookings");
  const gross_rev = sum(camps, "gross_booking_revenue");
  const disc_cost = sum(camps, "discount_cost");
  const miles_cost = sum(camps, "loyalty_reward_cost");
  const contrib_before = sum(camps, "contribution_before_promo");
  const contrib_after = sum(camps, "contribution_after_promo");

  const rct_inc_bookings = sum(rcts, "incremental_bookings");
  const rct_inc_rev = sum(rcts, "incremental_revenue");
  const rct_inc_contrib = sum(rcts, "incremental_contribution");
  const rct_attr_bookings = sum(rcts, "attributed_bookings");
  const rct_attr_contrib = sum(rcts, "contribution_after_promo");

  const kpis = {
    total_campaigns: camps.length,
    rct_campaigns: rcts.length,
    obs_campaigns: obs.length,
    total_spend: Number(total_spend.toFixed(2)),
    rct_spend: Number(rct_spend.toFixed(2)),
    customers_targeted: targeted,
    customers_reached: reached,
    reach_rate: targeted > 0 ? Number((reached / targeted).toFixed(4)) : 0,
    campaign_conversion_rate: reached > 0 ? Number((bookers / reached).toFixed(4)) : 0,
    booking_conversion_rate: targeted > 0 ? Number((bookers / targeted).toFixed(4)) : 0,
    total_attributed_bookings: attr_bookings,
    gross_booking_revenue: Number(gross_rev.toFixed(2)),
    discount_cost: Number(disc_cost.toFixed(2)),
    loyalty_reward_cost: Number(miles_cost.toFixed(2)),
    contribution_margin: Number(contrib_after.toFixed(2)),
    margin_erosion_pct: contrib_before > 0 ? Number(((disc_cost + miles_cost) / contrib_before).toFixed(4)) : 0,
    incremental_bookings: Number(rct_inc_bookings.toFixed(1)),
    incremental_revenue: Number(rct_inc_rev.toFixed(2)),
    incremental_contribution: Number(rct_inc_contrib.toFixed(2)),
    cost_per_incremental_booking: rct_inc_bookings > 1 ? Number((rct_spend / rct_inc_bookings).toFixed(2)) : null,
    incremental_roas: rct_spend > 0 ? Number((rct_inc_rev / rct_spend).toFixed(2)) : null,
    incremental_roi: rct_spend > 0 ? Number((rct_inc_contrib / rct_spend).toFixed(2)) : null,
    rct_attributed_bookings: rct_attr_bookings,
    rct_attributed_contribution: Number(rct_attr_contrib.toFixed(2)),
    attribution_overstatement_ratio:
      rct_inc_bookings > 1 ? Number((rct_attr_bookings / rct_inc_bookings).toFixed(2)) : null,
    rct_significant_count: rcts.filter((c) => c.is_statistically_significant).length,
    rct_value_creating_count: rcts.filter((c) => Number(c.incremental_contribution || 0) > 0).length,
    rct_value_destroying_count: rcts.filter((c) => Number(c.incremental_contribution || 0) < 0).length,
  };

  // Monthly trend
  const monthMap = new Map<string, any>();
  for (const c of camps) {
    const m = String(c.start_date).slice(0, 7);
    const cur = monthMap.get(m) || {
      month: m,
      campaigns: 0,
      rct_campaigns: 0,
      total_spend: 0,
      gross_revenue: 0,
      promo_incentive_cost: 0,
      rct_attributed_contrib: 0,
      rct_incremental_contrib: 0,
      rct_incremental_bookings: 0,
    };
    cur.campaigns += 1;
    cur.total_spend += Number(c.marketing_spend || 0);
    cur.gross_revenue += Number(c.gross_booking_revenue || 0);
    cur.promo_incentive_cost += Number(c.discount_cost || 0) + Number(c.loyalty_reward_cost || 0);
    if (c.experiment_type === "RCT") {
      cur.rct_campaigns += 1;
      cur.rct_attributed_contrib += Number(c.contribution_after_promo || 0);
      cur.rct_incremental_contrib += Number(c.incremental_contribution || 0);
      cur.rct_incremental_bookings += Number(c.incremental_bookings || 0);
    }
    monthMap.set(m, cur);
  }
  const monthly_trend = Array.from(monthMap.values()).sort((a, b) => a.month.localeCompare(b.month));

  // Channel & Segment & Campaign Type rollups
  const chMap = new Map<number, any>();
  const segMap = new Map<string, any>();
  const typeMap = new Map<string, any>();

  for (const c of camps) {
    const chId = Number(c.channel_id);
    const ch = chMap.get(chId) || {
      channel_id: chId,
      channel_name: c.channel_name,
      campaigns: 0,
      rct_campaigns: 0,
      spend: 0,
      rct_spend: 0,
      targeted: 0,
      reached: 0,
      attributed_bookings: 0,
      gross_revenue: 0,
      incentive_cost: 0,
      incremental_bookings: 0,
      incremental_revenue: 0,
      incremental_contribution: 0,
    };
    ch.campaigns += 1;
    ch.spend += Number(c.marketing_spend || 0);
    ch.targeted += Number(c.customers_targeted || 0);
    ch.reached += Number(c.customers_reached || 0);
    ch.attributed_bookings += Number(c.attributed_bookings || 0);
    ch.gross_revenue += Number(c.gross_booking_revenue || 0);
    ch.incentive_cost += Number(c.discount_cost || 0) + Number(c.loyalty_reward_cost || 0);
    if (c.experiment_type === "RCT") {
      ch.rct_campaigns += 1;
      ch.rct_spend += Number(c.marketing_spend || 0);
      ch.incremental_bookings += Number(c.incremental_bookings || 0);
      ch.incremental_revenue += Number(c.incremental_revenue || 0);
      ch.incremental_contribution += Number(c.incremental_contribution || 0);
    }
    chMap.set(chId, ch);

    const sKey = `${c.segment_id || 0}:${c.target_segment_name}`;
    const sg = segMap.get(sKey) || {
      segment_id: Number(c.segment_id || 0),
      segment_name: c.target_segment_name,
      campaigns: 0,
      rct_campaigns: 0,
      spend: 0,
      rct_spend: 0,
      attributed_bookings: 0,
      discount_cost: 0,
      miles_cost: 0,
      incremental_bookings: 0,
      incremental_revenue: 0,
      incremental_contribution: 0,
    };
    sg.campaigns += 1;
    sg.spend += Number(c.marketing_spend || 0);
    sg.attributed_bookings += Number(c.attributed_bookings || 0);
    sg.discount_cost += Number(c.discount_cost || 0);
    sg.miles_cost += Number(c.loyalty_reward_cost || 0);
    if (c.experiment_type === "RCT") {
      sg.rct_campaigns += 1;
      sg.rct_spend += Number(c.marketing_spend || 0);
      sg.incremental_bookings += Number(c.incremental_bookings || 0);
      sg.incremental_revenue += Number(c.incremental_revenue || 0);
      sg.incremental_contribution += Number(c.incremental_contribution || 0);
    }
    segMap.set(sKey, sg);

    const ct = c.campaign_type;
    const tp = typeMap.get(ct) || {
      campaign_type: ct,
      campaigns: 0,
      rct_campaigns: 0,
      rct_spend: 0,
      rct_attributed_bookings: 0,
      rct_incremental_bookings: 0,
      rct_attributed_contrib: 0,
      rct_incremental_contrib: 0,
      disc_sum: 0,
    };
    tp.campaigns += 1;
    tp.disc_sum += Number(c.discount_pct || 0);
    if (c.experiment_type === "RCT") {
      tp.rct_campaigns += 1;
      tp.rct_spend += Number(c.marketing_spend || 0);
      tp.rct_attributed_bookings += Number(c.attributed_bookings || 0);
      tp.rct_incremental_bookings += Number(c.incremental_bookings || 0);
      tp.rct_attributed_contrib += Number(c.contribution_after_promo || 0);
      tp.rct_incremental_contrib += Number(c.incremental_contribution || 0);
    }
    typeMap.set(ct, tp);
  }

  const by_channel = Array.from(chMap.values())
    .map((r) => ({
      ...r,
      reach_rate: r.targeted > 0 ? Number((r.reached / r.targeted).toFixed(4)) : 0,
      cost_per_incremental_booking: r.incremental_bookings > 1 ? Number((r.rct_spend / r.incremental_bookings).toFixed(2)) : null,
    }))
    .sort((a, b) => b.incremental_contribution - a.incremental_contribution);

  const by_segment = Array.from(segMap.values())
    .map((r) => ({
      ...r,
      cost_per_incremental_booking: r.incremental_bookings > 1 ? Number((r.rct_spend / r.incremental_bookings).toFixed(2)) : null,
    }))
    .sort((a, b) => b.incremental_contribution - a.incremental_contribution);

  const by_campaign_type = Array.from(typeMap.values())
    .map((r) => ({
      ...r,
      avg_discount_pct: r.campaigns > 0 ? Number((r.disc_sum / r.campaigns).toFixed(1)) : 0,
    }))
    .sort((a, b) => b.rct_incremental_contrib - a.rct_incremental_contrib);

  const portfolio_scatter = [...camps].sort(
    (a, b) => Number(b.incremental_contribution ?? -1e12) - Number(a.incremental_contribution ?? -1e12)
  );

  return {
    kpis,
    monthly_trend,
    portfolio_scatter,
    by_channel,
    by_segment,
    by_campaign_type,
    decision_queue: {
      scale_winners: portfolio_scatter.filter((c) => c.recommendation_status === "Scale Budget").slice(0, 6),
      margin_dilutive: [...rcts]
        .sort((a, b) => Number(a.incremental_contribution || 0) - Number(b.incremental_contribution || 0))
        .filter((c) => Number(c.incremental_contribution || 0) < 0)
        .slice(0, 6),
    },
  };
}

export function computeCampaignsFromSnapshot(
  f: ParsedFilters,
  search: string | null,
  sortBy: string,
  sortDir: string
): any {
  const snap = getSnapshot();
  let camps = filterCampaignRows(f);
  if (search && search.trim()) {
    const q = search.trim().toLowerCase();
    camps = camps.filter(
      (c) =>
        String(c.campaign_name).toLowerCase().includes(q) ||
        String(c.campaign_code).toLowerCase().includes(q) ||
        String(c.campaign_type).toLowerCase().includes(q) ||
        String(c.channel_name).toLowerCase().includes(q) ||
        String(c.target_segment_name).toLowerCase().includes(q) ||
        String(c.target_route_code).toLowerCase().includes(q)
    );
  }
  const asc = sortDir.toLowerCase() === "asc";
  camps.sort((a, b) => {
    const va = a[sortBy];
    const vb = b[sortBy];
    if (va === null || va === undefined) return 1;
    if (vb === null || vb === undefined) return -1;
    if (typeof va === "string") return asc ? va.localeCompare(vb) : vb.localeCompare(va);
    return asc ? Number(va) - Number(vb) : Number(vb) - Number(va);
  });

  const cIds = new Set<number>(camps.map((c) => Number(c.campaign_id)));
  const rMap = new Map<number, any>();
  for (const rc of snap.route_cube) {
    if (!cIds.has(Number(rc.campaign_id))) continue;
    if (f.route_market_id !== null && Number(rc.route_market_id) !== f.route_market_id) continue;
    const rid = Number(rc.route_market_id);
    const cur = rMap.get(rid) || {
      route_market_id: rid,
      market_code: rc.market_code,
      market_region: rc.market_region,
      haul_type: rc.haul_type,
      load_factor_baseline: Number(rc.load_factor_baseline),
      attributed_bookings: 0,
      gross_revenue: 0,
      discount_cost: 0,
      net_contribution: 0,
    };
    cur.attributed_bookings += Number(rc.attributed_bookings || 0);
    cur.gross_revenue += Number(rc.gross_revenue || 0);
    cur.discount_cost += Number(rc.discount_cost || 0);
    cur.net_contribution += Number(rc.net_contribution || 0);
    rMap.set(rid, cur);
  }

  return {
    count: camps.length,
    campaigns: camps,
    route_breakdown: Array.from(rMap.values())
      .sort((a, b) => b.net_contribution - a.net_contribution)
      .slice(0, 25),
  };
}

export function computeFunnelFromSnapshot(f: ParsedFilters): any {
  const snap = getSnapshot();
  const camps = filterCampaignRows(f);
  if (camps.length === 0) {
    return {
      campaign_count: 0,
      stages: [],
      treatment_vs_control: null,
      bottleneck: null,
      by_channel: [],
      by_segment: [],
      assigned_vs_exposed_gap: { assigned_targeted: 0, reached: 0, unreached: 0, reach_rate: 0 },
    };
  }
  const cIds = new Set<number>(camps.map((c) => Number(c.campaign_id)));
  let total_eligible = camps.reduce((a, c) => a + Number(c.eligible_audience_count || 0), 0);
  if (f.segment_id !== null) {
    total_eligible = Math.round(total_eligible * 0.17);
  }

  const cubes = snap.funnel_cube.filter(
    (fc: any) =>
      cIds.has(Number(fc.campaign_id)) &&
      (f.segment_id === null || Number(fc.segment_id) === f.segment_id)
  );

  const sumK = (arr: any[], k: string) => arr.reduce((a, r) => a + Number(r[k] || 0), 0);
  const total_assigned_all = sumK(cubes, "total_assigned_all");
  const assigned_targeted = sumK(cubes, "assigned_targeted");
  const assigned_control = sumK(cubes, "assigned_control");
  const reached = sumK(cubes, "reached_count");
  const engaged = sumK(cubes, "engaged_count");
  const booked = sumK(cubes, "booked_count");
  const completed = sumK(cubes, "completed_count");
  const eligible_eff = Math.max(total_eligible, total_assigned_all);

  const rawStages = [
    ["eligible", "Eligible Audience", eligible_eff, "Customers meeting CRM, opt-in, segment, and frequency-cap criteria prior to campaign allocation."],
    ["assigned", "Assigned to Campaign (Targeted)", assigned_targeted, `Customers assigned to receive the offer (${total_assigned_all.toLocaleString()} total assigned incl. ${assigned_control.toLocaleString()} RCT holdout controls).`],
    ["reached", "Reached / Exposed", reached, "Targeted customers verified as delivered/impressed; excludes bounces, suppressions, and all control subjects."],
    ["engaged", "Engaged with Offer", engaged, "Reached customers who clicked, viewed offer terms, enrolled in miles, or applied a promo code."],
    ["booked", "Booked (Non-Cancelled)", booked, "Engaged customers completing a confirmed non-cancelled airline reservation attributed to the offer."],
    ["completed", "Completed Travel", completed, "Booked customers whose itinerary has flown and completed travel."],
  ] as const;

  let bottleneck: any = null;
  const stages = rawStages.map(([key, label, count, desc], idx) => {
    const prev = idx > 0 ? rawStages[idx - 1][2] : count;
    const step_conv = idx > 0 && prev > 0 ? Number((count / prev).toFixed(4)) : 1;
    const drop_abs = idx > 0 ? prev - count : 0;
    const drop_pct = idx > 0 ? Number((1 - step_conv).toFixed(4)) : 0;
    const cum = idx === 0 ? 1 : assigned_targeted > 0 ? Number((count / assigned_targeted).toFixed(4)) : 0;
    if (idx >= 2 && (!bottleneck || drop_pct > bottleneck.dropoff_rate)) {
      bottleneck = {
        from_stage: rawStages[idx - 1][1],
        to_stage: label,
        dropoff_count: drop_abs,
        dropoff_rate: drop_pct,
        step_conversion_rate: step_conv,
      };
    }
    return {
      stage_key: key,
      stage_label: label,
      count,
      step_conversion_rate: step_conv,
      dropoff_count: drop_abs,
      dropoff_rate: drop_pct,
      cumulative_from_assigned: cum,
      description: desc,
    };
  });

  const rctCubes = cubes.filter((fc: any) => fc.experiment_type === "RCT");
  const rctCampCount = camps.filter((c) => c.experiment_type === "RCT").length;
  const t_a = sumK(rctCubes, "assigned_targeted");
  const c_a = sumK(rctCubes, "assigned_control");
  const t_r = sumK(rctCubes, "reached_count");
  const t_b = sumK(rctCubes, "rct_t_booked_itt");
  const t_c = sumK(rctCubes, "rct_t_completed_itt");
  const c_b = sumK(rctCubes, "rct_c_booked_itt");
  const c_c = sumK(rctCubes, "rct_c_completed_itt");

  const treatment_vs_control =
    t_a > 0 && c_a > 0
      ? {
          rct_campaign_count: rctCampCount,
          treatment: {
            assigned: t_a,
            reached: t_r,
            reach_rate: Number((t_r / t_a).toFixed(4)),
            booked_itt: t_b,
            booking_rate_itt: Number((t_b / t_a).toFixed(4)),
            completed_itt: t_c,
            completion_rate_itt: Number((t_c / t_a).toFixed(4)),
          },
          control: {
            assigned: c_a,
            reached: 0,
            reach_rate: 0,
            booked_itt: c_b,
            booking_rate_itt: Number((c_b / c_a).toFixed(4)),
            completed_itt: c_c,
            completion_rate_itt: Number((c_c / c_a).toFixed(4)),
          },
        }
      : null;

  const groupSlice = (keyField: "channel_name" | "segment_name") => {
    const m = new Map<string, any>();
    for (const fc of cubes) {
      const k = fc[keyField];
      const cur = m.get(k) || { [keyField]: k, assigned: 0, reached: 0, engaged: 0, booked: 0, completed: 0 };
      cur.assigned += Number(fc.assigned_targeted || 0);
      cur.reached += Number(fc.reached_count || 0);
      cur.engaged += Number(fc.engaged_count || 0);
      cur.booked += Number(fc.booked_count || 0);
      cur.completed += Number(fc.completed_count || 0);
      m.set(k, cur);
    }
    return Array.from(m.values())
      .map((r) => ({
        ...r,
        reach_rate: r.assigned > 0 ? Number((r.reached / r.assigned).toFixed(4)) : 0,
        engage_rate: r.reached > 0 ? Number((r.engaged / r.reached).toFixed(4)) : 0,
        book_of_engaged: r.engaged > 0 ? Number((r.booked / r.engaged).toFixed(4)) : 0,
        end_to_end_rate: r.assigned > 0 ? Number((r.completed / r.assigned).toFixed(4)) : 0,
      }))
      .sort((a, b) => b.assigned - a.assigned);
  };

  return {
    campaign_count: camps.length,
    stages,
    assigned_vs_exposed_gap: {
      assigned_targeted,
      reached,
      unreached: Math.max(0, assigned_targeted - reached),
      reach_rate: assigned_targeted > 0 ? Number((reached / assigned_targeted).toFixed(4)) : 0,
    },
    bottleneck,
    treatment_vs_control,
    by_channel: groupSlice("channel_name"),
    by_segment: groupSlice("segment_name"),
  };
}

export function computeExperimentsListFromSnapshot(f: ParsedFilters): any {
  const snap = getSnapshot();
  const camps = filterCampaignRows(f);
  const experiments = camps
    .map((c) => {
      const det = snap.experiment_details[String(c.campaign_id)];
      return {
        campaign_id: c.campaign_id,
        campaign_code: c.campaign_code,
        campaign_name: c.campaign_name,
        campaign_type: c.campaign_type,
        experiment_type: c.experiment_type,
        channel_name: c.channel_name,
        target_segment_name: c.target_segment_name,
        start_date: c.start_date,
        end_date: c.end_date,
        discount_pct: c.discount_pct,
        bonus_miles_offer: c.bonus_miles_offer,
        n_treatment: det?.diagnostics?.n_treatment ?? c.customers_targeted,
        n_control: det?.diagnostics?.n_control ?? c.control_customers,
        exposure_compliance_rate: det?.diagnostics?.exposure_compliance_rate ?? c.reach_rate,
        srm_passed: c.srm_passed,
        srm_p_value: det?.diagnostics?.srm_p_value ?? null,
        max_covariate_smd: det?.diagnostics?.max_covariate_smd ?? null,
        conversion_control: c.conversion_control,
        conversion_treatment: c.conversion_treatment,
        conversion_lift_abs: c.conversion_lift_abs,
        conversion_p_value: c.conversion_p_value,
        contrib_per_cust_control: det?.metrics_table?.[4]?.control_value ?? 0,
        contrib_per_cust_treatment: det?.metrics_table?.[4]?.treatment_value ?? 0,
        contrib_per_cust_p_value: c.contrib_per_cust_p_value,
        incremental_bookings: c.incremental_bookings,
        incremental_contribution: c.incremental_contribution,
        marketing_spend: c.marketing_spend,
        is_statistically_significant: c.is_statistically_significant,
        recommendation_status: c.recommendation_status,
      };
    })
    .sort((a, b) => {
      if (a.experiment_type !== b.experiment_type) return a.experiment_type === "RCT" ? -1 : 1;
      return String(b.start_date).localeCompare(String(a.start_date));
    });

  const rct_count = experiments.filter((e) => e.experiment_type === "RCT").length;
  return {
    summary: {
      total: experiments.length,
      rct_count,
      observational_count: experiments.length - rct_count,
      srm_passed_count: experiments.filter((e) => e.experiment_type === "RCT" && e.srm_passed).length,
      statistically_significant_count: experiments.filter((e) => e.is_statistically_significant).length,
    },
    experiments,
  };
}

export function computeEconomicsFromSnapshot(f: ParsedFilters): any {
  const snap = getSnapshot();
  const camps = filterCampaignRows(f);
  let tot_gross = 0,
    tot_disc = 0,
    tot_var = 0,
    tot_cb = 0,
    tot_miles = 0,
    tot_media = 0,
    tot_ca = 0,
    tot_inc_b = 0,
    tot_inc_r = 0,
    tot_inc_c = 0,
    tot_dw = 0,
    tot_rct_inc_cost = 0,
    rct_cnt = 0;

  const typeMap = new Map<string, any>();

  const campaign_economics = camps
    .map((r) => {
      const gross = Number(r.gross_booking_revenue || 0);
      const disc = Number(r.discount_cost || 0);
      const miles = Number(r.loyalty_reward_cost || 0);
      const var_c = Number(r.variable_cost || 0);
      const cb = Number(r.contribution_before_promo || 0);
      const media = Number(r.marketing_spend || 0);
      const ca = Number(r.contribution_after_promo || 0);
      const attr_b = Number(r.attributed_bookings || 0);
      const inc_b = r.incremental_bookings !== null ? Number(r.incremental_bookings) : null;
      const inc_r = r.incremental_revenue !== null ? Number(r.incremental_revenue) : null;
      const inc_c = r.incremental_contribution !== null ? Number(r.incremental_contribution) : null;

      tot_gross += gross;
      tot_disc += disc;
      tot_var += var_c;
      tot_cb += cb;
      tot_miles += miles;
      tot_media += media;
      tot_ca += ca;

      let deadweight: number | null = null;
      let inc_share: number | null = null;
      if (r.experiment_type === "RCT") {
        rct_cnt += 1;
        tot_inc_b += inc_b || 0;
        tot_inc_r += inc_r || 0;
        tot_inc_c += inc_c || 0;
        if (attr_b > 0) {
          const pcpb = (disc + miles) / attr_b;
          const inc_pos = Math.max(0, inc_b || 0);
          const base_red = Math.max(0, attr_b - inc_pos);
          deadweight = Number((base_red * pcpb).toFixed(2));
          inc_share = Number(Math.min(1, inc_pos / attr_b).toFixed(4));
          tot_dw += deadweight;
          tot_rct_inc_cost += disc + miles;
        }
      }

      const b = typeMap.get(r.campaign_type) || {
        campaign_type: r.campaign_type,
        campaigns: 0,
        rct_campaigns: 0,
        gross_revenue: 0,
        discount_cost: 0,
        bonus_miles_cost: 0,
        other_promo_cost: 0,
        contribution_before_promo: 0,
        contribution_after_promo: 0,
        incremental_contribution: 0,
        deadweight_subsidy: 0,
      };
      b.campaigns += 1;
      b.gross_revenue += gross;
      b.discount_cost += disc;
      b.bonus_miles_cost += miles;
      b.other_promo_cost += media;
      b.contribution_before_promo += cb;
      b.contribution_after_promo += ca;
      if (r.experiment_type === "RCT") {
        b.rct_campaigns += 1;
        b.incremental_contribution += inc_c || 0;
        b.deadweight_subsidy += deadweight || 0;
      }
      typeMap.set(r.campaign_type, b);

      return {
        campaign_id: r.campaign_id,
        campaign_code: r.campaign_code,
        campaign_name: r.campaign_name,
        campaign_type: r.campaign_type,
        experiment_type: r.experiment_type,
        channel_name: r.channel_name,
        target_segment_name: r.target_segment_name,
        discount_pct: r.discount_pct,
        bonus_miles_offer: r.bonus_miles_offer,
        attributed_bookings: attr_b,
        gross_revenue: gross,
        discount_cost: disc,
        variable_cost: var_c,
        contribution_before_promo: cb,
        bonus_miles_cost: miles,
        other_promo_cost: media,
        contribution_after_promo: ca,
        incremental_bookings: inc_b,
        incremental_revenue: inc_r,
        incremental_contribution: inc_c,
        deadweight_subsidy: deadweight,
        incremental_share_of_attributed: inc_share,
        margin_erosion_pct: cb > 0 ? Number(((disc + miles) / cb).toFixed(4)) : 0,
        recommendation_status: r.recommendation_status,
      };
    })
    .sort((a, b) => Number(b.incremental_contribution ?? -1e12) - Number(a.incremental_contribution ?? -1e12));

  const by_campaign_type = Array.from(typeMap.values())
    .map((b) => ({
      ...b,
      margin_erosion_pct:
        b.contribution_before_promo > 0
          ? Number(((b.discount_cost + b.bonus_miles_cost) / b.contribution_before_promo).toFixed(4))
          : 0,
    }))
    .sort((a, b) => b.incremental_contribution - a.incremental_contribution);

  return {
    summary: {
      campaign_count: camps.length,
      rct_campaign_count: rct_cnt,
      gross_revenue: Number(tot_gross.toFixed(2)),
      discount_cost: Number(tot_disc.toFixed(2)),
      variable_cost: Number(tot_var.toFixed(2)),
      contribution_before_promo: Number(tot_cb.toFixed(2)),
      bonus_miles_cost: Number(tot_miles.toFixed(2)),
      other_promo_cost: Number(tot_media.toFixed(2)),
      contribution_after_promo: Number(tot_ca.toFixed(2)),
      margin_erosion_pct: tot_cb > 0 ? Number(((tot_disc + tot_miles) / tot_cb).toFixed(4)) : 0,
      rct_incremental_bookings: Number(tot_inc_b.toFixed(1)),
      rct_incremental_revenue: Number(tot_inc_r.toFixed(2)),
      rct_incremental_contribution: Number(tot_inc_c.toFixed(2)),
      rct_deadweight_subsidy: Number(tot_dw.toFixed(2)),
      rct_subsidy_waste_share: tot_rct_inc_cost > 0 ? Number((tot_dw / tot_rct_inc_cost).toFixed(4)) : 0,
    },
    waterfall: [
      { label: "Gross Booking Revenue", value: Number(tot_gross.toFixed(2)), measure: "absolute" },
      { label: "Fare Discounts", value: Number((-tot_disc).toFixed(2)), measure: "relative" },
      { label: "Estimated Variable Costs", value: Number((-tot_var).toFixed(2)), measure: "relative" },
      { label: "Bonus Loyalty Miles Cost", value: Number((-tot_miles).toFixed(2)), measure: "relative" },
      { label: "Media & Other Promo Cost", value: Number((-tot_media).toFixed(2)), measure: "relative" },
      { label: "Contribution After Promo", value: Number(tot_ca.toFixed(2)), measure: "total" },
    ],
    by_campaign_type,
    campaigns: campaign_economics,
    formulas: snap.economics_formulas,
  };
}

export function computeSampleSizeTS(body: any): any {
  const p0 = Math.max(0.001, Math.min(0.95, Number(body.baseline_rate || 0.075)));
  const mde = Math.max(0.0005, Math.min(0.5, Math.abs(Number(body.mde_abs || 0.015))));
  const p1 = Math.min(0.99, p0 + mde);
  const alpha = Number(body.alpha || 0.05);
  const power = Number(body.power || 0.8);
  const split = Math.max(0.1, Math.min(0.9, Number(body.treatment_split || 0.5)));
  const ratio = split / (1 - split);

  const h = Math.abs(2 * Math.asin(Math.sqrt(p1)) - 2 * Math.asin(Math.sqrt(p0)));
  // Normal quantile approximation
  const zAlpha = alpha <= 0.01 ? 2.5758 : alpha <= 0.05 ? 1.96 : 1.6449;
  const zBeta = power >= 0.9 ? 1.2816 : power >= 0.85 ? 1.0364 : power >= 0.8 ? 0.8416 : 0.6745;

  const solveNControl = (effH: number) =>
    Math.ceil((((zAlpha + zBeta) ** 2) * (1 + 1 / ratio)) / Math.max(1e-9, effH ** 2));

  const erf = (x: number) => {
    const a1 = 0.254829592,
      a2 = -0.284496736,
      a3 = 1.421413741,
      a4 = -1.453152027,
      a5 = 1.061405429,
      p = 0.3275911;
    const sign = x < 0 ? -1 : 1;
    const ax = Math.abs(x);
    const t = 1 / (1 + p * ax);
    const y = 1 - ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax);
    return sign * y;
  };
  const normCdf = (z: number) => 0.5 * (1 + erf(z / Math.SQRT2));
  const calcPower = (effH: number, nc: number, nt: number) => {
    const se = Math.sqrt(1 / nc + 1 / nt);
    const noncent = effH / se;
    return Math.max(0, Math.min(1, 1 - normCdf(zAlpha - noncent) + normCdf(-zAlpha - noncent)));
  };

  const n_control = solveNControl(h);
  const n_treatment = Math.ceil(n_control * ratio);
  const multipliers = [0.2, 0.35, 0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 1.8, 2.2];
  const power_curve = multipliers.map((mult) => {
    const nc = Math.max(25, Math.round(n_control * mult));
    const nt = Math.max(25, Math.round(n_treatment * mult));
    return {
      total_sample: nc + nt,
      control_sample: nc,
      treatment_sample: nt,
      power: Number(calcPower(h, nc, nt).toFixed(4)),
    };
  });

  const mde_sensitivity = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0].map((factor) => {
    const m_abs = Number((mde * factor).toFixed(4));
    const p_alt = Math.min(0.99, p0 + m_abs);
    const h_alt = Math.abs(2 * Math.asin(Math.sqrt(p_alt)) - 2 * Math.asin(Math.sqrt(p0)));
    const nc_alt = solveNControl(h_alt);
    const nt_alt = Math.ceil(nc_alt * ratio);
    return {
      mde_abs_pp: Number((m_abs * 100).toFixed(2)),
      mde_rel_pct: Number(((m_abs / p0) * 100).toFixed(1)),
      n_control: nc_alt,
      n_treatment: nt_alt,
      n_total: nc_alt + nt_alt,
    };
  });

  return {
    baseline_rate: p0,
    target_treatment_rate: p1,
    mde_abs: mde,
    mde_rel: mde / p0,
    alpha,
    target_power: power,
    treatment_split: split,
    cohen_h: Number(h.toFixed(4)),
    required_n_control: n_control,
    required_n_treatment: n_treatment,
    required_n_total: n_control + n_treatment,
    power_curve,
    mde_sensitivity,
  };
}

export function computeSimulationTS(req: any): any {
  const snap = getSnapshot();
  const defaults = snap.simulator_defaults;
  const chMap = new Map<number, any>(defaults.channels.map((c: any) => [Number(c.channel_id), c]));
  const segMap = new Map<number, any>(defaults.segments.map((s: any) => [Number(s.segment_id), s]));
  const routeMap = new Map<number, any>(defaults.routes.map((r: any) => [Number(r.route_market_id), r]));

  const baseRow = req.base_campaign_id
    ? snap.campaigns.find((c: any) => Number(c.campaign_id) === Number(req.base_campaign_id))
    : null;

  const rcts = snap.campaigns.filter((c: any) => c.experiment_type === "RCT");
  const avg = (k: string) => rcts.reduce((a: number, r: any) => a + Number(r[k] || 0), 0) / Math.max(1, rcts.length);

  const base_label = baseRow
    ? `${baseRow.campaign_code} — ${baseRow.campaign_name}`
    : "Average RCT Campaign Benchmark (All 72 Randomized Experiments)";
  const base_spend = baseRow ? Number(baseRow.marketing_spend) : avg("marketing_spend");
  const base_targeted = baseRow ? Number(baseRow.customers_targeted) : Math.round(avg("customers_targeted"));
  const base_reach_rate = baseRow ? Number(baseRow.reach_rate || 0.81) : 0.81;
  const base_disc = baseRow ? Number(baseRow.discount_pct) : Number(avg("discount_pct").toFixed(1));
  const base_miles = baseRow ? Number(baseRow.bonus_miles_offer) : Math.round(avg("bonus_miles_offer"));
  const attr_b = Math.max(1, baseRow ? Number(baseRow.attributed_bookings) : Math.round(avg("attributed_bookings")));
  const base_gross_per_book = (baseRow ? Number(baseRow.gross_booking_revenue) : avg("gross_booking_revenue")) / attr_b;
  const base_var_per_book = (baseRow ? Number(baseRow.variable_cost) : avg("variable_cost")) / attr_b;
  const base_inc_bookings = baseRow ? Number(baseRow.incremental_bookings || 48) : avg("incremental_bookings");
  const base_inc_rev = baseRow ? Number(baseRow.incremental_revenue || 28000) : avg("incremental_revenue");
  const base_inc_contrib = baseRow ? Number(baseRow.incremental_contribution || 6500) : avg("incremental_contribution");
  const default_ch_id = baseRow ? Number(baseRow.channel_id) : 1;

  let sim_base_conv = 0.072,
    emp_disc_lift_15 = 0.025,
    emp_miles_lift_6k = 0.023,
    sure_share = 0.188,
    seg_label = "All Customer Segments (Network Portfolio)";

  if (req.target_segment_id && segMap.has(Number(req.target_segment_id))) {
    const s = segMap.get(Number(req.target_segment_id));
    sim_base_conv = Number(s.avg_baseline_prob);
    emp_disc_lift_15 = Math.max(0.002, Number(s.avg_discount_uplift));
    emp_miles_lift_6k = Math.max(0.002, Number(s.avg_miles_uplift));
    sure_share = Number(s.sure_things_share);
    seg_label = s.segment_name;
  }
  if (req.exclude_sure_things) {
    sim_base_conv *= Math.max(0.45, 1 - sure_share * 0.85);
    emp_disc_lift_15 *= 1.14;
    emp_miles_lift_6k *= 1.14;
  }

  let sim_gross_per_book = base_gross_per_book,
    sim_var_per_book = base_var_per_book,
    route_headroom_mult = 1.0,
    route_label = "Network-Wide Route Mix";

  if (req.route_market_id && routeMap.has(Number(req.route_market_id))) {
    const r = routeMap.get(Number(req.route_market_id));
    sim_gross_per_book = Number(r.avg_base_fare) * 1.42;
    sim_var_per_book = Number(r.variable_cost_per_pax) * 1.38 + sim_gross_per_book * 0.028;
    const lf = Number(r.load_factor_baseline);
    route_headroom_mult = Math.max(0.72, Math.min(1.28, 1 + (0.79 - lf) * 2.1));
    route_label = `${r.market_code} (${r.market_region}, Baseline LF ${(lf * 100).toFixed(1)}%)`;
  }

  const mult = Number(req.budget_multiplier || 1.0);
  const discPct = Number(req.discount_pct ?? 12);
  const bonusMiles = Number(req.bonus_miles_offer ?? 2500);
  const sim_spend = Number((base_spend * mult).toFixed(2));

  const allocs: [number, number][] = [];
  if (Array.isArray(req.channel_allocations)) {
    const rawSum = req.channel_allocations.reduce(
      (a: number, x: any) => a + (chMap.has(Number(x.channel_id)) && x.share_pct > 0 ? Number(x.share_pct) : 0),
      0
    );
    if (rawSum > 0) {
      for (const x of req.channel_allocations) {
        if (chMap.has(Number(x.channel_id)) && x.share_pct > 0) {
          allocs.push([Number(x.channel_id), Number(x.share_pct) / rawSum]);
        }
      }
    }
  }
  if (allocs.length === 0) allocs.push([default_ch_id, 1.0]);

  const meanLift =
    defaults.channels.reduce((a: number, c: any) => a + Math.max(0.005, Number(c.avg_conv_lift || 0.015)), 0) /
    defaults.channels.length;

  let weighted_unit_cost = 0,
    weighted_reach = 0,
    weighted_ch_lift_idx = 0;
  const channel_breakdown = allocs.map(([cid, sh]) => {
    const ch = chMap.get(cid);
    const u_cost = Math.max(0.03, Number(ch.unit_reach_cost));
    const deliv = Number(ch.avg_deliverability_rate);
    const lift_idx = Math.max(0.55, Math.min(1.45, Math.max(0.005, Number(ch.avg_conv_lift || meanLift)) / meanLift));
    weighted_unit_cost += sh * u_cost;
    weighted_reach += sh * deliv;
    weighted_ch_lift_idx += sh * lift_idx;
    return {
      channel_id: cid,
      channel_name: ch.channel_name,
      share_pct: Number((sh * 100).toFixed(1)),
      allocated_spend: Number((sim_spend * sh).toFixed(2)),
      empirical_lift_index: Number(lift_idx.toFixed(2)),
      deliverability_rate: Number(deliv.toFixed(3)),
    };
  });

  const base_ch_unit = Math.max(0.03, Number(chMap.get(default_ch_id)?.unit_reach_cost || 0.05));
  const cost_eff = Math.pow(base_ch_unit / Math.max(0.03, weighted_unit_cost), 0.28);
  const sim_targeted = Math.max(250, Math.round(base_targeted * Math.pow(mult, 0.72) * cost_eff));
  const sim_reached = Math.round(sim_targeted * weighted_reach);

  const disc_lift = discPct > 0 ? emp_disc_lift_15 * Math.sqrt(discPct / 15) : 0;
  const miles_lift = bonusMiles > 0 ? emp_miles_lift_6k * Math.sqrt(bonusMiles / 6000) : 0;
  const overlap = discPct > 0 && bonusMiles > 0 ? 0.86 : 1.0;
  const fatigue = Math.pow(mult, -0.14);

  const sim_itt_lift = Math.max(
    0,
    (disc_lift + miles_lift) *
      overlap *
      weighted_ch_lift_idx *
      route_headroom_mult *
      fatigue *
      (weighted_reach / Math.max(0.5, base_reach_rate))
  );

  const bpc = 1.08;
  const sim_inc_bookings = sim_targeted * sim_itt_lift * bpc;
  const sim_base_bookings = sim_targeted * sim_base_conv * bpc;

  const fare_share = 0.87;
  const disc_per_book = sim_gross_per_book * fare_share * (discPct / 100);
  const miles_per_book = bonusMiles * 1.35 * 0.0094;
  const rr_inc = discPct > 0 || bonusMiles > 0 ? 0.88 : 0;
  const rr_base = discPct > 0 || bonusMiles > 0 ? 0.58 * weighted_reach : 0;

  const inc_gross_rev = sim_inc_bookings * sim_gross_per_book;
  const base_disc_cannib = sim_base_bookings * rr_base * disc_per_book;
  const total_disc_cost = sim_inc_bookings * rr_inc * disc_per_book + base_disc_cannib;
  const base_miles_cannib = sim_base_bookings * rr_base * miles_per_book;
  const total_miles_cost = sim_inc_bookings * rr_inc * miles_per_book + base_miles_cannib;

  const sim_inc_net_revenue = inc_gross_rev - total_disc_cost;
  const inc_var_cost = sim_inc_bookings * sim_var_per_book;
  const sim_inc_contribution = inc_gross_rev - inc_var_cost - total_disc_cost - total_miles_cost - sim_spend;
  const sim_deadweight = base_disc_cannib + base_miles_cannib;

  const band = (m: number) => {
    const ib = sim_inc_bookings * m;
    const igr = ib * sim_gross_per_book;
    const ivc = ib * sim_var_per_book;
    const idisc = ib * rr_inc * disc_per_book + base_disc_cannib;
    const imiles = ib * rr_inc * miles_per_book + base_miles_cannib;
    return {
      incremental_bookings: Number(ib.toFixed(1)),
      incremental_revenue: Number((igr - idisc).toFixed(2)),
      incremental_contribution: Number((igr - ivc - idisc - imiles - sim_spend).toFixed(2)),
    };
  };

  const discount_frontier = [0, 5, 10, 15, 20, 25, 30].map((d_pct) => {
    const dl = d_pct > 0 ? emp_disc_lift_15 * Math.sqrt(d_pct / 15) : 0;
    const ov = d_pct > 0 && bonusMiles > 0 ? 0.86 : 1.0;
    const l_d = Math.max(
      0,
      (dl + miles_lift) * ov * weighted_ch_lift_idx * route_headroom_mult * fatigue * (weighted_reach / Math.max(0.5, base_reach_rate))
    );
    const ib_d = sim_targeted * l_d * bpc;
    const dpb = sim_gross_per_book * fare_share * (d_pct / 100);
    const rri = d_pct > 0 || bonusMiles > 0 ? 0.88 : 0;
    const rrb = d_pct > 0 || bonusMiles > 0 ? 0.58 * weighted_reach : 0;
    const td = ib_d * rri * dpb + sim_base_bookings * rrb * dpb;
    const tm = ib_d * rri * miles_per_book + sim_base_bookings * rrb * miles_per_book;
    const ic_d = ib_d * (sim_gross_per_book - sim_var_per_book) - td - tm - sim_spend;
    return {
      discount_pct: d_pct,
      projected_incremental_bookings: Number(ib_d.toFixed(1)),
      projected_incremental_contribution: Number(ic_d.toFixed(2)),
      projected_deadweight_subsidy: Number((sim_base_bookings * rrb * (dpb + miles_per_book)).toFixed(2)),
    };
  });

  return {
    disclaimer:
      "MODELLED SCENARIO ESTIMATE — NOT A GUARANTEED OUTCOME. Projections extrapolate empirical RCT elasticities and T-Learner uplift estimates under concave diminishing-returns assumptions. Competitive fare matching, seat inventory constraints, and macro demand shifts are not modeled; validate major shifts via controlled RCT holdouts.",
    scope: {
      baseline_reference: base_label,
      target_segment: seg_label,
      exclude_sure_things: Boolean(req.exclude_sure_things),
      route_market: route_label,
    },
    baseline: {
      spend: Number(base_spend.toFixed(2)),
      targeted_customers: base_targeted,
      discount_pct: base_disc,
      bonus_miles_offer: base_miles,
      incremental_bookings: Number(base_inc_bookings.toFixed(1)),
      incremental_revenue: Number(base_inc_rev.toFixed(2)),
      incremental_contribution: Number(base_inc_contrib.toFixed(2)),
      cost_per_incremental_booking: base_inc_bookings > 1 ? Number((base_spend / base_inc_bookings).toFixed(2)) : null,
    },
    simulated: {
      spend: sim_spend,
      targeted_customers: sim_targeted,
      reached_customers: sim_reached,
      discount_pct: discPct,
      bonus_miles_offer: bonusMiles,
      projected_itt_lift_pp: Number((sim_itt_lift * 100).toFixed(2)),
      incremental_bookings: Number(sim_inc_bookings.toFixed(1)),
      incremental_revenue: Number(sim_inc_net_revenue.toFixed(2)),
      incremental_contribution: Number(sim_inc_contribution.toFixed(2)),
      total_discount_cost: Number(total_disc_cost.toFixed(2)),
      total_miles_cost: Number(total_miles_cost.toFixed(2)),
      deadweight_subsidy: Number(sim_deadweight.toFixed(2)),
      cost_per_incremental_booking: sim_inc_bookings > 1 ? Number((sim_spend / sim_inc_bookings).toFixed(2)) : null,
      incremental_roi: sim_spend > 0 ? Number((sim_inc_contribution / sim_spend).toFixed(2)) : null,
    },
    deltas: {
      spend_delta: Number((sim_spend - base_spend).toFixed(2)),
      incremental_bookings_delta: Number((sim_inc_bookings - base_inc_bookings).toFixed(1)),
      incremental_revenue_delta: Number((sim_inc_net_revenue - base_inc_rev).toFixed(2)),
      incremental_contribution_delta: Number((sim_inc_contribution - base_inc_contrib).toFixed(2)),
    },
    uncertainty_bands: {
      conservative: band(0.82),
      base: band(1.0),
      upside: band(1.18),
    },
    channel_allocation_plan: channel_breakdown,
    discount_frontier,
    assumptions: [
      "Audience scale follows concave diminishing returns (budget^0.72) with marginal fatigue exponent (-0.14).",
      `Discount and miles lifts use square-root diminishing elasticity calibrated to empirical T-Learner RCT scores (${(emp_disc_lift_15 * 100).toFixed(2)}pp @ 15% off; ${(emp_miles_lift_6k * 100).toFixed(2)}pp @ 6k miles).`,
      `Baseline organic booking propensity (${(sim_base_conv * 100).toFixed(2)}%) absorbs promo subsidies at a ${(rr_base * 100).toFixed(1)}% reached-booker redemption rate (explicit cannibalization modeling).`,
      `Bonus loyalty miles liability valued at $0.0094/mile across avg 1.35 passengers per booking; route average gross ticket = $${sim_gross_per_book.toFixed(0)}, variable cost = $${sim_var_per_book.toFixed(0)}.`,
      `Route load-factor headroom multiplier = ${route_headroom_mult.toFixed(2)}x; uncertainty band spans +/-18% around projected lift.`,
    ],
  };
}
