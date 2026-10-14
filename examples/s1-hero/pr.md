# Receipt: the change Faultline executed for inc-s1-ee6d96e6

## flag paymentGate → off (flip_flag)

- **link:** https://github.com/Prashant-thakur77/faultline-demo-infra/pull/1 (simulated)
- **verdict:** APPLIED — flags.json at main HEAD has the change; checkout, frontend back in band for 3 minutes; no collateral on frontend-proxy
- **approval:** ap-act-inc-s1-ee6d96e6-2-90dde7c1 (plan hash `90dde7c112316822…`)
- **idempotency key:** `28232c940653a17080e89478612db6051f0e6b6ab63718c6966c5ce5d35a7687` → branch `faultline/fix-28232c94`

**Commit message**

```
fix: turn paymentGate off (contain inc-s1-ee6d96e6)

Faultline-Idem: 28232c940653a17080e89478612db6051f0e6b6ab63718c6966c5ce5d35a7687
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
Approved in Faultline (inc-s1-ee6d96e6).

Suggested reviewers (who_fixes): p-017, p-030, p-036

Rollback: set flags.paymentGate.state back to 'on' in flags.json

Faultline-Idem: 28232c940653a17080e89478612db6051f0e6b6ab63718c6966c5ce5d35a7687
```

**Rollback:** set flags.paymentGate.state back to 'on' in flags.json

_Keyless recording: the PR lives in the simulated GitHub of this run's clean room (labelled "(simulated)")._
