# AI Copilot routing: test report

Generated 08 October 2026, 22:37 by `scripts/ai_routing_report.py`. Providers are stand-ins that count what they were sent, so each scenario
checks not only the answer but what was sent where. No database, network or model is needed.
**56 of 56 routing tests passed.**


## The twelve scenarios

| # | Scenario | Result | What the test checks |
|---|---|---|---|
| 1 | Simple greeting | PASSED | Simple greeting: answered by the application itself; nothing is sent to any model or cloud. |
| 2 | Straightforward dashboard metric | PASSED | A dashboard metric: the backend tool answers it from data, with no model call at all. |
| 3 | Deterministic calculation | PASSED | A deterministic calculation: the backend calculator works it out exactly. |
| 4 | Complex synthesis: local first, cloud only when enabled and permitted | PASSED | Complex synthesis: local first; cloud only after the local answer fails its checks, and only if enabled and permitted. |
| 5 | Cloud escalation disabled: no cloud request | PASSED | Cloud escalation disabled: the local model does its best; no cloud call whatever the policy says. |
| 6 | Sensitive data under a local-only rule: no cloud request | PASSED | Sensitive request: stays on this machine even when the policy, the person and the budget would all allow cloud. |
| 7 | Local model unavailable: graceful, no unauthorised fallback | PASSED | Local model unavailable: a plain explanation and an offer; cloud is used only if the person chooses it for that question. |
| 8 | Invalid structured output: bounded retry, policy-controlled escalation | PASSED | Invalid structured output: bounded local retry, then escalation only if the policy allows. |
| 9 | Cloud budget exhausted: no further spending | PASSED | Cloud budget exhausted: no further cloud request is made. |
| 10 | Unauthorised data request: rejected by backend permissions | PASSED | Unauthorised data request: the tool is refused by the backend permission check; no data, no model. |
| 11 | Destructive action: verified confirmation required | PASSED | Destructive action: only prepared; it runs solely through the server-side confirmation, never on the model's say-so. |
| 12 | Cloud timeout: bounded retry and graceful recovery | PASSED | Cloud timeout: bounded retries, the circuit breaker notes it, and the person gets a plain message. |

Scenarios 1 to 3 go one step further than "use the local model": the application answers a greeting, a dashboard figure or a calculation by itself,
with no model at all, so they cost nothing and work even when the local model is not installed.

## Everything else in the routing tests

### Classifying

| Test | Result |
|---|---|
| a classification can be explained without repeating the question | PASSED |
| classifying costs no model call | PASSED |
| each category is recognised by rules alone | PASSED |

### Planning

| Test | Result |
|---|---|
| a reminder without a date asks instead of guessing | PASSED |
| asking to see a kind of record lists the latest | PASSED |
| asking what brings in the most money is a ranking | PASSED |
| common questions become tool calls | PASSED |
| counting is understood however it is phrased | PASSED |
| explaining a word is left to a model not answered with a report | PASSED |
| money in words is calculated exactly | PASSED |
| periods come from the words the page or a stated default never from guessing | PASSED |
| what needs thought is left to a model and what is dangerous is left to nobody | PASSED |

### Policy

| Test | Result |
|---|---|
| a policy that forbids application data still allows questions that need none | PASSED |
| a stopped local model needs the person to choose cloud for that question | PASSED |
| everything must agree and each failure is named | PASSED |
| the budget is checked against what the next answer could cost | PASSED |

### Minimising

| Test | Result |
|---|---|
| names in retrieved data become labels and come back in the answer | PASSED |
| private identifiers in data are redacted before anything is sent | PASSED |
| the cloud request carries the question and not the conversation | PASSED |

### Guards

| Test | Result |
|---|---|
| a failing provider is left alone for a while then tried again | PASSED |
| an open breaker keeps requests off the local model | PASSED |
| cloud cost is estimated from tokens when prices are known and flat otherwise | PASSED |
| the route log has no place for the question or the answer | PASSED |

### LocalProviderOverTheWire

| Test | Result |
|---|---|
| a tool conversation round trips in ollamas format | PASSED |
| an unknown model and a dead server become provider errors with a kind | PASSED |
| capabilities come from the model not from an assumption | PASSED |
| health reports what is running and which model will be used | PASSED |
| health says so when nothing is listening and when the model is not installed | PASSED |
| only one answer is written at a time by default | PASSED |
| structured output is constrained and validated | PASSED |
| tools are not sent when the caller says the model must answer now | PASSED |

### OpenAIProviderShape

| Test | Result |
|---|---|
| a streamed tool conversation is translated both ways | PASSED |
| sdk failures become provider errors the router can act on | PASSED |

### Interpreting

| Test | Result |
|---|---|
| a form that does not fit hands the question back to the free conversation | PASSED |
| a known client name is recognised in any case by the rules alone | PASSED |
| a model that is down is not asked twice | PASSED |
| a name the question does not contain is an invention and is dropped | PASSED |
| a narration with no lookup is never shown as an answer | PASSED |
| a question the rules miss is read by the local model and answered by orion | PASSED |
| a reading the words of the question do not support is thrown away | PASSED |
| the period the person wrote beats the one the model guessed | PASSED |
| what the model reads is checked against the tools own rules | PASSED |

### Explaining

| Test | Result |
|---|---|
| a request can be explained without being run | PASSED |
| the composed answers say what was assumed | PASSED |

