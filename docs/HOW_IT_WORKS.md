# How the automation metrics dashboard works (plain-English walkthrough)

Use this to explain the project in an interview.

## "What problem does it solve?"

I run three scheduled AI agents for my CV business: social posts three times a week, a weekly reel and a daily WhatsApp Status pack. Each one logs its run to a Make data store, with notes on anything that went wrong. Reading those notes run by run, I couldn't answer simple questions: how reliable are the agents, what fails most often, did any scheduled run silently never happen, and is this saving me real time? This project answers those questions from the log.

## "Where does the data come from, and how do you keep it safe?"

From the Make API, read-only. The client in `make_client.py` only sends GET requests, so it can't change a scenario or a record. The token lives in a `.env` file that is never committed, and the real database sits in a git-ignored folder. The public demo uses a generated, fictional dataset, so no real data is ever published.

## "How does the sync handle a flaky API?"

Three things:

- **Pagination:** the client asks for 100 records at a time and keeps going until a page comes back short.
- **Retries with backoff:** on a rate limit (429) or a server error (500 to 504), it waits and tries again, doubling the wait each time (2, 4, 8 seconds), or using the server's Retry-After header when given. After four retries it stops with a clear error.
- **Clear failures:** a bad token gives "Make rejected the token (401). Check MAKE_API_TOKEN", not a stack trace. Every sync, including failed ones, is written to a sync log table.

## "Why store raw records separately from the runs?"

So I never lose information and can change my mind about how to interpret it. The raw record is stored exactly as Make returned it, with a hash of its content. On the next sync, a record whose hash hasn't changed is skipped; that's what makes the sync incremental. Runs and incidents are derived from the raw records, so when I improve the incident rules, `amd rebuild` re-derives everything without calling the API again.

## "How do you classify what went wrong?"

With rules first. `config/incident_rules.yaml` lists categories, each with a severity and a few regular expressions. "Generation failed" means the design step failed. "Built by copying the checked layout" means the agent used its fallback. "Bad Gateway ... not re-run" means the agent confirmed the run had worked rather than posting twice.

The severities matter for the story the numbers tell:

- **failure**: nothing was delivered
- **recovered**: something went wrong, but the agent handled it itself
- **warning**: delivered, but the result couldn't be confirmed

A high count of recovered incidents with a high success rate means the guardrails I built into the agents are working. A rising failure count is what needs attention.

## "Where does AI come in?"

Only where rules fall short, and only as a suggestion. `amd unclassified` lists run notes that no rule matched. With AI switched on, it asks Claude (through the Claude Code CLI, using my normal plan, no API key) or a local Ollama model to suggest a category. The answer must be valid JSON naming one of the known categories, or it's discarded. A person then decides whether to turn it into a rule. The AI never writes to the database.

## "How do you know a scheduled run was missed?"

Each automation has a schedule in `config/agents.yaml`. For every day in the period, the metrics code works out which slots were due (social posts on Monday, Wednesday and Friday, WhatsApp packs daily) and checks whether a run was logged for that day. The weekly reel is covered by a run anywhere in its week, because a late reel still counts. A slot with no run at all is a missed run, which usually means the scheduler didn't fire. The real log had exactly that: three days in November with no WhatsApp pack.

## "Isn't 'hours saved' made up?"

It's an estimate, and the dashboard says so. Each automation has a stated assumption (for example, 60 minutes to make and post a social graphic by hand), and hours saved equals successful runs times that assumption. The assumptions are in a config file and shown on the dashboard, so anyone can disagree with them and change them.

## "How do you know it works?"

There are 35 automated tests. The Make API is replaced with a fake, so tests cover pagination, retry timing, the 401 message and running out of retries without touching the network. A one-week fixture with every kind of outcome checks the exact KPIs, which days are flagged as missed, and the platform rates. Other tests cover incremental sync, rebuilding after a rule change, the alerts, the AI response parser and a full render of the dashboard. GitHub Actions runs everything on every push.

## "What would you add next?"

- Cost per run, once the agents log token usage.
- Accuracy tracking: sampling published posts and recording whether a person would have approved them, to measure output quality as well as reliability.
- Pulling scenario execution history from the Make API to cross-check the agents' own logs.
