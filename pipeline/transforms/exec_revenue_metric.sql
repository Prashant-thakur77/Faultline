-- exec_revenue_metric: single-row executive KPI.
-- trailing_28d_median_revenue uses days -35..-8 relative to kpi_day (a stable
-- pre-cutover window) so the reference is robust to recent turbulence.
CREATE OR REPLACE TABLE marts.exec_revenue_metric AS
WITH latest AS (
    SELECT MAX(day) AS kpi_day FROM marts.fct_revenue
),
current_rev AS (
    SELECT f.day AS kpi_day, f.revenue_usd AS revenue
    FROM marts.fct_revenue f, latest l
    WHERE f.day = l.kpi_day
),
trailing_window AS (
    SELECT MEDIAN(f.revenue_usd) AS trailing_28d_median_revenue
    FROM marts.fct_revenue f, latest l
    WHERE f.day BETWEEN l.kpi_day - 35 AND l.kpi_day - 8
)
SELECT
    c.kpi_day,
    c.revenue,
    ROUND(t.trailing_28d_median_revenue, 2) AS trailing_28d_median_revenue,
    ROUND(c.revenue / t.trailing_28d_median_revenue, 4) AS anomaly_ratio
FROM current_rev c, trailing_window t;
