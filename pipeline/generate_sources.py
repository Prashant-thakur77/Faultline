"""Deterministic synthetic source generator for the Faultline demo fixture.

Generates 90 days of retail order data ending at ANCHOR_DAY (a fixed constant;
no wall clock is consulted anywhere). A single RNG seed (42) drives everything,
so output is byte-identical across runs.

Two modes:
  --mode healthy   : all rows carry decimal-dollar amounts.
  --mode incident  : rows processed by 'cloudpay_v2' (the provider all orders
                     migrated to at CUTOVER_TS, in BOTH modes) report `amount`
                     as integer cents instead of decimal dollars.

The base order stream is generated first, independent of mode; the mode only
changes how post-cutover cloudpay_v2 amounts are ENCODED when writing the CSV.
Pre-cutover rows are therefore byte-identical between modes.
"""

import argparse
import csv
import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Fixture constants (all deterministic; never read the wall clock)
# ---------------------------------------------------------------------------
ANCHOR_DAY = date(2026, 8, 9)          # fixed "today"
N_DAYS = 90                            # window ends at ANCHOR_DAY (inclusive)
SEED = 42

# Payment provider migration: from this instant every new order routes via
# cloudpay_v2. This migration is real and happens in BOTH modes.
CUTOVER_TS = datetime(2026, 8, 7, 0, 0, 0)

# FX feed distractor: the rates feed stops updating after this day (BOTH modes).
FX_LAST_DAY = date(2026, 8, 5)

N_CUSTOMERS = 3000

CURRENCIES = ["USD", "EUR", "GBP", "CAD"]
CURRENCY_P = [0.93, 0.04, 0.02, 0.01]

STATUSES = ["completed", "cancelled", "refunded"]
STATUS_P = [0.95, 0.04, 0.01]

SEGMENTS = ["consumer", "smb", "enterprise"]
SEGMENT_P = [0.80, 0.15, 0.05]

COUNTRIES = ["US", "CA", "GB", "DE", "FR", "AU"]
COUNTRY_P = [0.82, 0.05, 0.05, 0.03, 0.03, 0.02]

FX_START_RATES = {"EUR": 1.08, "GBP": 1.27, "CAD": 0.73}  # usd per 1 unit
FX_DAILY_SIGMA = 0.0015  # small multiplicative random walk

FIRST_NAMES = [
    "Ava", "Ben", "Chloe", "Dan", "Elena", "Felix", "Grace", "Hank",
    "Iris", "Jack", "Kara", "Liam", "Mia", "Noah", "Olive", "Pete",
    "Quinn", "Rosa", "Sam", "Tara", "Umar", "Vera", "Wes", "Xena",
    "Yuri", "Zoe", "Amir", "Bella", "Carl", "Dina", "Eli", "Faye",
]
LAST_NAMES = [
    "Adler", "Brooks", "Chen", "Diaz", "Evans", "Ford", "Garcia", "Hale",
    "Ito", "Jones", "Kim", "Lopez", "Mori", "Nash", "Okafor", "Park",
    "Quist", "Rivera", "Singh", "Tran", "Ueda", "Vogel", "Walsh", "Xu",
    "Young", "Zhang", "Abbot", "Boyd", "Cruz", "Dupont", "Egan", "Frey",
]


def _window_start() -> date:
    return ANCHOR_DAY - timedelta(days=N_DAYS - 1)


# ---------------------------------------------------------------------------
# Base stream generation (mode-independent)
# ---------------------------------------------------------------------------
def gen_base_orders(rng: np.random.Generator) -> list[dict]:
    """Generate the base order stream. Amounts are always decimal dollars here;
    mode-specific encoding happens only at CSV-write time."""
    start = _window_start()
    rows: list[dict] = []
    seq = 0
    for i in range(N_DAYS):
        d = start + timedelta(days=i)
        trend = 0.94 + 0.12 * i / (N_DAYS - 1)        # mild upward trend
        weekend = 0.82 if d.weekday() >= 5 else 1.00  # ~20% weekend dip
        n = max(50, int(round(rng.normal(400.0, 35.0) * weekend * trend)))

        secs = np.sort(rng.integers(0, 86400, size=n))
        cust_idx = rng.integers(0, N_CUSTOMERS, size=n)
        currencies = rng.choice(CURRENCIES, size=n, p=CURRENCY_P)
        amounts = np.exp(rng.normal(np.log(62.0), 0.72, size=n))
        amounts = np.clip(amounts, 5.0, 1800.0).round(2)
        statuses = rng.choice(STATUSES, size=n, p=STATUS_P)
        proc_pick = rng.random(n)  # drawn for every row; used only pre-cutover

        for j in range(n):
            ts = datetime(d.year, d.month, d.day) + timedelta(seconds=int(secs[j]))
            if ts >= CUTOVER_TS:
                proc = "cloudpay_v2"
            else:
                proc = "legacy_pos" if proc_pick[j] < 0.70 else "shopgate"
            rows.append(
                {
                    "order_id": hashlib.md5(f"faultline-order-{seq}".encode()).hexdigest()[:16],
                    "order_ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "customer_id": f"CUST-{int(cust_idx[j]):05d}",
                    "currency": str(currencies[j]),
                    "amount": float(amounts[j]),
                    "payment_processor": proc,
                    "status": str(statuses[j]),
                }
            )
            seq += 1
    return rows


def gen_customers(rng: np.random.Generator) -> list[dict]:
    created_lo = date(2023, 8, 9)
    created_hi = _window_start() - timedelta(days=1)  # all exist before the window
    span = (created_hi - created_lo).days
    rows = []
    for i in range(N_CUSTOMERS):
        first = FIRST_NAMES[int(rng.integers(0, len(FIRST_NAMES)))]
        last = LAST_NAMES[int(rng.integers(0, len(LAST_NAMES)))]
        created = created_lo + timedelta(
            days=int(rng.integers(0, span + 1)), seconds=int(rng.integers(0, 86400))
        )
        rows.append(
            {
                "customer_id": f"CUST-{i:05d}",
                "name": f"{first} {last}",
                "segment": str(rng.choice(SEGMENTS, p=SEGMENT_P)),
                "country": str(rng.choice(COUNTRIES, p=COUNTRY_P)),
                "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    return rows


def gen_fx_rates(rng: np.random.Generator) -> list[dict]:
    """Daily usd_rate per non-USD currency. The feed stops after FX_LAST_DAY
    (stale-feed distractor, present in BOTH modes)."""
    start = _window_start()
    rows = []
    rates = dict(FX_START_RATES)
    d = start
    while d <= FX_LAST_DAY:
        for cur in sorted(rates):  # CAD, EUR, GBP — fixed order
            rates[cur] *= float(np.exp(rng.normal(0.0, FX_DAILY_SIGMA)))
            rows.append(
                {
                    "rate_day": d.isoformat(),
                    "currency": cur,
                    "usd_rate": f"{rates[cur]:.6f}",
                }
            )
        d += timedelta(days=1)
    return rows


# ---------------------------------------------------------------------------
# Mode-specific encoding (the ONLY place `mode` matters)
# ---------------------------------------------------------------------------
def encode_amount(row: dict, mode: str) -> str:
    if mode == "incident" and row["payment_processor"] == "cloudpay_v2":
        # Semantic failure: cloudpay_v2 reports integer CENTS, not dollars.
        return str(int(round(row["amount"] * 100)))
    return f"{row['amount']:.2f}"


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def generate(mode: str, sources_dir: Path, warehouse_dir: Path) -> None:
    if mode not in ("incident", "healthy"):
        raise ValueError(f"unknown mode: {mode}")

    ss = np.random.SeedSequence(SEED)
    rng_orders, rng_customers, rng_fx = (np.random.default_rng(s) for s in ss.spawn(3))

    orders = gen_base_orders(rng_orders)
    _write_csv(
        sources_dir / "raw_orders.csv",
        ["order_id", "order_ts", "customer_id", "currency", "amount", "payment_processor", "status"],
        [
            [
                r["order_id"],
                r["order_ts"],
                r["customer_id"],
                r["currency"],
                encode_amount(r, mode),
                r["payment_processor"],
                r["status"],
            ]
            for r in orders
        ],
    )

    customers = gen_customers(rng_customers)
    _write_csv(
        sources_dir / "raw_customers.csv",
        ["customer_id", "name", "segment", "country", "created_at"],
        [[c["customer_id"], c["name"], c["segment"], c["country"], c["created_at"]] for c in customers],
    )

    fx = gen_fx_rates(rng_fx)
    _write_csv(
        sources_dir / "raw_fx_rates.csv",
        ["rate_day", "currency", "usd_rate"],
        [[r["rate_day"], r["currency"], r["usd_rate"]] for r in fx],
    )

    # Mode marker for eval tooling ONLY — never read by the pipeline or agent.
    warehouse_dir.mkdir(parents=True, exist_ok=True)
    (warehouse_dir / ".fixture_mode").write_text(mode + "\n")

    print(f"generated {len(orders)} orders, {len(customers)} customers, {len(fx)} fx rows -> {sources_dir} (mode={mode})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic Faultline source CSVs")
    parser.add_argument("--mode", required=True, choices=["incident", "healthy"])
    parser.add_argument("--sources-dir", default=None, help="override output dir (default: <repo>/data/sources)")
    parser.add_argument("--warehouse-dir", default=None, help="override warehouse dir (default: <repo>/data/warehouse)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    sources_dir = Path(args.sources_dir) if args.sources_dir else repo_root / "data" / "sources"
    warehouse_dir = Path(args.warehouse_dir) if args.warehouse_dir else repo_root / "data" / "warehouse"
    generate(args.mode, sources_dir, warehouse_dir)


if __name__ == "__main__":
    main()
