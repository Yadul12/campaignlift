-- ============================================================================
-- CampaignLift Migration 002: Performance Indexes & Reusable Analytical Views
-- ============================================================================

-- High-selectivity composite indexes optimizing ITT experiment joins,
-- funnel rollups, campaign economics, and global filter queries.

CREATE INDEX IF NOT EXISTS idx_customers_segment_tier ON customers (segment_id, loyalty_tier);
CREATE INDEX IF NOT EXISTS idx_customers_home_region ON customers (region, home_airport);

CREATE INDEX IF NOT EXISTS idx_campaigns_dates_type ON campaigns (start_date, end_date, experiment_type);
CREATE INDEX IF NOT EXISTS idx_campaigns_channel_segment_route ON campaigns (primary_channel_id, target_segment_id, target_route_market_id);

CREATE INDEX IF NOT EXISTS idx_assignments_campaign_group_cust ON campaign_assignments (campaign_id, assignment_group, customer_id);
CREATE INDEX IF NOT EXISTS idx_assignments_customer_campaign ON campaign_assignments (customer_id, campaign_id);
CREATE INDEX IF NOT EXISTS idx_assignments_channel ON campaign_assignments (channel_id, campaign_id);

CREATE INDEX IF NOT EXISTS idx_exposures_campaign_reached ON campaign_exposures (campaign_id, is_reached, customer_id);
CREATE INDEX IF NOT EXISTS idx_exposures_assignment ON campaign_exposures (assignment_id);

CREATE INDEX IF NOT EXISTS idx_responses_campaign_engaged ON customer_responses (campaign_id, engaged_flag, customer_id);
CREATE INDEX IF NOT EXISTS idx_responses_customer ON customer_responses (customer_id, campaign_id);

-- Critical index for Intention-to-Treat observation window joins:
-- Joins campaign_assignments.customer_id -> bookings.customer_id filtered by booking_date range & non-cancelled status.
CREATE INDEX IF NOT EXISTS idx_bookings_customer_date_status ON bookings (customer_id, booking_date, booking_status);
CREATE INDEX IF NOT EXISTS idx_bookings_attributed_campaign ON bookings (attributed_campaign_id, booking_status) WHERE attributed_campaign_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bookings_route_date ON bookings (route_market_id, booking_date);
CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings (booking_date);

CREATE INDEX IF NOT EXISTS idx_booking_items_booking ON booking_items (booking_id);
CREATE INDEX IF NOT EXISTS idx_ticket_revenue_booking ON ticket_revenue (booking_id);
CREATE INDEX IF NOT EXISTS idx_discount_tx_campaign_booking ON discount_transactions (campaign_id, booking_id);
CREATE INDEX IF NOT EXISTS idx_discount_tx_booking ON discount_transactions (booking_id);
CREATE INDEX IF NOT EXISTS idx_loyalty_rewards_campaign_booking ON loyalty_rewards (campaign_id, booking_id) WHERE campaign_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_loyalty_rewards_booking ON loyalty_rewards (booking_id);
CREATE INDEX IF NOT EXISTS idx_marketing_costs_campaign_channel ON marketing_costs (campaign_id, channel_id);
CREATE INDEX IF NOT EXISTS idx_marketing_costs_date ON marketing_costs (cost_date);
CREATE INDEX IF NOT EXISTS idx_propensity_archetype ON customer_propensity_scores (response_archetype, uplift_decile);

-- ============================================================================
-- Reusable Analytical View: Campaign-level Attributed & Spend Rollup
-- ============================================================================

CREATE OR REPLACE VIEW v_campaign_commercial_summary AS
WITH spend_agg AS (
    SELECT
        campaign_id,
        COALESCE(SUM(amount_usd), 0)::NUMERIC(14, 2) AS marketing_spend
    FROM marketing_costs
    GROUP BY campaign_id
),
assign_agg AS (
    SELECT
        campaign_id,
        COUNT(*) AS total_assigned,
        COUNT(*) FILTER (WHERE assignment_group IN ('treatment', 'observational_targeted')) AS targeted_customers,
        COUNT(*) FILTER (WHERE assignment_group = 'control') AS control_customers
    FROM campaign_assignments
    GROUP BY campaign_id
),
exposure_agg AS (
    SELECT
        campaign_id,
        COUNT(DISTINCT customer_id) FILTER (WHERE is_reached = TRUE) AS customers_reached
    FROM campaign_exposures
    GROUP BY campaign_id
),
response_agg AS (
    SELECT
        campaign_id,
        COUNT(DISTINCT customer_id) FILTER (WHERE engaged_flag = TRUE) AS customers_engaged
    FROM customer_responses
    GROUP BY campaign_id
),
booking_agg AS (
    SELECT
        b.attributed_campaign_id AS campaign_id,
        COUNT(DISTINCT b.booking_id) FILTER (WHERE b.booking_status <> 'cancelled') AS attributed_bookings,
        COUNT(DISTINCT b.customer_id) FILTER (WHERE b.booking_status <> 'cancelled') AS attributed_bookers,
        COUNT(DISTINCT b.customer_id) FILTER (WHERE b.travel_completed = TRUE) AS completed_travelers,
        COALESCE(SUM(tr.gross_total_revenue) FILTER (WHERE b.booking_status <> 'cancelled'), 0)::NUMERIC(14, 2) AS gross_booking_revenue,
        COALESCE(SUM(tr.discount_amount) FILTER (WHERE b.booking_status <> 'cancelled'), 0)::NUMERIC(14, 2) AS discount_cost,
        COALESCE(SUM(tr.net_ticket_revenue) FILTER (WHERE b.booking_status <> 'cancelled'), 0)::NUMERIC(14, 2) AS net_ticket_revenue,
        COALESCE(SUM(tr.estimated_variable_cost) FILTER (WHERE b.booking_status <> 'cancelled'), 0)::NUMERIC(14, 2) AS variable_cost,
        COALESCE(SUM(tr.contribution_before_promo) FILTER (WHERE b.booking_status <> 'cancelled'), 0)::NUMERIC(14, 2) AS contribution_before_promo
    FROM bookings b
    JOIN ticket_revenue tr ON tr.booking_id = b.booking_id
    WHERE b.attributed_campaign_id IS NOT NULL
    GROUP BY b.attributed_campaign_id
),
miles_agg AS (
    SELECT
        lr.campaign_id,
        COALESCE(SUM(lr.miles_awarded), 0) AS promo_miles_awarded,
        COALESCE(SUM(lr.reward_liability_cost), 0)::NUMERIC(14, 2) AS loyalty_reward_cost
    FROM loyalty_rewards lr
    JOIN bookings b ON b.booking_id = lr.booking_id
    WHERE lr.campaign_id IS NOT NULL
      AND b.booking_status <> 'cancelled'
    GROUP BY lr.campaign_id
)
SELECT
    c.campaign_id,
    c.campaign_code,
    c.campaign_name,
    c.campaign_type,
    c.experiment_type,
    c.start_date,
    c.end_date,
    c.booking_window_days,
    c.discount_pct,
    c.bonus_miles_offer,
    c.eligible_audience_count,
    c.planned_budget,
    c.status,
    ch.channel_id,
    ch.channel_name,
    cs.segment_id,
    COALESCE(cs.segment_name, 'All Segments') AS target_segment_name,
    rm.route_market_id,
    COALESCE(rm.market_code, 'Network-Wide') AS target_route_code,
    COALESCE(rm.market_region, 'All Regions') AS target_route_region,
    COALESCE(sa.marketing_spend, 0)::NUMERIC(14, 2) AS marketing_spend,
    COALESCE(aa.total_assigned, 0) AS total_assigned,
    COALESCE(aa.targeted_customers, 0) AS customers_targeted,
    COALESCE(aa.control_customers, 0) AS control_customers,
    COALESCE(ea.customers_reached, 0) AS customers_reached,
    COALESCE(ra.customers_engaged, 0) AS customers_engaged,
    COALESCE(ba.attributed_bookings, 0) AS attributed_bookings,
    COALESCE(ba.attributed_bookers, 0) AS attributed_bookers,
    COALESCE(ba.completed_travelers, 0) AS completed_travelers,
    COALESCE(ba.gross_booking_revenue, 0)::NUMERIC(14, 2) AS gross_booking_revenue,
    COALESCE(ba.discount_cost, 0)::NUMERIC(14, 2) AS discount_cost,
    COALESCE(ba.net_ticket_revenue, 0)::NUMERIC(14, 2) AS net_ticket_revenue,
    COALESCE(ba.variable_cost, 0)::NUMERIC(14, 2) AS variable_cost,
    COALESCE(ba.contribution_before_promo, 0)::NUMERIC(14, 2) AS contribution_before_promo,
    COALESCE(ma.promo_miles_awarded, 0) AS promo_miles_awarded,
    COALESCE(ma.loyalty_reward_cost, 0)::NUMERIC(14, 2) AS loyalty_reward_cost,
    (
        COALESCE(ba.gross_booking_revenue, 0)
        - COALESCE(ba.discount_cost, 0)
        - COALESCE(ba.variable_cost, 0)
        - COALESCE(ma.loyalty_reward_cost, 0)
        - COALESCE(sa.marketing_spend, 0)
    )::NUMERIC(14, 2) AS contribution_after_promo,
    ers.conversion_control,
    ers.conversion_treatment,
    ers.conversion_lift_abs,
    ers.conversion_lift_rel,
    ers.conversion_p_value,
    ers.contrib_per_cust_p_value,
    ers.incremental_bookings,
    ers.incremental_revenue,
    ers.incremental_contribution,
    ers.cost_per_incremental_booking,
    ers.is_statistically_significant,
    ers.srm_passed,
    ers.recommendation_status
FROM campaigns c
JOIN campaign_channels ch ON ch.channel_id = c.primary_channel_id
LEFT JOIN customer_segments cs ON cs.segment_id = c.target_segment_id
LEFT JOIN route_markets rm ON rm.route_market_id = c.target_route_market_id
LEFT JOIN spend_agg sa ON sa.campaign_id = c.campaign_id
LEFT JOIN assign_agg aa ON aa.campaign_id = c.campaign_id
LEFT JOIN exposure_agg ea ON ea.campaign_id = c.campaign_id
LEFT JOIN response_agg ra ON ra.campaign_id = c.campaign_id
LEFT JOIN booking_agg ba ON ba.campaign_id = c.campaign_id
LEFT JOIN miles_agg ma ON ma.campaign_id = c.campaign_id
LEFT JOIN experiment_results_store ers ON ers.campaign_id = c.campaign_id;
