# CampaignLift — Airline Marketing Promotions & Incremental Revenue Analytics Platform

**CampaignLift** is an enterprise airline commercial analytics platform built for **Meridian Air** (a fictional international carrier) to evaluate promotional campaigns, separate true causal incrementality from last-touch attribution, quantify discount margin erosion and baseline cannibalization, model customer response uplift, and support evidence-based marketing budget allocation.

> **Synthetic Data Disclosure**: All customer profiles, flight bookings, promotional campaigns, randomized experiments, and financial records in this platform are **synthetic and simulated** (deterministic seed `20260401`). No campaign lift or financial outcome is hard-coded; every metric, hypothesis test, ML evaluation, and exported report is computed directly from the PostgreSQL relational dataset.

---

## Architecture

| Layer | Technology | Purpose |
|---|---|---|
| **Database** | PostgreSQL 16 (`5448:5432`) | 15 core relational airline commercial tables + 3 persisted analytics metadata tables + composite B-tree analytical indexes + reusable commercial summary views |
| **Analytics & ML** | Python 3.12 · Pandas · NumPy · SciPy · Statsmodels · Scikit-learn | Reproducible vectorized data generator (`COPY` loader), Intention-to-Treat statistical engine, observational IPW sensitivity diagnostics, and chronological leakage-free ML + T-Learner uplift pipeline |
| **Backend API** | FastAPI · Psycopg 3 Pool · Pydantic v2 (`8048:8000`) | Validated REST API, live SQL Analytics runner with `EXPLAIN (ANALYZE)`, ReportLab PDF and OpenPyXL Excel report/table exporters |
| **Frontend UI** | Next.js 15 (App Router) · TypeScript · Tailwind CSS · Plotly (`3048:3000`) | 9 distinct enterprise commercial analytics views with global cross-filtering, drill-down drawers, interactive simulators, and export workflows |

---

## Quickstart (Docker Compose)

```bash
# 1. Start PostgreSQL and build/start FastAPI + Next.js
docker compose up -d --build

# 2. Run idempotent migrations, synthetic data generation, ITT experiment suite,
#    leakage-free ML pipeline, and mathematical integrity verification:
docker compose run --rm backend python -m analytics.bootstrap

# 3. Run automated statistical, API, filter, and export consistency tests:
docker compose exec -T backend pytest -v
```

- **Web Application**: http://localhost:3048
- **FastAPI OpenAPI Docs**: http://localhost:8048/docs
- **PostgreSQL**: `localhost:5448` (`campaignlift` / `campaignlift_dev_pw`)

---

## Relational Data Model (PostgreSQL)

All 15 required core tables are defined in `database/migrations/001_initial_schema.sql` with composite indexes and views in `database/migrations/002_indexes_and_views.sql`:

1. `customers` (52,000 rows — observable CRM attributes only; zero latent truth leakage)
2. `customer_segments` (6 commercial behavioral segments)
3. `campaigns` (108 campaigns across 8 airline promotion types: 72 RCTs + 36 Observational)
4. `campaign_channels` (8 marketing channels with cost/deliverability profiles)
5. `campaign_assignments` (248,970 rows with contact-frequency window exclusivity)
6. `campaign_exposures` (165,591 rows — strictly zero control-group exposures; models assigned vs. reached gap)
7. `bookings` (122,794 rows — campaign-window bookings for both T & C plus organic background bookings)
8. `booking_items` (235,933 fare and ancillary line items)
9. `ticket_revenue` (122,794 booking P&L records with exact accounting identities)
10. `discount_transactions` (10,054 promotional fare discount redemptions)
11. `loyalty_rewards` (121,660 base & promotional bonus miles liability transactions)
12. `route_markets` (36 O&D route markets across 5 regions & 3 haul types)
13. `marketing_costs` (432 granular spend line items across media, creative, delivery, agency)
14. `customer_responses` (65,314 engagement events preserving strict funnel monotonicity)
15. `calendar_dimension` (1,096 calendar days spanning 2024–2026 with airline seasonality)

Plus persisted analytical tables: `experiment_results_store`, `ml_model_runs`, `customer_propensity_scores`, and `dataset_metadata`.

---

## Analytical Methodology

### 1. Causal Experimentation (Intention-to-Treat)
- **RCTs (72 campaigns)**: Analyzed strictly on assigned groups (**Intention-to-Treat**) across `[start_date, end_date + booking_window_days]` regardless of exposure compliance or last-touch attribution.
  - **Conversion Rate**: Two-proportion z-test (`statsmodels`) + Pearson chi-square test (`scipy`) + Wald 95% CI + Cohen's $h$ achieved power.
  - **Booking Frequency, Net Revenue/Customer, Contribution Margin/Customer**: Welch's two-sample t-test (`equal_var=False`) + Welch-Satterthwaite 95% CI + Cohen's $d$ achieved power.
  - **Average Booking Value (Bookers Only)**: Welch's t-test explicitly flagged as conditional on post-treatment booking selection.
  - **Integrity Checks**: Chi-square Sample Ratio Mismatch (SRM, threshold $p \ge 0.001$) and pre-period covariate Standardized Mean Differences ($|\text{SMD}| < 0.10$).
- **Observational Campaigns (36 campaigns)**: Non-random targeting creates realistic pre-period selection bias ($|\text{SMD}| > 1.0$). Causal incremental totals are explicitly withheld (`NULL` / `Non-Causal`); an observable-covariate IPW sensitivity check is shown strictly as a non-causal bound.

### 2. Promotion Economics & Cannibalization
- `Contribution Before Promotion = Gross Booking Revenue - Estimated Variable Costs`
- `Contribution After Promotion = Gross Revenue - Fare Discounts - Variable Costs - Bonus Miles Liability - Media & Promo Spend`
- `Incremental Contribution (RCT) = (Mean Net Contrib_T - Mean Net Contrib_C) * N_T - Media & Promo Spend`
- `Deadweight Baseline Subsidy`: Quantifies fare discounts and bonus miles absorbed by organic customers who would have booked without an offer.

### 3. Leakage-Free Predictive & Causal Uplift Modeling
- Strict chronological split by campaign start date (`Train: 2024-01..2025-05`, `Val: 2025-06..2025-11`, `Test: 2025-12..2026-08`).
- Strictly pre-campaign observable CRM and offer features only; `ColumnTransformer` (`StandardScaler`, `OrdinalEncoder`, `OneHotEncoder`) fitted on training fold exclusively.
- Evaluates **Naive Base-Rate**, **Regularized Logistic Regression (Baseline)**, **HistGradientBoostingClassifier (Advanced)**, and a **Causal T-Learner Uplift** model (with bootstrap 95% CIs, calibration curves, confusion matrices, permutation feature importance, segment slice metrics, and out-of-time uplift deciles / Qini gain).

---

## Application Pages

1. **Executive Overview** (`/`) — Causal KPI strip, Attribution vs. Causality reality check, monthly spend/contribution trends, campaign type bridge, efficiency scatter, decision queue, and cross-filterable channel/segment scorecards.
2. **Campaign Performance** (`/campaigns`) — Searchable, sortable master ledger, route market breakdown, slide-over campaign detail inspector, and filtered CSV/Excel downloads.
3. **Campaign Funnel** (`/funnel`) — Monotonic 6-stage funnel (`Eligible → Assigned → Reached → Engaged → Booked → Completed Travel`), assigned-vs-reached compliance gap, RCT Treatment vs. Control progression, and channel/segment drop-off diagnostics.
4. **Experimentation Lab** (`/experiments`) — RCT ITT workbench, SRM & SMD balance diagnostics, HTE forest plots, observational selection-bias audits, and interactive Power & Sample-Size Calculator.
5. **Promotion Economics** (`/economics`) — Portfolio P&L waterfall, Gross Revenue vs. Incremental Profit scatter, deadweight baseline subsidy ledger, and documented accounting formulas.
6. **Customer Response** (`/customers`) — 6 behavioral response archetypes, Fare Discount vs. Bonus Miles segment elasticity, chronological ML comparison workbench, T-Learner uplift deciles, and scored customer cohort explorer.
7. **Campaign Comparison** (`/compare`) — 2-to-5 campaign head-to-head comparison matrix, spend/return bars, segment lift heatmap, and route overlap table.
8. **Budget Simulator** (`/simulator`) — Empirical elasticity & concave diminishing-returns simulator across budget scaling, discount depth, bonus miles, audience suppression, route targeting, and channel mix reallocation, with explicit uncertainty bands and assumptions.
9. **Reports & SQL Analytics** (`/reports`) — Executive Campaign Report preview + downloadable PDF & formatted multi-sheet Excel (exact same computed metrics as the dashboard), live read-only SQL Analytics Library (8 production queries with `EXPLAIN ANALYZE` and CSV export), and Data Lineage & Experiment Audit.
