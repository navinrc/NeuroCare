# NeuroCare — a cognitive substrate for Alexa+

**Demo video:** https://youtu.be/tjRjl7ehqKg

**Track:** Alexa+ (self-hosted MCP server, Streamable HTTP, plus the simulated-experience path)

## What it does

NeuroCare is an MCP server that gives Alexa+ what a neurodivergent brain (ADHD, autism, and others)
often has to supply by hand. Self-identification is enough: there's no diagnosis gating and no
medical data.

The hard parts of the day are rarely "set a timer". They are losing the thread after an
interruption, not feeling how much time has passed, decoding a terse message from a manager, and
loops that feed themselves: rumination, hyperfocus that skips food and water, and an assistant that
agrees with whatever you say. NeuroCare sits under Alexa+ and supplies six things:

| Pillar | What you say | What happens |
|---|---|---|
| **Memory** | "What was I doing?" · "Remember Priya is my manager" | Restores the context: the open work block, how long ago it started, and open loops. Recall is tiered (exact → alias → fuzzy → Titan embeddings) |
| **Sense of time** | "How long have I been at this?" · "What's next?" | Elapsed time on the current block, the next commitment, and leave-by buffers; check-ins scale from gentle to firm |
| **Ambiguity translator** | "What does this message mean?" | Likely meaning with confidence, priority, reply-by, the actual ask, a related promise you made, and a draft reply. Prompt-injection-safe: a message is data, never instructions |
| **Task breakdown** | "I don't know where to start with my taxes" | One 5-minute, verb-first first step at once; the full breakdown follows. "Too big" splits a step, "not now" skips it |
| **Daily plan** | "Plan my day, energy's low" · "Wrap up" | Picks at most three priorities, fewer when energy is low; wrap-up rolls unfinished items to tomorrow |
| **Guardrail** | (the third worry about the same thing) | Crisis precheck on every free-text tool (phrase list + Bedrock Guardrails) that answers only with helplines; rumination detection by embedding similarity; hyperfocus check-ins; the user can always override |

Every tool returns a short, literal `speak` line for Alexa to say, plus structured fields for its
reasoning. The design rules: information rather than instruction ("you started 70 minutes ago",
not "you should stop"), every threshold configurable, every guardrail overridable, and honest
uncertainty.

## How it works

- **MCP server** (Python, official `mcp` SDK v2) over **Streamable HTTP**, stateless with JSON
  responses. 29 tools, a `profile://me` resource, and server instructions that tell Alexa+ when to
  call what.
- **Fast first, refine later.** Alexa+ needs a < 500 ms round trip, so every language task returns
  a deterministic baseline at once and refines it with **Claude Haiku 4.5 on Amazon Bedrock** in the
  background: the Lambda invokes itself asynchronously. The next ask reads the refined result.
  Measured on the deployed stack: warm tool calls take 26 ms at the median and 67 ms at most,
  server time.
- **Safety first.** A crisis phrase list plus **Bedrock Guardrails** (`ApplyGuardrail`, 250 ms
  budget, re-run in the background on timeout) short-circuit every tool that takes free text. On a
  hit the tool returns only the crisis message and resources.
- **AWS:** Lambda (arm64) behind a Function URL, DynamoDB single-table design with TTLs, Cognito
  account linking (OAuth 2.1 auth code + PKCE S256, refresh tokens, Protected Resource Metadata per
  RFC 9728), Bedrock (Haiku 4.5, Titan Text Embeddings v2, Guardrails), all deployed with the
  **AWS CDK**.
- **Alexa+ simulator.** Entrants don't get Alexa+ developer tools, so the demo runs on an
  Echo Show–style simulator we built. It is a *real MCP client* of the deployed server: it does
  the real Cognito account-linking flow, sends the server's own instructions and tool list to its
  model (Haiku 4.5 on Bedrock) for tool use, speaks replies with the Web Speech API, and sets
  native-style reminders (chime + yellow light). The server can't tell it from Alexa.
- **Tested:** 497 automated tests, run against both SQLite and a moto-mocked DynamoDB, plus live
  Bedrock tests and a phase-by-phase verification log with live proofs.

## What we built during the hackathon

Everything. The first commit (2026-09-28) is an empty `uv` boilerplate; the spec, the server, the
AWS stack, and the simulator were all built in the submission window. The build history and every
decision are in `log.md` and `docs/verify/`.
