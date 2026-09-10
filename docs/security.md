# Security

The bundled Dashboard has been removed. The remaining FastAPI surface is a library interface and
has no command-execution route. Project commands are explicit allowlist entries. Secrets are not
persisted. Git errors are surfaced without reset, forced cleanup, or implicit conflict resolution.
Operators should inspect third-party provider commands before enabling them.

