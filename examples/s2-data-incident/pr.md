# Receipt: the change Faultline executed for inc-s2-2defc7b1

## repair the transform affected by D-cutover-1 (data_repair)

- **link:** local:pipeline/transforms/stg_orders.sql
- **verdict:** APPLIED — pipeline/transforms/stg_orders.sql carries the patch; on the incident's own data (mode incident, sources b8f24c5669d3) the rebuild passed 32/32 invariants and the KPI anomaly ratio is 0.933 (inside 0.8–1.3)
- **approval:** ap-act-inc-s2-2defc7b1-4-797a6c39 (plan hash `797a6c39d78342c8…`)
- **idempotency key:** `064c07b00a8a601414f0232ea93af4e5fea3bb33600dc213ecd0f3eb570b08f8` → branch `faultline/fix-064c07b0`

**Commit message**

```
fix(data): unit shift measured on staging.stg_orders.amount: the 327… (inc-s2-2defc7b1)

Faultline-Idem: 064c07b00a8a601414f0232ea93af4e5fea3bb33600dc213ecd0f3eb570b08f8
```

**Diff**

```diff
--- a/pipeline/transforms/stg_orders.sql
+++ b/pipeline/transforms/stg_orders.sql
@@ -7,7 +7,7 @@
     CAST(CAST(order_ts AS TIMESTAMP) AS DATE) AS order_day,
     customer_id,
     currency,
-    CAST(amount AS DOUBLE) AS amount,
+    CASE WHEN payment_processor = 'cloudpay_v2' THEN (CAST(amount AS DOUBLE)) / 100 ELSE CAST(amount AS DOUBLE) END AS amount,
     payment_processor,
     status
 FROM raw.raw_orders
```

**Rollback:** restore pipeline/transforms/stg_orders.sql to the plan's `before` (or its pristine copy) and rebuild the warehouse

_Keyless recording: the PR lives in the simulated GitHub of this run's clean room (labelled "(simulated)")._
