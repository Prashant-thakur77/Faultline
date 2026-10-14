-- stg_fx_rates: daily USD conversion rates, forward-filled over a full day
-- spine so that days where the upstream feed is missing carry the last known
-- rate forward. USD is added explicitly at 1.0.
CREATE OR REPLACE TABLE staging.stg_fx_rates AS
WITH bounds AS (
    SELECT MIN(order_day) AS d0, MAX(order_day) AS d1
    FROM staging.stg_orders
),
day_spine AS (
    SELECT CAST(r.range AS DATE) AS rate_day
    FROM bounds b,
         LATERAL range(CAST(b.d0 AS TIMESTAMP), CAST(b.d1 AS TIMESTAMP) + INTERVAL 1 DAY, INTERVAL 1 DAY) AS r
),
currencies AS (
    SELECT DISTINCT currency FROM raw.raw_fx_rates
),
spine AS (
    SELECT d.rate_day, c.currency
    FROM day_spine d CROSS JOIN currencies c
),
joined AS (
    SELECT
        s.rate_day,
        s.currency,
        CAST(r.usd_rate AS DOUBLE) AS usd_rate_raw
    FROM spine s
    LEFT JOIN raw.raw_fx_rates r
      ON CAST(r.rate_day AS DATE) = s.rate_day AND r.currency = s.currency
),
filled AS (
    SELECT
        rate_day,
        currency,
        LAST_VALUE(usd_rate_raw IGNORE NULLS) OVER (
            PARTITION BY currency
            ORDER BY rate_day
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS usd_rate
    FROM joined
)
SELECT rate_day, currency, usd_rate FROM filled
UNION ALL
SELECT rate_day, 'USD' AS currency, 1.0 AS usd_rate FROM day_spine
ORDER BY rate_day, currency;
