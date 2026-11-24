# Pending / Deferred Items

Things deliberately deferred during development, with the reasoning for revisiting later.

## `create_react_agent` deprecation (Researcher)

Not fixed. `langgraph.prebuilt.create_react_agent` (used in `researcher/graph.py`)
logs a deprecation warning — it's moving to `langchain.agents.create_agent` in a
future LangGraph version.

**Why deferred**: still fully functional, not yet removed — no urgency.

**Revisit when**: convenient, or if a future LangGraph upgrade actually removes it.

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

## Hotel check-in / car pickup derived from the actual flight arrival

Not built. When a trip includes a flight plus a hotel and/or car, the hotel
check-in and car pickup dates are set by the Enhancer *before* any flight has been
searched, so they're an estimate of the arrival date. The Enhancer prompt now
tells it that long-haul flights land later than people expect (overnight
transatlantic: +1 day; Americas → India/Asia/Australia: often +2), but it's still
a guess. Verified live against Duffel's test API: SEA → BOM departing Dec 10
lands Dec 12 — the "+1 day" rule we first tried would have been off by a day.

Planner's `check_dates` now compares against the flight's real local arrival
and return times, and tolerates arrivals that cross 1–2 days: a hotel that checks
in on the departure day, or the night before an early-morning landing, counts as
aligned; a car can't be picked up before landing; stay/car must end by the return
flight (the day before is fine for a pre-dawn departure). Genuine conflicts are
blocking problems (Planner retries once, often fixable by picking a different
flight); merely wasteful cases (e.g. paying for a night before a long-haul lands)
are ⚠️ notes on the review card and never trigger a retry.

When the dates genuinely conflict and no flight fixes it, the retry can't help
(every stay in `research_results` has the same dates), and the review card shows
a ⚠️ warning line. The traveler then has
to ask for the hotel dates to be shifted, which triggers a re-search via the
edit path.

**Why deferred**: it's a structural change to the Researcher. Today all searches
are requested in one LLM call and run concurrently, with no ordering; this needs flights searched first, then
stays/cars searched from the chosen (or top-ranked) flight's actual
`arriving_at` date, and the return flight's `departing_at` for check-out/drop-off.
That also raises the question of which flight's dates to use when the Planner
later picks a different one.

**Possible approach**: split the Researcher into two phases (flights, then
stays/cars) when `domains` includes flights plus anything else; derive
check-in/pickup from the top-ranked flight's arrival, and have the Planner
re-trigger the stays/cars search (via the existing NeedsResearcher edit path)
if it selects a flight with different dates. Also add a car-vs-flight date check
to `validate_consistency` — car results now carry `pickup_date`/`dropoff_date`,
so the old "cars carry no dates" gap no longer blocks it.

**Revisit when**: after the current preferences / review-card changes are
tested from the UI, or sooner if date-mismatch warnings show up on most
long-haul trips.
