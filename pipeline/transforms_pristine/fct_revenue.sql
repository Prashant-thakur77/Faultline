-- fct_revenue: daily revenue fact, USD-normalized via stg_fx_rates.
CREATE OR REPLACE TABLE marts.fct_revenue AS
SELECT
    o.order_day AS day,
    COUNT(*) AS order_count,
    ROUND(SUM(o.amount * fx.usd_rate), 2) AS revenue_usd,
    ROUND(AVG(o.amount * fx.usd_rate), 2) AS aov_usd,
    ROUND(MEDIAN(o.amount * fx.usd_rate), 2) AS aov_median_usd
FROM staging.stg_orders o
JOIN staging.stg_fx_rates fx
  ON fx.rate_day = o.order_day
 AND fx.currency = o.currency
GROUP BY o.order_day
ORDER BY o.order_day;
