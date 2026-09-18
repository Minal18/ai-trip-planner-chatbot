# Pending / Deferred Items

Things deliberately deferred during development, with the reasoning for revisiting later.

## Planner: "not consistent → re-invoke Researcher" escalation path

Not built. Planner currently only retries within its own loop (re-picking from
`research_results` already in hand) when its selected combination is inconsistent
(e.g. mismatched dates across domains) — it does not escalate back to Researcher to
search again.

**Why deferred**: in practice, flights and hotels almost always have *some*
availability for a given window — pricing varies, availability rarely doesn't
exist at all. Cars are the domain most likely to have genuine day-specific
unavailability in the real world, but since Cars currently runs on mock data
(Duffel access still pending — see `mcp-servers/cars/README.md`), this scenario
isn't meaningfully testable yet anyway.

**Revisit when**: real Cars API access is granted and genuine unavailability
becomes observable, or if flights/stays empty-intersection cases turn up in
practice despite the above assumption.

## §7.1 Supervisor subgraph diagram readability

The Mermaid diagram in `docs/architecture.md` §7.1 (added when Supervisor's
edit-feedback classification was designed) is hard to read — too many branches
crammed into one diagram once the `classify_edit_feedback` node and its three
sub-outcomes were added on top of the original state-check branches.

**Why deferred**: not blocking implementation — the diagram is still accurate,
just visually dense. Not worth redesigning mid-build.

**Revisit when**: implementation of Planner/HITL/edit-classification is done and
stable, so the diagram can be redrawn once (e.g. splitting the state-check
branches and the edit-classification sub-flow into two separate diagrams) rather
than reworking it repeatedly while the design is still moving.

## Chat UI

Not built. All testing so far has been via terminal REPL scripts
(`agent/tests/test_supervisor_repl.py`), standing in for a real chat interface.

**Why deferred (until now)**: earlier decided to hold off until the full agent
workflow existed, so the UI could be designed against real interaction patterns
(HITL's approve/edit/reject, Booker's passenger-detail collection) rather than a
placeholder that would need reworking once those existed.

**Revisit when**: now — the full pipeline (Enhancer → Researcher → Planner → HITL
→ Booker) is built, wired, and verified end-to-end, so this is the next planned
step.

## Prompt caching (latency/cost reduction)

Not implemented. Every LLM call re-sends its full system prompt from scratch on
every turn — e.g. Enhancer's system prompt is ~967 tokens, resent in full on every
single turn of a conversation, not just once.

**Why it matters**: real, avoidable latency and cost per turn, compounding as a
conversation grows — the growing message history genuinely needs to be resent
each time (that's unavoidable), but the *static* system prompt text re-transmitting
identically every turn is pure overhead.

**What to do**: Anthropic supports prompt caching — marking the system prompt as a
reusable cached block so repeated calls with an identical prefix are billed/load
at a fraction of full cost and latency. Since each agent's system prompt is
byte-for-byte identical across turns (Enhancer's only varies by the date, which
changes at most once a day), this is close to an ideal candidate.

**Revisit when**: conversation length or per-turn latency becomes a real concern
in practice — not urgent at current scale, but a well-understood, low-effort win
whenever it is.

## End-to-end workflow walkthrough (documentation)

Not written. `docs/architecture.md` covers the design (diagrams, per-agent
responsibilities), but there's no single doc that walks through, with a concrete
worked example, how a request actually moves through the whole system turn by
turn — what `decide_next_step` checks at each point, which agent gets invoked and
why, and how state fields get filled in as the conversation progresses.

**Why deferred**: explanatory/onboarding documentation, not something blocking
further implementation.

**What it should cover**: a full trace using one concrete example (e.g. "flight +
hotel to Honolulu") — the `SupervisorState` at each step, which node runs next and
which specific field-check in `decide_next_step` sent it there, and how each
agent's output becomes the next transition's input. Should make explicit that
most routing is a plain deterministic state check, with `classify_edit_feedback`
as the one LLM-judged exception.

**Revisit when**: good candidate to pair with the chat UI work, or whenever the
project needs onboarding/portfolio-ready documentation.
