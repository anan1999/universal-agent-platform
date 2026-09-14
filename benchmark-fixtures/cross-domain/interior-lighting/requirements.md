# Lighting requirements

For every room, calculate `fixture_count = ceil(area_m2 * target_lux / fixture_lumens)` and
`watts = fixture_count * fixture_watts`. Create `deliverable.json` with a `rooms` array, `total_watts`,
`minimum_circuits = ceil(total_watts / max_watts_per_circuit)`, and at least two `design_notes`.
Every room entry must include `id`, `fixture_count`, and `watts`.
