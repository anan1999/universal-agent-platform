# URL-only bootstrap acceptance (2026-09-16)

## Question

Can a fresh AI task receive only a project goal and
`https://github.com/anan1999/universal-agent-platform`, then actually use UAP?

The test message was exactly a small expense-tracker goal plus that URL. The Codex test
project had no files, no `AGENTS.md`, and no UAP configuration. The isolated virtual
environment initially had no UAP installation. No user project was modified.

## Results

| Check | Result | Evidence |
|---|---|---|
| Fresh Codex task, URL-only, host-controlled approvals | **FAIL for UAP bootstrap** | Codex could not retrieve GitHub, built the tracker independently, and reported that limitation. Its four tracker tests passed, but `.agent/project.yaml` and platform setup were absent. Provider-reported usage: 26,499 tokens. |
| Fresh Codex task, URL-only, host network reachable | **INCONCLUSIVE for normal write-capable assistants** | The host could `git ls-remote` the repository, but the nested Codex task was forced into a read-only sandbox, could not retrieve the URL, and could not write. It reported the limitation. Provider-reported usage: 24,462 tokens. |
| Clean virtual environment, direct GitHub installation | **PASS** | `pip install git+https://github.com/anan1999/universal-agent-platform.git` resolved `cd91b0a`, built a wheel, and installed UAP 2.3.1 with dependencies. |
| Outside source checkout: setup, init preview, init, doctor, prepare | **PASS** | A new temporary Git project and separate platform home passed all commands. `prepare --read --json` returned `mode: direct`, zero provider calls. |
| First repeated `init --auto` | **FAIL for byte-for-byte idempotency** | A fresh project's `AGENTS.md` gained two blank CRLF lines before `<!-- UAP:START -->` on the second init. Project config remained unchanged and there was still one marker pair. |
| Third `init --auto` | **PASS for stability after normalization** | `AGENTS.md` content was unchanged from the second init. |

## Interpretation

The GitHub installation and CLI bootstrap path work without a nearby source checkout. The
stronger claim that *any* AI will activate UAP from only a URL is not proven: URL retrieval,
terminal access, and permission to install/write are external prerequisites. The README now
states those limits, but a repository cannot enforce its instructions until the AI actually
reads it. An AI that cannot read the URL must not claim UAP is active.

The next useful acceptance test is a fresh task in a normally writable, GitHub-connected AI
host. Check the actual `.agent/project.yaml`, `AGENTS.md`, platform setup, doctor result,
and `prepare` output—not just the AI's final text. The first-repeat marker whitespace
change is a separate idempotency defect to fix before calling init fully stable.
