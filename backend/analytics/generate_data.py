"""
CampaignLift Reproducible Synthetic Airline Marketing Dataset Generator.

Generates a statistically grounded, relational PostgreSQL dataset for Meridian Air
(fictional international carrier) with:
- 52,000+ customers across 6 behavioral segments
- 36 realistic O&D route markets across 5 global regions
- 8 marketing channels with distinct reach/cost dynamics
- 1,096 calendar dates (2024-01-01 to 2026-12-31)
- 108 promotional campaigns (72 Randomized Controlled Trials + 36 Observational)
- 220,000+ campaign assignments with strict contact-frequency exclusivity
- 145,000+ campaign exposures (reached vs. assigned gap)
- 125,000+ bookings (campaign-window + organic background)
- Full booking items, ticket revenue, discount transactions, loyalty rewards,
  marketing costs, and customer responses.

All data and experiments are SYNTHETIC and SIMULATED.
No campaign lift or financial outcome is hardcoded; every analytical metric
emerges from individual-level behavioral simulation and is computed directly
from PostgreSQL tables.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import psycopg

from app.config import settings
from analytics.migrate import run_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("campaignlift.generator")


SEGMENTS = [
    (1, "CORP", "Corporate Road Warriors", "High-frequency business travelers flying hub-to-hub routes on corporate accounts; inelastic to fare discounts with high baseline booking propensity.", "Premium", 11.4, 9, "low_promo_sensitivity"),
    (2, "FLEIS", "Frequent Leisure Flyers", "Repeat vacation and VFR travelers booking 3-5 trips annually; responsive to both seasonal offers and loyalty miles.", "Core-High", 4.2, 34, "bonus_miles"),
    (3, "DEAL", "Price-Sensitive Deal Seekers", "Highly price-elastic leisure travelers who rarely book at undiscounted fares but respond strongly to percentage fare sales.", "Value", 1.8, 42, "fare_discount"),
    (4, "MILES", "Loyalty Miles Maximizers", "Co-brand cardholders and status-seeking members motivated primarily by bonus miles and tier accelerators rather than cash discounts.", "Core-High", 5.1, 28, "bonus_miles"),
    (5, "LAPSED", "Lapsed Occasional Travelers", "Infrequent flyers with no recent trip activity; very low organic baseline rate but strong relative response to reactivation offers.", "Recovery", 0.7, 38, "fare_discount"),
    (6, "PREM", "Premium Cabin Enthusiasts", "Affluent leisure and small-business travelers choosing Business/First cabins on long-haul routes; respond selectively to cabin upgrades.", "Premium", 4.6, 45, "cabin_upgrade"),
]

CHANNELS = [
    (1, "EMAIL", "Email", "Fixed+CPM", 0.045, 0.84, 0.21),
    (2, "PUSH", "Mobile Push", "Fixed+CPM", 0.032, 0.79, 0.25),
    (3, "INAPP", "In-App Offer", "CPM", 0.055, 0.74, 0.32),
    (4, "LOYALTY_WEB", "Loyalty Portal", "Fixed+CPM", 0.068, 0.71, 0.35),
    (5, "PAID_SEARCH", "Paid Search", "CPC", 1.850, 0.89, 0.27),
    (6, "PAID_SOCIAL", "Paid Social", "CPM", 0.980, 0.82, 0.14),
    (7, "DIRECT_MAIL", "Direct Mail", "Per-Piece", 2.450, 0.93, 0.16),
    (8, "OTA_PARTNER", "OTA Partner", "CPC", 1.380, 0.77, 0.19),
]

ROUTE_MARKETS = [
    # Domestic Hub-to-Hub
    (1, "ORD-SFO", "ORD", "SFO", "Domestic Hub-to-Hub", "Medium-Haul", 1846, 385.0, 128.0, 0.84, "Business-Heavy"),
    (2, "EWR-LAX", "EWR", "LAX", "Domestic Hub-to-Hub", "Medium-Haul", 2454, 445.0, 148.0, 0.86, "Year-Round"),
    (3, "ORD-EWR", "ORD", "EWR", "Domestic Hub-to-Hub", "Short-Haul", 719, 275.0, 88.0, 0.85, "Business-Heavy"),
    (4, "DEN-SFO", "DEN", "SFO", "Domestic Hub-to-Hub", "Short-Haul", 967, 260.0, 86.0, 0.81, "Year-Round"),
    (5, "IAH-ORD", "IAH", "ORD", "Domestic Hub-to-Hub", "Short-Haul", 925, 268.0, 85.0, 0.79, "Business-Heavy"),
    (6, "BOS-SFO", "BOS", "SFO", "Domestic Hub-to-Hub", "Medium-Haul", 2704, 430.0, 145.0, 0.82, "Year-Round"),
    (7, "EWR-DEN", "EWR", "DEN", "Domestic Hub-to-Hub", "Medium-Haul", 1605, 340.0, 114.0, 0.77, "Winter-Summer"),
    (8, "SEA-ORD", "SEA", "ORD", "Domestic Hub-to-Hub", "Medium-Haul", 1721, 355.0, 118.0, 0.76, "Summer-Peak"),
    (9, "LAX-IAH", "LAX", "IAH", "Domestic Hub-to-Hub", "Medium-Haul", 1379, 310.0, 104.0, 0.78, "Year-Round"),
    (10, "ORD-BOS", "ORD", "BOS", "Domestic Hub-to-Hub", "Short-Haul", 867, 265.0, 84.0, 0.80, "Business-Heavy"),
    (11, "EWR-IAH", "EWR", "IAH", "Domestic Hub-to-Hub", "Medium-Haul", 1400, 325.0, 108.0, 0.81, "Business-Heavy"),
    (12, "DEN-SEA", "DEN", "SEA", "Domestic Hub-to-Hub", "Short-Haul", 1024, 248.0, 82.0, 0.73, "Summer-Peak"),
    # Domestic Leisure
    (13, "ORD-MIA", "ORD", "MIA", "Domestic Leisure", "Short-Haul", 1197, 295.0, 94.0, 0.78, "Winter-Peak"),
    (14, "EWR-MCO", "EWR", "MCO", "Domestic Leisure", "Short-Haul", 937, 245.0, 80.0, 0.82, "Holiday-Peak"),
    (15, "DEN-LAS", "DEN", "LAS", "Domestic Leisure", "Short-Haul", 628, 198.0, 68.0, 0.71, "Year-Round"),
    (16, "SFO-HNL", "SFO", "HNL", "Domestic Leisure", "Medium-Haul", 2398, 520.0, 168.0, 0.83, "Summer-Winter"),
    (17, "IAH-PHX", "IAH", "PHX", "Domestic Leisure", "Short-Haul", 1009, 232.0, 76.0, 0.69, "Winter-Peak"),
    (18, "BOS-FLL", "BOS", "FLL", "Domestic Leisure", "Short-Haul", 1237, 268.0, 86.0, 0.75, "Winter-Peak"),
    (19, "ORD-LAS", "ORD", "LAS", "Domestic Leisure", "Medium-Haul", 1514, 272.0, 92.0, 0.74, "Year-Round"),
    (20, "LAX-HNL", "LAX", "HNL", "Domestic Leisure", "Medium-Haul", 2556, 495.0, 162.0, 0.84, "Summer-Winter"),
    # Transatlantic
    (21, "EWR-LHR", "EWR", "LHR", "Transatlantic", "Long-Haul", 3465, 980.0, 315.0, 0.85, "Summer-Peak"),
    (22, "ORD-LHR", "ORD", "LHR", "Transatlantic", "Long-Haul", 3953, 1020.0, 330.0, 0.82, "Summer-Peak"),
    (23, "EWR-FRA", "EWR", "FRA", "Transatlantic", "Long-Haul", 3862, 940.0, 310.0, 0.79, "Summer-Peak"),
    (24, "SFO-FRA", "SFO", "FRA", "Transatlantic", "Long-Haul", 5699, 1180.0, 385.0, 0.76, "Summer-Peak"),
    (25, "BOS-DUB", "BOS", "DUB", "Transatlantic", "Long-Haul", 2993, 790.0, 262.0, 0.72, "Summer-Peak"),
    (26, "IAH-AMS", "IAH", "AMS", "Transatlantic", "Long-Haul", 5012, 1060.0, 345.0, 0.74, "Shoulder-Soft"),
    (27, "EWR-CDG", "EWR", "CDG", "Transatlantic", "Long-Haul", 3635, 965.0, 318.0, 0.81, "Summer-Peak"),
    (28, "ORD-FCO", "ORD", "FCO", "Transatlantic", "Long-Haul", 4824, 1090.0, 352.0, 0.71, "Summer-Peak"),
    # Transpacific
    (29, "SFO-NRT", "SFO", "NRT", "Transpacific", "Long-Haul", 5124, 1290.0, 410.0, 0.80, "Spring-Fall"),
    (30, "LAX-HND", "LAX", "HND", "Transpacific", "Long-Haul", 5485, 1340.0, 425.0, 0.82, "Spring-Fall"),
    (31, "SFO-SIN", "SFO", "SIN", "Transpacific", "Long-Haul", 8446, 1520.0, 485.0, 0.75, "Year-Round"),
    (32, "ORD-NRT", "ORD", "NRT", "Transpacific", "Long-Haul", 6274, 1380.0, 440.0, 0.73, "Spring-Fall"),
    # Latin America & Caribbean
    (33, "IAH-CUN", "IAH", "CUN", "Latin America & Caribbean", "Short-Haul", 810, 335.0, 102.0, 0.80, "Winter-Peak"),
    (34, "EWR-CUN", "EWR", "CUN", "Latin America & Caribbean", "Medium-Haul", 1554, 435.0, 134.0, 0.79, "Winter-Peak"),
    (35, "MIA-BOG", "MIA", "BOG", "Latin America & Caribbean", "Medium-Haul", 1510, 465.0, 146.0, 0.70, "Holiday-Peak"),
    (36, "IAH-MEX", "IAH", "MEX", "Latin America & Caribbean", "Short-Haul", 764, 320.0, 98.0, 0.77, "Year-Round"),
]

HOME_AIRPORTS = [
    ("ORD", "Midwest"), ("EWR", "Northeast"), ("SFO", "West Coast"), ("IAH", "South Central"),
    ("DEN", "Mountain West"), ("LAX", "West Coast"), ("BOS", "Northeast"), ("MIA", "Southeast"),
    ("SEA", "Pacific Northwest"), ("LHR", "Europe"), ("FRA", "Europe"), ("NRT", "Asia-Pacific"),
]

CAMPAIGN_TYPES = [
    "Promotional Fare",
    "Discounted Ticket",
    "Bonus Loyalty Miles",
    "Seasonal Travel Offer",
    "Route-Specific Offer",
    "Customer Reactivation",
    "Premium Cabin Promotion",
    "Targeted Customer Offer",
]


def copy_rows(cur: psycopg.Cursor, table: str, columns: list[str], rows: list[tuple[Any, ...]]) -> None:
    """Fast bulk COPY loader via in-memory TSV/CSV buffer."""
    if not rows:
        return
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    for row in rows:
        writer.writerow(["\\N" if v is None else ("t" if v is True else ("f" if v is False else v)) for v in row])
    buf.seek(0)
    col_sql = ", ".join(columns)
    with cur.copy(f"COPY {table} ({col_sql}) FROM STDIN WITH (FORMAT text, NULL '\\N')") as copy:
        copy.write(buf.getvalue())


def get_travel_season(d: date) -> tuple[str, bool]:
    m, day = d.month, d.day
    is_holiday = (
        (m == 11 and 20 <= day <= 30)
        or (m == 12 and day >= 18)
        or (m == 1 and day <= 4)
        or (m == 7 and 1 <= day <= 7)
        or (m == 3 and 15 <= day <= 28)
    )
    if is_holiday:
        return "Holiday Peak", True
    if m in (6, 7, 8):
        return "Summer Peak", False
    if m in (1, 2):
        return "Winter Low", False
    if m in (3, 4, 5):
        return "Spring Shoulder", False
    return "Fall Shoulder", False


def build_calendar() -> list[tuple[Any, ...]]:
    start = date(2024, 1, 1)
    end = date(2026, 12, 31)
    rows = []
    curr = start
    while curr <= end:
        season, is_hol = get_travel_season(curr)
        q = (curr.month - 1) // 3 + 1
        dow = curr.weekday()  # 0=Mon..6=Sun
        rows.append((
            curr.isoformat(),
            curr.year,
            q,
            curr.month,
            curr.strftime("%B"),
            int(curr.strftime("%W")),
            dow,
            curr.strftime("%A"),
            dow >= 5,
            is_hol,
            season,
            f"FY{curr.year}-Q{q}",
        ))
        curr += timedelta(days=1)
    return rows


def generate_customers(rng: np.random.Generator, n_customers: int = 52000) -> tuple[list[tuple[Any, ...]], dict[str, np.ndarray]]:
    seg_probs = np.array([0.12, 0.24, 0.23, 0.16, 0.17, 0.08])
    seg_ids = rng.choice(np.arange(1, 7), size=n_customers, p=seg_probs)

    airport_probs = np.array([0.16, 0.16, 0.14, 0.11, 0.10, 0.09, 0.06, 0.05, 0.05, 0.04, 0.02, 0.02])
    airport_idx = rng.choice(len(HOME_AIRPORTS), size=n_customers, p=airport_probs)

    tiers = np.empty(n_customers, dtype=object)
    trips = np.zeros(n_customers, dtype=np.int32)
    spend = np.zeros(n_customers, dtype=np.float64)
    miles = np.zeros(n_customers, dtype=np.int32)
    age_bands = np.empty(n_customers, dtype=object)
    tenure = np.zeros(n_customers, dtype=np.int32)
    email_opt = np.zeros(n_customers, dtype=bool)
    push_opt = np.zeros(n_customers, dtype=bool)
    app_act = np.zeros(n_customers, dtype=bool)

    tier_choices = ["None", "Silver", "Gold", "Platinum", "Executive"]
    age_choices = ["18-29", "30-44", "45-59", "60+"]

    # Segment-specific realistic CRM attribute distributions
    seg_params = {
        1: dict(tier_p=[0.04, 0.16, 0.30, 0.32, 0.18], trips_lam=10.8, spend_per_trip=690, miles_base=115000, age_p=[0.08, 0.42, 0.40, 0.10], email=0.88, push=0.82, app=0.84, ten_mu=62),
        2: dict(tier_p=[0.18, 0.36, 0.28, 0.14, 0.04], trips_lam=4.1, spend_per_trip=440, miles_base=46000, age_p=[0.18, 0.34, 0.28, 0.20], email=0.90, push=0.76, app=0.72, ten_mu=46),
        3: dict(tier_p=[0.54, 0.31, 0.11, 0.03, 0.01], trips_lam=1.8, spend_per_trip=275, miles_base=11000, age_p=[0.34, 0.33, 0.20, 0.13], email=0.86, push=0.69, app=0.58, ten_mu=29),
        4: dict(tier_p=[0.05, 0.21, 0.36, 0.28, 0.10], trips_lam=5.0, spend_per_trip=490, miles_base=98000, age_p=[0.14, 0.39, 0.32, 0.15], email=0.94, push=0.84, app=0.85, ten_mu=54),
        5: dict(tier_p=[0.62, 0.27, 0.08, 0.02, 0.01], trips_lam=0.55, spend_per_trip=310, miles_base=7500, age_p=[0.24, 0.32, 0.25, 0.19], email=0.76, push=0.48, app=0.31, ten_mu=41),
        6: dict(tier_p=[0.06, 0.14, 0.26, 0.31, 0.23], trips_lam=4.5, spend_per_trip=1350, miles_base=142000, age_p=[0.06, 0.27, 0.41, 0.26], email=0.91, push=0.75, app=0.78, ten_mu=66),
    }

    for seg_id, p in seg_params.items():
        mask = seg_ids == seg_id
        cnt = int(mask.sum())
        tiers[mask] = rng.choice(tier_choices, size=cnt, p=p["tier_p"])
        t_cnt = rng.poisson(p["trips_lam"], size=cnt)
        trips[mask] = np.clip(t_cnt, 0, 32)
        noise = rng.lognormal(mean=0.0, sigma=0.30, size=cnt)
        spend[mask] = np.round(np.maximum(0.0, trips[mask] * p["spend_per_trip"] * noise + rng.uniform(0, 120, size=cnt) * (trips[mask] == 0)), 2)
        miles[mask] = np.clip((rng.gamma(shape=2.2, scale=p["miles_base"] / 2.2, size=cnt)).astype(np.int32), 0, 850000)
        age_bands[mask] = rng.choice(age_choices, size=cnt, p=p["age_p"])
        tenure[mask] = np.clip(rng.normal(p["ten_mu"], 22, size=cnt).astype(np.int32), 3, 120)
        email_opt[mask] = rng.random(cnt) < p["email"]
        push_opt[mask] = rng.random(cnt) < p["push"]
        app_act[mask] = rng.random(cnt) < p["app"]

    ref_date = date(2024, 1, 1)
    rows: list[tuple[Any, ...]] = []
    for i in range(n_customers):
        cid = i + 1
        ap, reg = HOME_AIRPORTS[airport_idx[i]]
        signup = ref_date - timedelta(days=int(tenure[i]) * 30 + int(rng.integers(0, 28)))
        rows.append((
            cid,
            f"MA-{cid:06d}",
            int(seg_ids[i]),
            tiers[i],
            ap,
            reg,
            signup.isoformat(),
            int(tenure[i]),
            age_bands[i],
            int(trips[i]),
            float(spend[i]),
            int(miles[i]),
            bool(email_opt[i]),
            bool(push_opt[i]),
            bool(app_act[i]),
            True,
        ))

    arrays = {
        "customer_id": np.arange(1, n_customers + 1, dtype=np.int64),
        "segment_id": seg_ids,
        "loyalty_tier": tiers,
        "home_airport": np.array([HOME_AIRPORTS[idx][0] for idx in airport_idx]),
        "region": np.array([HOME_AIRPORTS[idx][1] for idx in airport_idx]),
        "tenure_months": tenure,
        "trips_12m": trips,
        "spend_12m": spend,
        "miles_balance": miles,
        "email_opt_in": email_opt,
        "push_opt_in": push_opt,
        "app_active": app_act,
    }
    return rows, arrays


def build_campaign_blueprints(rng: np.random.Generator) -> list[dict[str, Any]]:
    """Create 108 realistic airline promotional campaigns (72 RCT + 36 Observational)."""
    # Strategic archetypes spanning all 8 campaign types with realistic economics
    templates = [
        # (campaign_type, prefix, seg_choices, ch_choices, disc_range, miles_choices, route_specific_prob, hypothesis)
        ("Promotional Fare", "Spring/Fall Fare Sale", [3, 2, None], [1, 5, 6, 8], (10, 22), [0, 0, 500], 0.45,
         "Targeted promotional fares on off-peak schedules will stimulate incremental price-elastic demand with positive net contribution."),
        ("Discounted Ticket", "Percent-Off Ticket Promo", [3, 2, 1, None], [1, 2, 6, 8], (14, 28), [0], 0.35,
         "Flat percentage ticket discounts will raise booking conversion; test whether incremental margin offsets baseline fare dilution."),
        ("Bonus Loyalty Miles", "Bonus Miles Accelerator", [4, 2, 1, None], [1, 4, 3, 2], (0, 5), [2500, 4000, 6000, 8000, 10000], 0.30,
         "Awarding promotional bonus miles will lift bookings among loyalty members with lower contribution margin erosion than cash discounts."),
        ("Seasonal Travel Offer", "Seasonal Escape Offer", [2, 3, None], [1, 5, 6, 2], (8, 18), [0, 1500, 3000], 0.40,
         "Seasonal travel incentives ahead of shoulder/peak periods will pull forward bookings and lift load factor on leisure markets."),
        ("Route-Specific Offer", "Route Launch & Fill Promo", [2, 3, 4, None], [1, 5, 3, 8], (10, 20), [0, 2000, 5000], 1.00,
         "Route-specific incentives on lower-load-factor O&D markets will fill otherwise unsold seat capacity at high marginal contribution."),
        ("Customer Reactivation", "Win-Back Reactivation", [5], [1, 7, 2, 6], (12, 24), [0, 2500, 5000], 0.25,
         "Targeted win-back incentives for lapsed travelers will generate high relative incremental bookings with minimal organic cannibalization."),
        ("Premium Cabin Promotion", "Business & First Cabin Offer", [6, 1, 4], [4, 1, 7, 3], (8, 16), [0, 5000, 10000], 0.60,
         "Selective premium cabin fare/miles incentives on long-haul routes will drive incremental high-yield cabin bookings."),
        ("Targeted Customer Offer", "Personalized CRM Offer", [2, 3, 4, 5, 6], [3, 2, 1, 4], (6, 16), [0, 2000, 4000], 0.35,
         "Segment-matched personalized offers in owned channels will deliver lower cost per incremental booking than broad media campaigns."),
    ]

    season_labels = {
        1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Late Spring",
        6: "Summer", 7: "Mid-Summer", 8: "Late Summer", 9: "Early Fall",
        10: "Autumn", 11: "Holiday", 12: "Year-End",
    }

    # Build 108 campaigns evenly spread across 2024-01-12 to 2026-08-25 (108 slots ~ every 8.8 days)
    blueprints: list[dict[str, Any]] = []
    base_start = date(2024, 1, 12)
    route_lookup = {r[0]: r for r in ROUTE_MARKETS}
    seg_lookup = {s[0]: s[2] for s in SEGMENTS}
    ch_lookup = {c[0]: c[2] for c in CHANNELS}

    for idx in range(108):
        cid = idx + 1
        t = templates[idx % len(templates)]
        ctype, prefix, seg_choices, ch_choices, disc_rng, miles_choices, route_prob, hyp = t

        # 72 RCT (exact 2/3), 36 Observational (1/3) distributed across time & types
        is_rct = (idx % 3) != 2
        exp_type = "RCT" if is_rct else "Observational"

        # Chronological spacing across 2024-01 through 2026-08
        day_offset = int(idx * 8.85) + int(rng.integers(0, 5))
        s_date = base_start + timedelta(days=day_offset)
        duration = int(rng.choice([14, 18, 21, 28]))
        e_date = s_date + timedelta(days=duration)
        book_win = int(rng.choice([7, 10, 14]))

        # Select segment, channel, route
        seg_id = seg_choices[int(rng.integers(0, len(seg_choices)))]
        ch_id = int(ch_choices[int(rng.integers(0, len(ch_choices)))])

        route_id = None
        if rng.random() < route_prob:
            if ctype == "Premium Cabin Promotion":
                # Prefer Long-Haul markets
                route_id = int(rng.choice([21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32]))
            else:
                route_id = int(rng.integers(1, len(ROUTE_MARKETS) + 1))

        # Construct realistic commercial mix including deliberate high-discount margin-erosion cases
        if ctype == "Bonus Loyalty Miles":
            disc_pct = float(rng.choice([0.0, 0.0, 0.0, 5.0]))
            bonus_miles = int(rng.choice([3000, 5000, 7500, 10000]))
        elif ctype == "Discounted Ticket" and seg_id in (1, None) and idx % 2 == 1:
            # Realistic over-discounted broad or corporate campaign -> margin erosion stress test
            disc_pct = float(rng.choice([20.0, 24.0, 28.0]))
            bonus_miles = 0
        else:
            disc_pct = float(np.round(rng.uniform(disc_rng[0], disc_rng[1]), 1))
            bonus_miles = int(rng.choice(miles_choices))

        # Small handful of weak/inconclusive RCTs for realistic portfolio distribution
        is_weak_creative = is_rct and (idx % 13 == 4)
        if is_weak_creative:
            disc_pct = min(disc_pct, 6.0)
            bonus_miles = min(bonus_miles, 1000)

        split_target = float(rng.choice([0.50, 0.60, 0.70, 0.80])) if is_rct else 0.70
        # Target assignment size: ~2,000 - 3,100 per RCT, ~1,600 - 2,200 per Observational
        assign_size = int(rng.integers(2050, 3050)) if is_rct else int(rng.integers(1650, 2250))

        # Build crisp airline campaign name
        s_label = season_labels[s_date.month]
        r_tag = f" ({route_lookup[route_id][1]})" if route_id else ""
        seg_tag = seg_lookup[seg_id].split()[0] if seg_id else "Network"
        offer_tag = f"{int(round(disc_pct))}% Off" if disc_pct >= 5 else f"{bonus_miles:,} Bonus Miles"
        cname = f"{s_date.year} {s_label} {prefix}: {seg_tag} {offer_tag}{r_tag}"

        elig_desc = (
            f"Segment: {seg_lookup[seg_id] if seg_id else 'All Active Segments'}; "
            f"Channel: {ch_lookup[ch_id]}; "
            f"Market: {route_lookup[route_id][1] if route_id else 'Network-Wide'}; "
            f"Contact-capped (no overlapping active campaign window)."
        )

        # Planned budget scaled realistically to channel unit cost + fixed creative/ops
        ch_unit = CHANNELS[ch_id - 1][4]
        est_treated = assign_size * split_target
        fixed_prod = float(rng.uniform(4500, 14000)) if ch_id in (5, 6, 7, 8) else float(rng.uniform(1800, 5500))
        planned_budget = round(fixed_prod + est_treated * ch_unit * float(rng.uniform(1.15, 1.85)), 2)

        status = "Completed" if e_date + timedelta(days=book_win) <= date(2026, 9, 30) else "Active"

        blueprints.append({
            "campaign_id": cid,
            "campaign_code": f"CMP-{s_date.year}-{cid:03d}",
            "campaign_name": cname,
            "campaign_type": ctype,
            "experiment_type": exp_type,
            "primary_channel_id": ch_id,
            "target_segment_id": seg_id,
            "target_route_market_id": route_id,
            "start_date": s_date,
            "end_date": e_date,
            "booking_window_days": book_win,
            "discount_pct": disc_pct,
            "bonus_miles_offer": bonus_miles,
            "treatment_split_target": split_target if is_rct else None,
            "assign_size": assign_size,
            "planned_budget": planned_budget,
            "status": status,
            "hypothesis": hyp,
            "eligibility_criteria": elig_desc,
            "is_weak_creative": is_weak_creative,
        })

    return blueprints


def main() -> None:
    t0 = time.perf_counter()
    seed = settings.data_generation_seed
    rng = np.random.default_rng(seed)

    logger.info("Running SQL migrations before data generation...")
    run_migrations()

    logger.info("Generating dimension tables and 52,000 synthetic customers (seed=%s)...", seed)
    cal_rows = build_calendar()
    cust_rows, cust = generate_customers(rng, n_customers=52000)
    n_customers = len(cust_rows)
    blueprints = build_campaign_blueprints(rng)

    # Precompute customer baseline propensity drivers (from observable CRM features only)
    seg_base_rate = np.array([0.0, 0.165, 0.088, 0.032, 0.074, 0.015, 0.082])
    tier_mult_map = {"None": 0.78, "Silver": 0.96, "Gold": 1.12, "Platinum": 1.24, "Executive": 1.35}
    tier_mult = np.array([tier_mult_map[t] for t in cust["loyalty_tier"]], dtype=np.float64)
    trips_factor = 0.78 + 0.038 * np.minimum(cust["trips_12m"], 15)
    app_factor = np.where(cust["app_active"], 1.12, 0.94)
    # Individual unobserved stable noise (small, realistic)
    indiv_noise = rng.lognormal(0.0, 0.14, size=n_customers)
    cust_base_prop = np.clip(seg_base_rate[cust["segment_id"]] * tier_mult * trips_factor * app_factor * indiv_noise, 0.005, 0.42)

    # Segment elasticity profiles for structural treatment simulation
    # Columns: [0 unused, CORP, FLEIS, DEAL, MILES, LAPSED, PREM]
    seg_disc_sens = np.array([0.0, 0.004, 0.036, 0.058, 0.018, 0.044, 0.015])
    seg_miles_sens = np.array([0.0, 0.016, 0.032, 0.009, 0.056, 0.024, 0.028])
    seg_prem_sens = np.array([0.0, 0.022, 0.014, 0.004, 0.024, 0.006, 0.062])

    route_lookup = {r[0]: r for r in ROUTE_MARKETS}
    ch_lookup = {c[0]: c for c in CHANNELS}
    season_mult = {
        "Winter Low": 0.86,
        "Spring Shoulder": 0.98,
        "Summer Peak": 1.18,
        "Fall Shoulder": 0.95,
        "Holiday Peak": 1.24,
    }

    # Track occupied dates per customer so no customer is in two overlapping campaign windows
    # Use ordinal integer last_occupied_day per customer (campaigns are sorted chronologically!)
    blueprints.sort(key=lambda b: b["start_date"])
    last_window_end_ord = np.zeros(n_customers, dtype=np.int32)
    # Also store per-customer occupied intervals for organic booking collision avoidance
    cust_windows: dict[int, list[tuple[int, int]]] = {}

    campaign_rows: list[tuple[Any, ...]] = []
    assignment_rows: list[tuple[Any, ...]] = []
    exposure_rows: list[tuple[Any, ...]] = []
    response_rows: list[tuple[Any, ...]] = []
    booking_rows: list[tuple[Any, ...]] = []
    booking_item_rows: list[tuple[Any, ...]] = []
    ticket_rev_rows: list[tuple[Any, ...]] = []
    discount_tx_rows: list[tuple[Any, ...]] = []
    loyalty_rows: list[tuple[Any, ...]] = []
    cost_rows: list[tuple[Any, ...]] = []

    next_assign_id = 1
    next_exp_id = 1
    next_resp_id = 1
    next_book_id = 1
    next_item_id = 1
    next_rev_id = 1
    next_disc_id = 1
    next_rew_id = 1
    next_cost_id = 1

    # Route probability weights by segment
    all_route_ids = np.arange(1, len(ROUTE_MARKETS) + 1)
    hub_routes = np.arange(1, 13)
    leisure_routes = np.arange(13, 21)
    longhaul_routes = np.arange(21, 33)
    latam_routes = np.arange(33, 37)

    def pick_route_for_customer(seg_id: int, target_route: int | None) -> int:
        if target_route is not None and rng.random() < 0.74:
            return target_route
        if seg_id == 1:
            return int(rng.choice(hub_routes if rng.random() < 0.72 else longhaul_routes))
        if seg_id == 6:
            return int(rng.choice(longhaul_routes if rng.random() < 0.70 else hub_routes))
        if seg_id in (3, 5):
            r = rng.random()
            if r < 0.55:
                return int(rng.choice(leisure_routes))
            if r < 0.80:
                return int(rng.choice(hub_routes))
            return int(rng.choice(latam_routes))
        return int(rng.choice(all_route_ids))

    def append_booking_financials(
        booking_id: int,
        customer_id: int,
        seg_id: int,
        route_id: int,
        b_date: date,
        camp_id: int | None,
        camp_code: str | None,
        ctype: str | None,
        disc_pct_offer: float,
        bonus_miles_offer: int,
        apply_promo: bool,
        is_completed: bool,
        is_cancelled: bool,
    ) -> None:
        nonlocal next_item_id, next_rev_id, next_disc_id, next_rew_id
        route = route_lookup[route_id]
        base_fare = float(route[7])
        var_cost_pax = float(route[8])
        haul = route[5]

        # Cabin class selection realistic by segment & campaign type
        if ctype == "Premium Cabin Promotion" and apply_promo:
            cabin = str(rng.choice(["Economy Plus", "Business", "First"], p=[0.20, 0.62, 0.18]))
        elif seg_id == 6:
            cabin = str(rng.choice(["Economy Plus", "Business", "First"], p=[0.18, 0.60, 0.22]))
        elif seg_id == 1:
            cabin = str(rng.choice(["Economy", "Economy Plus", "Business"], p=[0.35, 0.35, 0.30]))
        elif seg_id == 4:
            cabin = str(rng.choice(["Economy", "Economy Plus", "Business"], p=[0.55, 0.33, 0.12]))
        else:
            cabin = str(rng.choice(["Economy", "Economy Plus", "Business"], p=[0.78, 0.19, 0.03]))

        cabin_fare_mult = {"Economy": 1.0, "Economy Plus": 1.28, "Business": 2.45, "First": 3.40}[cabin]
        cabin_cost_mult = {"Economy": 1.0, "Economy Plus": 1.12, "Business": 1.72, "First": 2.15}[cabin]

        pax = 1 if seg_id == 1 else int(rng.choice([1, 2, 3, 4], p=[0.54, 0.32, 0.09, 0.05]))
        trip_type = "Round-Trip" if rng.random() < 0.82 else "One-Way"
        trip_mult = 1.0 if trip_type == "Round-Trip" else 0.58

        season_name, _ = get_travel_season(b_date)
        fare_season_mult = {"Winter Low": 0.90, "Spring Shoulder": 0.99, "Summer Peak": 1.14, "Fall Shoulder": 0.97, "Holiday Peak": 1.22}[season_name]

        unit_fare = round(base_fare * cabin_fare_mult * trip_mult * fare_season_mult * float(rng.uniform(0.86, 1.18)), 2)
        gross_fare = round(unit_fare * pax, 2)
        base_var_cost = round(var_cost_pax * cabin_cost_mult * trip_mult * pax * float(rng.uniform(0.93, 1.07)), 2)

        # Booking item 1: Base Fare
        booking_item_rows.append((next_item_id, booking_id, "Base Fare", pax, unit_fare, gross_fare, base_var_cost))
        next_item_id += 1

        # Optional ancillary items (Seat Selection, Baggage, Lounge, Priority Boarding, Upgrade)
        anc_rev = 0.0
        anc_cost = 0.0
        if rng.random() < 0.52:
            seat_price = round(float(rng.uniform(24, 68)) * (1.4 if haul == "Long-Haul" else 1.0), 2)
            s_rev = round(seat_price * pax, 2)
            s_cost = round(s_rev * 0.08, 2)
            booking_item_rows.append((next_item_id, booking_id, "Seat Selection", pax, seat_price, s_rev, s_cost))
            next_item_id += 1
            anc_rev += s_rev
            anc_cost += s_cost
        if cabin == "Economy" and rng.random() < 0.44:
            bag_price = 40.0 if haul != "Long-Haul" else 65.0
            b_rev = round(bag_price * pax, 2)
            b_cost = round(9.5 * pax, 2)
            booking_item_rows.append((next_item_id, booking_id, "Baggage Fee", pax, bag_price, b_rev, b_cost))
            next_item_id += 1
            anc_rev += b_rev
            anc_cost += b_cost
        if cabin in ("Economy", "Economy Plus") and rng.random() < 0.14:
            pb_price = 28.0
            p_rev = round(pb_price * pax, 2)
            p_cost = round(2.5 * pax, 2)
            booking_item_rows.append((next_item_id, booking_id, "Priority Boarding", pax, pb_price, p_rev, p_cost))
            next_item_id += 1
            anc_rev += p_rev
            anc_cost += p_cost
        if seg_id in (1, 4, 6) and rng.random() < 0.12:
            lg_price = 59.0
            l_rev = round(lg_price * pax, 2)
            l_cost = round(18.0 * pax, 2)
            booking_item_rows.append((next_item_id, booking_id, "Lounge Access", pax, lg_price, l_rev, l_cost))
            next_item_id += 1
            anc_rev += l_rev
            anc_cost += l_cost

        gross_total = round(gross_fare + anc_rev, 2)
        total_var_cost = round(base_var_cost + anc_cost + gross_total * 0.028, 2)  # +2.8% payment/GDS variable cost

        disc_amt = 0.0
        if apply_promo and camp_id is not None and disc_pct_offer > 0:
            disc_amt = round(gross_fare * (disc_pct_offer / 100.0), 2)
            disc_type = "Cabin Upgrade Discount" if ctype == "Premium Cabin Promotion" else ("Percentage Off" if disc_pct_offer >= 10 else "Fixed Dollar Off")
            discount_tx_rows.append((
                next_disc_id,
                booking_id,
                camp_id,
                customer_id,
                f"MA{camp_code.replace('-', '')[-6:]}",
                disc_type,
                round(disc_pct_offer, 2),
                disc_amt,
                datetime(b_date.year, b_date.month, b_date.day, int(rng.integers(7, 22)), int(rng.integers(0, 60)), tzinfo=timezone.utc).isoformat(),
            ))
            next_disc_id += 1

        net_rev = round(max(0.0, gross_total - disc_amt), 2)
        taxes = round(net_rev * (0.14 if haul == "Long-Haul" else 0.115), 2)
        contrib_before_promo = round(gross_total - total_var_cost, 2)

        ticket_rev_rows.append((
            next_rev_id,
            booking_id,
            gross_fare,
            round(anc_rev, 2),
            gross_total,
            disc_amt,
            net_rev,
            total_var_cost,
            taxes,
            contrib_before_promo,
        ))
        next_rev_id += 1

        # Base miles (for non-cancelled bookings)
        if not is_cancelled:
            base_miles = int(round(net_rev * 5))
            cpm_base = 0.0082
            loyalty_rows.append((
                next_rew_id,
                booking_id,
                None,
                customer_id,
                "Base Miles",
                base_miles,
                cpm_base,
                round(base_miles * cpm_base, 2),
                datetime(b_date.year, b_date.month, b_date.day, 12, 0, tzinfo=timezone.utc).isoformat(),
            ))
            next_rew_id += 1

            # Promotional bonus miles when applicable
            if apply_promo and camp_id is not None and bonus_miles_offer > 0:
                cpm_promo = 0.0094  # slightly higher redemption liability on engaged promo miles
                rew_type = "Reactivation Bonus" if ctype == "Customer Reactivation" else (
                    "Tier Status Accelerator" if ctype == "Premium Cabin Promotion" else "Promotional Bonus Miles"
                )
                miles_tot = int(bonus_miles_offer * pax)
                loyalty_rows.append((
                    next_rew_id,
                    booking_id,
                    camp_id,
                    customer_id,
                    rew_type,
                    miles_tot,
                    cpm_promo,
                    round(miles_tot * cpm_promo, 2),
                    datetime(b_date.year, b_date.month, b_date.day, 14, 0, tzinfo=timezone.utc).isoformat(),
                ))
                next_rew_id += 1

        # Booking status & channel metadata
        dep_lead = int(rng.integers(10, 75))
        dep_date = b_date + timedelta(days=dep_lead)
        if seg_id == 1:
            b_ch = str(rng.choice(["Corporate TMC", "Airline Web", "Mobile App"], p=[0.52, 0.28, 0.20]))
        elif seg_id == 3:
            b_ch = str(rng.choice(["Airline Web", "OTA", "Mobile App"], p=[0.44, 0.36, 0.20]))
        else:
            b_ch = str(rng.choice(["Airline Web", "Mobile App", "OTA", "Call Center"], p=[0.48, 0.32, 0.14, 0.06]))

        status_str = "cancelled" if is_cancelled else ("completed" if is_completed else "confirmed_upcoming")
        pnr = f"M{booking_id:07X}"[:8]

        booking_rows.append((
            booking_id,
            pnr,
            customer_id,
            route_id,
            b_date.isoformat(),
            dep_date.isoformat(),
            cabin,
            pax,
            trip_type,
            b_ch,
            status_str,
            is_completed and not is_cancelled,
            camp_id if apply_promo else None,
        ))

    logger.info("Simulating 108 campaigns, assignments, exposures, responses, and window bookings...")
    cutoff_travel = date(2026, 9, 15)

    for bp in blueprints:
        cid = bp["campaign_id"]
        s_date: date = bp["start_date"]
        e_date: date = bp["end_date"]
        win_days: int = bp["booking_window_days"]
        win_end = e_date + timedelta(days=win_days)
        s_ord = s_date.toordinal()
        e_ord = win_end.toordinal()

        ch_id = bp["primary_channel_id"]
        seg_id = bp["target_segment_id"]
        route_id = bp["target_route_market_id"]
        is_rct = bp["experiment_type"] == "RCT"
        disc_pct = bp["discount_pct"]
        bonus_miles = bp["bonus_miles_offer"]
        ctype = bp["campaign_type"]

        # Eligibility mask (strictly observable pre-campaign criteria + non-overlapping window)
        elig_mask = last_window_end_ord < s_ord
        if seg_id is not None:
            elig_mask &= (cust["segment_id"] == seg_id)
        if ch_id == 1:
            elig_mask &= cust["email_opt_in"]
        elif ch_id == 2:
            elig_mask &= cust["push_opt_in"]
        elif ch_id == 3:
            elig_mask &= cust["app_active"]

        elig_indices = np.flatnonzero(elig_mask)
        eligible_count = int(len(elig_indices))
        target_n = min(bp["assign_size"], max(600, int(eligible_count * 0.78)))
        if target_n > eligible_count:
            target_n = eligible_count

        # Sample assigned customers from eligible pool
        if is_rct:
            chosen_idx = rng.choice(elig_indices, size=target_n, replace=False)
            # Strictly independent random assignment matching treatment_split_target
            split = bp["treatment_split_target"]
            is_treat = rng.random(target_n) < split
            groups = np.where(is_treat, "treatment", "control")
        else:
            # Observational campaign: realistic SELECTION BIAS!
            # Marketers preferentially target higher-engagement / higher-spend customers
            chosen_idx = rng.choice(elig_indices, size=target_n, replace=False)
            score = (
                0.75 * (cust["trips_12m"][chosen_idx] - cust["trips_12m"][chosen_idx].mean()) / (cust["trips_12m"][chosen_idx].std() + 1e-6)
                + 0.55 * (cust["spend_12m"][chosen_idx] - cust["spend_12m"][chosen_idx].mean()) / (cust["spend_12m"][chosen_idx].std() + 1e-6)
                + 0.65 * cust["app_active"][chosen_idx].astype(np.float64)
                + rng.normal(0.0, 0.85, size=target_n)
            )
            # Top ~65% score become observational_targeted; bottom ~35% become observational_comparison
            thresh = np.quantile(score, 0.35)
            is_treat = score >= thresh
            groups = np.where(is_treat, "observational_targeted", "observational_comparison")

        # Mark customer windows as occupied
        last_window_end_ord[chosen_idx] = e_ord
        for idx_c in chosen_idx:
            cust_id_val = int(idx_c + 1)
            cust_windows.setdefault(cust_id_val, []).append((s_ord, e_ord))

        # Store campaign row with exact eligible_audience_count (>= assigned)
        campaign_rows.append((
            cid,
            bp["campaign_code"],
            bp["campaign_name"],
            ctype,
            bp["experiment_type"],
            ch_id,
            seg_id,
            route_id,
            s_date.isoformat(),
            e_date.isoformat(),
            win_days,
            disc_pct,
            bonus_miles,
            bp["treatment_split_target"],
            eligible_count,
            bp["planned_budget"],
            bp["status"],
            bp["hypothesis"],
            bp["eligibility_criteria"],
            True,
        ))

        # Marketing cost line items (realistic media + creative + delivery/ops)
        ch_info = ch_lookup[ch_id]
        unit_cost = float(ch_info[4])
        n_targeted = int(is_treat.sum())
        media_cost = round(n_targeted * unit_cost * float(rng.uniform(1.05, 1.55)), 2)
        creative_cost = round(float(rng.uniform(2200, 8800)) if ch_id in (5, 6, 7) else float(rng.uniform(950, 3400)), 2)
        delivery_cost = round(n_targeted * (0.015 if ch_id in (1, 2, 3, 4) else 0.18), 2)
        agency_cost = round((media_cost + creative_cost) * float(rng.uniform(0.06, 0.14)), 2)

        for cat, amt, d_off in [
            ("Media Spend", media_cost, 0),
            ("Creative & Production", creative_cost, 0),
            ("Channel Delivery Fee", delivery_cost, 2),
            ("Agency & Operations", agency_cost, 5),
        ]:
            if amt > 0:
                c_date = min(e_date, s_date + timedelta(days=d_off))
                cost_rows.append((next_cost_id, cid, ch_id, c_date.isoformat(), cat, amt))
                next_cost_id += 1

        # Vectorized behavioral simulation for this campaign's assigned cohort
        season_name, _ = get_travel_season(s_date)
        s_mult = season_mult[season_name]
        # Window length scales baseline booking opportunity
        win_len_days = (win_end - s_date).days
        win_mult = win_len_days / 28.0

        c_segs = cust["segment_id"][chosen_idx]
        p_base = np.clip(cust_base_prop[chosen_idx] * s_mult * win_mult, 0.004, 0.55)

        # Reach probability for treated/targeted customers
        base_deliv = float(ch_info[5])
        base_eng = float(ch_info[6])
        # Route load factor headroom bonus (lower baseline load factor => more promo seat inventory => higher lift)
        lf_bonus = 1.18 if (route_id and float(route_lookup[route_id][9]) < 0.76) else (0.88 if (route_id and float(route_lookup[route_id][9]) > 0.83) else 1.0)
        # Channel effectiveness multiplier
        ch_lift_mult = {1: 1.08, 2: 1.10, 3: 1.22, 4: 1.26, 5: 1.18, 6: 0.74, 7: 0.86, 8: 0.96}[ch_id]
        weak_mult = 0.22 if bp["is_weak_creative"] else 1.0

        # Concave diminishing returns in discount % and bonus miles
        disc_term = np.sqrt(max(0.0, disc_pct) / 15.0) if disc_pct > 0 else 0.0
        miles_term = np.sqrt(max(0.0, bonus_miles) / 5000.0) if bonus_miles > 0 else 0.0
        prem_term = 1.0 if ctype == "Premium Cabin Promotion" else 0.0
        react_term = 1.35 if ctype == "Customer Reactivation" else 1.0

        raw_lift = (
            seg_disc_sens[c_segs] * disc_term
            + seg_miles_sens[c_segs] * miles_term
            + seg_prem_sens[c_segs] * prem_term
        ) * lf_bonus * ch_lift_mult * react_term * weak_mult

        # Add slight campaign-specific execution variance
        exec_quality = float(rng.uniform(0.84, 1.18))
        raw_lift = np.clip(raw_lift * exec_quality, 0.0, 0.22)

        # Simulate reach, engagement, bookings for each assigned customer
        reach_draws = rng.random(target_n)
        eng_draws = rng.random(target_n)
        book_draws = rng.random(target_n)
        second_book_draws = rng.random(target_n)
        cancel_draws = rng.random(target_n)
        redeem_draws = rng.random(target_n)

        # Engagement probability boosted by incentive fit
        eng_prob = np.clip(base_eng * (0.75 + 4.5 * raw_lift), 0.05, 0.68)

        for k in range(target_n):
            c_idx = int(chosen_idx[k])
            customer_id = c_idx + 1
            seg_k = int(c_segs[k])
            grp = str(groups[k])
            treated = bool(is_treat[k])

            aid = next_assign_id
            next_assign_id += 1
            assignment_rows.append((aid, cid, customer_id, ch_id, grp, s_date.isoformat()))

            reached = False
            engaged = False
            exp_id = None
            exp_date = s_date + timedelta(days=int(rng.integers(0, max(1, min(7, (e_date - s_date).days + 1)))))

            if treated:
                if reach_draws[k] < base_deliv:
                    reached = True
                    deliv_status = "delivered"
                    imps = int(rng.choice([1, 2, 3, 4], p=[0.42, 0.33, 0.17, 0.08]))
                else:
                    deliv_status = "bounced" if rng.random() < 0.62 else "suppressed"
                    imps = 1
                exp_id = next_exp_id
                next_exp_id += 1
                exp_ts = datetime(exp_date.year, exp_date.month, exp_date.day, int(rng.integers(6, 21)), int(rng.integers(0, 60)), tzinfo=timezone.utc)
                exposure_rows.append((exp_id, aid, cid, customer_id, ch_id, exp_ts.isoformat(), imps, deliv_status, reached))

                if reached and eng_draws[k] < eng_prob[k]:
                    engaged = True
                    resp_ts = exp_ts + timedelta(hours=int(rng.integers(1, 72)))
                    if bonus_miles > 0 and disc_pct < 5:
                        inc_type = "bonus_miles"
                        r_type = str(rng.choice(["click", "offer_view", "miles_enrolled"], p=[0.45, 0.35, 0.20]))
                    elif ctype == "Premium Cabin Promotion":
                        inc_type = "cabin_upgrade"
                        r_type = str(rng.choice(["click", "offer_view", "promo_code_applied"], p=[0.50, 0.35, 0.15]))
                    else:
                        inc_type = "fare_discount"
                        r_type = str(rng.choice(["click", "offer_view", "promo_code_applied"], p=[0.50, 0.32, 0.18]))
                    response_rows.append((next_resp_id, aid, exp_id, cid, customer_id, resp_ts.isoformat(), r_type, True, inc_type))
                    next_resp_id += 1
                elif reached and rng.random() < 0.28:
                    # Non-engaged passive open
                    resp_ts = exp_ts + timedelta(hours=int(rng.integers(1, 48)))
                    response_rows.append((next_resp_id, aid, exp_id, cid, customer_id, resp_ts.isoformat(), "open", False, "none"))
                    next_resp_id += 1

            # Determine booking probability under Intention-to-Treat causal DGP
            # Control & unreached Treatment book strictly at p_base!
            # Reached Treatment books at p_base + raw_lift (with engaged subset carrying higher realized share)
            if treated and reached:
                # Preserve exact expected ITT lift across reached group regardless of engagement split:
                # Let E[lift | reached] = raw_lift[k]
                # Engaged customers carry 2.1x lift weight, non-engaged reached carry remainder (clipped)
                p_book = min(0.82, float(p_base[k] + raw_lift[k] * (1.85 if engaged else 0.55)))
            else:
                p_book = float(p_base[k])

            if book_draws[k] < p_book:
                # How many bookings in window (mostly 1, occasional 2 for frequent segments)
                n_books = 2 if (seg_k in (1, 4, 2) and second_book_draws[k] < (0.16 if seg_k == 1 else 0.08)) else 1
                for b_num in range(n_books):
                    # Booking date within [exp_date if reached else s_date, win_end]
                    min_d = exp_date if (treated and reached) else s_date
                    span = max(1, (win_end - min_d).days + 1)
                    b_date = min(date(2026, 10, 15), min_d + timedelta(days=int(rng.integers(0, span))))
                    is_cancelled = (cancel_draws[k] < 0.065) if b_num == 0 else (rng.random() < 0.065)
                    is_completed = (not is_cancelled) and (b_date + timedelta(days=25) <= cutoff_travel)

                    # Does this booking use the campaign promo / get attributed?
                    # Only treated + reached customers can redeem/be attributed; both baseline & incremental bookers can redeem!
                    apply_promo = False
                    if treated and reached:
                        redeem_p = 0.88 if engaged else 0.42
                        if redeem_draws[k] < redeem_p:
                            apply_promo = True
                            # Ensure strict funnel monotonicity: if promo applied without prior click, log promo_code_applied / miles_enrolled response!
                            if not engaged:
                                engaged = True
                                r_ts = datetime(b_date.year, b_date.month, b_date.day, 10, 0, tzinfo=timezone.utc)
                                r_t = "miles_enrolled" if (bonus_miles > 0 and disc_pct < 5) else "promo_code_applied"
                                inc_t = "bonus_miles" if (bonus_miles > 0 and disc_pct < 5) else ("cabin_upgrade" if ctype == "Premium Cabin Promotion" else "fare_discount")
                                response_rows.append((next_resp_id, aid, exp_id, cid, customer_id, r_ts.isoformat(), r_t, True, inc_t))
                                next_resp_id += 1

                    r_id = pick_route_for_customer(seg_k, route_id if apply_promo else None)
                    bid = next_book_id
                    next_book_id += 1
                    append_booking_financials(
                        booking_id=bid,
                        customer_id=customer_id,
                        seg_id=seg_k,
                        route_id=r_id,
                        b_date=b_date,
                        camp_id=cid if apply_promo else None,
                        camp_code=bp["campaign_code"] if apply_promo else None,
                        ctype=ctype if apply_promo else None,
                        disc_pct_offer=disc_pct if apply_promo else 0.0,
                        bonus_miles_offer=bonus_miles if apply_promo else 0,
                        apply_promo=apply_promo,
                        is_completed=is_completed,
                        is_cancelled=is_cancelled,
                    )

    logger.info("Campaign-window bookings generated: %d. Generating organic non-window bookings...", len(booking_rows))

    # Generate ~88,000 organic background bookings outside customers' occupied campaign windows
    # so total bookings comfortably exceeds 105,000-125,000 and full network trends are rich!
    target_organic = max(108000, 132000 - len(booking_rows))
    # Weight organic customer selection by baseline propensity
    org_weights = cust_base_prop / cust_base_prop.sum()
    org_cust_indices = rng.choice(n_customers, size=target_organic, replace=True, p=org_weights)
    cal_start_ord = date(2024, 1, 1).toordinal()
    cal_end_ord = date(2026, 9, 25).toordinal()
    org_date_ords = rng.integers(cal_start_ord, cal_end_ord + 1, size=target_organic)

    organic_added = 0
    for j in range(target_organic):
        c_idx = int(org_cust_indices[j])
        customer_id = c_idx + 1
        d_ord = int(org_date_ords[j])
        # Skip if date falls inside an active campaign observation window for this customer
        occupied = cust_windows.get(customer_id)
        if occupied:
            conflict = False
            for w_s, w_e in occupied:
                if w_s <= d_ord <= w_e:
                    conflict = True
                    break
            if conflict:
                continue

        b_date = date.fromordinal(d_ord)
        seg_k = int(cust["segment_id"][c_idx])
        r_id = pick_route_for_customer(seg_k, None)
        is_cancelled = rng.random() < 0.06
        is_completed = (not is_cancelled) and (b_date + timedelta(days=25) <= cutoff_travel)

        bid = next_book_id
        next_book_id += 1
        append_booking_financials(
            booking_id=bid,
            customer_id=customer_id,
            seg_id=seg_k,
            route_id=r_id,
            b_date=b_date,
            camp_id=None,
            camp_code=None,
            ctype=None,
            disc_pct_offer=0.0,
            bonus_miles_offer=0,
            apply_promo=False,
            is_completed=is_completed,
            is_cancelled=is_cancelled,
        )
        organic_added += 1

    logger.info(
        "Generation complete in %.1fs. Counts: customers=%d, campaigns=%d, assignments=%d, exposures=%d, responses=%d, bookings=%d, items=%d, discounts=%d, rewards=%d, costs=%d",
        time.perf_counter() - t0,
        len(cust_rows),
        len(campaign_rows),
        len(assignment_rows),
        len(exposure_rows),
        len(response_rows),
        len(booking_rows),
        len(booking_item_rows),
        len(discount_tx_rows),
        len(loyalty_rows),
        len(cost_rows),
    )

    logger.info("Loading all 15 relational tables into PostgreSQL via COPY...")
    t_load = time.perf_counter()
    with psycopg.connect(settings.database_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            # Clean reload for strict reproducibility
            cur.execute(
                """
                TRUNCATE TABLE
                    customer_propensity_scores,
                    ml_model_runs,
                    experiment_results_store,
                    marketing_costs,
                    loyalty_rewards,
                    discount_transactions,
                    ticket_revenue,
                    booking_items,
                    bookings,
                    customer_responses,
                    campaign_exposures,
                    campaign_assignments,
                    campaigns,
                    calendar_dimension,
                    campaign_channels,
                    route_markets,
                    customers,
                    customer_segments,
                    dataset_metadata
                RESTART IDENTITY CASCADE;
                """
            )

            copy_rows(cur, "customer_segments", [
                "segment_id", "segment_code", "segment_name", "description",
                "target_margin_tier", "avg_annual_trips", "typical_booking_lead_days", "incentive_affinity",
            ], SEGMENTS)

            copy_rows(cur, "campaign_channels", [
                "channel_id", "channel_code", "channel_name", "cost_model",
                "unit_reach_cost", "avg_deliverability_rate", "avg_engagement_rate",
            ], CHANNELS)

            copy_rows(cur, "route_markets", [
                "route_market_id", "market_code", "origin_airport", "destination_airport",
                "market_region", "haul_type", "distance_miles", "avg_base_fare",
                "variable_cost_per_pax", "load_factor_baseline", "seasonality_profile",
            ], ROUTE_MARKETS)

            copy_rows(cur, "calendar_dimension", [
                "calendar_date", "year", "quarter", "month", "month_name", "week_of_year",
                "day_of_week", "day_name", "is_weekend", "is_holiday_peak", "travel_season", "fiscal_period",
            ], cal_rows)

            copy_rows(cur, "customers", [
                "customer_id", "customer_code", "segment_id", "loyalty_tier", "home_airport",
                "region", "signup_date", "tenure_months", "age_band", "historical_trips_12m",
                "historical_spend_12m", "miles_balance", "email_opt_in", "push_opt_in",
                "app_active", "is_synthetic",
            ], cust_rows)

            copy_rows(cur, "campaigns", [
                "campaign_id", "campaign_code", "campaign_name", "campaign_type", "experiment_type",
                "primary_channel_id", "target_segment_id", "target_route_market_id",
                "start_date", "end_date", "booking_window_days", "discount_pct", "bonus_miles_offer",
                "treatment_split_target", "eligible_audience_count", "planned_budget", "status",
                "hypothesis", "eligibility_criteria", "is_synthetic",
            ], campaign_rows)

            copy_rows(cur, "campaign_assignments", [
                "assignment_id", "campaign_id", "customer_id", "channel_id", "assignment_group", "assigned_at",
            ], assignment_rows)

            copy_rows(cur, "campaign_exposures", [
                "exposure_id", "assignment_id", "campaign_id", "customer_id", "channel_id",
                "exposed_at", "impression_count", "delivery_status", "is_reached",
            ], exposure_rows)

            copy_rows(cur, "customer_responses", [
                "response_id", "assignment_id", "exposure_id", "campaign_id", "customer_id",
                "response_timestamp", "response_type", "engaged_flag", "incentive_type_engaged",
            ], response_rows)

            copy_rows(cur, "bookings", [
                "booking_id", "booking_reference", "customer_id", "route_market_id", "booking_date",
                "departure_date", "cabin_class", "passengers", "trip_type", "booking_channel",
                "booking_status", "travel_completed", "attributed_campaign_id",
            ], booking_rows)

            copy_rows(cur, "booking_items", [
                "booking_item_id", "booking_id", "item_type", "quantity", "unit_price",
                "item_revenue", "estimated_variable_cost",
            ], booking_item_rows)

            copy_rows(cur, "ticket_revenue", [
                "ticket_revenue_id", "booking_id", "gross_fare_revenue", "ancillary_revenue",
                "gross_total_revenue", "discount_amount", "net_ticket_revenue",
                "estimated_variable_cost", "taxes_and_fees", "contribution_before_promo",
            ], ticket_rev_rows)

            copy_rows(cur, "discount_transactions", [
                "discount_tx_id", "booking_id", "campaign_id", "customer_id", "promo_code",
                "discount_type", "discount_pct_applied", "discount_amount", "applied_at",
            ], discount_tx_rows)

            copy_rows(cur, "loyalty_rewards", [
                "reward_id", "booking_id", "campaign_id", "customer_id", "reward_type",
                "miles_awarded", "cost_per_mile", "reward_liability_cost", "awarded_at",
            ], loyalty_rows)

            copy_rows(cur, "marketing_costs", [
                "cost_id", "campaign_id", "channel_id", "cost_date", "cost_category", "amount_usd",
            ], cost_rows)

            # Sync sequences & write dataset metadata
            for tbl, col in [
                ("customer_segments", "segment_id"),
                ("campaign_channels", "channel_id"),
                ("route_markets", "route_market_id"),
                ("customers", "customer_id"),
                ("campaigns", "campaign_id"),
                ("campaign_assignments", "assignment_id"),
                ("campaign_exposures", "exposure_id"),
                ("customer_responses", "response_id"),
                ("bookings", "booking_id"),
                ("booking_items", "booking_item_id"),
                ("ticket_revenue", "ticket_revenue_id"),
                ("discount_transactions", "discount_tx_id"),
                ("loyalty_rewards", "reward_id"),
                ("marketing_costs", "cost_id"),
            ]:
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{tbl}', '{col}'), COALESCE((SELECT MAX({col}) FROM {tbl}), 1))")

            meta_entries = [
                ("dataset_type", "SYNTHETIC_AIRLINE_PROMOTIONS"),
                ("airline_persona", "Meridian Air (Fictional International Carrier)"),
                ("generation_seed", str(seed)),
                ("generated_at_utc", datetime.now(timezone.utc).isoformat()),
                ("customers_count", str(len(cust_rows))),
                ("campaigns_count", str(len(campaign_rows))),
                ("rct_campaigns_count", str(sum(1 for b in blueprints if b["experiment_type"] == "RCT"))),
                ("observational_campaigns_count", str(sum(1 for b in blueprints if b["experiment_type"] == "Observational"))),
                ("assignments_count", str(len(assignment_rows))),
                ("bookings_count", str(len(booking_rows))),
                ("organic_bookings_count", str(organic_added)),
            ]
            for k, v in meta_entries:
                cur.execute(
                    "INSERT INTO dataset_metadata (meta_key, meta_value) VALUES (%s, %s) ON CONFLICT (meta_key) DO UPDATE SET meta_value = EXCLUDED.meta_value, updated_at = NOW()",
                    (k, v),
                )

            conn.commit()
            cur.execute("ANALYZE;")
            conn.commit()

    logger.info("PostgreSQL COPY load + ANALYZE finished in %.1fs (total %.1fs).", time.perf_counter() - t_load, time.perf_counter() - t0)


if __name__ == "__main__":
    main()
