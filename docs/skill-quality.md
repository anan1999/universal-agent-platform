# Skill quality and lifecycle

UAP records quality per Skill ID and exact version. Each use may record success, deterministic
artifact quality, provider/model, invocation count, measured tokens when available, estimated
context tokens, and safety failure state. Missing token data stays unavailable; it is never
fabricated.

Fewer than three comparable runs is `INSUFFICIENT_HISTORY`. A temporary Skill becomes only a
promotion candidate after at least three successful uses and no safety failure. Promotion is not
automatic: a human should review scope, evidence, security, portability, and versioning first.
The platform emits `skill_promotion_candidate` when the third qualifying result is recorded.

Deprecation and retirement are explicit lifecycle states. Historical records remain associated
with their original version. A repaired procedure should be published under a new version and
validated again; V2.2 deliberately does not perform autonomous mutation or promotion.

Artifact evaluation is authoritative when a task declares required files or sections. An Agent
claiming completion cannot override missing deterministic evidence; the task fails and enters the
normal repair/escalation path.

