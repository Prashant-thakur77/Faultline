# Receipt: the change Faultline executed for inc-s1-66af9843

## flag paymentGate → off (flip_flag)

- **link:** https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1 (simulated)
- **verdict:** APPLIED — flags.json at main HEAD has the change; checkout, frontend back in band for 3 minutes; no collateral on frontend-proxy
- **approval:** ap-act-inc-s1-66af9843-1-175bd315 (plan hash `175bd3155b8fb220…`)
- **idempotency key:** `46a4c301d15f18c0f17caff4bbaa9ba1dc03a50d0d15b8261147f449b9682c38` → branch `faultline/fix-46a4c301`

**Commit message**

```
fix: turn paymentGate off (contain inc-s1-66af9843)

Faultline-Idem: 46a4c301d15f18c0f17caff4bbaa9ba1dc03a50d0d15b8261147f449b9682c38
```

**Diff**

```diff
--- a/flags.json
+++ b/flags.json
@@ -26,7 +26,7 @@
         "payment",
         "checkout"
       ],
-      "state": "on"
+      "state": "off"
     },
     "paymentUnreachable": {
       "state": "off"
```

**PR / issue body**

```
Approved in Faultline (inc-s1-66af9843).

Suggested reviewers (who_fixes): p-017, p-030, p-036

Rollback: set flags.paymentGate.state back to 'on' in flags.json

Faultline-Idem: 46a4c301d15f18c0f17caff4bbaa9ba1dc03a50d0d15b8261147f449b9682c38
```

**Rollback:** set flags.paymentGate.state back to 'on' in flags.json

_Keyless recording: the PR lives in the simulated GitHub of this run's clean room (labelled "(simulated)")._
