-- ============================================================================
-- CampaignLift SQL Analytics Library
-- Production analytical queries powering airline commercial decision-making.
-- Techniques: CTEs, Multi-Table Joins, Window Functions, Conditional
-- Aggregation, Cohort Analysis, Campaign Rankings, Time Comparisons,
-- Customer Aggregation, and Intention-to-Treat Experiment Comparisons.
-- ============================================================================

-- @id: rct_itt_group_comparison
-- @title: RCT Intention-to-Treat (ITT) Treatment vs. Control Performance
-- @category: Experimentation
-- @techniques: CTEs, Multi-Table Joins, Conditional Aggregation, ITT Window Join
-- @indexes: idx_assignments_campaign_group_cust, idx_bookings_customer_date_status, idx_ticket_revenue_booking, idx_loyalty_rewards_booking
-- @decision: Identifies which randomized promotional campaigns generate true causal incremental bookings and net contribution rather than subsidizing organic demand.
WITH rct_assignments AS (
    SELECT
        ca.campaign_id,
        c.campaign_code,
        c.campaign_name,
        c.campaign_type,
        c.start_date,
        (c.end_date + (c.booking_window_days || ' days')::INTERVAL)::DATE AS window_end_date,
        ca.customer_id,
        ca.assignment_group
    FROM campaign_assignments ca
    JOIN campaigns c ON c.campaign_id = ca.campaign_id
    WHERE c.experiment_type = 'RCT'
      AND ca.assignment_group IN ('treatment', 'control')
),
customer_window_outcomes AS (
    SELECT
        ra.campaign_id,
        ra.campaign_code,
        ra.campaign_name,
        ra.campaign_type,
        ra.customer_id,
        ra.assignment_group,
        COUNT(DISTINCT b.booking_id) AS bookings_cnt,
        CASE WHEN COUNT(DISTINCT b.booking_id) > 0 THEN 1 ELSE 0 END AS converted,
        COALESCE(SUM(tr.net_ticket_revenue), 0) AS net_revenue,
        COALESCE(SUM(tr.gross_total_revenue - tr.discount_amount - tr.estimated_variable_cost), 0)
            - COALESCE(SUM(CASE WHEN lr.campaign_id = ra.campaign_id THEN lr.reward_liability_cost ELSE 0 END), 0) AS net_contribution
    FROM rct_assignments ra
    LEFT JOIN bookings b
        ON b.customer_id = ra.customer_id
        AND b.booking_date BETWEEN ra.start_date AND ra.window_end_date
        AND b.booking_status <> 'cancelled'
    LEFT JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
    LEFT JOIN (
        SELECT booking_id, campaign_id, SUM(reward_liability_cost) AS reward_liability_cost
        FROM loyalty_rewards
        WHERE campaign_id IS NOT NULL
        GROUP BY booking_id, campaign_id
    ) lr ON lr.booking_id = b.booking_id AND lr.campaign_id = ra.campaign_id
    GROUP BY ra.campaign_id, ra.campaign_code, ra.campaign_name, ra.campaign_type, ra.customer_id, ra.assignment_group
),
spend_by_campaign AS (
    SELECT campaign_id, SUM(amount_usd) AS marketing_spend
    FROM marketing_costs
    GROUP BY campaign_id
)
SELECT
    o.campaign_code,
    o.campaign_name,
    o.campaign_type,
    COUNT(*) FILTER (WHERE o.assignment_group = 'treatment') AS n_treatment,
    COUNT(*) FILTER (WHERE o.assignment_group = 'control') AS n_control,
    ROUND(AVG(o.converted) FILTER (WHERE o.assignment_group = 'control') * 100.0, 2) AS control_conv_pct,
    ROUND(AVG(o.converted) FILTER (WHERE o.assignment_group = 'treatment') * 100.0, 2) AS treatment_conv_pct,
    ROUND((AVG(o.converted) FILTER (WHERE o.assignment_group = 'treatment')
        - AVG(o.converted) FILTER (WHERE o.assignment_group = 'control')) * 100.0, 2) AS lift_pp,
    ROUND((AVG(o.bookings_cnt) FILTER (WHERE o.assignment_group = 'treatment')
        - AVG(o.bookings_cnt) FILTER (WHERE o.assignment_group = 'control'))
        * COUNT(*) FILTER (WHERE o.assignment_group = 'treatment'), 1) AS est_incremental_bookings,
    ROUND(((AVG(o.net_contribution) FILTER (WHERE o.assignment_group = 'treatment')
        - AVG(o.net_contribution) FILTER (WHERE o.assignment_group = 'control'))
        * COUNT(*) FILTER (WHERE o.assignment_group = 'treatment')) - COALESCE(s.marketing_spend, 0), 2) AS est_net_incremental_contribution
FROM customer_window_outcomes o
LEFT JOIN spend_by_campaign s ON s.campaign_id = o.campaign_id
GROUP BY o.campaign_id, o.campaign_code, o.campaign_name, o.campaign_type, s.marketing_spend
ORDER BY est_net_incremental_contribution DESC
LIMIT 25;

-- @id: campaign_efficiency_ranking
-- @title: Campaign Ranking by Incremental Contribution & Efficiency Within Campaign Type
-- @category: Rankings & Portfolio Allocation
-- @techniques: Window Functions (DENSE_RANK, PERCENT_RANK, SUM OVER), CTEs, Multi-Table Joins
-- @indexes: idx_campaigns_channel_segment_route, idx_marketing_costs_campaign_channel
-- @decision: Guides commercial investment reallocation by ranking RCT campaigns within each promotion category and measuring cumulative portfolio contribution.
WITH ranked_rct AS (
    SELECT
        c.campaign_code,
        c.campaign_name,
        c.campaign_type,
        ch.channel_name,
        COALESCE(cs.segment_name, 'All Segments') AS target_segment,
        ers.marketing_spend,
        ers.incremental_bookings,
        ers.incremental_revenue,
        ers.incremental_contribution,
        ers.cost_per_incremental_booking,
        ers.conversion_p_value,
        DENSE_RANK() OVER (
            PARTITION BY c.campaign_type
            ORDER BY ers.incremental_contribution DESC
        ) AS rank_within_type,
        ROUND((PERCENT_RANK() OVER (ORDER BY ers.incremental_contribution) * 100)::NUMERIC, 1) AS portfolio_percentile,
        SUM(ers.incremental_contribution) OVER (
            ORDER BY ers.incremental_contribution DESC
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_incremental_contrib
    FROM campaigns c
    JOIN experiment_results_store ers ON ers.campaign_id = c.campaign_id
    JOIN campaign_channels ch ON ch.channel_id = c.primary_channel_id
    LEFT JOIN customer_segments cs ON cs.segment_id = c.target_segment_id
    WHERE c.experiment_type = 'RCT'
)
SELECT
    campaign_code,
    campaign_name,
    campaign_type,
    channel_name,
    target_segment,
    rank_within_type,
    portfolio_percentile,
    ROUND(marketing_spend, 2) AS marketing_spend,
    ROUND(incremental_bookings, 1) AS incremental_bookings,
    ROUND(incremental_contribution, 2) AS incremental_contribution,
    ROUND(cost_per_incremental_booking, 2) AS cost_per_inc_booking,
    ROUND(cumulative_incremental_contrib, 2) AS cumulative_portfolio_contrib
FROM ranked_rct
ORDER BY incremental_contribution DESC
LIMIT 30;

-- @id: quarterly_time_comparison
-- @title: Quarterly Promotional Spend, Incremental Contribution & QoQ Trajectory
-- @category: Time-Based Comparisons
-- @techniques: Calendar Dimension Join, LAG Window Functions, Rolling 2-Quarter Averages, Conditional Aggregation
-- @indexes: idx_campaigns_dates_type, idx_marketing_costs_date
-- @decision: Tracks seasonal shifts in promotional effectiveness and margin erosion quarter-over-quarter to optimize timing across peak vs. shoulder travel seasons.
WITH quarterly_rct AS (
    SELECT
        cal.year,
        cal.quarter,
        CONCAT(cal.year, '-Q', cal.quarter) AS fiscal_quarter,
        COUNT(DISTINCT c.campaign_id) AS rct_campaigns,
        SUM(ers.marketing_spend) AS total_spend,
        SUM(ers.incremental_bookings) AS incremental_bookings,
        SUM(ers.incremental_revenue) AS incremental_revenue,
        SUM(ers.incremental_contribution) AS incremental_contribution,
        AVG(c.discount_pct) AS avg_discount_pct,
        COUNT(*) FILTER (WHERE ers.is_statistically_significant AND ers.incremental_contribution > 0) AS winning_campaigns
    FROM campaigns c
    JOIN calendar_dimension cal ON cal.calendar_date = c.start_date
    JOIN experiment_results_store ers ON ers.campaign_id = c.campaign_id
    WHERE c.experiment_type = 'RCT'
    GROUP BY cal.year, cal.quarter
)
SELECT
    fiscal_quarter,
    rct_campaigns,
    winning_campaigns,
    ROUND(total_spend, 2) AS total_spend,
    ROUND(incremental_bookings, 1) AS incremental_bookings,
    ROUND(incremental_contribution, 2) AS incremental_contribution,
    ROUND(incremental_contribution - LAG(incremental_contribution) OVER (ORDER BY year, quarter), 2) AS qoq_contrib_change,
    ROUND(AVG(incremental_contribution) OVER (
        ORDER BY year, quarter ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
    ), 2) AS rolling_2q_avg_contrib,
    ROUND(CASE WHEN total_spend > 0 THEN incremental_contribution / total_spend ELSE NULL END, 2) AS incremental_roi_ratio,
    ROUND(avg_discount_pct, 1) AS avg_discount_pct
FROM quarterly_rct
ORDER BY year, quarter;

-- @id: signup_cohort_promo_response
-- @title: Customer Acquisition Cohort Repeat Booking & Promotional Responsiveness
-- @category: Cohort Analysis
-- @techniques: Date Truncation Cohorts, Multi-Level Customer Aggregation, Conditional Ratios
-- @indexes: idx_customers_segment_tier, idx_assignments_customer_campaign, idx_bookings_customer_date_status
-- @decision: Evaluates whether newer vs. tenured loyalty cohorts generate durable post-promotion repeat bookings or only transact during heavy fare sales.
WITH customer_cohorts AS (
    SELECT
        c.customer_id,
        DATE_TRUNC('year', c.signup_date)::DATE AS cohort_year_start,
        EXTRACT(YEAR FROM c.signup_date)::INT AS signup_year,
        cs.segment_name
    FROM customers c
    JOIN customer_segments cs ON cs.segment_id = c.segment_id
),
cohort_bookings AS (
    SELECT
        cc.signup_year,
        cc.segment_name,
        COUNT(DISTINCT cc.customer_id) AS cohort_customers,
        COUNT(DISTINCT b.booking_id) FILTER (WHERE b.booking_status <> 'cancelled') AS total_bookings,
        COUNT(DISTINCT b.booking_id) FILTER (WHERE b.booking_status <> 'cancelled' AND b.attributed_campaign_id IS NOT NULL) AS promo_attributed_bookings,
        COUNT(DISTINCT b.booking_id) FILTER (WHERE b.booking_status <> 'cancelled' AND b.attributed_campaign_id IS NULL) AS organic_bookings,
        COALESCE(SUM(tr.net_ticket_revenue) FILTER (WHERE b.booking_status <> 'cancelled'), 0) AS total_net_revenue,
        COALESCE(SUM(tr.discount_amount) FILTER (WHERE b.booking_status <> 'cancelled'), 0) AS total_discounts
    FROM customer_cohorts cc
    LEFT JOIN bookings b ON b.customer_id = cc.customer_id
    LEFT JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
    GROUP BY cc.signup_year, cc.segment_name
)
SELECT
    signup_year,
    segment_name,
    cohort_customers,
    total_bookings,
    ROUND(total_bookings::NUMERIC / NULLIF(cohort_customers, 0), 2) AS bookings_per_customer,
    ROUND(promo_attributed_bookings * 100.0 / NULLIF(total_bookings, 0), 1) AS promo_share_pct,
    ROUND(total_net_revenue / NULLIF(cohort_customers, 0), 2) AS net_rev_per_customer,
    ROUND(total_discounts * 100.0 / NULLIF(total_net_revenue + total_discounts, 0), 2) AS effective_discount_rate_pct
FROM cohort_bookings
WHERE cohort_customers >= 100
ORDER BY signup_year DESC, net_rev_per_customer DESC
LIMIT 30;

-- @id: margin_erosion_cannibalization
-- @title: Promotion Margin Erosion & Baseline Cannibalization Audit
-- @category: Promotion Economics
-- @techniques: Multi-Table Financial Joins, CTEs, Unit Economics Decomposition
-- @indexes: idx_bookings_attributed_campaign, idx_discount_tx_campaign_booking, idx_loyalty_rewards_campaign_booking
-- @decision: Pinpoints campaigns generating high gross revenue while destroying contribution margin through excessive fare discounting to customers who would have booked anyway.
WITH promo_ledger AS (
    SELECT
        c.campaign_id,
        c.campaign_code,
        c.campaign_name,
        c.campaign_type,
        c.discount_pct,
        c.bonus_miles_offer,
        COUNT(DISTINCT b.booking_id) AS attributed_bookings,
        COALESCE(SUM(tr.gross_total_revenue), 0) AS gross_revenue,
        COALESCE(SUM(tr.discount_amount), 0) AS discount_cost,
        COALESCE(SUM(tr.estimated_variable_cost), 0) AS variable_cost,
        COALESCE(SUM(tr.contribution_before_promo), 0) AS contrib_before_promo
    FROM campaigns c
    JOIN bookings b ON b.attributed_campaign_id = c.campaign_id AND b.booking_status <> 'cancelled'
    JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
    WHERE c.experiment_type = 'RCT'
    GROUP BY c.campaign_id, c.campaign_code, c.campaign_name, c.campaign_type, c.discount_pct, c.bonus_miles_offer
),
miles_ledger AS (
    SELECT campaign_id, COALESCE(SUM(reward_liability_cost), 0) AS miles_cost
    FROM loyalty_rewards
    WHERE campaign_id IS NOT NULL
    GROUP BY campaign_id
)
SELECT
    p.campaign_code,
    p.campaign_name,
    p.campaign_type,
    p.discount_pct,
    p.attributed_bookings,
    ROUND(p.gross_revenue, 2) AS gross_revenue,
    ROUND(p.discount_cost, 2) AS discount_cost,
    ROUND(COALESCE(m.miles_cost, 0), 2) AS miles_cost,
    ROUND(ers.marketing_spend, 2) AS media_spend,
    ROUND(p.contrib_before_promo - p.discount_cost - COALESCE(m.miles_cost, 0) - ers.marketing_spend, 2) AS contrib_after_promo,
    ROUND(ers.incremental_contribution, 2) AS true_incremental_contribution,
    ROUND((p.discount_cost + COALESCE(m.miles_cost, 0)) * 100.0 / NULLIF(p.contrib_before_promo, 0), 1) AS margin_erosion_pct
FROM promo_ledger p
JOIN experiment_results_store ers ON ers.campaign_id = p.campaign_id
LEFT JOIN miles_ledger m ON m.campaign_id = p.campaign_id
ORDER BY margin_erosion_pct DESC
LIMIT 25;

-- @id: channel_funnel_dropoff_diagnostics
-- @title: Marketing Channel Funnel Reach, Engagement & Drop-Off Diagnostics
-- @category: Funnel Analytics
-- @techniques: Multi-Stage CTE Aggregation, Conditional Counting, Stage-to-Stage Ratios
-- @indexes: idx_assignments_channel, idx_exposures_campaign_reached, idx_responses_campaign_engaged
-- @decision: Highlights whether underperforming channels suffer from deliverability/reach bottlenecks vs. creative engagement failure vs. booking checkout drop-off.
WITH channel_funnel AS (
    SELECT
        ch.channel_id,
        ch.channel_name,
        ch.cost_model,
        COUNT(DISTINCT ca.assignment_id) FILTER (WHERE ca.assignment_group IN ('treatment', 'observational_targeted')) AS assigned_targeted,
        COUNT(DISTINCT ce.assignment_id) FILTER (WHERE ce.is_reached = TRUE) AS reached_count,
        COUNT(DISTINCT cr.assignment_id) FILTER (WHERE cr.engaged_flag = TRUE) AS engaged_count
    FROM campaign_channels ch
    LEFT JOIN campaign_assignments ca ON ca.channel_id = ch.channel_id
    LEFT JOIN campaign_exposures ce ON ce.assignment_id = ca.assignment_id
    LEFT JOIN customer_responses cr ON cr.assignment_id = ca.assignment_id
    GROUP BY ch.channel_id, ch.channel_name, ch.cost_model
),
channel_outcomes AS (
    SELECT
        c.primary_channel_id AS channel_id,
        COUNT(DISTINCT b.booking_id) FILTER (WHERE b.booking_status <> 'cancelled') AS attributed_bookings,
        COUNT(DISTINCT b.booking_id) FILTER (WHERE b.travel_completed = TRUE) AS completed_trips,
        COALESCE(SUM(mc.amount_usd), 0) AS total_channel_spend
    FROM campaigns c
    LEFT JOIN bookings b ON b.attributed_campaign_id = c.campaign_id
    LEFT JOIN (
        SELECT campaign_id, SUM(amount_usd) AS amount_usd FROM marketing_costs GROUP BY campaign_id
    ) mc ON mc.campaign_id = c.campaign_id
    GROUP BY c.primary_channel_id
)
SELECT
    cf.channel_name,
    cf.cost_model,
    cf.assigned_targeted,
    cf.reached_count,
    ROUND(cf.reached_count * 100.0 / NULLIF(cf.assigned_targeted, 0), 1) AS reach_rate_pct,
    cf.engaged_count,
    ROUND(cf.engaged_count * 100.0 / NULLIF(cf.reached_count, 0), 1) AS engagement_of_reached_pct,
    COALESCE(co.attributed_bookings, 0) AS attributed_bookings,
    ROUND(COALESCE(co.attributed_bookings, 0) * 100.0 / NULLIF(cf.engaged_count, 0), 1) AS book_of_engaged_pct,
    COALESCE(co.completed_trips, 0) AS completed_trips,
    ROUND(COALESCE(co.total_channel_spend, 0), 2) AS total_spend
FROM channel_funnel cf
LEFT JOIN channel_outcomes co ON co.channel_id = cf.channel_id
ORDER BY attributed_bookings DESC;

-- @id: route_market_promo_economics
-- @title: Route Market Promotional Load-Factor Elasticity & Unit Margin
-- @category: Network & Route Commercials
-- @techniques: Multi-Table Joins, Window Share-of-Revenue, Conditional Aggregation
-- @indexes: idx_bookings_route_date, idx_ticket_revenue_booking
-- @decision: Identifies O&D route markets with low baseline load factors where targeted fare/miles offers unlock high-margin incremental seat fill without diluting constrained peak routes.
WITH route_stats AS (
    SELECT
        rm.market_code,
        rm.market_region,
        rm.haul_type,
        rm.load_factor_baseline,
        rm.avg_base_fare,
        COUNT(DISTINCT b.booking_id) FILTER (WHERE b.booking_status <> 'cancelled') AS total_bookings,
        COUNT(DISTINCT b.booking_id) FILTER (WHERE b.booking_status <> 'cancelled' AND b.attributed_campaign_id IS NOT NULL) AS promo_bookings,
        COALESCE(SUM(tr.gross_total_revenue) FILTER (WHERE b.booking_status <> 'cancelled'), 0) AS gross_revenue,
        COALESCE(SUM(tr.discount_amount) FILTER (WHERE b.booking_status <> 'cancelled'), 0) AS total_discounts,
        COALESCE(SUM(tr.contribution_before_promo - tr.discount_amount) FILTER (WHERE b.booking_status <> 'cancelled'), 0) AS net_route_contribution
    FROM route_markets rm
    LEFT JOIN bookings b ON b.route_market_id = rm.route_market_id
    LEFT JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
    GROUP BY rm.route_market_id, rm.market_code, rm.market_region, rm.haul_type, rm.load_factor_baseline, rm.avg_base_fare
)
SELECT
    market_code,
    market_region,
    haul_type,
    ROUND(load_factor_baseline * 100, 1) AS baseline_lf_pct,
    total_bookings,
    promo_bookings,
    ROUND(promo_bookings * 100.0 / NULLIF(total_bookings, 0), 1) AS promo_mix_pct,
    ROUND(net_route_contribution, 2) AS net_route_contribution,
    ROUND(net_route_contribution / NULLIF(total_bookings, 0), 2) AS avg_contrib_per_booking,
    ROUND(net_route_contribution * 100.0 / NULLIF(SUM(net_route_contribution) OVER (), 0), 2) AS network_contrib_share_pct
FROM route_stats
ORDER BY net_route_contribution DESC
LIMIT 25;

-- @id: customer_segment_incentive_preference
-- @title: Customer-Level Aggregation: Fare Discount vs. Bonus Miles Response by Segment
-- @category: Customer Response & Targeting
-- @techniques: Customer-Level CTE Rollup, Incentive Type Pivoting, Propensity Score Join
-- @indexes: idx_customers_segment_tier, idx_propensity_archetype, idx_responses_customer
-- @decision: Determines which customer segments should receive lower-cost loyalty miles incentives versus direct fare discounts, and which segments should be suppressed to prevent subsidy waste.
WITH customer_rollup AS (
    SELECT
        cu.customer_id,
        cs.segment_name,
        cu.loyalty_tier,
        cu.historical_spend_12m,
        cps.baseline_booking_prob,
        cps.predicted_uplift,
        cps.discount_uplift_score,
        cps.miles_uplift_score,
        cps.response_archetype,
        COUNT(DISTINCT cr.response_id) FILTER (WHERE cr.incentive_type_engaged = 'fare_discount') AS discount_engagements,
        COUNT(DISTINCT cr.response_id) FILTER (WHERE cr.incentive_type_engaged = 'bonus_miles') AS miles_engagements
    FROM customers cu
    JOIN customer_segments cs ON cs.segment_id = cu.segment_id
    LEFT JOIN customer_propensity_scores cps ON cps.customer_id = cu.customer_id
    LEFT JOIN customer_responses cr ON cr.customer_id = cu.customer_id AND cr.engaged_flag = TRUE
    GROUP BY
        cu.customer_id, cs.segment_name, cu.loyalty_tier, cu.historical_spend_12m,
        cps.baseline_booking_prob, cps.predicted_uplift, cps.discount_uplift_score,
        cps.miles_uplift_score, cps.response_archetype
)
SELECT
    segment_name,
    response_archetype,
    COUNT(*) AS customer_count,
    ROUND(AVG(historical_spend_12m), 2) AS avg_12m_spend,
    ROUND((AVG(baseline_booking_prob) * 100.0)::NUMERIC, 2) AS avg_baseline_prob_pct,
    ROUND((AVG(predicted_uplift) * 100.0)::NUMERIC, 2) AS avg_pred_uplift_pp,
    ROUND((AVG(discount_uplift_score) * 100.0)::NUMERIC, 2) AS avg_discount_uplift_pp,
    ROUND((AVG(miles_uplift_score) * 100.0)::NUMERIC, 2) AS avg_miles_uplift_pp,
    SUM(discount_engagements) AS discount_engagements,
    SUM(miles_engagements) AS miles_engagements
FROM customer_rollup
WHERE response_archetype IS NOT NULL
GROUP BY segment_name, response_archetype
ORDER BY avg_pred_uplift_pp DESC
LIMIT 25;
