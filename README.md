# ChickenTruck

Knowledge Engineering for Python — turning information into structured,
traceable knowledge, one nugget at a time.

**Status: pre-alpha, architectural stub.** The public API below exists so
the intended shape of the project is visible and importable, but the real
extraction, validation, and storage logic is not implemented yet. Nothing
in this package should be relied on for production use.

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

## Preliminary menu

Names describe what each piece actually does, not just a theme — see
`PROJECT.md` for the full design notes.

| Module | Concept |
|---|---|
| `chicken_nuggets` | Atomic knowledge extraction / representation — breaking information into small, individual facts |
| `chicken_tenders` | Candidate assertions "tendered" for consideration, not yet accepted as knowledge |
| `grilled_chicken` | Validation — putting a candidate assertion "on the grill" before it's accepted |
| `chicken_stock` | The foundational, backend-independent store for accepted knowledge |

Only these four are scaffolded today, and only lightly — see
`PROJECT.md` for what's designed versus what's still open.

## Conceptual pipeline

```
Raw Information
      |
      v
chicken_nuggets      (atomic knowledge)
      |
      v
chicken_tenders      (candidate assertions)
      |
      v
grilled_chicken      (validation)
      |
      v
chicken_stock        (accepted, structured knowledge)
```

This is a conceptual direction, not a finalized API contract.

## Installation

Not yet published. Once available:

```bash
pip install chickentruck
```

## Development status

Pre-alpha. The name and package structure are reserved; the knowledge
engineering architecture is being designed deliberately before it's
built, rather than bolted together module by module. Current behavior:

- `chickentruck.nuggets.Nugget` — a plain subject/predicate/object dataclass, usable today
- `chickentruck.tenders.ChickenTender` — a plain candidate-assertion dataclass, usable today
- `chickentruck.stock.ChickenStock` — a minimal in-memory store, usable today
- `chickentruck.nuggets.extract_nuggets()` and `chickentruck.grilled.grill()` — raise `NotImplementedError`; the extraction and validation engines haven't been designed yet

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
