## Inspiration

For people with ADHD, autism, and other neurodivergent brains, the hard part of the day is rarely
"set a timer". It's losing the thread after an interruption, not *feeling* how long you've been at
something, decoding a terse "per my last email", and loops that feed themselves: the same worry for
the fifth time, hyperfocus that skips water and food, and an assistant that cheerfully agrees with
whatever you say.

Alexa+ is a capable conversational agent, but each conversation starts from nothing. We wanted to
give it what a neurodivergent brain often has to supply by hand: **memory, a sense of time, a
translator for ambiguity, and restraint.** Self-identification is enough. There's no diagnosis
gating and no medical data.

## What it does

NeuroCare is an MCP server that sits under Alexa+ as a *cognitive substrate*. It has six pillars
and 29 tools:

- **Memory:** "What was I doing?" brings back the open work block, how long ago it started, and
  your open loops. Recall is tiered: exact → alias → fuzzy → Titan embeddings.
- **Sense of time:** elapsed time on the current task, what's next, and leave-by buffers.
  Check-ins scale from gentle to firm.
- **Ambiguity translator:** "What does this message mean?" gives the likely meaning with
  confidence, priority, the actual ask, a related promise you made, and a draft reply. The
  message is treated as data, never as instructions (prompt-injection safe).
- **Task breakdown:** "I don't know where to start" gives one 5-minute, verb-first step at once.
  "Too big" splits it; "not now" skips it.
- **Daily plan:** at most three priorities, fewer when your energy is low. "Wrap up" rolls
  unfinished work to tomorrow.
- **Guardrail:**
  - A crisis precheck on every free-text tool returns only helplines.
  - Rumination is detected by embedding similarity: the third similar worry inside the window
    triggers a gentle redirect,
    $$\cos(\theta) = \frac{\mathbf{a}\cdot\mathbf{b}}{\lVert\mathbf{a}\rVert\,\lVert\mathbf{b}\rVert} \ge 0.40 .$$
  - Hyperfocus check-ins.
  - The user can always override ("I know, keep going").

Every tool returns a short, literal `speak` line. The design rules: **information, not
instruction** ("you started 70 minutes ago", not "you should stop"), every threshold configurable,
every guardrail overridable, honest uncertainty.

## How we built it

- **MCP server:** Python with the official `mcp` SDK v2, served over **Streamable HTTP**, stateless,
  with JSON responses. It has tools, a `profile://me` resource, and server instructions that tell
  Alexa+ when to call what.
- **Fast first, refine later.** Alexa+ needs a round trip under 500 ms, so every language task
  returns a deterministic baseline immediately. The Lambda then **invokes itself asynchronously**
  to refine the result with **Claude Haiku 4.5 on Amazon Bedrock**, and the next ask reads the
  refined result. Warm tool calls measure **26 ms median, 67 ms max** of server time.
- **Safety:** a phrase list first, then **Bedrock Guardrails** `ApplyGuardrail` (a self-harm denied
  topic plus the Violence filter). It has a 250 ms budget and re-runs in the background on timeout.
  A hit there makes the next call return the crisis message first.
- **AWS:**
  - Lambda (arm64) behind Function URLs;
  - DynamoDB, a single-table design with TTLs;
  - Cognito account linking: OAuth 2.1 auth code + PKCE S256, refresh tokens, and Protected
    Resource Metadata per RFC 9728;
  - Bedrock: Haiku 4.5, Titan Text Embeddings v2, Guardrails;
  - all of it in **AWS CDK**.
- **Alexa+ simulator.** Entrants can't deploy to real Alexa+, so we built an Echo Show–style
  simulator. It is a *real MCP client* of the deployed server:
  - real Cognito account linking;
  - the server's own instructions and tool list, sent to Bedrock for tool use;
  - Web Speech API voice;
  - native-style reminders (chime + yellow light).
  The server can't tell it from Alexa.
- **Testing:** 497 automated tests. Every store-backed test runs on both SQLite and a moto-mocked
  DynamoDB. There are also live Bedrock tests, and a verification doc with live proofs for every
  build phase.
- **The demo video** is one scripted live take of the deployed stack, recorded with Playwright and
  cut with ffmpeg, so it can be re-rendered exactly.

## Challenges we ran into

- **No Alexa+ developer access for entrants.** We built account linking before learning the
  `alexa-ai` tools weren't available. The simulator turned that into a feature: a real MCP client
  with real OAuth.
- **Cognito's metadata doesn't meet Alexa+'s linking requirements.** It has no
  `code_challenge_methods_supported`, and `/.well-known/oauth-authorization-server` returns 400.
- **Lambda Function URLs rename `WWW-Authenticate`** on a 401 to
  `x-amzn-Remapped-www-authenticate`. That breaks standard MCP auth discovery, so we also serve the
  metadata at the root path.
- **The MCP SDK's session manager starts once per instance,** which breaks the usual Lambda
  adapter. We wrote a small adapter that keeps one event loop and one lifespan per container.
- **Real embeddings aren't test embeddings.** Reworded worries scored a cosine of 0.44–0.70 on
  Titan v2, not the 0.8 we had assumed. We tuned the threshold from live data.
- **Two deploy bugs found only live.** An import-order bug published `127.0.0.1` as the OAuth
  resource URL, and importing a shared adapter started a whole server inside the simulator's
  Lambda. Both now have tests that catch them.

## What we learned

- With voice, latency is a design constraint, not an optimisation. "Fast first, refine later"
  shaped every tool.
- Restraint is a feature. The most useful thing an assistant can do in a worry loop is *not* to
  analyse the worry again.
- Spec-first, phase-gated building, where each phase gets a verification doc and a live proof,
  caught bugs that unit tests never would.

## What's next

- A Telegram companion for forwarded messages and opt-in nudges (designed in the spec).
- Proactive notifications, if Alexa+ opens them to MCP add-ons.
- Running on real Alexa+ once the developer tools are available.
