// id: Q-BASE-BAND
// purpose: the gate band of a healthy baseline series computed in the engine (avg, stDevP, percentileCont over the nonzero baseline windows); band = max(floor, 1 + k * sd / mu), fewer than two nonzero windows give the floor; Python only rounds it to 4 places
// returns: single-row
MATCH (w:MetricWindow {target_id:$target, metric:$metric, kind:'baseline'})
WITH count(w) AS n, count(CASE WHEN w.value <> 0 THEN 1 END) AS n_nz,
     avg(CASE WHEN w.value <> 0 THEN w.value END) AS mu,
     stDevP(CASE WHEN w.value <> 0 THEN w.value END) AS sd,
     percentileCont(CASE WHEN w.value <> 0 THEN w.value END, 0.95) AS p95
WITH n, n_nz, mu, sd, p95,
     CASE WHEN n_nz < 2 THEN null WHEN mu = 0 THEN 1.0 ELSE 1.0 + $k * (sd / mu) END AS raw
RETURN n, n_nz, mu, sd, p95, raw, CASE WHEN raw IS NULL OR raw < $floor THEN $floor ELSE raw END AS band
LIMIT 1
