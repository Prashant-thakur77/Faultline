/*
 * Faultline's own FalkorDB UDF library: the arithmetic that turns graph facts into a ranking, run inside the engine.
 *
 * Loaded with `GRAPH.UDF LOAD REPLACE faultline <this file>` after its sha256 is checked (backend/faultline/graph/udf.py)
 * and called from read-only templates as faultline.<name>(...), so the blast radius, the notify list and a recall of
 * shared agent notes come back from FalkorDB already scored and ordered. Pure functions over numbers: no graph
 * access, network, require, eval or Function.
 * Every weight arrives as a query parameter read from backend/faultline/agent/weights.yaml (numbers come from code).
 */

/**
 * Weight of a component's tier: tw[tier - 1] for tiers 1..tw.length; a missing, zero or unknown tier counts as tier 3
 * (the same rule as agent/weights.py::tier_weight).
 *
 * @param {number[]} tw tier weights, index 0 = tier 1
 * @param {number|null} tier
 * @returns {number}
 */
function tierWeight(tw, tier) {
	const t = (tier === null || tier === undefined || tier === 0) ? 3 : Math.trunc(tier);
	return (t >= 1 && t <= tw.length) ? tw[t - 1] : tw[2];
}

/**
 * Blast-radius impact of a reachable node: tier weight × 1/(1+hops) × ln(1 + traffic + 1).
 * A missing or zero hop count counts as 1 and negative traffic as 0, as mcp_server/tools.py::impact did in Python.
 *
 * @param {number[]} tw tier weights
 * @param {number|null} tier
 * @param {number|null} hops shortest hop distance (algo.SSpaths)
 * @param {number|null} traffic bottleneck capacity × 100
 * @returns {number}
 */
function impact(tw, tier, hops, traffic) {
	const h = hops ? hops : 1;
	return tierWeight(tw, tier) * (1.0 / (1 + h)) * Math.log1p(Math.max(traffic ? traffic : 0.0, 0.0) + 1.0);
}

/**
 * What an owning team stands to lose at a node in the blast radius: tier weight × bottleneck cap / (1 + hops).
 *
 * @param {number[]} tw tier weights
 * @param {number|null} tier
 * @param {number|null} cap bottleneck capacity on the best path (algo.SSpaths)
 * @param {number} hops shortest hop distance
 * @returns {number}
 */
function capImpact(tw, tier, cap, hops) {
	return tierWeight(tw, tier) * (cap ? cap : 0.0) / (1 + hops);
}

/**
 * Python's round(x, 4): nearest on the exact binary value, an exact half to even. x·10⁴ ends in exactly .5 only when
 * x·32 is an odd integer (x = k/32), which the power-of-two product tests exactly; toFixed rounds every other value
 * on its exact binary value. Engine and code therefore agree on every rounded number.
 *
 * @param {number|null} x
 * @returns {number|null}
 */
function round4(x) {
	if (x === null || x === undefined || !Number.isFinite(x)) {
		return x;
	}
	const t = x * 32;
	if (Number.isInteger(t) && Math.abs(t) % 2 === 1) {
		const lo = Math.floor(x * 10000);
		return (lo % 2 === 0 ? lo : lo + 1) / 10000;
	}
	return parseFloat(x.toFixed(4));
}

/**
 * Rank of a shared agent note for a recall: w[0] × similarity to the question (vector index) + w[1] × 1/(1+hops) from
 * the component asked about (graph distance) + w[2] × e^(−age/τ) with τ = w[3] minutes. A note found by only one of
 * the two routes gets 0 for the other; weights from weights.yaml `notes`.
 *
 * @param {number[]} w [w_meaning, w_near, w_fresh, fresh_tau_min]
 * @param {number|null} sim cosine similarity, or null when the note was found by graph distance only
 * @param {number|null} hops hops from the component asked about, or null when found by meaning only
 * @param {number} ageMin minutes since the note was written
 * @returns {number}
 */
function noteScore(w, sim, hops, ageMin) {
	const meaning = (sim === null || sim === undefined) ? 0.0 : sim;
	const near = (hops === null || hops === undefined) ? 0.0 : 1.0 / (1 + hops);
	return w[0] * meaning + w[1] * near + w[2] * Math.exp(-Math.max(ageMin, 0.0) / w[3]);
}

falkor.register('tierWeight', tierWeight);
falkor.register('impact', impact);
falkor.register('capImpact', capImpact);
falkor.register('round4', round4);
falkor.register('noteScore', noteScore);
