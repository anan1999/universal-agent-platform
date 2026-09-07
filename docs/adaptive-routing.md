# Adaptive routing

Explorer and Tester default to `gpt-5.6-luna / low`; Developer and Reviewer use `gpt-5.6-sol / medium`; specialists use Sol, with high reasoning only for high-risk work. Astra remains an explicit strongest-class interface and is never selected by default.

Routing considers task type, role, risk, required capabilities, budget rules, and comparable performance history. Fewer than five samples never changes the baseline. After five samples, a cheap route upgrades only when its escalation rate exceeds the configured threshold. Every decision stores a human-readable reason.

Escalation follows cheap → standard → strong with at most two escalations. Authentication, environment, tool, and timeout failures stop without model escalation.

