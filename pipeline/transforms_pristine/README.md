# Pristine transforms

Byte-identical copies of `pipeline/transforms/*.sql` as shipped. `SHA256SUMS` lists their digests, and
`backend/faultline/repair.py::PRISTINE_DIGEST` pins the digest of `SHA256SUMS` itself, so the pristine set cannot drift
without a code change.

Every warehouse mode switch (`scenario.set_pipeline_mode`) and every re-arm restores `pipeline/transforms/` from here
(`repair.restore_pristine`): an approved data repair lasts until the next run sets its fixture mode, never longer
(review round 5, M3). To change a transform on purpose, edit it in both places, regenerate `SHA256SUMS`
(`sha256sum *.sql > SHA256SUMS`) and update `PRISTINE_DIGEST`.
