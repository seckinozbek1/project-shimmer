# INFRA-042 DELTA, ratified

**Status:** RATIFIED by the operator on 2026-06-24 (`operator_approved: true`). The object below
is appended to `config/constitution.json` `amendments[]` through the normal append-only DELTA path
(the INFRA-029 amendment tripwire permits adding a new id; it does not modify or delete any seed
law or existing amendment). This document remains the human-readable record; the canonical record
is the constitution entry. The build (OPT-2 PART 2.2) happens only after ratification (now granted).

## Verification (re-checked against the repo, not recall)

- **Next free id:** `INFRA-042`. The roster ends at INFRA-041 (tail INFRA-039, INFRA-040,
  INFRA-041), the ids are contiguous with no gap, INFRA-042 is not in the roster, and a repo-wide
  grep finds INFRA-042 nowhere outside the job spec. Append-only, no-gap, never-reused satisfied.
- **`genesis_part: "XVIII"` verified against genesis.md:** the relaxed CONV+REF citation rule lives
  in Part XVIII. The rule text is at genesis.md line 1434 ("An amendment without at least one
  CONV-* and one REF-* is a contract violation") and its checklist form is item 35 at line 1554.
  Part XVIII begins at line 1090 and Part XIX at line 1608, so both 1434 and 1554 fall inside Part
  XVIII. The validator and genesis name it "Part XVIII Section D"; the analogous prior carve-out
  (absence findings, document-level location) is anchored to the same Section D (genesis.md line
  1686).
- **Both governed surfaces covered:** `empty_convention_carveout` relaxes the Part XVIII Section D
  / checklist-35 CONV-required rule for the empty-registry state only (analogous to the Part XXIII
  document-level carve-out); `web_ref_backed` promotes WEB-REF from Part XX prose (genesis.md line
  1630) to a real structured WEB-REF-NNNN form accepted by the citation validators.

## Governance posture

Proposal-side, operator-ratified, does not self-apply (no agent has a write path to
`config/constitution.json`), under the meta-law tripwire (`scripts/constitution_guard.py`).

## The DELTA object (appended to `amendments[]` on ratification)

```json
{
  "id": "INFRA-042",
  "created": "2026-06-24",
  "kind": "empty_convention_citation_regime_and_web_ref",
  "title": "Empty-convention citation regime + WEB-REF as a backed citation form",
  "genesis_part": "XVIII",
  "operator_approved": true,
  "change": {
    "empty_convention_carveout": "Carve-out to the Part XVIII Section D / checklist-35 rule (genesis.md line 1434, 'An amendment without at least one CONV-* and one REF-* is a contract violation', and checklist item 35 at line 1554), directly analogous to the Part XXIII document-level location carve-out. WHEN the convention registry is empty (the existing convention_review_enabled=False signal, i.e. the conventions list is empty or absent), an amendment grounded by at least one REF-* OR at least one WEB-REF-* is VALID and is NOT flagged with a spurious missing-CONV error, and convention_ref is not required. This is the ONLY state in which the CONV-* requirement is relaxed. When conventions exist the rule holds UNCHANGED (at least one CONV-* AND at least one REF-*, convention_ref required). Rationale: with zero conventions in existence a CONV-* citation is unsatisfiable, so the finding grounds in retrieved context (REF-*) or a discovered web reference (WEB-REF-*) instead.",
    "web_ref_backed": "WEB-REF, today only Part XX prose (genesis.md line 1630: discovered references are cited with full URL, title, issuing body, year, and marked as [WEB-REF] to distinguish them from corpus references [REF-*]), becomes a REAL structured citation form: a monotonic WEB-REF-NNNN id minted and persisted by the per-run reference index (parallel to REF-NNNN, in a web_references list), carrying url, title, issuing_body, year, and citable in the ref_ids array exactly as a REF-*. The citation validators accept WEB-REF-* as a grounding form. WEB-REF ids are minted from the STRUCTURED web-source fields only: FACT_CHECKER source_url, PRACTICE_AUDITOR reference_url, and PRACTICE_AUDITOR reference_source. Those raw fields remain a transitional fallback.",
    "scope_boundary": "WEB-REF covers every web reference carried in a STRUCTURED field (source_url, reference_url, reference_source), which is the complete set in the empty-registry regime this DELTA addresses. INLINE free-text URLs and inline [WEB-REF] markings (in evidence, recommendation, reasoning, comment) are OUT OF SCOPE: Part XX inline web discovery is convention-activated and does not fire in the empty-registry state, so inline extraction is deferred to a separate later build if convention-driven web discovery is live and real use shows inline URLs slipping through. No universality is claimed.",
    "regex_disambiguation": "The corpus-REF detector is tightened to (?<!WEB-)\\bREF-\\d{4,}\\b so a WEB-REF-NNNN id is never accidentally matched as a REF; a WEB-REF detector \\bWEB-REF-\\d{4,}\\b is added. Applied consistently in the amendment validator and the OPT-1 verifiability gate.",
    "opt1_consistency": "The OPT-1 verifiability gate is_grounded recognizes a WEB-REF-* id as grounding (with the raw source_url / reference_url / reference_source clause kept as fallback), so OPT-1 and this carve-out agree on what grounded means.",
    "scope": "Pipeline behavior plus this governed carve-out. No seed law is touched. The relaxation is state-gated (empty registry only) and never blanket. Inline web-reference extraction is explicitly deferred. principle_id and other deferred items are untouched."
  },
  "reason": "Empty-registry runs currently ship amendments carrying a spurious missing-CONV validator error, because the CONV-* requirement is unconditional while zero conventions exist to cite (the cold-battery state). This DELTA relaxes the CONV requirement ONLY in the empty state, grounding amendments in retrieved context (REF-*) or discovered web references (WEB-REF-*), and promotes WEB-REF from Part XX prose to a backed, citable form minted from the three structured web-source fields. Inline free-text URL extraction is deferred as a separate convention-activated concern that does not arise in the empty-registry regime. It is a governed carve-out analogous to the Part XXIII document-level carve-out, so it is ratified before it is built.",
  "note": "Append-only DELTA (allowed by the INFRA-029 amendment tripwire; no seed law or existing amendment modified or deleted). Relaxes a governed genesis rule (Part XVIII Section D + checklist 35 + check_35) for the empty-registry state ONLY; unchanged when conventions exist. Backs Part XX WEB-REF prose with real structure, minted from FACT_CHECKER source_url + PRACTICE_AUDITOR reference_url + PRACTICE_AUDITOR reference_source (structured fields only; inline free-text out of scope, no universality claimed). Proposal-side, operator-ratified, does not self-apply, under the meta-law tripwire. The build (PART 2.2) implements the reference-builder WEB-REF minting/persistence, the three-field mint pass, the registry-empty-aware validator, the OPT-1 is_grounded reconciliation, the contract-field declaration, and the regex disambiguation, with executed-coverage gate checks; built only after this DELTA is ratified."
}
```

*End of draft. Nothing built, nothing appended to config/. The operator ratifies this object before OPT-2 PART 2.2 build.*
