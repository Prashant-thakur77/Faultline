-- stg_orders: cleaned order stream.
-- Excludes cancelled and refunded orders from the revenue path.
CREATE OR REPLACE TABLE staging.stg_orders AS
SELECT
    order_id,
    CAST(order_ts AS TIMESTAMP) AS order_ts,
    CAST(CAST(order_ts AS TIMESTAMP) AS DATE) AS order_day,
    customer_id,
    currency,
    CAST(amount AS DOUBLE) AS amount,
    payment_processor,
    status
FROM raw.raw_orders
WHERE status NOT IN ('cancelled', 'refunded');
