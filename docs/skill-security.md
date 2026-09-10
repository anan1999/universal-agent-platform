# Skill security

Skill files are instructions and must be treated as untrusted input until their provenance is
known. Trust states are `built_in`, `trusted`, `project_local`, `unverified`, `review_required`,
and `blocked`. Lifecycle status is separate from trust.

The static validator blocks known destructive deletion, blind remote-script execution, and
instructions that request secret access. Any unverified Skill declaring scripts, shell, network,
or tools remains `review_required`; execution requires an explicit `skill:<id>` approval. Generated
temporary Skills default to no scripts, network, or filesystem writes and never silently replace
an existing package.

Validation is defense in depth, not a sandbox. Review executable Skills, pin versions, keep
credentials in environment or secure configuration references, and retain the platform command
allowlist and normal approval gates. Never place secret values in a manifest, instructions,
project configuration, events, or receipts.

