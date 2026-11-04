# AI Copilot: setup, privacy and troubleshooting

The Copilot answers in three ways, cheapest and most private first. **It works with none of the settings below**; they only
add capability.

| | What answers | Needs | Leaves this computer? |
|---|---|---|---|
| 1 | **Orion itself**: figures, rankings, comparisons, who owes what, records, reminders, reports, exports, small talk, arithmetic | nothing | never |
| 2 | **A model on this computer** (Ollama): open-ended questions, drafting, anything the rules do not recognise | Ollama and a model | never |
| 3 | **A cloud model** (OpenAI or Anthropic): only when the local model could not answer, and only if permitted | an API key, a budget, the organisation's policy and the person's permission | yes, minimised (see "Privacy") |

A subscription to Claude or ChatGPT is not needed and does not help: cloud use is through an *API key*, which is a separate,
pay-as-you-go account. With no key, nothing is ever sent anywhere.

## 1. Orion by itself (nothing to set up)

Ask "How are we doing this month?", "Who are my top 10 customers?", "Why did revenue fall last month?", "Compare September with
August", "Who owes us the most?", "How many clients do we have?", "What is 15% of 2,40,000?", "Remind me to chase Acme next week",
"Create a receivables report", "Delete client CL-0007" (it asks you to confirm). The application works out the answer from the
real data with the same code the dashboards use and writes it in plain words. What it does not recognise goes to a model.

The answer is marked **Orion** when it was made this way.

## 2. A local model with Ollama

Do this on the computer that runs Orion (the API runs there; browsers only talk to the API).

1. Install Ollama: <https://ollama.com/download>. It starts a small service on `127.0.0.1:11434`.
2. Download a model. Choose by the computer:
   * No graphics card, 8 GB of memory (like the dev PC): `ollama pull qwen2.5:1.5b-instruct` (about 1 GB, about 11 words a second on a 2-core i3) or
     `qwen2.5:3b-instruct` (about 2 GB, slower, better). Common questions are answered by Orion itself in under a second either way.
   * A graphics card or 16 GB or more: `ollama pull qwen2.5:7b-instruct` or a larger model of your choice.
   * Use a model that supports **tools** (the Copilot looks things up with tools). `ollama show <model>` lists "tools" under
     capabilities. A model without tools can still chat, but cannot answer data questions it has to look up; Orion's own answers
     (above) still cover the common ones.
3. Tell Orion which model, in `.env` (never committed), then restart the API:

   ```
   ORION_AI_LOCAL_PROVIDER=ollama
   ORION_AI_LOCAL_MODEL=qwen2.5:3b-instruct
   ```

   Leave `ORION_AI_LOCAL_MODEL` empty to use the first model Ollama has.
4. Settings > **AI Copilot** > *How answers are made* > **Check now**. It shows Running, the model, and how long a trivial reply took.

Other settings (all optional): `ORION_AI_LOCAL_URL` (default `http://127.0.0.1:11434`), `ORION_AI_LOCAL_CONTEXT` (tokens of
context to ask for, default 8192; more uses more memory), `ORION_AI_LOCAL_TIMEOUT` (default 180 s), `ORION_AI_LOCAL_CONCURRENCY`
(answers at once, default 1), `ORION_AI_LOCAL_RETRIES` (extra attempts when an answer fails its checks, default 1),
`ORION_AI_LOCAL_TOOLS` (`auto`, `on`, `off`).

If you run without a local model on purpose (`ORION_AI_LOCAL_PROVIDER=none`), the organisation's policy and each person's standing choice are enough for cloud AI to be used when Orion's own answers do not cover a question. The extra "Use cloud AI for this question" step is only for a local model that is configured but not running.

Ollama is never assumed. If it is not installed, not running, or has no such model, the Copilot says so in plain words, keeps
answering everything Orion can answer itself, and never silently turns to a cloud model.

## 3. Cloud models (optional, off by default)

Three things must all be true before a question can reach a cloud model:

1. **The server allows it**: `.env` has `ORION_AI_CLOUD_ESCALATION=1`, a provider, its key and a model, and a budget:

   ```
   ORION_AI_CLOUD_ESCALATION=1
   ORION_AI_CLOUD_PROVIDER=openai            # or anthropic
   OPENAI_API_KEY=...                        # or ANTHROPIC_API_KEY=...
   ORION_AI_OPENAI_MODEL=<a model you choose>  # (Anthropic defaults to ORION_AI_ANTHROPIC_MODEL, else a Claude Sonnet)
   ORION_AI_CLOUD_MONTHLY_BUDGET_USD=10      # 0 (the default) means no cloud spending at all
   ```

   Optional: `ORION_AI_CLOUD_USER_DAILY` (answers per person a day, default 20), `ORION_AI_CLOUD_RPM` (requests a minute, all
   people, default 20), `ORION_AI_CLOUD_TIMEOUT`, `ORION_AI_CLOUD_RETRIES`, `ORION_AI_CLOUD_PRICE_IN` / `_OUT` (US dollars per million
   tokens, so cost is estimated from tokens; without them each answer is assumed to cost `ORION_AI_CLOUD_EST_PER_REQUEST_USD`, default 0.05).
   `ORION_AI_ROUTING_MODE=local_only` switches cloud off whatever else is set.
2. **The organisation's policy allows it.** An administrator picks one under Settings > AI Copilot (default: *Local only*):

   | Policy | Meaning |
   |---|---|
   | Local only | nothing is ever sent to a cloud model |
   | Never send application data to cloud models | cloud may be used only for questions that need none of your data (a general explanation, a text you typed) |
   | Local first, with approved cloud fallback | the local model answers first; cloud may be tried when it cannot, with minimised data |
   | Cloud allowed for eligible tasks | as above, and for heavy analysis the local model is not retried before cloud is considered |
3. **The person allows it.** Settings > AI Copilot > *Let cloud AI help with my hard questions* (off by default). When the local model
   is not running at all, even that is not enough: the Copilot offers a button, **Use cloud AI for this question**, and nothing is sent unless it is pressed.

Even then a request is **never** sent when it is *sensitive* (it contains or asks about credentials, Aadhaar, PAN, bank, card, IFSC,
GST or phone numbers, email addresses, or pay and personal records), when the budget or the person's daily allowance is used up,
when the cloud provider is failing (a circuit breaker leaves it alone for a minute), or when the rate limit is reached.

## Privacy: what a cloud model is given

* The person's **question**, and the page's tab and filters. Not the conversation so far, not who is asking.
* Figures the application retrieved to answer it, with **names** (clients, cases, domains) replaced by labels such as "Party 1",
  and any phone, email, PAN or similar still found in them replaced by `[phone]`, `[email]`... The answer's labels are turned back into names on the way back.
* A bounded amount: the question is limited to 4,000 characters and each retrieved result to about 14,000.

This reduces what the provider learns; it does not make the data safe to send, which is why the policy and the person decide, not the
masking. Every answer shows where it was made (**Orion**, **Local AI**, or **Cloud AI · provider**); the label comes from the server and
is never "Local AI" for something that went to a cloud model.

What is recorded: for each answer, the category, who answered (application, local, cloud), the model, reasons as short codes,
attempts, time, tokens, estimated cost and outcome (`ai_route_log`). **Never** the question, the answer or any data. Each tool call
also goes in the audit trail (`ai_audit`) as before.

## How a request is routed

1. A **classifier** (rules, no model) puts it in a category: A conversation, B dashboard, C retrieval, D calculation, E summary, F multi-step
   reasoning, G document analysis, H code, I action, J sensitive. `POST /api/ai/route/explain` shows the category and what would happen without running anything.
2. If a **rule recognises** it, Orion answers by itself (tools plus plain-words templates). These patterns are narrow on purpose: a wrong guess is worse than asking a model.
3. If the rules do not recognise it but it looks like a question about the data, the **local model reads it into a short form** (`routing/interpret.py`):
   which of a fixed list of intents is this, and a metric, period, record type or name. Its answer is forced into a JSON schema, checked against the
   words of the question (a reading the words do not support is thrown away, and a name the question does not contain is dropped), and turned into the
   same tool calls the rules make. Orion then does the lookup and writes the answer, so the model can neither invent a figure nor call anything outside
   the list. This is what makes a very small model useful: it is bad at free tool calling but good at filling in a form. Client and case names are
   recognised from the database in any case ("is sunrise school paying?").
4. Otherwise the **local model** converses with it, with only the dozen or so tools that suit the request (a small model cannot weigh thirty). Its answer is checked:
   it must not be empty, must not state figures without having looked anything up, its figures must match what the tools returned,
   and its tool calls must not keep failing. A model that looked nothing up, when the figures can be looked up, is sent back once; on the last try only a
   short question back to the person is accepted ("I'll look at the revenue..." is a plan, not an answer). A failed answer is retried (once by default) with a note of what was wrong.
5. If it still fails, or cannot be used (no tool support, too large for its context, not running), the **policy** decides whether a cloud
   model may be tried. If not, the person is told why in one line. If the only flaw was unmatched figures, the local answer is shown flagged;
   an ungrounded answer is never shown as an answer.
6. Everything is bounded: attempts, timeouts, one answer at a time on the local model, a circuit breaker per provider.

## Troubleshooting

| You see | Cause and fix |
|---|---|
| "The local AI model is not running" | Start Ollama (it runs as a service after install; on Windows look in the system tray). Then *Check now*. |
| "Model not installed" | `ollama pull <model>` for the name in `ORION_AI_LOCAL_MODEL`, or clear that setting. |
| "The local AI model can't look things up in your data" | That model has no tool support. Pull one that does (`ollama show <model>`), or set `ORION_AI_LOCAL_TOOLS=on` to try anyway. |
| Slow first answer | The model is loading into memory. Later answers are faster. A computer without a graphics card is slow with larger models. |
| "Neither the local AI nor the cloud AI could complete that" | Both failed or timed out. Raise `ORION_AI_LOCAL_TIMEOUT`, or try a simpler question. See the API log for the technical reason. |
| Cloud AI shows "Not permitted" | The organisation's policy is *Local only* (an administrator changes it), or `ORION_AI_CLOUD_ESCALATION` is 0. |
| Cloud AI "Needs your permission" | Turn on *Let cloud AI help with my hard questions* in your settings. |
| Cloud never used though allowed | `ORION_AI_CLOUD_MONTHLY_BUDGET_USD` is 0 (no spending), the key or model is missing, or the question was sensitive. *Check now* (administrators) tests the cloud key. |

Test report for the routing rules: [ai-routing-test-report.md](ai-routing-test-report.md) (regenerate with `scripts/ai_routing_report.py`).
