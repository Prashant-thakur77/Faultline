-- stg_customers: cleaned customer dimension.
CREATE OR REPLACE TABLE staging.stg_customers AS
SELECT
    customer_id,
    name,
    segment,
    country,
    CAST(created_at AS TIMESTAMP) AS created_at
FROM raw.raw_customers;
