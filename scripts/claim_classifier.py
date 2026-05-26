"""Claim extractor + classifier (genesis Part VIII).

GPT-4o primary with deterministic regex fallback covering all 11 claim types.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Iterable


CLAIM_TYPES = ("statistic", "date_event", "attribution", "status", "legal_regulatory",
               "institutional", "procedure", "standard_ref", "convention", "currency", "anti_pattern")


@dataclass
class Claim:
    claim_id: str
    text: str
    type: str
    entities: list
    temporal: bool
    searchable: bool
    dedup_key: str
    query_plan: dict

    def as_dict(self): return self.__dict__


@dataclass
class ClaimExtractor:
    openai_key: str = ""
    model: str = "gpt-4o"

    def extract(self, text, *, use_gpt=True):
        if use_gpt and self.openai_key:
            try:
                claims = self._gpt_extract(text)
                if claims: return claims
            except Exception: pass
        return self._regex_extract(text)

    def _gpt_extract(self, text):
        import importlib
        openai = importlib.import_module("openai")
        client = openai.OpenAI(api_key=self.openai_key)
        prompt = _build_gpt_prompt(text)
        resp = client.chat.completions.create(model=self.model, max_tokens=2048,
                                              messages=[{"role": "user", "content": prompt}])
        return _parse_claims_json(resp.choices[0].message.content or "")

    def _regex_extract(self, text):
        claims = []; seen_keys = set()
        for span in _split_sentences(text):
            t = span.strip()
            if not t or len(t) < 12: continue
            claim_type = _classify(t)
            if claim_type is None: continue
            entities = _extract_entities(t)
            temporal = bool(_TEMPORAL_RE.search(t))
            dedup_key = _make_dedup_key(claim_type, entities, t)
            if dedup_key in seen_keys: continue
            seen_keys.add(dedup_key)
            query_plan = _build_query_plan(t, claim_type, entities)
            searchable = bool(query_plan.get("primary") or query_plan.get("fallback"))
            claims.append(Claim(claim_id=f"C-{uuid.uuid4().hex[:8]}", text=t, type=claim_type,
                                entities=entities, temporal=temporal, searchable=searchable,
                                dedup_key=dedup_key, query_plan=query_plan))
        return claims


def dedup_claims(claims):
    by_key = {}
    for c in claims:
        if c.dedup_key not in by_key:
            by_key[c.dedup_key] = c
    return list(by_key.values())


def _build_gpt_prompt(text):
    return ("You are FACT_CHECKER's claim extractor for Project Shimmer.\n"
            "Extract every verifiable factual claim from the text.\n"
            f"Allowed types: {', '.join(CLAIM_TYPES)}\n\n"
            "Return a JSON array. Each item: text, type, entities, temporal, searchable, dedup_key, "
            "query_plan with optional primary/fallback (engine in {api,direct,ddg,brave}).\n\n"
            f"--- TEXT ---\n{text}\n--- END ---\nRespond JSON only.")


def _parse_claims_json(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"): raw = raw[4:].strip()
    start = raw.find("["); end = raw.rfind("]")
    if start < 0 or end <= start: return []
    try: items = json.loads(raw[start:end + 1])
    except json.JSONDecodeError: return []
    out = []
    for it in items:
        if not isinstance(it, dict) or "text" not in it: continue
        out.append(Claim(
            claim_id=f"C-{uuid.uuid4().hex[:8]}", text=str(it.get("text", "")).strip(),
            type=str(it.get("type", "attribution")), entities=list(it.get("entities", []) or []),
            temporal=bool(it.get("temporal", False)), searchable=bool(it.get("searchable", True)),
            dedup_key=str(it.get("dedup_key") or _make_dedup_key(
                str(it.get("type", "attribution")), list(it.get("entities", []) or []),
                str(it.get("text", "")))),
            query_plan=dict(it.get("query_plan", {}) or {})))
    return out


_SENT_RE = re.compile(r"(?<=[\.!?])\s+(?=[A-Z0-9])")
def _split_sentences(text): return _SENT_RE.split(re.sub(r"\s+", " ", text))

_STAT_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:%|percent|million|billion|trillion)\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b", re.IGNORECASE)
_LEGAL_RE = re.compile(r"\b(?:article|chapter|section|clause|regulation|protocol|annex)\s+[A-Z0-9]+(?:\.[A-Z0-9]+)*\b", re.IGNORECASE)
_INST_RE = re.compile(r"\b(?:United Nations|UN|General Assembly|Security Council|World Bank|IMF|WTO|WHO|UNESCO|UNHCR|ICC|ICJ|EU|NATO|OECD|G20|G7|African Union|ASEAN|OAS|ISO|IEEE|IETF|OIC|UNDP|ITU|WEF|GPAI)\b")
_STANDARD_RE = re.compile(r"\b(?:ISO|IEC|IEEE|RFC|ANSI|ASTM)[\s/\-]?\d+(?:[-:]\d+)*\b")
_CONVENTION_RE = re.compile(r"\b(?:Convention|Treaty|Charter|Declaration|Protocol|Pact)\s+(?:of|on)\s+[A-Z][\w\s]+", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"(?:\$|€|£|¥|USD|EUR|GBP|JPY|CHF|CNY)\s?\d|\b\d+(?:,\d{3})*(?:\.\d+)?\s?(?:USD|EUR|GBP|dollars?|euros?)\b")
_PROCEDURE_RE = re.compile(r"\b(?:procedure|process|protocol|workflow|step|stage|phase)\b", re.IGNORECASE)
_STATUS_RE = re.compile(r"\b(?:is|are|remains?|continues? to be|has been|have been)\s+(?:the|a|an)?\s*\w+", re.IGNORECASE)
_ANTI_PATTERN_RE = re.compile(r"\b(?:anti.?pattern|deprecated|discouraged|considered harmful|legacy)\b", re.IGNORECASE)
_TEMPORAL_RE = re.compile(r"\b(?:19|20)\d{2}\b|\b(?:today|yesterday|this year|last year|currently)\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b", re.IGNORECASE)

_CLASSIFY_ORDER = [
    ("anti_pattern", _ANTI_PATTERN_RE), ("currency", _CURRENCY_RE),
    ("standard_ref", _STANDARD_RE), ("convention", _CONVENTION_RE),
    ("legal_regulatory", _LEGAL_RE), ("statistic", _STAT_RE),
    ("date_event", _DATE_RE), ("institutional", _INST_RE),
    ("procedure", _PROCEDURE_RE), ("status", _STATUS_RE),
]


def _classify(t):
    for name, rx in _CLASSIFY_ORDER:
        if rx.search(t): return name
    return None


def _extract_entities(t):
    ents = set()
    for m in _INST_RE.finditer(t): ents.add(m.group(0))
    for m in re.finditer(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3}\b", t):
        token = m.group(0)
        if len(token) >= 4 and token.split()[0] not in {"The", "A", "An", "In", "On"}:
            ents.add(token)
    return sorted(ents)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _make_dedup_key(claim_type, entities, text):
    base_parts = [claim_type] + [_SLUG_RE.sub("_", e.lower()).strip("_") for e in entities[:3]]
    base = "_".join(p for p in base_parts if p)
    if not entities:
        body = _SLUG_RE.sub("_", text.lower()).strip("_")
        base += "_" + body[:40]
    return base[:120]


def _build_query_plan(text, claim_type, entities):
    plan = {}
    primary_query = " ".join(entities[:3] + [_keyword(text)]) if entities else text[:120]
    plan["primary"] = {"engine": "ddg", "query": primary_query}
    if claim_type in {"institutional", "convention", "legal_regulatory"} and entities:
        plan["fallback"] = {"engine": "ddg", "query": f"{entities[0]} official site"}
    return plan


def _keyword(t):
    words = re.findall(r"[A-Za-z]{4,}", t)
    return words[0] if words else ""
