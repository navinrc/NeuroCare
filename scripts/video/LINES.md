# Lines to record

Record each line as its own file in `scripts/video/audio/` (QuickTime → File → New Audio Recording → save as `.m4a`), named by the id. Quiet room, same distance from the mic, about a second of silence before and after. Missing files fall back to a synthetic voice. Then run `scripts/video/render.sh`.

## Narration (calm, like explaining to a friend)

| File | Line |
|---|---|
| `n_title.m4a` | For ADHD and autistic people, the hard part isn't setting a timer. It's losing the thread, time blindness, ambiguous messages, and worry loops. NeuroCare gives Alexa plus what it's missing. |
| `n_architecture.m4a` | It's an MCP server on AWS Lambda, with DynamoDB, Cognito account linking, and Bedrock. Here it runs live, in our Alexa plus simulator. |
| `n_closing.m4a` | Every reply came from live tool calls on AWS. Thanks for watching. |
| `n_u01.m4a` | Context, back after an interruption. |
| `n_u02.m4a` | Low energy: one priority, not three. |
| `n_u04.m4a` | Likely meaning, urgency, and a draft reply. |
| `n_u06.m4a` | One small step at a time. |
| `n_u09.m4a` | Third time around, it notices the loop. |
| `n_u10.m4a` | Native reminders, for hyperfocus. |

## You, speaking to Alexa (natural, as if to a device across the room)

| File | Line |
|---|---|
| `u01.m4a` | Alexa, what was I doing? |
| `u02.m4a` | Plan my day. My energy's low. |
| `u03.m4a` | What does this message from Priya mean? Per my last email, I still need the Q3 deck. Can you send it by today? |
| `u04.m4a` | What should I say? |
| `u05.m4a` | I don't know where to start with my taxes. |
| `u06.m4a` | This one's too big. |
| `u07.m4a` | I'm worried about the presentation tomorrow. |
| `u08.m4a` | I'm worried my presentation will go badly. |
| `u09.m4a` | I'm worried the presentation won't be okay. |
| `u10.m4a` | Remind me in one minute to drink water. |
| `u11.m4a` | Wrap up for today. |
