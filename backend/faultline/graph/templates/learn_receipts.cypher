// id: Q-LEARN-RECEIPTS
// purpose: forget receipts of learned influence in audit_<t>: whose influence was forgotten, who approved it, the receipt token, what was deleted and recomputed, and the proof re-read after it (events left, preferences still citing one)
// home: audit
// seen: person
MATCH (r:ForgetReceipt)
WHERE r.kind = 'learned_influence'
RETURN r.person AS person, r.approver AS approver, r.token AS token, r.events AS events, r.guidelines AS guidelines,
       r.relationships AS relationships, r.families_recomputed AS families, r.responders_recomputed AS responders,
       r.gaps_recomputed AS gaps, r.events_left AS events_left, r.preferences_still_citing AS preferences_still_citing,
       r.graph AS graph, r.at AS at
ORDER BY at DESC, person
LIMIT 20
