# Verification

One file per build phase (`docs/spec.md` §11). Each has: what "done" means, manual steps you can
run in the Inspector, decisions to review, known gaps, a sign-off checklist, and an automated
**Proof** section captured from a live server run.

| Phase | File | Status |
|---|---|---|
| 2 · Sense of time | [phase-2.md](phase-2.md) | merged |
| 3 · Translator + Bedrock wrapper | [phase-3.md](phase-3.md) | merged; live Bedrock test needs you |

[FINDINGS.md](FINDINGS.md) collects every bug, gap, and decision across phases.

## Re-running a proof

```bash
scripts/prove.sh scripts/smoke/phase2.yaml          # prints Markdown to stdout
scripts/prove.sh scripts/smoke/phase2.yaml out.md   # or to a file
```

It seeds a temporary SQLite file, starts the server on port 8765 (`PROOF_PORT` to change) with a
static token, checks an unauthenticated request gets 401, runs the steps over Streamable HTTP, and
stops the server. Steps with `expect:` fail the run when a field doesn't match.
