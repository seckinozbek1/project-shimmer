"""LAW-IV PII-rule production (Mechanism 1 input, relocated in Phase 1b).

Compiles the OPERATOR REDACTION RULES the scrubber applies. This is privacy in
PURPOSE: it decides which spans are marked for masking. It RECEIVES the operator's
convention registry as a plain DATA dict (passed by the pipeline) and reads its
fields; it does NOT import convention_parser or any editorial schema/code, so there
is no dependency edge from the privacy home into editorial logic. Editorial-convention
PARSING stays in convention_parser; this module only consumes the compiled registry
data and hands back compiled rules.
"""

from __future__ import annotations

import re

# Redact-verb regex. Self-contained copy: this module owns redaction-phrasing
# detection and deliberately does NOT import the editorial _ACTION_PATTERNS from
# convention_parser (that would be a privacy->editorial edge).
_REDACT_VERB_RE = re.compile(
    r"\b(redact|mask|conceal|withhold|remove\s+from\s+output|do not (?:print|publish|disclose|reveal))\b",
    re.IGNORECASE)

# A convention is an OPERATOR REDACTION RULE: a machine-usable instruction the
# redactors APPLY to document spans (LAW-IV's own phrase, "content marked for
# redaction"). This replaces the phantom of a model JUDGING what is "sensitive";
# the operator declares the rules, the redactors apply them.
#
# A convention is recognized as REDACTION-INTENT if EITHER:
#   - its category OR id CONTAINS a redaction keyword (substring match, deliberately
#     narrow — only these keywords; not every mention of "confidential" elsewhere), or
#   - its rule text has redaction phrasing (an explicit redact verb OR prohibition
#     phrasing that implies redaction), or its action is already 'redact'.
# So `## CONV-CONFIDENTIALITY` (category slug "conv-confidentiality", contains
# "confiden") and a rule worded "must not contain …" both qualify.
_REDACTION_KEYWORDS = ("confiden", "redact", "privacy", "pii")

# Prohibition phrasing that implies redaction without an explicit redact verb.
_PROHIBITION_RE = re.compile(
    r"\b(?:must|shall|may)\s+not\s+(?:contain|include|appear|carry|state|name|be\s+"
    r"(?:published|disclosed|printed|included|shown|present))"
    r"|\bnot\s+be\s+(?:published|disclosed|printed|included|shown)\b",
    re.IGNORECASE)

# Built-in redaction categories. These are NOT an automatic floor (that would be
# the engine asserting sensitivity on its own — forbidden by operator-sovereignty,
# the 3a phantom). They remain ONLY as a named ruleset an operator can CONSCIOUSLY
# opt into (see `redaction_rules(..., opt_in_default_ruleset=True)`); nothing
# applies them automatically. With no operator rule in force, redaction hard-stops
# (the caller refuses the run or the operator declares redact-nothing) — it never
# silently substitutes these.
DEFAULT_REDACTION_RULES = [
    {"id": "RED-DFLT-001", "category": "confidentiality", "action": "redact", "severity": "required",
     "rule": "National identity / passport / tax / similar government ID numbers."},
    {"id": "RED-DFLT-002", "category": "confidentiality", "action": "redact", "severity": "required",
     "rule": "Named natural persons (private individuals) attached to identifying data."},
    {"id": "RED-DFLT-003", "category": "confidentiality", "action": "redact", "severity": "required",
     "rule": "Confidential turnover / revenue / financial figures not in the public record."},
    {"id": "RED-DFLT-004", "category": "confidentiality", "action": "redact", "severity": "required",
     "rule": "Business secrets / proprietary commercial terms marked confidential."},
]


def _is_redaction_category(category, conv_id) -> bool:
    """True if the category OR id contains a redaction keyword (substring match)."""
    blob = f"{str(category)} {str(conv_id)}".lower()
    return any(k in blob for k in _REDACTION_KEYWORDS)


def _has_redaction_phrasing(text) -> bool:
    """True if the rule text expresses redaction INTENT: an explicit redact verb
    (the redact-verb regex) OR prohibition phrasing ('must not contain', 'shall not
    include', 'may not appear', …)."""
    t = text or ""
    return bool(_REDACT_VERB_RE.search(t)) or bool(_PROHIBITION_RE.search(t))


def redaction_rules(registry, *, opt_in_default_ruleset=False) -> dict:
    """Compile OPERATOR REDACTION RULES from the convention registry and REPORT
    whether the operator's rules are in force or only the defaults apply.

    A convention is REDACTION-INTENT when it is in a redaction category (keyword in
    category/id) OR its rule text has redaction phrasing OR its action is 'redact'.
    A redaction-intent convention with non-empty rule text COMPILES to an operator
    rule (action=redact; its text carries the targets, e.g. company turnover, named
    individual + ID number). A redaction-intent convention that does NOT compile
    (no usable rule text) is NEVER silently dropped: it raises a WARNING naming the
    id and reason, surfaced by the caller (console + bus).

    `registry` is a plain DATA dict (the parsed convention registry); this function
    reads its fields and imports nothing from convention_parser.

    Returns a report dict:
      rules:             the rules the redactors APPLY = the compiled OPERATOR rules
                         (NO automatic default floor — operator-sovereignty). Empty
                         when no operator rule is in force; the caller then hard-stops.
      operator_rules:    the compiled operator rules (may be [])
      operator_in_force: bool — True iff at least one operator rule compiled
      source:            "operator" (rules in force) | "none" (caller must hard-stop)
      warnings:          [{id, category, reason}] for redaction-intent that failed
                         to compile (loud, never silent)
    1c (operator-sovereignty): there is NO silent fallback to engine-defined default
    categories. The built-in DEFAULT_REDACTION_RULES are applied ONLY when the
    operator CONSCIOUSLY opts in (opt_in_default_ruleset=True); otherwise they never
    appear in `rules`. When no operator rule is in force, redaction does not quietly
    apply defaults — the caller refuses the run unless the operator declares
    redact-nothing for the run (logged to the governance ledger)."""
    convs = (registry.get("conventions") if isinstance(registry, dict) else None) or []
    operator, warnings = [], []
    for c in convs:
        cid = str(c.get("id", ""))
        cat = str(c.get("category", "")).strip().lower()
        act = str(c.get("action", "")).strip().lower()
        rule_text = str(c.get("rule", "")).strip()
        is_cat = _is_redaction_category(cat, cid)
        is_phrase = _has_redaction_phrasing(rule_text)
        if not (is_cat or is_phrase or act == "redact"):
            continue  # not redaction-intent — leave it as an ordinary convention
        if not rule_text:
            warnings.append({"id": cid, "category": cat,
                             "reason": "redaction-intent convention has no rule text to compile"})
            continue
        operator.append({"id": cid, "category": cat or "confidentiality",
                         "rule": rule_text, "severity": c.get("severity", "required"),
                         "action": "redact",
                         "matched_by": ("category" if is_cat else "action" if act == "redact" else "phrasing")})
    operator_in_force = bool(operator)
    # 1c: NO automatic default floor. Defaults are included ONLY on conscious opt-in.
    rules = list(operator)
    if opt_in_default_ruleset:
        rules += list(DEFAULT_REDACTION_RULES)
    if operator_in_force:
        source = "operator+optin_defaults" if opt_in_default_ruleset else "operator"
    else:
        source = "optin_defaults" if opt_in_default_ruleset else "none"
    return {
        "rules": rules,
        "operator_rules": operator,
        "operator_in_force": operator_in_force,
        "source": source,
        "defaults_available": True,   # named ruleset exists for conscious opt-in (never auto)
        "warnings": warnings,
    }
