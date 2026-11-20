-- ============================================================================
-- CampaignLift: Airline Marketing Promotions & Incremental Revenue Analytics
-- Migration 001: Core 15 Relational Tables + Analytics Metadata Tables
-- All datasets generated into this schema are SYNTHETIC and SIMULATED.
-- ============================================================================

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 1. customer_segments
CREATE TABLE IF NOT EXISTS customer_segments (
    segment_id SERIAL PRIMARY KEY,
    segment_code VARCHAR(32) NOT NULL UNIQUE,
    segment_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT NOT NULL,
    target_margin_tier VARCHAR(32) NOT NULL,
    avg_annual_trips NUMERIC(6, 2) NOT NULL,
    typical_booking_lead_days INT NOT NULL,
    incentive_affinity VARCHAR(32) NOT NULL -- 'fare_discount', 'bonus_miles', 'cabin_upgrade', 'low_promo_sensitivity'
);

-- 2. customers
CREATE TABLE IF NOT EXISTS customers (
    customer_id BIGSERIAL PRIMARY KEY,
    customer_code VARCHAR(24) NOT NULL UNIQUE,
    segment_id INT NOT NULL REFERENCES customer_segments(segment_id),
    loyalty_tier VARCHAR(24) NOT NULL CHECK (loyalty_tier IN ('None', 'Silver', 'Gold', 'Platinum', 'Executive')),
    home_airport CHAR(3) NOT NULL,
    region VARCHAR(40) NOT NULL,
    signup_date DATE NOT NULL,
    tenure_months INT NOT NULL CHECK (tenure_months >= 0),
    age_band VARCHAR(16) NOT NULL CHECK (age_band IN ('18-29', '30-44', '45-59', '60+')),
    historical_trips_12m INT NOT NULL CHECK (historical_trips_12m >= 0),
    historical_spend_12m NUMERIC(12, 2) NOT NULL CHECK (historical_spend_12m >= 0),
    miles_balance INT NOT NULL CHECK (miles_balance >= 0),
    email_opt_in BOOLEAN NOT NULL DEFAULT TRUE,
    push_opt_in BOOLEAN NOT NULL DEFAULT TRUE,
    app_active BOOLEAN NOT NULL DEFAULT FALSE,
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE
);

-- 3. route_markets
CREATE TABLE IF NOT EXISTS route_markets (
    route_market_id SERIAL PRIMARY KEY,
    market_code VARCHAR(16) NOT NULL UNIQUE,
    origin_airport CHAR(3) NOT NULL,
    destination_airport CHAR(3) NOT NULL,
    market_region VARCHAR(48) NOT NULL,
    haul_type VARCHAR(24) NOT NULL CHECK (haul_type IN ('Short-Haul', 'Medium-Haul', 'Long-Haul')),
    distance_miles INT NOT NULL CHECK (distance_miles > 0),
    avg_base_fare NUMERIC(10, 2) NOT NULL CHECK (avg_base_fare > 0),
    variable_cost_per_pax NUMERIC(10, 2) NOT NULL CHECK (variable_cost_per_pax > 0),
    load_factor_baseline NUMERIC(5, 4) NOT NULL CHECK (load_factor_baseline > 0 AND load_factor_baseline <= 1),
    seasonality_profile VARCHAR(32) NOT NULL
);

-- 4. campaign_channels
CREATE TABLE IF NOT EXISTS campaign_channels (
    channel_id SERIAL PRIMARY KEY,
    channel_code VARCHAR(32) NOT NULL UNIQUE,
    channel_name VARCHAR(64) NOT NULL UNIQUE,
    cost_model VARCHAR(32) NOT NULL,
    unit_reach_cost NUMERIC(10, 4) NOT NULL CHECK (unit_reach_cost >= 0),
    avg_deliverability_rate NUMERIC(5, 4) NOT NULL,
    avg_engagement_rate NUMERIC(5, 4) NOT NULL
);

-- 5. calendar_dimension
CREATE TABLE IF NOT EXISTS calendar_dimension (
    calendar_date DATE PRIMARY KEY,
    year INT NOT NULL,
    quarter INT NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month INT NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name VARCHAR(16) NOT NULL,
    week_of_year INT NOT NULL,
    day_of_week INT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    day_name VARCHAR(16) NOT NULL,
    is_weekend BOOLEAN NOT NULL,
    is_holiday_peak BOOLEAN NOT NULL,
    travel_season VARCHAR(32) NOT NULL,
    fiscal_period VARCHAR(16) NOT NULL
);

-- 6. campaigns
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id SERIAL PRIMARY KEY,
    campaign_code VARCHAR(32) NOT NULL UNIQUE,
    campaign_name VARCHAR(160) NOT NULL,
    campaign_type VARCHAR(48) NOT NULL CHECK (
        campaign_type IN (
            'Promotional Fare',
            'Discounted Ticket',
            'Bonus Loyalty Miles',
            'Seasonal Travel Offer',
            'Route-Specific Offer',
            'Customer Reactivation',
            'Premium Cabin Promotion',
            'Targeted Customer Offer'
        )
    ),
    experiment_type VARCHAR(24) NOT NULL CHECK (experiment_type IN ('RCT', 'Observational')),
    primary_channel_id INT NOT NULL REFERENCES campaign_channels(channel_id),
    target_segment_id INT REFERENCES customer_segments(segment_id),
    target_route_market_id INT REFERENCES route_markets(route_market_id),
    start_date DATE NOT NULL REFERENCES calendar_dimension(calendar_date),
    end_date DATE NOT NULL REFERENCES calendar_dimension(calendar_date),
    booking_window_days INT NOT NULL DEFAULT 14 CHECK (booking_window_days >= 0),
    discount_pct NUMERIC(5, 2) NOT NULL DEFAULT 0 CHECK (discount_pct >= 0 AND discount_pct <= 60),
    bonus_miles_offer INT NOT NULL DEFAULT 0 CHECK (bonus_miles_offer >= 0),
    treatment_split_target NUMERIC(5, 4) CHECK (treatment_split_target > 0 AND treatment_split_target <= 1),
    eligible_audience_count INT NOT NULL CHECK (eligible_audience_count >= 0),
    planned_budget NUMERIC(12, 2) NOT NULL CHECK (planned_budget >= 0),
    status VARCHAR(24) NOT NULL CHECK (status IN ('Completed', 'Active')),
    hypothesis TEXT NOT NULL,
    eligibility_criteria TEXT NOT NULL,
    is_synthetic BOOLEAN NOT NULL DEFAULT TRUE,
    CHECK (end_date >= start_date)
);

-- 7. campaign_assignments
CREATE TABLE IF NOT EXISTS campaign_assignments (
    assignment_id BIGSERIAL PRIMARY KEY,
    campaign_id INT NOT NULL REFERENCES campaigns(campaign_id),
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    channel_id INT NOT NULL REFERENCES campaign_channels(channel_id),
    assignment_group VARCHAR(32) NOT NULL CHECK (
        assignment_group IN ('treatment', 'control', 'observational_targeted', 'observational_comparison')
    ),
    assigned_at DATE NOT NULL REFERENCES calendar_dimension(calendar_date),
    UNIQUE (campaign_id, customer_id)
);

-- 8. campaign_exposures
CREATE TABLE IF NOT EXISTS campaign_exposures (
    exposure_id BIGSERIAL PRIMARY KEY,
    assignment_id BIGINT NOT NULL REFERENCES campaign_assignments(assignment_id),
    campaign_id INT NOT NULL REFERENCES campaigns(campaign_id),
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    channel_id INT NOT NULL REFERENCES campaign_channels(channel_id),
    exposed_at TIMESTAMPTZ NOT NULL,
    impression_count INT NOT NULL DEFAULT 1 CHECK (impression_count >= 1),
    delivery_status VARCHAR(24) NOT NULL CHECK (delivery_status IN ('delivered', 'bounced', 'suppressed')),
    is_reached BOOLEAN NOT NULL
);

-- 9. customer_responses
CREATE TABLE IF NOT EXISTS customer_responses (
    response_id BIGSERIAL PRIMARY KEY,
    assignment_id BIGINT NOT NULL REFERENCES campaign_assignments(assignment_id),
    exposure_id BIGINT REFERENCES campaign_exposures(exposure_id),
    campaign_id INT NOT NULL REFERENCES campaigns(campaign_id),
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    response_timestamp TIMESTAMPTZ NOT NULL,
    response_type VARCHAR(32) NOT NULL CHECK (
        response_type IN ('open', 'click', 'offer_view', 'promo_code_applied', 'miles_enrolled')
    ),
    engaged_flag BOOLEAN NOT NULL,
    incentive_type_engaged VARCHAR(32) NOT NULL CHECK (
        incentive_type_engaged IN ('fare_discount', 'bonus_miles', 'cabin_upgrade', 'none')
    )
);

-- 10. bookings
CREATE TABLE IF NOT EXISTS bookings (
    booking_id BIGSERIAL PRIMARY KEY,
    booking_reference VARCHAR(12) NOT NULL UNIQUE,
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    route_market_id INT NOT NULL REFERENCES route_markets(route_market_id),
    booking_date DATE NOT NULL REFERENCES calendar_dimension(calendar_date),
    departure_date DATE NOT NULL,
    cabin_class VARCHAR(24) NOT NULL CHECK (cabin_class IN ('Economy', 'Economy Plus', 'Business', 'First')),
    passengers INT NOT NULL CHECK (passengers BETWEEN 1 AND 9),
    trip_type VARCHAR(16) NOT NULL CHECK (trip_type IN ('Round-Trip', 'One-Way')),
    booking_channel VARCHAR(32) NOT NULL CHECK (
        booking_channel IN ('Airline Web', 'Mobile App', 'Corporate TMC', 'OTA', 'Call Center')
    ),
    booking_status VARCHAR(24) NOT NULL CHECK (booking_status IN ('completed', 'confirmed_upcoming', 'cancelled')),
    travel_completed BOOLEAN NOT NULL DEFAULT FALSE,
    attributed_campaign_id INT REFERENCES campaigns(campaign_id)
);

-- 11. booking_items
CREATE TABLE IF NOT EXISTS booking_items (
    booking_item_id BIGSERIAL PRIMARY KEY,
    booking_id BIGINT NOT NULL REFERENCES bookings(booking_id),
    item_type VARCHAR(32) NOT NULL CHECK (
        item_type IN ('Base Fare', 'Seat Selection', 'Baggage Fee', 'Lounge Access', 'Cabin Upgrade', 'Priority Boarding')
    ),
    quantity INT NOT NULL CHECK (quantity >= 1),
    unit_price NUMERIC(10, 2) NOT NULL CHECK (unit_price >= 0),
    item_revenue NUMERIC(12, 2) NOT NULL CHECK (item_revenue >= 0),
    estimated_variable_cost NUMERIC(12, 2) NOT NULL CHECK (estimated_variable_cost >= 0)
);

-- 12. ticket_revenue
CREATE TABLE IF NOT EXISTS ticket_revenue (
    ticket_revenue_id BIGSERIAL PRIMARY KEY,
    booking_id BIGINT NOT NULL UNIQUE REFERENCES bookings(booking_id),
    gross_fare_revenue NUMERIC(12, 2) NOT NULL CHECK (gross_fare_revenue >= 0),
    ancillary_revenue NUMERIC(12, 2) NOT NULL CHECK (ancillary_revenue >= 0),
    gross_total_revenue NUMERIC(12, 2) NOT NULL CHECK (gross_total_revenue >= 0),
    discount_amount NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    net_ticket_revenue NUMERIC(12, 2) NOT NULL CHECK (net_ticket_revenue >= 0),
    estimated_variable_cost NUMERIC(12, 2) NOT NULL CHECK (estimated_variable_cost >= 0),
    taxes_and_fees NUMERIC(12, 2) NOT NULL CHECK (taxes_and_fees >= 0),
    contribution_before_promo NUMERIC(12, 2) NOT NULL
);

-- 13. discount_transactions
CREATE TABLE IF NOT EXISTS discount_transactions (
    discount_tx_id BIGSERIAL PRIMARY KEY,
    booking_id BIGINT NOT NULL REFERENCES bookings(booking_id),
    campaign_id INT NOT NULL REFERENCES campaigns(campaign_id),
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    promo_code VARCHAR(32) NOT NULL,
    discount_type VARCHAR(32) NOT NULL CHECK (
        discount_type IN ('Percentage Off', 'Fixed Dollar Off', 'Companion Fare', 'Cabin Upgrade Discount')
    ),
    discount_pct_applied NUMERIC(5, 2) NOT NULL CHECK (discount_pct_applied >= 0),
    discount_amount NUMERIC(12, 2) NOT NULL CHECK (discount_amount >= 0),
    applied_at TIMESTAMPTZ NOT NULL
);

-- 14. loyalty_rewards
CREATE TABLE IF NOT EXISTS loyalty_rewards (
    reward_id BIGSERIAL PRIMARY KEY,
    booking_id BIGINT NOT NULL REFERENCES bookings(booking_id),
    campaign_id INT REFERENCES campaigns(campaign_id),
    customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
    reward_type VARCHAR(32) NOT NULL CHECK (
        reward_type IN ('Base Miles', 'Promotional Bonus Miles', 'Tier Status Accelerator', 'Reactivation Bonus')
    ),
    miles_awarded INT NOT NULL CHECK (miles_awarded >= 0),
    cost_per_mile NUMERIC(8, 5) NOT NULL CHECK (cost_per_mile >= 0),
    reward_liability_cost NUMERIC(12, 2) NOT NULL CHECK (reward_liability_cost >= 0),
    awarded_at TIMESTAMPTZ NOT NULL
);

-- 15. marketing_costs
CREATE TABLE IF NOT EXISTS marketing_costs (
    cost_id BIGSERIAL PRIMARY KEY,
    campaign_id INT NOT NULL REFERENCES campaigns(campaign_id),
    channel_id INT NOT NULL REFERENCES campaign_channels(channel_id),
    cost_date DATE NOT NULL REFERENCES calendar_dimension(calendar_date),
    cost_category VARCHAR(32) NOT NULL CHECK (
        cost_category IN ('Media Spend', 'Creative & Production', 'Agency & Operations', 'Channel Delivery Fee', 'Partner Co-Op')
    ),
    amount_usd NUMERIC(12, 2) NOT NULL CHECK (amount_usd >= 0)
);

-- ============================================================================
-- Analytical Metadata & Persisted Reproducible Computation Tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS experiment_results_store (
    campaign_id INT PRIMARY KEY REFERENCES campaigns(campaign_id),
    experiment_type VARCHAR(24) NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    methodology_version VARCHAR(32) NOT NULL DEFAULT 'itt-v1.0',
    n_treatment INT NOT NULL,
    n_control INT NOT NULL,
    reached_treatment INT NOT NULL,
    exposure_compliance_rate NUMERIC(6, 4) NOT NULL,
    srm_chi2 NUMERIC(12, 4),
    srm_p_value DOUBLE PRECISION,
    srm_passed BOOLEAN,
    max_covariate_smd NUMERIC(8, 4),
    covariate_balance_json JSONB NOT NULL,
    conversion_control NUMERIC(8, 6) NOT NULL,
    conversion_treatment NUMERIC(8, 6) NOT NULL,
    conversion_lift_abs NUMERIC(8, 6) NOT NULL,
    conversion_lift_rel NUMERIC(10, 4),
    conversion_z_stat NUMERIC(10, 4),
    conversion_p_value DOUBLE PRECISION,
    conversion_chi2_stat NUMERIC(10, 4),
    conversion_chi2_p_value DOUBLE PRECISION,
    conversion_ci_low NUMERIC(8, 6),
    conversion_ci_high NUMERIC(8, 6),
    conversion_power NUMERIC(6, 4),
    booking_freq_control NUMERIC(10, 6) NOT NULL,
    booking_freq_treatment NUMERIC(10, 6) NOT NULL,
    booking_freq_p_value DOUBLE PRECISION,
    booking_freq_ci_low NUMERIC(10, 6),
    booking_freq_ci_high NUMERIC(10, 6),
    rev_per_cust_control NUMERIC(12, 4) NOT NULL,
    rev_per_cust_treatment NUMERIC(12, 4) NOT NULL,
    rev_per_cust_p_value DOUBLE PRECISION,
    rev_per_cust_ci_low NUMERIC(12, 4),
    rev_per_cust_ci_high NUMERIC(12, 4),
    abv_control NUMERIC(12, 4),
    abv_treatment NUMERIC(12, 4),
    abv_p_value DOUBLE PRECISION,
    contrib_per_cust_control NUMERIC(12, 4) NOT NULL,
    contrib_per_cust_treatment NUMERIC(12, 4) NOT NULL,
    contrib_per_cust_p_value DOUBLE PRECISION,
    contrib_per_cust_ci_low NUMERIC(12, 4),
    contrib_per_cust_ci_high NUMERIC(12, 4),
    incremental_bookings NUMERIC(12, 2),
    incremental_revenue NUMERIC(14, 2),
    incremental_contribution NUMERIC(14, 2),
    marketing_spend NUMERIC(14, 2) NOT NULL,
    cost_per_incremental_booking NUMERIC(12, 2),
    ipw_conversion_lift_abs NUMERIC(8, 6),
    ipw_contrib_lift_per_cust NUMERIC(12, 4),
    is_statistically_significant BOOLEAN NOT NULL,
    recommendation_status VARCHAR(32) NOT NULL,
    metrics_detail_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS ml_model_runs (
    run_id SERIAL PRIMARY KEY,
    run_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_name VARCHAR(64) NOT NULL,
    model_role VARCHAR(32) NOT NULL CHECK (model_role IN ('naive_baseline', 'linear_baseline', 'advanced_gbdt', 'causal_uplift_tlearner')),
    train_period VARCHAR(64) NOT NULL,
    val_period VARCHAR(64) NOT NULL,
    test_period VARCHAR(64) NOT NULL,
    n_train INT NOT NULL,
    n_val INT NOT NULL,
    n_test INT NOT NULL,
    roc_auc DOUBLE PRECISION,
    roc_auc_ci_low DOUBLE PRECISION,
    roc_auc_ci_high DOUBLE PRECISION,
    pr_auc DOUBLE PRECISION,
    pr_auc_ci_low DOUBLE PRECISION,
    pr_auc_ci_high DOUBLE PRECISION,
    brier_score DOUBLE PRECISION,
    log_loss_val DOUBLE PRECISION,
    f1_score_val DOUBLE PRECISION,
    precision_top_20 DOUBLE PRECISION,
    lift_top_decile DOUBLE PRECISION,
    qini_auc DOUBLE PRECISION,
    training_seconds DOUBLE PRECISION,
    confusion_matrix_json JSONB,
    calibration_json JSONB,
    feature_importance_json JSONB,
    slice_metrics_json JSONB,
    uplift_deciles_json JSONB,
    limitations_json JSONB
);

CREATE TABLE IF NOT EXISTS customer_propensity_scores (
    customer_id BIGINT PRIMARY KEY REFERENCES customers(customer_id),
    scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    baseline_booking_prob DOUBLE PRECISION NOT NULL,
    promo_booking_prob DOUBLE PRECISION NOT NULL,
    predicted_uplift DOUBLE PRECISION NOT NULL,
    discount_uplift_score DOUBLE PRECISION NOT NULL,
    miles_uplift_score DOUBLE PRECISION NOT NULL,
    uplift_decile INT NOT NULL CHECK (uplift_decile BETWEEN 1 AND 10),
    response_archetype VARCHAR(48) NOT NULL,
    recommended_incentive VARCHAR(32) NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_metadata (
    meta_key VARCHAR(64) PRIMARY KEY,
    meta_value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
