---
id: chat-payment-timeouts
kind: chat
title: "#inc-checkout-pool: payment timeouts exhausting checkout connections"
reviewed_at: 2026-03-11
about: [payment, checkout]
---
**Synthetic incident-channel transcript (excerpt).**

- **on-call (checkout):** checkout pool is pinned at max connections again; every slot is waiting on payment.
- **payments:** the card processor is slow tonight; our client timeout is 8 s and we retry zero times.
- **checkout lead:** an 8 s timeout means one slow processor takes the whole storefront down with it.
- **payments:** proposal: cap the client timeout at 2 s and keep two fast retries; slow becomes a retryable failure.
- **architect:** agreed. Writing it up as two decisions: timeout cap and minimum retries. Anyone raising the
  timeout later needs a capacity review of checkout.
