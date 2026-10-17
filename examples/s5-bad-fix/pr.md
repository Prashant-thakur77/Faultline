# Receipt: the change Faultline executed for inc-s1-f3885826

## roll back D-email-88 (forced bad plan) (rollback_deploy)

- **link:** https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1 (simulated)
- **verdict:** NOT_APPLIED — still out of band after the change: checkout, frontend
- **approval:** ap-act-inc-s1-f3885826-bad-d7a89ce3 (plan hash `d7a89ce373b59fd2…`)
- **idempotency key:** `74fcb11569ff4ed0a9b194e7f0e6bf4420abfbd06b382ed903d9d64c27627442` → branch `faultline/fix-74fcb115`

**Commit message**

```
revert: roll back D-email-88 on email (inc-s1-f3885826)

Faultline-Idem: 74fcb11569ff4ed0a9b194e7f0e6bf4420abfbd06b382ed903d9d64c27627442
```

**Diff**

```diff
--- a/deploys.json
+++ b/deploys.json
@@ -1,3 +1,7 @@
 {
-  "deploys": {}
+  "deploys": {
+    "email": {
+      "reverted": "D-email-88"
+    }
+  }
 }
```

**PR / issue body**

```
Approved in Faultline (inc-s1-f3885826).

Rollback: re-deploy D-email-88

Faultline-Idem: 74fcb11569ff4ed0a9b194e7f0e6bf4420abfbd06b382ed903d9d64c27627442
```

**Rollback:** re-deploy D-email-88

_Keyless recording: the PR lives in the simulated GitHub of this run's clean room (labelled "(simulated)")._
