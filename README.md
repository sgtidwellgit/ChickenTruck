# ChickenTruck

Knowledge Engineering for Python — turning information into structured,
traceable knowledge, one nugget at a time.

**Status: pre-alpha.** Release 1 is built: the knowledge data model,
schema, entity resolution, validation, and an in-memory, conflict-aware
store. Exports, the SQLite backend, and extractors come in later
releases (see `PROJECT.md`). The API may still change.

## Purpose

ChickenTruck's job is to take raw information and turn it into
structured, validated, traceable knowledge — atomic facts with sources,
confidence, and temporal validity attached, ready to feed a graph
database, a relational database, a RAG pipeline, or an agent.

## The problem

Extracted information is not automatically trustworthy. A model or
pipeline that pulls a fact out of a document has no idea, on its own,
whether that fact is well-formed, whether it conflicts with something
already known, whether it's still true, or where it even came from.
ChickenTruck exists to put a disciplined pipeline between "information
we found" and "knowledge we're willing to act on."

Knowledge graphs are one important consumer of that output, but
ChickenTruck is not a knowledge-graph library — it's a knowledge
*engineering* toolkit. The graph is one possible destination, not the
definition of the project.

## Food Truck Fleet context

ChickenTruck is a member of a fleet of independent, food-themed Python
packages. Each truck owns one stage of a data pipeline and none of them
import each other — they compose only through plain data (DataFrames,
and here, structured knowledge objects) at the application layer:

- **SushiTruck** — ingestion (streaming sources, REST APIs, file/object stores)
- **ThaiTruck** — DataFrame cleaning and transformation
- **RamenTruck** — modeling / ML
- **BentoTruck** — agent orchestration
- **FishTruck** — anomaly / data-quality detection
- **ChickenTruck** — knowledge engineering (this package)

## Planned responsibilities

- Entity extraction and entity resolution
- Relationship / triple extraction
- Atomic fact and claim representation
- Candidate assertions with source, confidence, and temporal metadata
- Ontology / schema validation
- Conflict detection and knowledge reconciliation
- Provenance and source tracking throughout
- A backend-independent store for accepted knowledge
- Export shaped for graph databases, relational databases, RAG systems, and agents

## What ChickenTruck does *not* own

- Raw data acquisition — that's **SushiTruck**
- General DataFrame cleaning — that's **ThaiTruck**
- Machine learning / model training — that's **RamenTruck**
- Agent orchestration or agent memory — that's **BentoTruck**
- General-purpose anomaly / data-quality detection — that's **FishTruck**

ChickenTruck is also meant to stay independent of any one LLM provider,
graph database, relational database, vector database, NLP framework, or
agent framework. Anything backend-specific will eventually live behind an
optional adapter, not in core.

## The menu

Names describe what each piece actually does, not just a theme.

| Module | What it does |
|---|---|
| `chicken_nuggets` | `Nugget`: a bare subject/predicate/object fact |
| `chicken_tenders` | `ChickenTender`: a candidate claim with `Evidence` from `Source`s, validity, and qualifiers |
| `chicken_coop` | `Entity`, `Ref`, `Mention`, and `ChickenCoop`: entity registry and resolution |
| `chicken_recipe` | `Schema`: entity types, subtypes, and predicate definitions |
| `grilled_chicken` | `grill()`: validation into accepted / rejected / needs-review, producing a `Fact` |
| `chicken_stock` | `ChickenStock`: the indexed store for accepted knowledge, with conflict detection |

## Pipeline

```
Raw Information
  -> Nugget / ChickenTender   candidate claim + evidence
  -> ChickenCoop              mentions resolved to entities
  -> grill                    accepted / rejected / needs review
  -> ChickenStock             accepted Facts, queryable
```

## Quick start

```python
from chickentruck import (
    ChickenCoop, ChickenStock, ChickenTender, Entity, EntityType,
    Evidence, Predicate, Schema, Source, grill,
)

schema = Schema()
schema.add_type(EntityType("Person"))
schema.add_type(EntityType("Place"))
schema.add_predicate(Predicate("BORN_IN", domain="Person", range="Place",
                               cardinality="one", temporal="moment"))

coop = ChickenCoop(schema=schema)
coop.add(Entity("person:franklin", "Benjamin Franklin", "Person", aliases={"Ben Franklin"}))

encyclopedia = Source("encyclopedia", uri="https://example.org/franklin", authority=0.9)
tender = ChickenTender(
    "Ben Franklin", "BORN_IN", "Boston",
    evidence=[Evidence(encyclopedia, quote="born in Boston", confidence=0.95)],
    valid_from="1706-01-17",
)

tender = coop.resolve_tender(tender)   # "Ben Franklin" -> Ref("person:franklin"), "Boston" -> new provisional Place
result = grill(tender, schema=schema, coop=coop)
print(result.status)                   # accepted

stock = ChickenStock(schema=schema)
stock.add(result)
for fact in stock.find(subject="person:franklin", predicate="BORN_IN"):
    print(fact.object, round(fact.confidence, 3), fact.valid_from)
    # place:boston 0.855 1706-01-17

# A contradicting claim is kept, and the conflict recorded for review
blog = Source("blog", authority=0.6)
rival = coop.resolve_tender(ChickenTender(
    "Benjamin Franklin", "BORN_IN", "Philadelphia",
    evidence=[Evidence(blog, confidence=0.9)], valid_from="1706-01-17",
))
stock.add(grill(rival, schema=schema, coop=coop))
print(stock.conflicts(open_only=True))  # one open Conflict between the two facts
```

Key behaviors:

- **Nothing is guessed.** Ambiguous mentions stay unresolved and go to
  review; unmatched mentions become *provisional* entities.
- **Provenance is required.** A tender without evidence is rejected
  unless you opt out.
- **Confidence combines.** Evidence is weighted by source authority and
  combined with noisy-OR; the same claim from two sources merges into
  one `Fact`.
- **Time has precision.** `"1706"` stays a year. Validity is
  `[valid_from, valid_to)`; `find(valid_at=...)` asks what was true
  then, `find(as_of=...)` asks what the stock believed then.
- **Conflicts are never resolved silently.** The default `keep_both`
  policy records them; `highest_confidence`, `highest_authority`, and
  `most_recent_evidence` are opt-in. Losers are superseded, not deleted.

## Installation

```bash
pip install chickentruck
```

The published `0.1.0` is the original name-reservation stub; the
release described here (`2026.10.9`) is not on PyPI yet. ChickenTruck has
no runtime dependencies.

## Development status

- **Release 1 (built):** data model, schema, resolution, `grill`,
  in-memory `ChickenStock` with `find` and conflict detection.
- **Release 2 (planned):** SQLite backend, graph and relational exports,
  RAG helpers (`render_facts`, `check_claim`).
- **Release 3 (planned):** extractors. Until then `extract_nuggets()`
  raises `NotImplementedError`.

## Design principles

- Don't claim capabilities that don't exist yet — an unimplemented
  feature raises `NotImplementedError` rather than faking output.
- Don't duplicate what another fleet member already owns.
- Stay backend- and provider-independent in core; push anything
  specific (an LLM, a graph database, a vector store) into optional
  adapters.
- Food names describe function, not just theme.

## License

MIT — see `LICENSE`.
