# ChickenTruck

[![Tests](https://github.com/sgtidwellgit/ChickenTruck/actions/workflows/tests.yml/badge.svg)](https://github.com/sgtidwellgit/ChickenTruck/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/chickentruck.svg)](https://pypi.org/project/chickentruck/)
[![Python](https://img.shields.io/pypi/pyversions/chickentruck.svg)](https://pypi.org/project/chickentruck/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/sgtidwellgit/ChickenTruck/blob/main/LICENSE)

**Knowledge Engineering for Python.** ChickenTruck turns raw text and
other information into structured, validated, traceable knowledge.
The result is atomic facts that each carry their sources, confidence,
and time of validity, ready for a graph database, a relational database,
a RAG pipeline, or an agent.

- **Extract** candidate claims from text with readable patterns or any
  language model (you supply the function that calls it).
- **Resolve** names to entities ("Ben Franklin" and "Benjamin Franklin"
  are the same person), and never guess when a name is ambiguous.
- **Validate** every claim against a schema and confidence thresholds
  before it counts as knowledge.
- **Store** accepted facts with full provenance. Detect contradictions
  and ask what was true at any point in time.
- **Serve** knowledge as a property graph, relational tables, RDF, or
  cited prompt context. Check an agent's claims against it.

Pure Python, **zero runtime dependencies**, Python 3.9+.

```bash
pip install chickentruck
```

---

## Contents

- [Why ChickenTruck](#why-chickentruck)
- [Quick start](#quick-start)
- [How it fits together](#how-it-fits-together)
- [Guide](#guide)
  1. [Describe your domain with a schema](#1-describe-your-domain-with-a-schema)
  2. [Sources and evidence](#2-sources-and-evidence)
  3. [Extract claims with patterns](#3-extract-claims-with-patterns)
  4. [Extract claims with a language model](#4-extract-claims-with-a-language-model)
  5. [Resolve entities](#5-resolve-entities)
  6. [Validate with grill](#6-validate-with-grill)
  7. [Store and query knowledge](#7-store-and-query-knowledge)
  8. [Conflicts](#8-conflicts)
  9. [Persist to SQLite](#9-persist-to-sqlite)
  10. [Export: graph, tables, RDF](#10-export-graph-tables-rdf)
  11. [Ground prompts and check claims](#11-ground-prompts-and-check-claims)
- [Recipes](#recipes)
- [API reference](#api-reference)
- [Design principles](#design-principles)
- [The Food Truck Fleet](#the-food-truck-fleet)
- [Limitations](#limitations)
- [Development](#development)

---

## Why ChickenTruck

Extracted information isn't automatically trustworthy. A model or
script that pulls a "fact" out of a document can't tell you, by itself:

- whether the fact is well formed (is "Boston" a valid birthplace for
  a *person*?),
- which real-world thing a name refers to,
- whether it contradicts something you already know,
- when it was true, or
- where it came from, and how much to trust that source.

ChickenTruck puts a disciplined pipeline between *information we
found* and *knowledge we're willing to act on*. Every fact keeps the
evidence behind it, so any answer can be traced back to a source and a
quote.

ChickenTruck isn't a graph database or a knowledge-graph library. A
graph is one place its output can go, not the point of the project.

## Quick start

Text in, validated and cited knowledge out:

```python
from chickentruck import (
    ChickenCoop, ChickenStock, EntityType, Pattern, PatternExtractor,
    Predicate, Schema, Source, check_claim, process_text, render_facts,
)

# 1. What kinds of things and relationships exist
schema = Schema()
schema.add_type(EntityType("Person"))
schema.add_type(EntityType("Place"))
schema.add_type(EntityType("Organization"))
schema.add_predicate(Predicate("BORN_IN", domain="Person", range="Place",
                               cardinality="one", temporal="moment"))
schema.add_predicate(Predicate("WORKED_AT", domain="Person", range="Organization"))

# 2. How those relationships are phrased in text
extractor = PatternExtractor([
    Pattern("BORN_IN", "{subject} was born in {object} on {valid_from}"),
    Pattern("BORN_IN", "{subject} was born in {object}"),
    Pattern("WORKED_AT", "{subject} served as {role} at the {object} "
                         "from {valid_from:year} to {valid_to:year}"),
])

# 3. Run text through extract -> resolve -> validate -> store
text = (
    "Benjamin Franklin was born in Boston on January 17, 1706. "
    "Benjamin Franklin served as Deputy Postmaster General at the "
    "Post Office from 1753 to 1774."
)
source = Source("bio", title="A short biography",
                uri="https://example.org/franklin", authority=0.9)
coop = ChickenCoop(schema=schema)      # the entities
stock = ChickenStock(schema=schema)    # the accepted knowledge

results = process_text(text, source=source, extractor=extractor,
                       coop=coop, stock=stock)
print([r.status for r in results])
# ['accepted', 'accepted']

# 4. Use it
print(render_facts(stock.all(), coop=coop))
# - Benjamin Franklin born in Boston (from 1706-01-17; confidence 0.63) [1]
# - Benjamin Franklin worked at Post Office (role: Deputy Postmaster General; from 1753 to 1774; confidence 0.63) [1]
#
# Sources:
# [1] A short biography - https://example.org/franklin

print(check_claim(stock, "Benjamin Franklin", "BORN_IN", "Philadelphia", coop=coop).verdict)
# contradicted
```

Every fact remembers the quote it came from:

```python
fact = stock.find(predicate="BORN_IN")[0]
print(fact.evidence[0].quote)    # Benjamin Franklin was born in Boston on January 17, 1706
print(fact.evidence[0].locator)  # chars 0-56
```

## How it fits together

```
 raw text
    |
    |  PatternExtractor / LLMExtractor / your own   (chicken_fryer)
    v
 ChickenTender      candidate claim + Evidence + validity   (chicken_tenders)
    |
    |  ChickenCoop.resolve_tender                   (chicken_coop)
    v
 ChickenTender      names replaced by entity Refs
    |
    |  grill                                        (grilled_chicken)
    v
 accepted / needs_review / rejected
    |
    |  only accepted results become Facts
    v
 ChickenStock / SqliteStock   query, time travel, conflicts   (chicken_stock)
    |
    +--> to_graph / to_tables / to_ntriples         (chicken_platter)
    +--> render_facts / check_claim                 (chicken_soup)
```

`process_text` runs everything from extraction through storage in a
single call. Each stage is also usable on its own.

### The menu

Each module's name says what it does.

| Module | Main pieces | What it does |
|---|---|---|
| `chicken_recipe` | `Schema`, `EntityType`, `Predicate` | Entity types, subtypes, and what each predicate accepts |
| `chicken_fryer` | `PatternExtractor`, `Pattern`, `LLMExtractor`, `process_text` | Raw text in, candidate claims out |
| `chicken_nuggets` | `Nugget`, `extract_nuggets` | Bare subject/predicate/object facts with nothing attached |
| `chicken_tenders` | `ChickenTender`, `Source`, `Evidence` | A candidate claim with its evidence, validity, and qualifiers |
| `chicken_coop` | `ChickenCoop`, `Entity`, `Ref`, `Mention` | The entity registry and name resolution |
| `grilled_chicken` | `grill`, `GrillResult`, `Fact`, `Finding` | Validation: accepted, needs review, or rejected |
| `chicken_stock` | `ChickenStock`, `SqliteStock`, `Conflict` | Stores accepted facts and detects conflicts |
| `chicken_platter` | `to_graph`, `to_tables`, `to_ntriples` | Knowledge as a graph, tables, or RDF |
| `chicken_soup` | `render_facts`, `check_claim` | Cited prompt context and grounding checks for RAG and agents |

Everything is importable from the top-level `chickentruck` package.

---

## Guide

The examples build on each other, in order. They're all run as part of
the test suite, so they stay correct.

### 1. Describe your domain with a schema

A `Schema` is optional, but it powers most of the checking. It declares
**entity types** (with single inheritance) and **predicates**:

```python
from chickentruck import EntityType, Predicate, Schema

schema = Schema()
schema.add_type(EntityType("Person"))
schema.add_type(EntityType("Scientist", parent="Person"))   # a Scientist is a Person
schema.add_type(EntityType("Place"))
schema.add_type(EntityType("Organization"))

schema.add_predicate(Predicate(
    "BORN_IN",
    domain="Person",          # who can have this (subtypes count)
    range="Place",            # an entity type...
    cardinality="one",        # one birthplace at a time -> enables conflict detection
    temporal="moment",        # happens at a point: valid_from only
    description="Where a person was born",
))
schema.add_predicate(Predicate("BIRTH_YEAR", domain="Person",
                               range="integer", cardinality="one"))   # ...or a literal type
schema.add_predicate(Predicate("WORKED_AT", domain="Person", range="Organization"))
schema.add_predicate(Predicate("HEADQUARTERED_IN", domain="Organization",
                               range="Place", cardinality="one"))
```

| `Predicate` field | Values | Effect |
|---|---|---|
| `domain` | type name(s), or empty for any | Subject must be one of these types (or a subtype) |
| `range` | an entity type, `string`, `integer`, `number`, `boolean`, `time`, or `None` | What the object must be. Entity ranges also tell resolution that the object is an entity |
| `cardinality` | `"many"` (default) or `"one"` | `"one"` means a subject holds one value at a time, so different values conflict |
| `temporal` | `"span"` (default) or `"moment"` | Moments may only set `valid_from` |

Schemas round-trip through dicts and JSON, so you can keep them in a
file:

```python
saved = schema.to_json(indent=2)
assert Schema.from_json(saved).to_dict() == schema.to_dict()
```

`Schema(strict=True)` makes `grill` reject predicates the schema
doesn't define. By default they pass with an informational note.

### 2. Sources and evidence

Every claim needs evidence (this is on by default). A `Source` is where
information came from. `Evidence` records one sighting of a claim in
that source.

```python
from chickentruck import Evidence, Source

encyclopedia = Source(
    "encyclopedia",                    # a stable id
    kind="document",                   # document | api | human | model
    title="Encyclopedia",
    uri="https://example.org/franklin",
    authority=0.9,                     # 0..1: how much you trust this source
)
evidence = Evidence(
    encyclopedia,
    locator="p. 12",                   # where in the source
    quote="born in Boston on January 17, 1706",
    confidence=0.95,                   # 0..1: how strongly this supports the claim
    extractor="manual",
)
print(round(evidence.weighted_confidence, 3))   # 0.855 = confidence x authority
```

When several pieces of evidence support the same claim, they combine
by **noisy-OR**: `1 - (1 - c1*a1)(1 - c2*a2)...`. Two independent
sources at 0.6 give 0.84. Agreement builds confidence, and no single
source can push it to 1.

### 3. Extract claims with patterns

`PatternExtractor` is deterministic and needs no dependencies. You
describe how each predicate is phrased with a **template**:

```python
from chickentruck import Pattern, PatternExtractor

patterns = PatternExtractor([
    # List specific patterns first: an overlapping match from a later
    # pattern for the same predicate is dropped.
    Pattern("BORN_IN", "{subject} was born in {object} on {valid_from}"),
    Pattern("BORN_IN", "{subject} was born in {object}"),
    Pattern("WORKED_AT", "{subject} served as {role} at the {object} "
                         "from {valid_from:year} to {valid_to:year}"),
    Pattern("BIRTH_YEAR", "{subject} (born {object:int})"),
])

bio = Source("bio", title="A short biography", authority=0.9)
text = (
    "Benjamin Franklin was born in Boston on January 17, 1706. "
    "He was born in Boston, his letters say. "
    "Ben Franklin served as Deputy Postmaster General at the Post Office "
    "from 1753 to 1774. Ada Lovelace (born 1815) was a mathematician."
)

for tender in patterns.extract(text, source=bio):
    print(tender.subject, "|", tender.predicate, "|", tender.object, "|",
          tender.valid_from, tender.valid_to, tender.qualifiers)
# Benjamin Franklin | BORN_IN | Boston | 1706-01-17 None {}
# Ben Franklin | WORKED_AT | Post Office | 1753 1774 {'role': 'Deputy Postmaster General'}
# Ada Lovelace | BIRTH_YEAR | 1815 | None None {}
```

Notice what *didn't* match. "He was born in Boston" is skipped,
because the pattern extractor doesn't guess what a pronoun refers to.

**Template rules**

- `{subject}` and `{object}` are required. `{valid_from}` and
  `{valid_to}` set validity. Any other placeholder, like `{role}`,
  becomes a **qualifier**.
- Literal words match regardless of case, and any run of whitespace
  matches a single space.
- Each placeholder can take a kind, written `{name:kind}`:

| Kind | Matches | Becomes | Default for |
|---|---|---|---|
| `name` | Proper names: `Benjamin Franklin`, `J. R. de Silva`, `University of Pennsylvania`. Never starts with a pronoun or article | `str` | `subject`, `object` |
| `date` | `1706`, `1706-01-17`, `January 17, 1706`, `17 Jan 1706`, `Sept 1706` | ISO string | `valid_from`, `valid_to` |
| `year` | four digits | `str` | |
| `int` | `42`, `16,382` | `int` | |
| `number` | `3.5`, `1,234.5` | `float` | |
| `word` | one word | `str` | |
| `text` | words up to the next sentence punctuation | `str` | any other placeholder |

**Options:** `subject_type=` / `object_type=` wrap the match in a typed
`Mention`, which guides entity resolution. `confidence=` sets the
evidence confidence (default 0.7). `convert={"object": fn}` post-processes
a value. For full control, pass a raw regular expression with named
groups:

```python
age = Pattern(
    "AGE_AT_DEATH",
    r"(?P<subject>[A-Z]\w+(?: [A-Z]\w+)*) died at (?P<object>\d+)",
    regex=True,
    convert={"object": int},
)
[tender] = PatternExtractor([age]).extract("Benjamin Franklin died at 84.", source=bio)
print(tender.object + 1)   # 85
```

Each match's evidence records the quote, its character span
(`"chars 0-56"`), the extractor name, and the extraction time.

### 4. Extract claims with a language model

`LLMExtractor` asks a model for claims as JSON. ChickenTruck doesn't
import any provider SDK. Instead you give it a function that takes a
prompt string and returns the model's reply as a string, so any hosted
or local model works:

```python
# illustration only: wrap whichever client you already use
from chickentruck import LLMExtractor

def complete(prompt: str) -> str:
    return my_client.generate(prompt)          # your model call here

llm = LLMExtractor(complete, schema=schema)
tenders = llm.extract(open("article.txt").read(), source=Source("article"))
```

The runnable example below uses a stand-in for the model so you can see
exactly what happens to each claim it returns:

```python
import json
from chickentruck import LLMExtractor, build_prompt

def fake_model(prompt: str) -> str:
    claims = [
        {"subject": "Benjamin Franklin", "subject_type": "Person",
         "predicate": "born in", "object": "Boston",
         "valid_from": "1706-01-17",
         "quote": "Benjamin Franklin was born in Boston", "confidence": 0.95},
        {"subject": "Benjamin Franklin", "predicate": "BIRTH_YEAR",
         "object": "1706", "quote": "January 17, 1706"},
        # Made up: this quote is not in the text, so it is dropped
        {"subject": "Benjamin Franklin", "predicate": "DIED_IN",
         "object": "Paris", "quote": "died in Paris"},
    ]
    fence = "`" * 3   # models often wrap JSON in a code fence; that's fine
    return f"Here are the claims:\n{fence}json\n{json.dumps({'claims': claims})}\n{fence}"

llm = LLMExtractor(fake_model, schema=schema)
report = llm.extract_with_report(text, source=bio)

for tender in report.tenders:
    print(tender.predicate, tender.object, tender.evidence[0].locator)
# BORN_IN Boston chars 0-36      (a Mention typed 'Place', ready to resolve)
# BIRTH_YEAR 1706 chars 40-56

for skipped in report.skipped:
    print(skipped.reason, "->", skipped.item["predicate"])
# quote not found in the text -> DIED_IN
```

What the extractor does for you:

- **Builds the prompt.** It lists your schema's types and predicates
  (see `build_prompt(text, schema)`) and adds any extra
  `instructions=` you pass.
- **Parses the reply.** It accepts `{"claims": [...]}`, a bare list, or
  a single object, with or without a code fence or chatter around it.
  A reply with no JSON raises `ExtractionError`, and the raw reply is
  kept in `.response`.
- **Checks quotes.** With `require_quote=True` (the default), a claim is
  kept only if its quote appears in the text, ignoring case and
  whitespace. This guards against claims the model made up. The
  evidence then stores the exact source text and its character span.
- **Normalizes.** `"born in"` becomes `BORN_IN`. Literal objects are
  converted using `object_type` or the schema's range (`"1706"` becomes
  `1706` for an `integer` range). Entity objects become typed `Mention`s.
- **Skips bad claims.** Malformed claims are dropped one at a time with
  a reason (`extract_with_report(...).skipped`); the rest of the reply
  is still used.
- **Chunks long text.** Text longer than `max_chars` (default 12,000) is
  split at paragraph, then sentence, boundaries and sent in pieces.
  Locators still point into the full text.
- **Fills in confidence.** A claim's own `confidence` is used if it's
  valid; otherwise the extractor's `confidence=` default (0.6) applies.

Combine extractors by passing a list to `process_text`, for example
patterns for the phrasings you know plus a model for everything else.

**Your own extractor.** Anything with an
`extract(text, *, source) -> list[ChickenTender]` method works:

```python
from chickentruck import ChickenTender

class CsvRowExtractor:
    def extract(self, text, *, source):
        tenders = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            name, city = (part.strip() for part in line.split(","))
            tenders.append(ChickenTender(
                name, "BORN_IN", city,
                evidence=[Evidence(source, locator=f"line {line_no}",
                                   confidence=0.9, extractor="csv")],
            ))
        return tenders

rows = CsvRowExtractor().extract("Ada Lovelace, London\nAlan Turing, London",
                                 source=Source("people.csv"))
print(len(rows))   # 2
```

If you just want bare triples with no provenance, `extract_nuggets`
strips tenders down to `Nugget(subject, predicate, object)`:

```python
from chickentruck import extract_nuggets

print(extract_nuggets("Ada Lovelace was born in London.", patterns)[0])
# Nugget(subject='Ada Lovelace', predicate='BORN_IN', object='London')
```

### 5. Resolve entities

Text only ever *names* things. The `ChickenCoop` keeps your entities
and decides which entity each name refers to:

```python
from chickentruck import ChickenCoop, Entity

coop = ChickenCoop(schema=schema)
coop.add(Entity("person:franklin", "Benjamin Franklin", "Scientist",
                aliases={"Ben Franklin"}))
coop.add(Entity("place:boston", "Boston", "Place"))
coop.add(Entity("place:philadelphia", "Philadelphia", "Place"))
coop.add(Entity("org:post-office", "Post Office", "Organization"))

print(coop.resolve("Ben Franklin").entity_id)     # person:franklin   (alias, score 1.0)
print(coop.resolve("ben  FRANKLIN.").score)       # 0.9               (case/spacing/punctuation ignored)
```

Resolution is deliberately conservative:

| Situation | Outcome |
|---|---|
| Exact label or alias | Resolved, score 1.0 |
| Same after ignoring case, whitespace, and punctuation | Resolved, score 0.9 |
| Several entities match equally | **Ambiguous: left unresolved**, never guessed |
| Type hint doesn't fit (subtypes count) | Not a match |
| No match | A **provisional** entity is created to review later (`create=False` turns this off) |

```python
coop.add(Entity("place:paris-fr", "Paris", "Place"))
coop.add(Entity("place:paris-tx", "Paris", "Place"))
paris = coop.resolve("Paris")
print(paris.ambiguous, paris.candidates)   # True ('place:paris-fr', 'place:paris-tx')

deborah = coop.resolve("Deborah Read", type="Person")
print(deborah.entity_id, coop.get(deborah.entity_id).provisional)   # person:deborah-read True
coop.confirm(deborah.entity_id)                                     # reviewed: no longer provisional
coop.add_alias("person:franklin", "Poor Richard")                   # teach it a new name
```

`resolve_tender` resolves a whole claim. The subject is always an
entity. The object is treated as an entity if it's a `Mention` or the
schema's range says so; otherwise it's a literal:

```python
from chickentruck import ChickenTender, Ref

tender = ChickenTender("Ben Franklin", "BORN_IN", "Boston",
                       evidence=[Evidence(encyclopedia, confidence=0.95)],
                       valid_from="1706-01-17")
resolved = coop.resolve_tender(tender)
print(resolved.subject, resolved.object)   # person:franklin place:boston
```

To plug in fuzzy or embedding matching, pass any object with a
`resolve(mention, type) -> Resolution` method as `resolver=`.

### 6. Validate with grill

`grill` decides whether a claim becomes knowledge. It has no side
effects and returns a `GrillResult`:

```python
from chickentruck import grill

result = grill(resolved, schema=schema, coop=coop)
print(result.status, round(result.fact.confidence, 3))   # accepted 0.855

bad = grill(ChickenTender(
    Ref("place:boston"), "BORN_IN", Ref("person:franklin"),   # backwards
    evidence=[Evidence(encyclopedia, confidence=0.9)],
), schema=schema, coop=coop)
print(bad.status)          # rejected
for finding in bad.findings:
    print(finding.severity, finding.rule)
# error schema.domain
# error schema.range
```

**Statuses:** any *error* → `rejected`, any *warning* → `needs_review`,
otherwise → `accepted`. Only an accepted result carries a `Fact`, and
only a `Fact` can be stored.

| Rule | Severity | When |
|---|---|---|
| `provenance.missing` | error | No evidence (turn off with `require_evidence=False`) |
| `predicate.empty`, `object.missing` | error | Malformed claim |
| `time.naive`, `time.empty_interval` | error | Datetime without a timezone; `valid_to` not after `valid_from` |
| `schema.domain`, `schema.range` | error | Subject or object of the wrong type |
| `schema.moment_with_end` | error | A `moment` predicate with `valid_to` |
| `schema.unknown_predicate` | info (error if `strict`) | Predicate not in the schema |
| `subject.unresolved`, `object.unresolved` | warning | Still a name, not an entity |
| `subject.unknown_entity`, `object.unknown_entity` | warning | A `Ref` the coop doesn't know |
| `confidence.too_low` | error | Below `reject_below` (default 0.2) |
| `confidence.below_accept` | warning | Below `accept_at` (default 0.5) |
| `confidence.unknown` | info | No confidence given (not penalized) |

Add your own checks as functions that return findings:

```python
from chickentruck import Finding

def no_future_births(tender):
    if tender.predicate == "BORN_IN" and tender.valid_from and tender.valid_from.value.year > 2026:
        yield Finding("custom.future_birth", "error", "birth date is in the future")

print(grill(resolved, schema=schema, coop=coop, rules=[no_future_births]).status)   # accepted
```

### 7. Store and query knowledge

`ChickenStock` holds accepted facts in memory and indexes them by
subject, predicate, and object. When the same claim arrives from
another source, its evidence **merges** into the existing fact and the
confidence goes up:

```python
from chickentruck import ChickenStock

stock = ChickenStock(schema=schema)
stock.add(result)

letters = Source("letters", title="Collected letters", authority=0.8)
again = coop.resolve_tender(ChickenTender(
    "Benjamin Franklin", "BORN_IN", "Boston",
    evidence=[Evidence(letters, quote="I was born in Boston", confidence=0.7)],
    valid_from="1706-01-17",
))
fact = stock.add(grill(again, schema=schema, coop=coop))
print(len(stock), [e.source.id for e in fact.evidence], round(fact.confidence, 3))
# 1 ['encyclopedia', 'letters'] 0.936

worked = coop.resolve_tender(ChickenTender(
    "Benjamin Franklin", "WORKED_AT", "Post Office",
    evidence=[Evidence(letters, confidence=0.9)],
    valid_from="1753", valid_to="1774",
    qualifiers={"role": "Deputy Postmaster General"},
))
stock.add(grill(worked, schema=schema, coop=coop))
```

`find` matches any combination of subject, predicate, and object, then
filters:

```python
stock.find(subject="person:franklin")                 # everything about Franklin
stock.find(predicate="WORKED_AT", object=Ref("org:post-office"))   # entities as Refs
stock.find(min_confidence=0.8)

print(len(stock.find(predicate="WORKED_AT", valid_at="1760")))   # 1   true in 1760
print(len(stock.find(predicate="WORKED_AT", valid_at="1780")))   # 0   no longer true
```

**Time has precision.** `"1706"` stays a year, `"1706-01"` a month,
`"1706-01-17"` a day, and full ISO datetimes need a timezone. Validity
is the half-open interval `[valid_from, valid_to)`, and a missing end
means it's still true.

**There are two timelines.** `valid_at=` asks *what was true then*.
`as_of=` asks *what the stock believed then*, using the time each fact
was recorded and superseded. Superseded facts are hidden unless you pass
`include_superseded=True`.

### 8. Conflicts

For a `cardinality="one"` predicate, two active facts with the same
subject, different objects, and overlapping validity are a
**conflict**. ChickenTruck never settles one silently by default:

```python
blog = Source("blog", authority=0.6)
rival = coop.resolve_tender(ChickenTender(
    "Benjamin Franklin", "BORN_IN", "Philadelphia",
    evidence=[Evidence(blog, confidence=0.9)], valid_from="1706-01-17",
))
stock.add(grill(rival, schema=schema, coop=coop))

[conflict] = stock.conflicts(open_only=True)
print(conflict.predicate, conflict.policy, conflict.winner)   # BORN_IN keep_both None

# A reviewer settles it; the loser is superseded, never deleted
boston = stock.find(subject="person:franklin", predicate="BORN_IN", object=Ref("place:boston"))[0]
stock.resolve_conflict(conflict.conflict_id, boston.fact_id)
print([f.object.id for f in stock.find(predicate="BORN_IN")])   # ['place:boston']
print(len(stock.find(predicate="BORN_IN", include_superseded=True)))   # 2
```

| Policy | Behavior |
|---|---|
| `keep_both` (default) | Record the conflict; a person decides with `resolve_conflict` |
| `highest_confidence` | Keep the fact with the higher combined confidence |
| `highest_authority` | Keep the fact backed by the most authoritative source |
| `most_recent_evidence` | Keep the fact with the newest evidence |

Pass a policy with `ChickenStock(schema=schema, policy=highest_confidence)`.
On a tie, every policy keeps both facts and leaves the conflict open.

### 9. Persist to SQLite

`SqliteStock` follows exactly the same rules, stored in a file with
Python's built-in `sqlite3`. It saves the schema, facts, evidence,
sources, conflicts, and entities. Give the coop the stock as its
`store` and entities are saved too:

```python
from chickentruck import SqliteStock

with SqliteStock("knowledge.db", schema=schema) as db:
    db_coop = ChickenCoop(schema=schema, store=db)
    for entity in coop.entities():
        db_coop.add(entity)
    for fact in stock.all():
        db.add(fact)

# Later, in another process: everything is in the file
with SqliteStock("knowledge.db") as db:
    db_coop = ChickenCoop(schema=db.schema, store=db)
    print(len(db), db_coop.resolve("Ben Franklin").entity_id)   # 3 person:franklin
    # (3 facts: the superseded Philadelphia fact is kept as history)
```

Each `add` is a single transaction. The conflict policy is code, so you
pass it each time you open the file. The stock test suite runs against
both backends, so they behave identically.

### 10. Export: graph, tables, RDF

```python
from chickentruck import to_graph, to_ntriples, to_tables

graph = to_graph(stock, coop=coop)
print(graph.nodes[0])
# {'id': 'person:franklin', 'label': 'Benjamin Franklin', 'type': 'Scientist',
#  'aliases': ['Ben Franklin', 'Poor Richard'], 'provisional': False, 'properties': {}}
print(graph.edges[0]["predicate"], graph.edges[0]["target"], graph.edges[0]["sources"])
# BORN_IN place:boston ['encyclopedia', 'letters']
```

- **`to_graph`**: entities become nodes and entity-to-entity facts
  become edges carrying `fact_id`, confidence, validity, qualifiers, and
  source IDs. Literal facts become node `properties` (`mode="simple"`),
  or separate `statements` that keep their provenance (`mode="full"`).
  `graph.to_dict()` is JSON-ready, so you can load it into Neo4j,
  NetworkX, or a visualizer.
- **`to_tables`**: normalized relational tables (`entities`, `aliases`,
  `sources`, `facts`, `evidence`, `qualifiers`, `conflicts`), each a
  list of flat dicts with scalar cells. History is included by default.
- **`to_ntriples`**: RDF N-Triples with XSD-typed literals by
  precision (`gYear`, `date`, ...), for semantic-web tools. Only active
  facts are exported.

```python
tables = to_tables(stock, coop=coop)
print(sorted(tables))
# ['aliases', 'conflicts', 'entities', 'evidence', 'facts', 'qualifiers', 'sources']
print(to_ntriples(stock, coop=coop).splitlines()[0])
# <urn:chickentruck:entity/person%3Afranklin> <http://www.w3.org/2000/01/rdf-schema#label> "Benjamin Franklin" .
```

### 11. Ground prompts and check claims

`render_facts` turns facts into cited lines ready to paste into a
prompt:

```python
print(render_facts(stock.find(subject="person:franklin"), coop=coop))
# - Benjamin Franklin born in Boston (from 1706-01-17; confidence 0.94) [1, 2]
# - Benjamin Franklin worked at Post Office (role: Deputy Postmaster General; from 1753 to 1774; confidence 0.72) [2]
#
# Sources:
# [1] Encyclopedia - https://example.org/franklin
# [2] Collected letters
```

`check_claim` checks a statement, for example an agent's answer,
against the stock:

```python
for city in ("Boston", "Philadelphia", "Paris"):
    print(city, check_claim(stock, "Ben Franklin", "BORN_IN", city, coop=coop).verdict)
# Boston supported
# Philadelphia contradicted
# Paris contradicted

print(check_claim(stock, "Ben Franklin", "WORKED_AT", "Post Office", at="1760", coop=coop).verdict)
# supported
```

| Verdict | Meaning |
|---|---|
| `supported` | An active fact states the claim |
| `contradicted` | The predicate is single-valued and an active fact says otherwise |
| `disputed` | Both: the stock holds an open conflict about this |
| `unknown` | Nothing either way (multi-valued predicates are never contradicted) |

The returned `ClaimCheck` also includes the `supporting` and
`contradicting` facts and their `evidence`, so an agent can cite them.

---

## Recipes

**Load the tables into pandas** (pandas isn't a dependency; this is
your code):

```python
# illustration only
import pandas as pd
frames = {name: pd.DataFrame(rows) for name, rows in to_tables(stock).items()}
```

**Grounded question answering:**

```python
# illustration only
facts = stock.find(subject=coop.resolve(user_question_entity).entity_id)
prompt = f"Answer using only these facts:\n{render_facts(facts, coop=coop)}\n\nQ: {question}"
```

**A review queue:** keep the results `process_text` didn't accept, and
the provisional entities it created:

```python
results = process_text(
    "Grace Hopper was born in New York. Hopper worked at the Navy.",
    source=Source("forum", authority=0.6),
    extractor=PatternExtractor([
        Pattern("BORN_IN", "{subject} was born in {object}"),
        Pattern("WORKED_AT", "{subject} worked at the {object}"),
    ]),
    coop=coop, stock=stock,
)
review = [r for r in results if not r.accepted]
for r in review:
    print(r.status, r.tender.predicate, r.reasons)
# needs_review BORN_IN ['confidence 0.42 is below the acceptance threshold 0.50']
# needs_review WORKED_AT ['confidence 0.42 is below the acceptance threshold 0.50']

# New names became provisional entities for a person to review:
# confirm the real ones, and notice that "Hopper" is probably "Grace Hopper"
print([e.label for e in coop.provisional()])
# ['Grace Hopper', 'New York', 'Hopper', 'Navy']
```

## API reference

| Name | Kind | Summary |
|---|---|---|
| `Schema(entity_types, predicates, strict)` | class | `add_type`, `add_predicate`, `predicate`, `is_a`, `to_dict` / `from_dict`, `to_json` / `from_json` |
| `EntityType(name, parent, description)` | class | A kind of entity |
| `Predicate(name, domain, range, cardinality, temporal, description)` | class | What a predicate accepts |
| `Source(id, kind, uri, title, retrieved_at, authority)` | class | Where information came from |
| `Evidence(source, locator, quote, confidence, extractor, extracted_at)` | class | One sighting of a claim |
| `ChickenTender(subject, predicate, object, evidence, valid_from, valid_to, qualifiers)` | class | A candidate claim |
| `Nugget(subject, predicate, object)` | class | A bare fact |
| `Pattern(predicate, template, subject_type, object_type, confidence, regex, convert)` | class | One phrasing of a claim |
| `PatternExtractor(patterns, name, clock)` | class | Deterministic extractor |
| `LLMExtractor(complete, schema, instructions, confidence, require_quote, max_chars, name, clock)` | class | Model-backed extractor: `extract`, `extract_with_report` |
| `Extractor` | protocol | `extract(text, *, source) -> list[ChickenTender]` |
| `extract_nuggets(text, extractor, *, source=None)` | function | Bare `Nugget`s from any extractor |
| `process_text(text, *, source, extractor, coop, schema, stock, **grill_options)` | function | Extract, resolve, grill, store; returns every `GrillResult` |
| `build_prompt(text, schema, instructions)` / `parse_claims(response)` | functions | The LLM extractor's prompt and parser, for reuse |
| `ChickenCoop(schema, store)` | class | `add`, `get`, `entities`, `resolve`, `resolve_tender`, `add_alias`, `confirm`, `provisional`, `candidates` |
| `Entity(id, label, type, aliases, provisional)`, `Ref(id)`, `Mention(text, type)` | classes | Entities, references, unresolved names |
| `grill(tender, *, schema, coop, rules, accept_at, reject_below, require_evidence, combine)` | function | Validate into a `GrillResult(status, findings, fact)` |
| `Fact` | class | Accepted knowledge: `fact_id`, `subject`, `predicate`, `object`, `evidence`, `confidence`, validity, `qualifiers`, `status`, `recorded_at`, `superseded_at` |
| `ChickenStock(schema, policy, combine, clock)` / `SqliteStock(path, *, schema, policy, combine, clock)` | classes | `add`, `get`, `find`, `all`, `sources`, `conflicts`, `resolve_conflict`, entity storage |
| `keep_both`, `highest_confidence`, `highest_authority`, `most_recent_evidence` | policies | Conflict handling |
| `to_graph`, `to_tables`, `to_ntriples` | functions | Exports |
| `render_facts`, `check_claim` | functions | RAG and agent helpers |
| `noisy_or`, `parse_time`, `TimePoint` | helpers | Confidence combination and time handling |

## Design principles

- **Nothing is guessed.** Ambiguous names stay unresolved, pronouns
  aren't followed, made-up quotes are dropped, and conflicts wait for a
  decision.
- **Provenance is required.** Every fact can answer "says who, and
  where?"
- **Nothing is deleted.** Losers are superseded and stay queryable with
  `as_of`.
- **No lock-in.** There are no runtime dependencies. Models are reached
  through a plain function. Exports are plain dicts and text.
- **Honest scope.** Features that don't exist raise errors instead of
  producing fake output.

## The Food Truck Fleet

ChickenTruck is one of a fleet of independent, food-themed Python
packages. Each owns one stage of a data pipeline. They never import each
other and compose only through plain data at the application layer.

| Package | Owns |
|---|---|
| **SushiTruck** | Ingestion: streaming sources, REST APIs, file and object stores |
| **ThaiTruck** | DataFrame cleaning and transformation |
| **RamenTruck** | Modeling and machine learning |
| **BentoTruck** | Agent orchestration |
| **FishTruck** | Anomaly and data-quality detection |
| **ChickenTruck** | Knowledge engineering (this package) |

So ChickenTruck doesn't fetch data, clean DataFrames, train models,
orchestrate agents, or do general anomaly detection.

## Limitations

- The pattern extractor matches proper names by capitalization and
  doesn't follow pronouns or other references across sentences. A
  capitalized word at the start of a sentence can end up in a name
  ("Yesterday Ben Franklin"). Put specific patterns first and review
  provisional entities.
- Entity resolution is exact or normalized matching only. Fuzzy and
  embedding resolvers plug in through `resolver=`; none are built in yet.
- `find` is pattern matching plus filters, not a query language.
- Evidence merged into a fact reflects the current state, so an `as_of`
  query shows which facts were believed then, with the evidence they
  hold now.
- Postgres and Neo4j backends, RDFS/OWL import, and spaCy extraction
  are possible future optional extras.

## Development

```bash
git clone https://github.com/sgtidwellgit/ChickenTruck
cd ChickenTruck
pip install -e ".[dev]"
pytest
```

CI runs the suite on Linux, Windows, and macOS for Python 3.9-3.12.
Design decisions are recorded in [`PROJECT.md`](https://github.com/sgtidwellgit/ChickenTruck/blob/main/PROJECT.md).
Versions are date-based (`YYYY.M.D`).

## License

MIT. See [`LICENSE`](https://github.com/sgtidwellgit/ChickenTruck/blob/main/LICENSE).
