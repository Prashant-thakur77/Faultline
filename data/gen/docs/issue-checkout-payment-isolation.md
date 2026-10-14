---
id: issue-checkout-payment-isolation
kind: issue
title: "Checkout should degrade, not fail, when payment is slow"
reviewed_at: 2026-08-20
about: [checkout, payment]
incidents: [inc-h008]
---
**Synthetic tracker issue.** After inc-h008, checkout failed every order while payment was erroring. Proposal:
put payment behind the `paymentGate` flag so checkout can accept orders and defer the charge to the queue when
payment is unhealthy. Status: shipped (the flag exists; it is the containment lever used by on-call).
