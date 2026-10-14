# OTel Demo topology: source notes for `data/topology/otel-demo.yaml` (M1)

Fetched 2026-10-13 from https://opentelemetry.io/docs/demo/architecture/ and https://opentelemetry.io/docs/demo/feature-flags/ (public; hand-encoded, nothing copied beyond names).

## Services (language)
accounting (.NET) · ad (Java) · agent (Python) · cache = Valkey (datastore) · cart (.NET) · chatbot (Python) · checkout (Go) · currency (C++) · email (Ruby) · flagd (Go) · flagd-ui (Elixir) · fraud-detection (Kotlin) · frontend (TypeScript) · frontend-proxy = Envoy · image-provider = nginx · load-generator (Python) · mcp (Python) · payment (JavaScript) · product-catalog (Go) · quote (PHP) · recommendation (Python) · shipping (Rust) · queue = Kafka (datastore) · react-native-app (TypeScript) · astronomy-db = PostgreSQL (datastore)

## Call edges (client → server, protocol)
Internet/load-generator/react-native-app → frontend-proxy (HTTP) · frontend-proxy → frontend, image-provider, flagd-ui, chatbot (HTTP), flagd (gRPC) · frontend → ad, cart, currency, checkout, product-catalog, recommendation (gRPC), shipping (HTTP) · checkout → currency, cart, payment, product-catalog (gRPC), email, shipping (HTTP), queue (TCP) · cart → cache · shipping → quote (HTTP) · recommendation → product-catalog (gRPC) · product-catalog → astronomy-db · queue → accounting, fraud-detection (TCP) · accounting → astronomy-db · chatbot → agent (HTTP) · agent → frontend, mcp (HTTP) · mcp → frontend (HTTP) · ad, cart, payment, recommendation, fraud-detection, frontend-proxy → flagd (gRPC)

## Modelling decisions for acme
- **Entry:** `frontend-proxy` = 1000 rps (fixed traffic matrix). The revenue path is frontend-proxy → frontend → checkout → {payment, cart, currency, shipping, email, product-catalog}.
- **flagd edges** are control-plane, so they are modelled as `FeatureFlag -[:GATES]-> Service/Endpoint` and not as data-plane CALLS (otherwise flagd becomes a fake betweenness hub).
- **Hero S1 shape (superseded by `scenario_numbers.md` §3):** symptom = **checkout** error rate; `checkout→email` cap 0.02 (best-effort, declared per edge in M1) so `D-email-88` is eliminated by G5; `D-rec-12` on recommendation has no failure-direction path to checkout, so it is eliminated by G2.
- **Flags used by scenarios:** `paymentFailure` (S1 effect), `paymentUnreachable` (alternative cut lever on checkout), `productCatalogLockContention` (S3), `recommendationCacheFailure` (S1 noise / S8 family), `kafkaQueueProblems` (S12-style lag), `emailMemoryLeak` (distractor flavour), `cartFailure`, `adFailure`.
- **Datastores:** cache (valkey), queue (kafka), astronomy-db (postgres) as `Datastore`. Cross-domain: `payment -EMITS-> raw.raw_orders` (S2).
- The AI services (chatbot, agent, mcp) are kept as a non-revenue branch: realistic, and they give betweenness and blast radius something to rank below the revenue path.
