# Idea Draft — NeuroCare: a Cognitive Substrate for Neurodivergent People (Alexa+ Track)

> Name: **NeuroCare**
> Track: Alexa+ (self-hosted MCP server, Streamable HTTP, spec 2025-11-25+)
> Mini-challenges: AWS Builder, Open Source

## One-liner

An MCP server that gives Alexa+ what a neurodivergent brain often has to supply by hand:
**memory**, **a sense of time**, **a translator for social and corporate ambiguity**, and
**a guardrail** that refuses to amplify rumination, hyperfocus, or sycophancy.

Self-identification is sufficient. No diagnosis gating, no medical data.

## Problem

Alexa+ is a capable conversational agent, but each conversation is largely stateless and
context-free. For ADHD, autistic, and other neurodivergent users, the hard parts of the day
are rarely "set a timer". They are:

- **Losing the thread** — forgetting what you were doing after an interruption, dropping
  open loops, re-explaining context every time.
- **Time blindness** — not feeling how long has passed, underestimating transitions,
  missing the moment to leave.
- **Ambiguous communication** — "per my last email", "let's circle back", a terse message
  from a manager. Decoding intent and tone costs real energy and causes anxiety.
- **Loops that feed themselves** — rumination on the same worry, hyperfocus that skips
  food and water, and assistants that agree with whatever the user says.

A general-purpose assistant can make these worse: it's endlessly willing to re-analyze a
worry, never notices four hours have passed, and tends toward agreement.

## Solution

A **cognitive substrate**: a self-hosted MCP server that sits under Alexa+ and provides
persistent state, temporal awareness, contextual interpretation, and restraint. Alexa+ supplies
the language and reasoning; the substrate supplies what it lacks.

### Design principles

1. **Self-ID is enough.** Anyone who finds it useful can use it. No diagnosis, no labels stored.
2. **Information, not instruction.** Surface facts ("you started 70 min ago") rather than scold.
3. **User stays in charge.** Every threshold is configurable; every guardrail has an override.
4. **Literal, low-demand language.** Configurable per user: step size, tone, urgency wording.
5. **Honest uncertainty.** The translator gives confidence and alternatives, never false certainty.

## The four pillars

### 1. Memory

Persistent, user-owned context across conversations.

| Tool / Resource | Purpose |
|---|---|
| `remember(fact, kind)` | Store a fact, person, preference, or commitment |
| `recall(query)` | Retrieve relevant memory |
| `what_was_i_doing()` | Restore context after an interruption |
| `open_loops()` | Unfinished tasks, promises, pending replies |
| `profile` (resource) | Communication preferences, step size, triggers, people map (e.g. "Priya: manager, blunt, not angry") |

### 2. Sense of time

Makes elapsed and remaining time tangible.

| Tool | Purpose |
|---|---|
| `now_context()` | Current time, time on current task, next hard commitment, transition buffer ("leave in 22 min; you usually need 15") |
| `start_block(task)` | Begin a tracked block of work |
| `check_in()` | Drift detection: "You started the email 70 min ago" |

**Constraint:** the MCP server cannot push to the device on its own. Time-based nudges are
delegated by returning guidance for Alexa to set native reminders.

### 3. Ambiguity translator

Decodes social and corporate messages using the user's relationship context.

`decode(message, sender?)` returns:

- **Literal meaning**: what the words actually say
- **Likely intent**, with confidence and alternative readings
- **Emotional temperature**: neutral / warm / tense
- **Reply needed?** And by when
- **Suggested reply** in the user's own register

Relationship memory is what sets this apart from asking a bare LLM: the same message
from a blunt manager and from a usually warm colleague means different things. Decoding runs
on Amazon Bedrock inside the server for consistent, testable output.

### 4. Guardrail

Refuses to amplify patterns the user has asked it to watch for.

- **Rumination:** `log_topic(topic)` tracks repeated returns to the same worry. Past a
  user-set threshold, tool results direct Alexa to stop re-analyzing and offer one concrete
  action or a deliberate switch.
- **Hyperfocus:** combines elapsed time with body needs ("4h, no water logged"), framed as
  information.
- **Sycophancy:** `reality_check(claim)` returns a counter-view and relevant evidence from
  memory. Server instructions ask Alexa to prefer accuracy over agreement.
- **Override:** "I know, keep going" is always respected and logged.

**Honest limit:** the server influences Alexa only through server instructions, tool
descriptions, and tool results. It never sees Alexa's final reply, so the sycophancy
guardrail is best-effort. We'll document this in the friction log as product feedback.

## Safety

- **Crisis path overrides everything.** If rumination content shows distress or self-harm
  signals, all redirect/coaching logic stops. The response gives crisis resources. It never
  "redirects away" from a crisis.
- **No medical claims.** Positioned as a productivity and communication aid, not treatment.
- **Sensitive data by default.** Minimal collection, encrypted at rest, no personal content in logs.
- **User owns the data.** Export-all and delete-all tools.
- **No real personal data in the demo.**

## Architecture (initial)

> Superseded in detail by the locked spec: [`docs/spec.md`](docs/spec.md).

```
Alexa+ ──Streamable HTTP──▶ MCP server (Python, mcp v2 MCPServer)
                              ├── memory store   (SQLite local / DynamoDB on AWS)
                              ├── time engine    (blocks, commitments, buffers)
                              ├── translator     (Amazon Bedrock)
                              └── guardrail      (topic loop counts, thresholds, crisis check)
```

## Build order (MVP first)

1. **Memory + profile**: foundation for everything else
2. **Sense of time**
3. **Ambiguity translator**
4. **Guardrail**: rumination first; hyperfocus next; sycophancy as stretch

Each step is demoable on its own. Three solid pillars beat four half-built ones.

## Demo arc (≤ 3 min): "One day"

1. **Morning:** "What was I doing yesterday?" Memory restores context and open loops.
2. **Work:** A vague message from a manager is decoded, with a suggested reply.
3. **Afternoon:** Hyperfocus check-in: "You've been on this 3.5 hours. Water?"
4. **Evening:** Third loop on the same worry. The guardrail redirects to one concrete action.

## Judging fit

| Criterion | How we address it |
|---|---|
| Tech Implementation | Spec-compliant Streamable HTTP MCP server; tools, resources, server instructions; Bedrock |
| Design | Voice-first, low-demand, user-configurable; coherent single-day story |
| Potential Impact | Large, underserved audience; self-ID widens reach; validated with real users |
| Quality of Idea | Substrate framing uses Alexa+ for what it's good at and supplies what it lacks |

## Submission checklist

- [ ] Public repo, open-source license (Open Source mini-challenge)
- [ ] AWS usage documented: Bedrock, DynamoDB (AWS Builder mini-challenge)
- [ ] Demo video < 3 min, English, public
- [ ] Product feedback on every tool, API, and SDK used
- [ ] Friction log (up to 10% bonus)
- [ ] Test with 2–3 neurodivergent people before recording; quote them
- [ ] Confirm the real deadline on Devpost (page text currently looks garbled)

## Open questions

- Does Alexa+ honor MCP server `instructions`, and how strongly? (Mitigations in [spec §12](docs/spec.md#12-open-risks); verify during testing.)
- ~~Does Alexa+ support MCP sampling or elicitation?~~ Resolved: design assumes no; server calls Bedrock itself ([spec §2](docs/spec.md#2-alexa-constraints-and-design-responses)).
- ~~Auth/account linking model for a per-user memory store.~~ Resolved for MVP: bearer token → single `user_id`; OAuth 2.1 later ([spec §3](docs/spec.md#3-locked-decisions)).
- ~~Final name.~~ Resolved: **NeuroCare**.
