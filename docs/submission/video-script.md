# Demo video script (target 2:50)

The rules allow narration, music, and shortened waits, as long as everything shown is real and
running. Record the simulator in Chrome at 1920×1080 with the dev panel **off**, except where noted.
Cut the model wait (about 2 s per turn) in editing.

## Before recording (10 min)

1. Re-seed, so "What was I doing?" says about 40 minutes:
   `AWS_PROFILE=neurocare-deployer AWS_REGION=us-east-1 STORE=dynamo DEMO_USER_ID=84f8e4b8-10c1-7043-0e96-03269bcbc164 uv run alexa-mcp-seed --reset`
2. Warm both Lambdas: open the simulator, then type "ping" once and discard it.
3. Check the link: green dot. Unlink and re-link once on camera if you want to show the linking
   (see 0:25).
4. Close other tabs, turn notifications off, and use a quiet room. Test the mic level.
5. Have the message for the decode step on the clipboard (see 1:05).

## Shots

| Time | On screen | Narration (you) / spoken to Alexa |
|---|---|---|
| 0:00–0:15 | Title card: **NeuroCare — a cognitive substrate for Alexa+** | "For ADHD and autistic people, the hard part of the day isn't setting a timer. It's losing the thread, not feeling time pass, decoding a terse message, and worry loops. NeuroCare gives Alexa+ the memory, time sense, and restraint it doesn't have." |
| 0:15–0:25 | Architecture slide (`docs/diagrams/aws_architecture.png`) | "It's an MCP server over Streamable HTTP on AWS Lambda, with DynamoDB, Cognito account linking, and Bedrock. Entrants can't deploy to real Alexa+, so this is our simulator: a real MCP client, real OAuth, live." |
| 0:25–0:35 | Simulator; click **Link NeuroCare** → Cognito sign-in → green dot *(optional; cut if tight)* | — |
| 0:35–0:55 | Hold mic: **"Alexa, what was I doing?"** | Reply: budget email, about 40 minutes ago, three open things. Narrate: "Context is back after an interruption, in literal words." |
| 0:55–1:05 | **"Plan my day, my energy's low."** | Reply: one priority. "Low energy, so one thing, not three." |
| 1:05–1:35 | Type or paste: **"What does this mean? From Priya: 'Per my last email, I still need the Q3 deck. Can you send it by today?'"** | Reply: most likely she's waiting on you, urgent, reply today at 5, related: your open commitment. Then say **"What should I say?"** for the draft reply. "Decoded with honest uncertainty, linked to a promise I'd made." |
| 1:35–1:55 | **"I don't know where to start with my taxes."** → then **"This one's too big."** | A 5-minute first step, then a smaller one. "One small step at a time. The full plan refines in the background." |
| 1:55–2:15 | **"I keep worrying about the presentation tomorrow."** Say it three times, reworded | The third time: a gentle redirect to one concrete action. "It notices the loop and doesn't feed it. And I can always say 'I know, keep going'." |
| 2:15–2:30 | **"Remind me in one minute to drink water."** Jump cut → chime, yellow light, spoken reminder | "Hyperfocus check-ins and native reminders." |
| 2:30–2:40 | **"Wrap up for today."** | Unfinished items roll to tomorrow. |
| 2:40–2:50 | Dev panel **on**, scroll past the tool calls; then a slide: *29 tools · 26 ms warm server time · 497 tests · crisis precheck on every free-text tool* | "Every reply came from live tool calls on AWS. Crisis language always gets only helplines. Thanks for watching." |

## If something goes wrong

- **The model picks the wrong tool or wording:** re-take; the replies are live, not scripted.
- **"Link your account":** the session expired; click Link NeuroCare.
- **Times look off:** re-seed (step 1). The seed is relative to when it's loaded.
- **Slow first turn:** a Lambda started cold; warm it again (step 2).

## Don't show

- Third-party music without a license, and any real person's messages. The seed data is
  synthetic.
- The crisis path, unless you choose to. If you show it, type the text rather than saying it, and
  keep it brief.
