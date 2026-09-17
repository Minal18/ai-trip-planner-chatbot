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
