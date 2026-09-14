# Observable action diagnostics

`scripts/direct_benchmark.py` now adds an ordered `telemetry.actions` list to each
side of a fresh-session benchmark. The comparison still uses the same fixture,
goal, provider/model, and frozen acceptance contract. Instrumentation does not
change the executor prompt.

Each completed command/tool/file-change event records only derived metadata:

- Overlapping lexical labels: inspection, editing, validation, environment,
  repository status, or unclassified.
- A command hash and whether identical command text appeared earlier.
- Mentions of a fixed allowlist of public fixture paths.
- Output character count, integer exit code when available, and generic failure
  hints (permission, missing dependency, test failure).

Raw command text, tool arguments, stdout, assistant text and arbitrary paths are
not copied into the report. Hashes are equality fingerprints, not encryption;
do not use this benchmark as a general sensitive-workload telemetry collector.

## Interpretation

A command may read and test in one call, so labels are not exclusive and their
counts must not be summed as tool-call totals. File-change events are separate
from the historical completed-tool-call metric. Repeated commands can be valid
post-edit checks, and a mentioned path is not proof the file was read. Absence of
a lexical hint is not proof no such operation happened. These observations do
not reveal private reasoning, prove necessity, or measure subscription usage.
Per-action duration is unavailable in this buffered event interface.

Before changing runtime behavior, inspect failed validation and environment
retries first, then repeated inspection. Turn verified recurring procedures into
small explicit commands or task-specific recipes. Preserve validation that
provides new evidence; avoid global instructions to simply use fewer tools.
