# ChickenTruck — Project Notes

This document records ChickenTruck's architecture decisions and release
plan, separately from `README.md`. The design pass of 2026-10-09
answered every open question from the original stub; those answers are
below, each marked with the release that delivers it.

## Purpose recap

ChickenTruck is a Knowledge Engineering toolkit: it turns raw
information into structured, validated, traceable, temporal, queryable
knowledge, suitable for graph databases, relational databases, RAG
systems, agents, and other consumers. It is not a knowledge-graph
library specifically — the graph is one output shape among several.

Ground rules: zero runtime dependencies in core, Python 3.9+, and no
coupling to any one LLM provider, database, NLP framework, or agent
framework. Anything backend-specific lives behind an optional adapter.

## Pipeline

```
Raw Information
  -> Nugget            bare subject/predicate/object mentions     (chicken_nuggets)
  -> ChickenTender     candidate claim + evidence + validity      (chicken_tenders)
  -> resolve_tender    mentions become entity Refs                (chicken_coop)
  -> grill             ACCEPTED / REJECTED / NEEDS_REVIEW         (grilled_chicken)
  -> Fact              accepted knowledge                         (grilled_chicken)
  -> ChickenStock      indexed, bitemporal, conflict-aware store  (chicken_stock)
     / SqliteStock     the same, persisted in SQLite
  -> to_graph / to_tables / to_ntriples                           (chicken_platter)
  -> render_facts / check_claim                                   (chicken_soup)
```

A tender is never mutated into a fact; `grill` produces a new `Fact`.
The schema (`chicken_recipe`) informs resolution, validation, and
conflict detection, but is optional throughout.

## Release plan

Versions are date-based (`YYYY.M.D`). All three releases ship to PyPI
together once release 3 is done, versioned by the publish date.

| Release | Scope | Status |
|---|---|---|
| 1 | Data model, schema, entities + exact/alias resolution, `grill`, in-memory stock with `find`, conflict detection | **Built** |
| 2 | SQLite backend, graph export, relational export, RAG helpers (`render_facts`, `check_claim`) | **Built** |
| 3 | Extractors: pattern-based, and LLM via a caller-supplied completion function | Planned |

## Decisions

### 1. Entity representation — release 1
`Entity(id, label, type, aliases, provisional)`, frozen. IDs are stable
strings, either supplied by the caller or generated as `type:slug`
(`person:benjamin-franklin`). Objects are either an entity reference
(`Ref(id)`) or a literal value; the `Ref` wrapper is what tells them
apart. Before resolution, entities are plain strings or `Mention`s.

### 2. Entity resolution — release 1 (basic), later (fuzzy/embedding)
`chicken_coop.ChickenCoop` holds entities and resolves mentions: exact
label/alias match (score 1.0), then normalized match ignoring case,
whitespace, and punctuation (score 0.9). Type hints honor schema
subtypes. Several equal matches are **ambiguous and stay unresolved** —
never guessed. No match creates a **provisional** entity (reviewable,
then `confirm`ed). Other strategies plug in through the `Resolver`
protocol; fuzzy (`difflib`, opt-in) and embedding resolvers come later.

### 3. Predicates — release 1
Plain strings by default. A schema `Predicate` optionally defines
domain (subject entity types), range (an entity type or one of
`string`/`integer`/`number`/`boolean`/`time`), cardinality
(`one`/`many`), and temporal kind (`span`/`moment`).

### 4. Triples and beyond — release 1
Subject–predicate–object stays the core, plus a `qualifiers` dict for
n-ary detail (role, location, ...) and first-class validity fields.
Every `Fact` has a stable `fact_id` derived from the claim (subject,
predicate, object, validity, qualifiers — not the evidence), so the
same claim from two sources merges, and other facts can point at it.
No full RDF reification.

### 5. Claims vs. accepted facts — release 1
`grill` is side-effect free and returns a `GrillResult` with status
`accepted` / `rejected` / `needs_review` and structured `Finding`s
(`rule`, `severity`, `message`). Any error rejects; any warning sends
to review. Unresolved entities go to review, not rejection. Only an
accepted result carries a `Fact`, and only a `Fact` can be stocked.
Rejected tenders go back to the caller; a review UI is out of scope.

### 6. Provenance — release 1
`Source(id, kind, uri, title, retrieved_at, authority)` where kind is
document / api / human / model and authority is optional 0..1.
`Evidence(source, locator, quote, confidence, extractor, extracted_at)`
records each sighting of a claim. Tenders carry evidence; facts merge
evidence from every tender that supports them. Evidence is required by
default (`grill(require_evidence=False)` waives it).

### 7. Confidence — release 1
0..1, "how strongly this evidence suggests the claim is true"; `None`
means unknown. Independent evidence combines by noisy-OR,
`1 − Π(1 − cᵢ·aᵢ)`, with each confidence weighted by its source's
authority (unknown authority counts as 1). The combiner is pluggable.
`grill` rejects below `reject_below` (default 0.2) and reviews below
`accept_at` (default 0.5); unknown confidence is noted, not penalized.

### 8. Time — release 1
`TimePoint(value, precision)` with precision year / month / day /
instant, so "1706" stays a year. ISO strings are parsed on input; a
datetime without a timezone fails validation. Validity is the
half-open interval `[valid_from, valid_to)`, `None` meaning unbounded;
`moment` predicates may only set `valid_from`. The stock adds a second
timeline — `recorded_at` / `superseded_at` — so it answers both "true
at T" (`valid_at`) and "believed at T" (`as_of`).

### 9. Ontology — release 1
`chicken_recipe.Schema`: entity types with single inheritance plus
predicate definitions, built in Python or loaded from dict/JSON.
Schema-free operation works: `grill` then runs structural checks only.
`strict=True` rejects predicates the schema doesn't define. RDFS/OWL
import/export is a later adapter.

### 10. Conflicts — release 1
Detected when a fact is stocked: a `one`-cardinality predicate, same
subject, different object, overlapping validity, both active. The
**default policy is `keep_both`**: record a `Conflict`, pick no
winner, and let a reviewer settle it with `resolve_conflict`. Opt-in
policies: `highest_confidence`, `highest_authority`,
`most_recent_evidence` (ties keep both). Losers are marked superseded,
never deleted. Without a schema there is no cardinality, so no
conflict detection.

### 11. Storage interface — release 1 (interface + memory), release 2 (SQLite)
`StockBackend` protocol: `add`, `get`, `find`, `all`, `sources`,
`conflicts`, `resolve_conflict`, `put_entity`, `get_entity`,
`entities`, `__len__`. `find` is a pattern match (subject /
predicate / object) plus filters (`valid_at`, `as_of`,
`min_confidence`, `include_superseded`) — not a query language.
The rules (merging, conflict detection, query filtering) are written
once in `StockLogic`; a backend only supplies storage primitives, so
every backend behaves identically — the test suite runs every stock
test against both.

- `ChickenStock`: in memory, indexed by subject, predicate, and object.
- `SqliteStock` (release 2): stdlib `sqlite3`, still zero dependencies.
  Values are stored as tagged JSON so `Ref`s, time points, dates, and
  datetimes round-trip; other literals must be JSON-compatible. Each
  `add` is one transaction. The schema is saved in the file and reused
  when it is reopened without one; the conflict policy is code and is
  passed in each time. A storage-format version is checked on open.

Entities persist in the backend too: `ChickenCoop(store=stock)` loads
the store's entities and writes every change through. Postgres and
Neo4j come later as optional extras.

Known limitation: merged evidence is current-state only — an `as_of`
query shows which facts were believed then, with the evidence they
hold now.

### 12. Graph export — release 2
`chicken_platter.to_graph`: entities become nodes; entity-to-entity
facts become edges carrying `fact_id`, confidence, validity,
qualifiers, and source IDs. Literal-valued facts become node
properties ("simple" mode) or separate statements that keep their
provenance ("full" mode). Superseded facts are left out unless asked
for. `to_ntriples` is a dependency-free N-Triples serializer (IRIs
under `urn:chickentruck:` by default, XSD-typed literals by precision);
plain triples can't carry confidence or provenance, so it exports
active facts only.

### 13. Relational export — release 2
Normalized tables — `entities`, `aliases`, `sources`, `facts`,
`evidence`, `qualifiers`, `conflicts` — emitted as lists of dicts per
table (`chicken_platter.to_tables`), with no pandas dependency. Every
cell is a scalar; container values become JSON text. Superseded facts
are included by default so the history is complete. Turning the
tables into DataFrames is user code.

### 14. RAG and agents — release 2
In `chicken_soup`: `render_facts()` turns facts into cited lines with
a numbered source list, ready for a prompt. `check_claim(s, p, o)`
answers **supported / contradicted / disputed / unknown** with the
facts and evidence behind it. *Disputed* (both supporting and
contradicting facts are active, typically an open conflict) was added
during implementation so an unresolved conflict is never reported as
plain support. Contradiction needs a single-valued predicate in the
schema. With a coop, subjects and objects can be given as names. An agent framework's
grounding checks can call `check_claim` from application code;
ChickenTruck itself never imports another fleet member.

### 15. Extractors — release 3
`Extractor` protocol: `extract(text, *, source) -> list[ChickenTender]`
— tenders rather than nuggets, so provenance is attached at the start.
First a deterministic pattern-based extractor (no dependencies). The
LLM extractor takes a caller-supplied `complete(prompt) -> str`
function and parses JSON from it: no vendor SDK and no model IDs in
source. spaCy is a later optional extra. Until then
`extract_nuggets()` raises `NotImplementedError`.

## Fleet boundaries (do not duplicate)

- Raw data acquisition → **SushiTruck**
- General DataFrame cleaning → **ThaiTruck**
- Machine learning / model training → **RamenTruck**
- Agent orchestration or agent memory → **BentoTruck**
- General-purpose anomaly / data-quality detection → **FishTruck**

ChickenTruck never imports another fleet member; composition happens
at the application layer only.

## Working principle

Unimplemented features raise `NotImplementedError` rather than faking
output. New scope beyond the decisions above gets its own design
decision before implementation.
