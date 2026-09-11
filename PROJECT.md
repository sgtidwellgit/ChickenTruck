# ChickenTruck — Project Notes

This document captures longer-term architecture ideas for ChickenTruck,
separately from `README.md`. Everything here is **design-stage** —
none of it is a committed API contract, and most of it is not
implemented at all yet. Where something below has actually been built,
that's called out explicitly; assume "not built" otherwise.

## Purpose recap

ChickenTruck is a Knowledge Engineering toolkit: it turns raw
information into structured, validated, traceable, temporal, queryable
knowledge, suitable for graph databases, relational databases, RAG
systems, agents, and other consumers. It is not a knowledge-graph
library specifically — the graph is one output shape among several.

## Current state (v0.1.0)

Only the following exist as real code:

- `chickentruck.nuggets.Nugget` — a frozen dataclass: `subject`,
  `predicate`, `object`. No validation, no typing beyond `Any` for
  `object`.
- `chickentruck.tenders.ChickenTender` — a dataclass carrying the same
  three fields plus `source`, `confidence`, `valid_from`, `valid_to`,
  and a free-form `extraction_metadata` dict. `ChickenTender.from_nugget`
  copies a `Nugget`'s fields in.
- `chickentruck.grilled.grill` / `GrillResult` — the function raises
  `NotImplementedError` unconditionally; `GrillResult` documents the
  intended return shape (`tender`, `accepted`, `reasons`) but nothing
  produces one yet.
- `chickentruck.stock.ChickenStock` — a plain in-memory list wrapper
  (`add`, `all`, `__len__`). This is the only "backend" that exists.
- `chickentruck.nuggets.extract_nuggets` — raises `NotImplementedError`.

Everything below this line is exploration, not a spec.

## Design-stage concepts for future exploration

### Entity representation

How an "entity" (a person, place, organization, ...) is identified and
typed is undecided. Options range from a bare string label up through a
typed entity object with an ontology-defined class and stable ID. This
decision gates entity resolution, so it should probably come first.

### Entity resolution

Deciding that two extracted mentions ("Ben Franklin", "Benjamin
Franklin") refer to the same real-world entity. Needs a resolution
strategy (exact match, fuzzy match, embedding similarity, human review
queue) and a way to represent resolved identity. Not started.

### Relationship representation

How a predicate is typed (free-text string vs. a fixed relationship
vocabulary vs. an ontology-defined relation with its own constraints).
Affects how `grilled_chicken` validates predicates and how
`chicken_stock` exports to a graph schema.

### Triples and beyond

The subject/predicate/object shape covers simple facts but not
n-ary relationships (e.g. "X worked at Y from date A to date B") without
either reifying the relationship or attaching temporal fields directly
to the triple, as `ChickenTender` does today. Whether that's sufficient
long-term, or triples need to become first-class reified objects, is
open.

### Claims versus accepted facts

`chicken_tenders` already separates "proposed" from "accepted," but the
actual promotion path — what `grilled_chicken` checks, what happens to
rejected tenders (discarded? retained with a rejection reason? sent to
human review?) — is undesigned.

### Provenance and source authority

Every `ChickenTender` carries an optional free-text `source`, which is
almost certainly too weak long-term: knowing *that* something has a
source is different from knowing whether that source is trustworthy,
how source authority should factor into confidence, and whether
provenance needs to be a structured, queryable object rather than a
string.

### Confidence

Currently an optional bare `float` with no defined scale, no
combination rules (what happens when the same fact arrives from two
sources with different confidence?), and no consumer that reads it.

### Temporal validity

`valid_from` / `valid_to` exist on `ChickenTender` as plain optional
strings — no defined format, no timezone handling, and no representation
yet of facts that are true at a point in time versus true over an
interval versus always true.

### Ontology / schema validation

`grilled_chicken` is meant to eventually check subject type, predicate
validity, object type, and ontology constraints, but no ontology
representation exists yet — this needs a decision on whether
ChickenTruck defines its own lightweight schema format, adopts an
existing one (e.g. RDF Schema / OWL), or stays schema-agnostic and lets
adapters enforce constraints.

### Conflict detection and knowledge reconciliation

What happens when two accepted facts contradict each other (e.g. two
different birth years for the same person)? Detection requires knowing
which predicates are single-valued vs. multi-valued; reconciliation
requires a policy (most recent wins? highest confidence wins? both kept
with a recorded conflict?). Entirely undesigned.

### Storage abstraction

`ChickenStock` is a single concrete in-memory implementation today, not
an abstraction. A real backend interface (what methods every adapter
must implement, how queries are expressed in a backend-agnostic way)
needs to be designed before adapters like PostgreSQL, Neo4j, or RDF
stores are attempted — implementing an adapter against an interface
that doesn't exist yet would just have to be redone.

### Knowledge graph output

Exporting accepted knowledge as nodes/edges for a graph database is a
likely early adapter, but the export shape depends on the entity and
relationship representation decisions above.

### Relational output

Exporting accepted knowledge into relational tables (e.g. for a
data warehouse) is a plausible alternate consumer; likely needs a
different denormalization strategy than the graph export.

### Integration with RAG / AI systems

Structured knowledge as retrieval context, or as grounding for an
agent's answers, is a target use case but not designed — depends on
`chicken_stock` having a query interface, which doesn't exist yet.

### Optional NLP / LLM extraction adapters

`extract_nuggets` will eventually need something to actually do
extraction — an NLP pipeline, an LLM call, or both, offered as optional
adapters so core stays free of a hard dependency on any one provider or
framework. Which adapter ships first, and what interface it implements,
is undecided.

## Fleet boundaries (do not duplicate)

- Raw data acquisition → **SushiTruck**
- General DataFrame cleaning → **ThaiTruck**
- Machine learning / model training → **RamenTruck**
- Agent orchestration or agent memory → **BentoTruck**
- General-purpose anomaly / data-quality detection → **FishTruck**

ChickenTruck packages never import another fleet member; composition
happens at the application layer only.

## Working principle

Each design-stage item above should get its own scoped decision (with
the user) before implementation starts, the same way ThaiTruck's
remaining roadmap items were handled — no speculative implementation
against an undecided design.
