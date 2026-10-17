// id: Q-LEARN-PREFS
// purpose: every learned preference of the tenant (the learned-state panel): per family and action kind, decayed to $now, the Beta-smoothed preference, its counts and its events
// home: oncall
// seen: id, family, events
MATCH (p:Preference)
WITH p, exp(-0.6931471805599453 * toFloat($now - p.computed_at) / $half_life_ms) AS k
RETURN p.id AS id, p.family AS family, p.action_kind AS action_kind, p.approvals * k AS approvals,
       p.rejections * k AS rejections, p.others * k AS others,
       (p.approvals * k + 1.0) / (p.approvals * k + p.rejections * k + p.others * k + 2.0) AS pref,
       p.n_approve AS n_approve, p.n_reject AS n_reject, p.n_family_approve AS n_family_approve, p.n_family AS n_family,
       p.last_at AS last_at, p.last_event_at AS last_event_at, p.computed_at AS computed_at, p.events AS events
ORDER BY family, pref DESC, action_kind
LIMIT 100
