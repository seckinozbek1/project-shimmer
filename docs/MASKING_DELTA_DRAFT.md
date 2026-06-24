# MASKING-PROTOCOL DELTA -- RATIFIED (operator-approved 2026-06-24)

**Status:** RATIFIED. The operator approved INFRA-041 on 2026-06-24. The amendment object
below is appended to `config/constitution.json` `amendments[]` (the canonical record),
through the normal append-only DELTA path (the INFRA-029 amendment tripwire permits adding
a new id; it does not modify or delete any seed law or existing amendment). This document
remains the human-readable ratification spec; the canonical record is the constitution entry.

**Chosen INFRA id:** `INFRA-041`
- Roster check: ids run unbroken INFRA-017 .. INFRA-040 across `config/constitution.json`
  and `genesis.md`; the highest in force is INFRA-040.
- No-gap rule (genesis Part XXVII / lines 1921-1925): amendment ids are append-only, never
  reused, never inserted between existing ids, never renumbered. The next free id is the
  successor of the highest, so `INFRA-041`. Confirmed unused anywhere in the repo.

**Governance posture (stated explicitly, per the job spec):**
- This DELTA is **proposal-side**: it is drafted here for the operator, not enacted by the
  swarm.
- It is **operator-ratified**: nothing in PART 1..5 is built until the operator ratifies
  this object (and may edit it first).
- It **does NOT self-apply**: no agent has a write path to `config/constitution.json`; the
  swarm cannot enact its own amendment.
- It sits **under the meta-law tripwire**: `scripts/constitution_guard.py` intercepts any
  attempt to modify or delete an existing `amendments[]` entry or seed law from any code
  path. Appending this new id is the allowed DELTA path; altering a prior entry would STOP
  and require explicit operator approval.

---

## Proposed amendment object (spec form)

```jsonc
{
  "id": "INFRA-041",
  "created": "2026-06-24",
  "kind": "law_iv_masking_protocol",
  "title": "LAW-IV outbound masking protocol (full sensitivity layer activation + payload-free cross-run stores)",
  "genesis_part": "XVIII",
  "operator_approved": true,             // RATIFIED by the operator on 2026-06-24
  "change": {

    "law": "Activates the full LAW-IV sensitivity layer (Mechanism 2, today dormant at LAYER_ACTIVE=False) as a real outbound MASKING PROTOCOL. The protocol is an x/y split applied to every item that would cross an external boundary (any API call or web request): x = non-sensitive items, passed through unchanged; y = sensitive items, HELD LOCAL and replaced in the outbound payload by a typed placeholder [REDACTED:TYPE] that carries only the field TYPE, never the content. Sensitivity is OPERATOR-DEFINED, never model-judged: the y set is exactly the spans the operator's compiled conventions mark (the existing scripts/sensitivity_layer/rules.py convention-compile path; no new sensitivity judge is invented, mirroring INFRA-038). Each item carries a per-item EXPOSURE TAG recording whether it was passed (x) or masked (y) and the placeholder TYPE. After the external call returns, the held-local y content is rejoined to the response by the INFRA-037 canonical envelope keys (item_id + revision), deduped on those keys (highest revision wins, the existing rejoin discipline). Every masking decision is written to a per-item EXPOSURE LEDGER under durable/governance (append-only, survives reset, never deleted): this ledger IS the LAW-IV audit trail proving no sensitive span left the machine. LAW-IV is CITED, not modified: 'no sensitive content may traverse a network, enter an API call, or leave the operator's machine.'",

    "chokepoints": "The protocol engages at the FOUR egress chokepoints found in the audit, sensitive mode only, network paths only: (1) the per-agent API call -- agent_wrapper.run_task/dispatch, UPSTREAM of build_prompt, for the claude_api and openai_api backends ONLY (qwen_local is local hardware and is EXEMPT: sensitive content is permitted to reach the local model, which is the whole point of may_handle_sensitive routing); (2) search_router.search (the web query path); (3) the claim/verification path (claim_classifier claim assembly + the VERIFIER/FACT_CHECKER source_text / source_excerpt / processor_draft payloads); (4) document_dating.date_from_web, the BOOT-time web egress that today can send an operator document title to the web. At chokepoint 4 the safe action is to SUPPRESS the web call under sensitive mode rather than mask it (a masked title is meaningless for a date search, so withhold the call and fall back to the local filename/metadata/text cascade). may_handle_sensitive becomes the LIVE routing consumer at these chokepoints (today a zero-caller flag): an agent reaches a network boundary with raw content only if may_handle_sensitive is true for it; otherwise its outbound items pass through mask_for_external.",

    "boot_stores_option_b": "The BOOT learning/reference stores are made payload-free BY CONSTRUCTION (Option B: re-architect WHAT is stored, not mask-after), because the audit confirmed adaptive_spawn and document_dating both ingest the operator's input/context/ case documents (the same corpus from which the under-review operational/ set is drawn), so these stores are operator-content-derived in every mode. Changes: (a) citation_convention.json stores the matched pattern id + sample count and DROPS the verbatim substring examples (the examples are the only operator-span leak; the pattern + count remain useful); (b) situational_awareness.md and linguistic_identity.md store institution CATEGORIES (by the existing institution-marker classes) not verbatim names, and DROP the verbatim quoted representative sentences; (c) document_dates.json stores filename + date (+ date_source/date_confidence) only and DROPS title-from-content and abs_path. speech_acts_taxonomy.json is unchanged (its examples are generic verb forms, not operator spans). The abstracted stores must stay USEFUL and must NOT hold a verbatim operator span in ANY mode (this is by-construction, not mode-gated); downstream readers (ontology_graph build_graph ingest, situational consumers) must still build against the abstracted form.",

    "cross_run_gaps": "Two cross-run store gaps from the audit are closed, reusing the PART-1 mask path (no second masker is forked): (a) ontology_graph.build_graph gains a sensitive parameter and masks Convention.rule (Q5) and CitationForm.examples (Q6) under sensitive mode, real content under non-sensitive (today build_graph has no sensitive mode and writes both raw); (b) ontology_capture delta_proposals gating is extended from evidence-only to ALSO mask trigger and proposed_change under sensitive mode (today only evidence is gated, so a source span quoted in trigger/proposed_change would persist raw across runs). B1 provisions and B3 gnn_state are already payload-free and are unchanged.",

    "closure_condition": "Every scaffold part that was BUILT-BUT-DORMANT must end this DELTA with a LIVE DUTY, gate-proven, with NO dormant-but-claimed-built scaffold remaining: mask_for_external gets a real implementation AND live callers at the four chokepoints (was a zero-caller pass-through stub); may_handle_sensitive becomes the live routing consumer at the chokepoints (was a zero-caller flag); LAYER_ACTIVE / is_active gate the protocol on; the exposure ledger has a real writer. The standing closure check applies after every part: account for every new or touched function, flag, field, branch, and store against a live caller or an executed gate path, and flag anything with zero duty.",

    "gates": "Each part lands its own executed-coverage checks (the WIRE-AT-THE-END discipline; non-mutating, tempdir, CPU-deterministic where model-free): P1 -- mask_for_external produces typed placeholders for y, passes x, writes the per-item ledger, rejoins/dedupes by item_id/revision, and is idempotent on already-masked input. P2 -- each of the four chokepoints masks or withholds under sensitive mode and passes raw under non-sensitive; the qwen_local path is proven EXEMPT; chokepoint 4 is proven NOT to send a raw title under sensitive mode. P3 -- the BOOT stores contain no verbatim operator span post-BOOT on a synthetic corpus, and downstream ingest still builds. P4 -- graph.json masks rule + examples under sensitive mode (real under non-sensitive); delta_proposals masks all three of evidence/trigger/proposed_change under sensitive mode. P5 (paid, operator-go-only) -- one real activated sensitive run proving end-to-end masking at all four chokepoints, the per-step hard gate, the per-item ledger, all stores payload-free, and no raw operator span reaching any API, web, or cross-run store.",

    "build_sequence": "Built in five sequenced parts, each committed standalone with the gate green and non-mutating: P1 masking engine; P2 wire the four chokepoints; P3 Option-B BOOT stores; P4 close the two cross-run gaps; P5 deploy-then-test (the only paid step, run only on explicit operator go). The full philosophy of the sensitivity layer (sensitivity as a first-class concept, may_handle_sensitive routing) moves from BUILT-BUT-UNWIRED to BUILT-AND-WIRED by this DELTA; the inactive-layer hard gate (require the --sensitivity-layer-inactive-override waiver) remains the refuse-to-start posture until the layer is proven active in P5."
  },

  "reason": "The audit found the full LAW-IV sensitivity layer is a scaffold, not an implementation: mask_for_external is a zero-caller pass-through stub, may_handle_sensitive is a zero-caller flag, all four egress chokepoints send raw operator content, the BOOT learning stores are operator-content-derived (citation examples, quoted sentences, document titles, abs_path), and two cross-run stores (graph.json convention.rule + citation examples, delta_proposals trigger + proposed_change) persist raw spans. This DELTA closes that leak surface as a real outbound masking protocol grounded in operator conventions (never a model sensitivity judge), gives both dormant scaffold parts a live gate-proven duty, makes the BOOT stores payload-free by construction, and proves the whole thing end-to-end on one activated sensitive run. It is ratified before it is built so the masking law is implemented, not re-litigated.",

  "note": "Append-only DELTA (allowed by the INFRA-029 amendment tripwire: adding a new id is not a violation; no seed law or existing amendment is modified or deleted). LAW-IV (seed law) is cited and ENACTED, not modified. Proposal-side, operator-ratified, does not self-apply, under the meta-law tripwire (stated above). Sensitivity source is operator conventions via scripts/sensitivity_layer/rules.py (INFRA-038 lineage); no new sensitivity judge. qwen_local is exempt from masking (local hardware is the sanctioned sensitive handler). Option B (payload-free by construction) is preferred over mask-after for the BOOT stores because they are operator-content-derived in every mode. The exposure ledger is the LAW-IV audit trail. principle_id and the meta-precedent store remain deferred to their separate DELTA and are not introduced here. P5 is the only paid step and runs only on explicit operator go."
}
```

---

## Coverage map (job spec PART 0 checklist)

| Required element | Where in the object |
|---|---|
| Masking law: x/y split | `change.law` |
| Typed placeholder outbound `[REDACTED:TYPE]` | `change.law` |
| y held local | `change.law` |
| Per-item exposure tag | `change.law` |
| INFRA-037 item_id/revision rejoin + dedupe | `change.law` |
| Per-item exposure ledger = LAW-IV audit trail | `change.law`, `change.closure_condition` |
| The 4 egress chokepoints | `change.chokepoints` |
| Option-B payload-free BOOT stores | `change.boot_stores_option_b` |
| The 2 cross-run gaps | `change.cross_run_gaps` |
| Closure condition (every scaffold part gets a live duty) | `change.closure_condition` |
| Proposal-side / operator-ratified / no self-apply / meta-law tripwire | Governance posture section + `note` |

---

*End of draft. Nothing built or wired. The operator ratifies (and may edit) this object before PART 1.*
