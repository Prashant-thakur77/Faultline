---
id: chat-catalog-migrations
kind: chat
title: "#catalog-db: off-peak migrations still lock the catalog"
reviewed_at: 2026-06-02
about: [product-catalog, astronomy-db]
---
**Synthetic channel transcript (excerpt).**

- **catalog:** last night's "off-peak" migration still held a table lock for 4 minutes; product pages timed out.
- **dba:** off-peak doesn't help when the lock is the problem. We should require online (non-locking) migrations.
- **catalog lead:** agreed; supersede the off-peak rule with an online-migrations rule.
