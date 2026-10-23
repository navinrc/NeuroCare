# Feature requests

| # | Request | Why it matters | Urgency |
|---|---|---|---|
| 1 | **Alexa+ sandbox for MCP add-ons** that hackathon entrants and new developers can use: a development stage plus a hosted test client | Without it nobody can check account linking, tool selection, or latency against the real Alexa+ before shipping | Critical |
| 2 | **Proactive notifications for MCP add-ons** (the chime and yellow light) | Time blindness and hyperfocus need a nudge the user didn't ask for. Stateless MCP can't push; we can only suggest the user set a reminder | Important |
| 3 | **User time zone and locale in the MCP request context** | Every "in 30 minutes", "leave by", and "today" depends on it. Today the server has to guess from the profile | Important |
| 4 | **Cognito: RFC 8414 metadata with `code_challenge_methods_supported` and `grant_types_supported`**, plus a "require PKCE" setting | It lets Cognito be the authorization server for Alexa+ and any MCP server without a proxy | Important |
| 5 | **Lambda Function URLs: pass `WWW-Authenticate` through on 401** (at least opt-in) | MCP authorization discovery depends on it | Important |
| 6 | **MCP Python SDK: an official Lambda handler** (stateless, JSON responses, lifespan once per container) | The most common serverless target needs a custom adapter today | Nice-to-have |
| 7 | **Bedrock Guardrails: a self-harm content category** with optional crisis-resource text | Safety-critical apps currently hand-roll denied topics | Important |
| 8 | **Alexa+ docs: say what the model sees** (do tool descriptions, server instructions, and `structured_content` reach the reasoning model?) and list the redirect URIs inline | Developers tune behaviour only through these levers | Nice-to-have |
