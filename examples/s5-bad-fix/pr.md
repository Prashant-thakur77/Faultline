# Receipt: the change Faultline executed for inc-s1-b0472ed3

## roll back D-email-88 (forced bad plan) (rollback_deploy)

- **link:** https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1 (simulated)
- **verdict:** NOT_APPLIED — still out of band after the change: checkout, frontend
- **approval:** ap-act-inc-s1-b0472ed3-bad-7ae21055 (plan hash `7ae2105584c43912…`)
- **idempotency key:** `e7aa8deacee79af97cf623e57857d0f16a726222c5b48c41ef8fafb1d15aad8b` → branch `faultline/fix-e7aa8dea`

**Commit message**

```
revert: roll back D-email-88 on email (inc-s1-b0472ed3)

Faultline-Idem: e7aa8deacee79af97cf623e57857d0f16a726222c5b48c41ef8fafb1d15aad8b
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
Approved in Faultline (inc-s1-b0472ed3).

Rollback: re-deploy D-email-88

Faultline-Idem: e7aa8deacee79af97cf623e57857d0f16a726222c5b48c41ef8fafb1d15aad8b
```

**Rollback:** re-deploy D-email-88

_Keyless recording: the PR lives in the simulated GitHub of this run's clean room (labelled "(simulated)")._
