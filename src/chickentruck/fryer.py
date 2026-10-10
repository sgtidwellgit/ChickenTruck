"""chicken_fryer -- turning raw text into candidate claims.

Raw text goes into the fryer and comes out as `ChickenTender`s:
candidate claims that already carry their `Evidence` (which source,
where in it, the quoted text, which extractor, how confident). Nothing
an extractor produces is trusted yet -- it still has to be resolved by
a `ChickenCoop` and pass `grill`.

Two extractors are provided, both behind the `Extractor` protocol:

- `PatternExtractor` -- deterministic, dependency-free matching of
  `Pattern`s written as readable templates
  (``"{subject} was born in {object}"``) or raw regular expressions.
- `LLMExtractor` -- asks a language model for claims as JSON. The model
  is reached through a plain ``complete(prompt) -> str`` function the
  caller supplies, so no provider SDK is imported and any model works.
  Claims whose quote cannot be found in the text are dropped.

`process_text` runs the whole pipeline: extract, resolve, grill, and
stock what is accepted.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Pattern as RegexPattern,
    Protocol,
    Sequence,
    Tuple,
    Union,
)

from .coop import ChickenCoop, Mention
from .grilled import GrillResult, grill
from .recipe import LITERAL_TYPES, Schema
from .tenders import ChickenTender, Evidence, Source


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Extractor(Protocol):
    """Anything that turns text from a source into candidate claims."""

    def extract(self, text: str, *, source: Source) -> List[ChickenTender]:
        ...


# --- Patterns -------------------------------------------------------------

_UPPER = "A-Z" + chr(0xC0) + "-" + chr(0xD6) + chr(0xD8) + "-" + chr(0xDE)  # Latin-1 capitals
_APOSTROPHES = "'" + chr(0x2019)
_NAME_WORD = rf"(?:[{_UPPER}]\.|[{_UPPER}][\w{_APOSTROPHES}-]*)"
_CONNECTOR = r"(?:of|the|and|de|del|della|der|du|da|la|le|van|von|y)"

#: Capitalized words that start sentences but never start a name.
STOP_WORDS = (
    "A An And As At But By For From He Her Hers Him His However I In Is It Its "
    "My Of On Or Our She So That The Their Them Then There These They This "
    "Those To We When Where Which While Who You Your"
).split()

#: A proper name: capitalized words, with initials and lowercase
#: connectors allowed inside ("Benjamin Franklin", "J. R. Smith",
#: "University of Pennsylvania"). A name never starts with a pronoun or
#: other `STOP_WORDS` entry, so "He" is not a name and "The University
#: of Pennsylvania" matches as "University of Pennsylvania".
NAME = (
    rf"(?!(?:{'|'.join(STOP_WORDS)})\b(?!\.))"
    rf"{_NAME_WORD}(?:(?:\s+{_CONNECTOR})*\s+{_NAME_WORD})*"
)

_MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}
_MONTH = "(?i:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"

#: A date: ISO (``1706``, ``1706-01``, ``1706-01-17``) or written out
#: (``January 17, 1706``, ``17 January 1706``, ``January 1706``).
DATE = (
    rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{4}}-\d{{2}}"
    rf"|{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}"
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\s+\d{{4}}"
    rf"|{_MONTH}\s+\d{{4}}"
    rf"|\d{{4}})"
)


def to_iso_date(text: str) -> str:
    """Normalize a `DATE` match to ISO: ``"January 17, 1706"`` -> ``"1706-01-17"``."""

    text = text.strip()
    if re.fullmatch(r"\d{4}(-\d{2}){0,2}", text):
        return text
    words = re.findall(r"[A-Za-z]+|\d+", text)
    month = day = year = None
    for word in words:
        lowered = word.lower()
        if lowered in _MONTHS:
            month = _MONTHS[lowered]
        elif word.isdigit() and len(word) == 4:
            year = word
        elif word.isdigit():
            day = int(word)
    if year is None or month is None:
        raise ValueError(f"not a recognizable date: {text!r}")
    if day is None:
        return f"{year}-{month:02d}"
    return f"{year}-{month:02d}-{day:02d}"


#: Placeholder kinds usable in templates: ``{name:kind}``.
KINDS: Dict[str, Tuple[str, Optional[Callable[[str], Any]]]] = {
    "name": (NAME, None),
    "date": (DATE, to_iso_date),
    "year": (r"\d{4}", None),
    "int": (r"-?\d[\d,]*", lambda s: int(s.replace(",", ""))),
    "number": (r"-?\d[\d,]*(?:\.\d+)?", lambda s: float(s.replace(",", ""))),
    "word": (rf"[\w{_APOSTROPHES}-]+", None),
    "text": (r"[^.;:!?\n]+", None),
}

_DEFAULT_KINDS = {"subject": "name", "object": "name", "valid_from": "date", "valid_to": "date"}
_PLACEHOLDER = re.compile(r"\{(\w+)(?::(\w+))?\}")
_RESERVED = ("subject", "object", "valid_from", "valid_to")


def _compile_template(template: str) -> Tuple[str, Dict[str, Callable[[str], Any]]]:
    parts: List[str] = []
    converters: Dict[str, Callable[[str], Any]] = {}
    seen = set()
    pieces = _PLACEHOLDER.split(template)
    # split() yields: literal, name, kind, literal, name, kind, ..., literal
    for index in range(0, len(pieces), 3):
        literal = pieces[index]
        if literal:
            words = literal.split()
            body = r"\s+".join(re.escape(w) for w in words)
            lead = r"\s+" if literal[0].isspace() else ""
            trail = r"\s+" if literal[-1].isspace() and words else ""
            if not words:
                parts.append(r"\s+")
            else:
                parts.append(f"{lead}(?i:{body}){trail}")
        if index + 1 >= len(pieces):
            break
        name, kind = pieces[index + 1], pieces[index + 2]
        if name in seen:
            raise ValueError(f"placeholder {{{name}}} appears twice in {template!r}")
        seen.add(name)
        kind = kind or _DEFAULT_KINDS.get(name, "text")
        if kind not in KINDS:
            raise ValueError(f"unknown placeholder kind {kind!r}; use one of {sorted(KINDS)}")
        regex, convert = KINDS[kind]
        parts.append(f"(?P<{name}>{regex})")
        if convert is not None:
            converters[name] = convert
    missing = {"subject", "object"} - seen
    if missing:
        raise ValueError(f"template {template!r} needs {{subject}} and {{object}}")
    return r"(?<![\w'])" + "".join(parts) + r"(?![\w'])", converters


@dataclass(frozen=True)
class Pattern:
    """One way a claim is phrased in text.

    ``template`` is readable text with placeholders, e.g.
    ``"{subject} was born in {object}"``. Placeholders take a kind
    (``{object:int}``); see `KINDS`. ``subject`` and ``object`` default
    to proper names, ``valid_from`` / ``valid_to`` to dates, and any
    other placeholder (``{role}``) becomes a qualifier. Literal words
    match case-insensitively and any run of whitespace.

    With ``regex=True`` the template is a raw regular expression using
    the same named groups.

    ``convert`` maps a placeholder name to a function applied to its
    matched text (overriding the kind's own conversion).
    ``subject_type`` / ``object_type`` become type hints on the
    `Mention`s, which guide resolution.
    """

    predicate: str
    template: str
    subject_type: Optional[str] = None
    object_type: Optional[str] = None
    confidence: Optional[float] = 0.7
    regex: bool = False
    convert: Mapping[str, Callable[[str], Any]] = field(default_factory=dict)
    compiled: RegexPattern = field(init=False, repr=False, compare=False)
    converters: Dict[str, Callable[[str], Any]] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.predicate:
            raise ValueError("a pattern needs a predicate")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {self.confidence!r}")
        if self.regex:
            compiled = re.compile(self.template)
            if not {"subject", "object"} <= set(compiled.groupindex):
                raise ValueError("a regex pattern needs (?P<subject>...) and (?P<object>...) groups")
            converters: Dict[str, Callable[[str], Any]] = {}
        else:
            source, converters = _compile_template(self.template)
            compiled = re.compile(source)
        converters.update(self.convert)
        object.__setattr__(self, "compiled", compiled)
        object.__setattr__(self, "converters", converters)

    def matches(self, text: str) -> List["re.Match[str]"]:
        return list(self.compiled.finditer(text))


@dataclass
class PatternExtractor:
    """Deterministic extraction by `Pattern` matching.

    Every match becomes one tender whose evidence quotes the matched
    text and locates it as ``"chars START-END"``. List specific patterns
    before general ones: a match that overlaps an earlier pattern's match
    for the same predicate is dropped, so "born in Boston on January 17,
    1706" is not also reported by a plain "born in" pattern. Pronouns and other
    references across sentences are not followed: "He was born in
    Boston" yields nothing, which is preferable to a wrong guess.
    """

    patterns: Sequence[Pattern]
    name: str = "pattern"
    clock: Callable[[], datetime] = _utc_now

    def extract(self, text: str, *, source: Source) -> List[ChickenTender]:
        found = []
        taken: Dict[str, List[Tuple[int, int]]] = {}
        for order, pattern in enumerate(self.patterns):
            spans = taken.setdefault(pattern.predicate, [])
            for match in pattern.matches(text):
                if any(match.start() < end and start < match.end() for start, end in spans):
                    continue
                spans.append((match.start(), match.end()))
                found.append((match.start(), order, pattern, match))
        found.sort(key=lambda item: (item[0], item[1]))
        now = self.clock()
        return [self._tender(pattern, match, source, now) for _, _, pattern, match in found]

    def _tender(self, pattern: Pattern, match: "re.Match[str]", source: Source, now: datetime) -> ChickenTender:
        values: Dict[str, Any] = {}
        for group, raw in match.groupdict().items():
            if raw is None:
                continue
            raw = raw.strip()
            convert = pattern.converters.get(group)
            values[group] = convert(raw) if convert is not None else raw

        subject = values.pop("subject")
        if pattern.subject_type:
            subject = Mention(subject, pattern.subject_type)
        obj = values.pop("object")
        if isinstance(obj, str) and pattern.object_type:
            obj = Mention(obj, pattern.object_type)

        evidence = Evidence(
            source,
            locator=f"chars {match.start()}-{match.end()}",
            quote=match.group(0),
            confidence=pattern.confidence,
            extractor=self.name,
            extracted_at=now,
        )
        return ChickenTender(
            subject,
            pattern.predicate,
            obj,
            evidence=[evidence],
            valid_from=values.pop("valid_from", None),
            valid_to=values.pop("valid_to", None),
            qualifiers=values,
        )


# --- Language models ------------------------------------------------------


class ExtractionError(ValueError):
    """A model's response could not be read as claims at all."""

    def __init__(self, message: str, response: str = ""):
        super().__init__(message)
        self.response = response


@dataclass(frozen=True)
class Skipped:
    """A claim from a model that was dropped, and why."""

    item: Any
    reason: str


@dataclass(frozen=True)
class Extraction:
    """The full outcome of an `LLMExtractor` run."""

    tenders: Tuple[ChickenTender, ...]
    skipped: Tuple[Skipped, ...]
    responses: Tuple[str, ...]


_PROMPT = """\
Extract factual claims from the text below as JSON.

Return a JSON object of the form {{"claims": [...]}}. Each claim has:
  "subject"       the entity the claim is about, named as in the text
  "subject_type"  its entity type{type_hint}
  "predicate"     the relationship{predicate_hint}
  "object"        another entity's name, or a literal value (number, true/false, text, date)
  "object_type"   the object's entity type, or one of: {literals}
  "valid_from"    when the claim became true (YYYY, YYYY-MM, or YYYY-MM-DD), or null
  "valid_to"      when it stopped being true, or null
  "qualifiers"    an object with extra detail (such as a role), or {{}}
  "quote"         the exact words from the text that state the claim
  "confidence"    0 to 1, how clearly the text states the claim

Rules:
- Only extract what the text states. Do not add outside knowledge.
- Replace pronouns with the name they refer to.
- "quote" must be copied exactly from the text.
- If there are no claims, return {{"claims": []}}.
{schema}{instructions}
Text:
\"\"\"
{text}
\"\"\"
"""


def describe_schema(schema: Schema) -> str:
    """The schema as prompt text: entity types and predicates."""

    lines = ["Entity types:"]
    for entity_type in schema.entity_types.values():
        line = f"- {entity_type.name}"
        if entity_type.parent:
            line += f" (a kind of {entity_type.parent})"
        if entity_type.description:
            line += f": {entity_type.description}"
        lines.append(line)
    lines.append("Predicates:")
    for predicate in schema.predicates.values():
        domain = " or ".join(predicate.domain) or "anything"
        line = f"- {predicate.name}: {domain} -> {predicate.range or 'anything'}"
        if predicate.cardinality == "one":
            line += ", one value at a time"
        if predicate.temporal == "moment":
            line += ", happens at a moment (valid_from only)"
        if predicate.description:
            line += f". {predicate.description}"
        lines.append(line)
    return "\n".join(lines)


def build_prompt(text: str, schema: Optional[Schema] = None, instructions: str = "") -> str:
    """The prompt `LLMExtractor` sends for ``text``."""

    if schema is not None and schema.predicates:
        predicate_hint = ", one of the predicates listed below"
        schema_text = "\nUse only these types and predicates:\n" + describe_schema(schema) + "\n"
    else:
        predicate_hint = ", in UPPER_SNAKE_CASE (e.g. BORN_IN)"
        schema_text = ""
    type_hint = ", one of the types listed below" if schema_text and schema.entity_types else ", or null"
    extra = f"\n{instructions.strip()}\n" if instructions.strip() else ""
    return _PROMPT.format(
        type_hint=type_hint,
        predicate_hint=predicate_hint,
        literals=", ".join(LITERAL_TYPES),
        schema=schema_text,
        instructions=extra,
        text=text,
    )


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_claims(response: str) -> List[Any]:
    """Pull the list of claims out of a model response.

    Accepts ``{"claims": [...]}``, a bare list, or a single claim
    object, with or without a code fence or surrounding prose.
    """

    candidates = [m.group(1) for m in _FENCE.finditer(response)] + [response]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for start, char in enumerate(candidate):
            if char not in "[{":
                continue
            try:
                data, _ = decoder.raw_decode(candidate, start)
            except ValueError:
                continue
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and isinstance(data.get("claims"), list):
                return data["claims"]
            if isinstance(data, dict) and "subject" in data:
                return [data]
    raise ExtractionError("no JSON claims found in the model response", response)


def split_text(text: str, max_chars: int) -> List[Tuple[int, str]]:
    """Split ``text`` into ``(offset, chunk)`` pieces of at most ``max_chars``.

    Breaks fall on paragraph boundaries where possible, then sentence
    ends, then whitespace; a chunk is only cut mid-word as a last resort.
    """

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    chunks: List[Tuple[int, str]] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            window = text[start:end]
            for pattern in (r"\n\s*\n", r"[.!?]\s", r"\s"):
                breaks = [m.end() for m in re.finditer(pattern, window)]
                if breaks and breaks[-1] > 0:
                    end = start + breaks[-1]
                    break
        chunk = text[start:end]
        if chunk.strip():
            chunks.append((start, chunk))
        start = end
    return chunks


_PREDICATE_CLEAN = re.compile(r"[^0-9A-Za-z]+")


def _predicate_name(value: str) -> str:
    return _PREDICATE_CLEAN.sub("_", value.strip()).strip("_").upper()


def _find_quote(quote: str, text: str) -> Optional[Tuple[int, int]]:
    words = quote.split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(w) for w in words)
    match = re.search(pattern, text, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


class _Skip(Exception):
    pass


@dataclass
class LLMExtractor:
    """Extraction by a language model, through a caller-supplied function.

    ``complete`` takes a prompt string and returns the model's text
    reply; wrap whichever client you use in it. With a ``schema`` the
    prompt lists its types and predicates. Each returned claim becomes
    a tender; claims are dropped (and reported in `Extraction.skipped`)
    when they are malformed or, with ``require_quote`` (the default),
    when their quote does not appear in the text -- a guard against
    claims the model made up.

    ``confidence`` is used when the model gives none. Long text is sent
    in chunks of at most ``max_chars`` characters.
    """

    complete: Callable[[str], str]
    schema: Optional[Schema] = None
    instructions: str = ""
    confidence: Optional[float] = 0.6
    require_quote: bool = True
    max_chars: Optional[int] = 12000
    name: str = "llm"
    clock: Callable[[], datetime] = _utc_now

    def extract(self, text: str, *, source: Source) -> List[ChickenTender]:
        return list(self.extract_with_report(text, source=source).tenders)

    def extract_with_report(self, text: str, *, source: Source) -> Extraction:
        """Like `extract`, but also returns skipped claims and raw responses."""

        chunks = split_text(text, self.max_chars) if self.max_chars else [(0, text)]
        tenders: List[ChickenTender] = []
        skipped: List[Skipped] = []
        responses: List[str] = []
        for offset, chunk in chunks:
            response = self.complete(build_prompt(chunk, self.schema, self.instructions))
            responses.append(response)
            now = self.clock()
            for item in parse_claims(response):
                try:
                    tenders.append(self._tender(item, chunk, offset, source, now))
                except _Skip as reason:
                    skipped.append(Skipped(item, str(reason)))
        return Extraction(tuple(tenders), tuple(skipped), tuple(responses))

    def _tender(self, item: Any, chunk: str, offset: int, source: Source, now: datetime) -> ChickenTender:
        if not isinstance(item, dict):
            raise _Skip("claim is not a JSON object")
        subject = item.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            raise _Skip("missing subject")
        predicate = item.get("predicate")
        if not isinstance(predicate, str) or not _predicate_name(predicate):
            raise _Skip("missing predicate")
        predicate = _predicate_name(predicate)
        obj = item.get("object")
        if obj is None or (isinstance(obj, str) and not obj.strip()):
            raise _Skip("missing object")
        if isinstance(obj, (list, dict)):
            raise _Skip("object must be a single value")

        subject_type = item.get("subject_type") or None
        subject_value: Any = Mention(subject.strip(), subject_type) if isinstance(subject_type, str) else subject.strip()
        obj = self._object(obj, item.get("object_type"), predicate)

        locator = quote = None
        raw_quote = item.get("quote")
        span = _find_quote(raw_quote, chunk) if isinstance(raw_quote, str) else None
        if span is not None:
            quote = chunk[span[0] : span[1]]
            locator = f"chars {offset + span[0]}-{offset + span[1]}"
        elif self.require_quote:
            raise _Skip("quote not found in the text" if raw_quote else "missing quote")

        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            confidence = self.confidence

        qualifiers = item.get("qualifiers") or {}
        if not isinstance(qualifiers, dict):
            raise _Skip("qualifiers must be a JSON object")

        try:
            return ChickenTender(
                subject_value,
                predicate,
                obj,
                evidence=[
                    Evidence(
                        source,
                        locator=locator,
                        quote=quote,
                        confidence=confidence,
                        extractor=self.name,
                        extracted_at=now,
                    )
                ],
                valid_from=item.get("valid_from") or None,
                valid_to=item.get("valid_to") or None,
                qualifiers={str(k): v for k, v in qualifiers.items()},
            )
        except (TypeError, ValueError) as error:
            raise _Skip(f"invalid claim: {error}") from None

    def _object(self, value: Any, object_type: Any, predicate: str) -> Any:
        if not isinstance(object_type, str) or not object_type:
            object_type = None
            if self.schema is not None and self.schema.predicate(predicate) is not None:
                object_type = self.schema.predicate(predicate).range
        if not isinstance(value, str):
            return value
        value = value.strip()
        if object_type == "integer":
            try:
                return int(value.replace(",", ""))
            except ValueError:
                raise _Skip(f"object {value!r} is not an integer") from None
        if object_type == "number":
            try:
                return float(value.replace(",", ""))
            except ValueError:
                raise _Skip(f"object {value!r} is not a number") from None
        if object_type == "boolean":
            if value.lower() in ("true", "yes"):
                return True
            if value.lower() in ("false", "no"):
                return False
            raise _Skip(f"object {value!r} is not true or false")
        if object_type is None or object_type in LITERAL_TYPES:
            return value
        return Mention(value, object_type)


# --- The whole pipeline ---------------------------------------------------


def process_text(
    text: str,
    *,
    source: Source,
    extractor: Union[Extractor, Sequence[Extractor]],
    coop: Optional[ChickenCoop] = None,
    schema: Optional[Schema] = None,
    stock: Any = None,
    **grill_options: Any,
) -> List[GrillResult]:
    """Extract, resolve, grill, and stock: text in, results out.

    Runs each extractor over ``text``, resolves mentions with ``coop``
    (when given), grills every tender, and adds the accepted ones to
    ``stock`` (when given). Returns every `GrillResult`, so rejected and
    needs-review claims can be inspected. ``schema`` defaults to the
    coop's, then the stock's. Extra keyword arguments go to `grill`.
    """

    extractors = list(extractor) if isinstance(extractor, (list, tuple)) else [extractor]
    if schema is None and coop is not None:
        schema = coop.schema
    if schema is None and stock is not None:
        schema = getattr(stock, "schema", None)

    results = []
    for each in extractors:
        for tender in each.extract(text, source=source):
            if coop is not None:
                if coop.schema is None and schema is not None:
                    tender = _type_mentions(tender, schema)
                tender = coop.resolve_tender(tender)
            result = grill(tender, schema=schema, coop=coop, **grill_options)
            if stock is not None and result.accepted:
                stock.add(result)
            results.append(result)
    return results


def _type_mentions(tender: ChickenTender, schema: Schema) -> ChickenTender:
    """Give plain-string entities the type hints a schema-less coop can't infer."""

    predicate = schema.predicate(tender.predicate)
    if predicate is None:
        return tender
    subject, obj = tender.subject, tender.object
    if isinstance(subject, str) and len(predicate.domain) == 1:
        subject = Mention(subject, predicate.domain[0])
    if isinstance(obj, str) and predicate.range_is_entity:
        obj = Mention(obj, predicate.range)
    return dataclasses.replace(tender, subject=subject, object=obj)
