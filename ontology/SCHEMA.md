# OGE Schema — DRAFT for operator ratification

**Status:** DRAFT. Not built, not wired. No script reads from or writes to `ontology/`
(confirmed at HEAD f5cb4a3). This document is a *specification* of a two-tier graph
schema for the future Ontology Graph Engine (cross-run knowledge graph + GNN), grounded
field-by-field in the durable stores that exist **today**. Every Tier-1 node/edge/field
traces to a real store and a real field name (re-verified on disk, not from memory). Tier-2
items are explicitly marked as having **no backing store yet**.

**Design invariant (carried from the privacy audit):** the graph must be
*payload-free-under-sensitive-mode*. Every field that carries raw document content is flagged
**RAW** below; under an active masking layer those fields must hold masked/typed placeholders,
never raw source text. Fields flagged **SAFE** are structural/abstract (ids, counts, dates,
regex patterns, categories) and need no masking.

---

## STEP 1 — Re-verified stores (actual paths + real field names)

| Store | Actual path | Top-level keys | Record fields |
|---|---|---|---|
| Document dates | `durable/learnings/document_dates.json` | `schema_version, generated_at, documents[]` | `documents[]`: `filename, date, date_source, date_confidence, title, abs_path` |
| Amendments master | `output/runs/<run_id>/deliverables/<doc>__amendments.json` **(per-run, transient)** | `document_id, amendments[], _validator_errors` | `amendments[]`: `location, convention_ref, context_refs[], finding_type, original_text, proposed_text, action, comment, severity` |
| Convention registry | `config/convention_registry.json` | `schema_version, generated_at, source_files, conventions[]` | `conventions[]`: `id, category, rule, source_file, source_location, severity, action` |
| Citation conventions | `durable/learnings/citation_convention.json` *(NOT config/)* | `schema_version, generated_at, source, rules[]` | `rules[]`: `name, pattern, sample_count, examples[]` |
| Speech-act taxonomy | `durable/learnings/speech_acts_taxonomy.json` *(NOT config/)* | `schema_version, generated_at, source, speech_acts[]` | `speech_acts[]`: `name, pattern, evidence_count, examples[]` |
| DELTA proposals | `output/runs/<run_id>/audit/delta_proposals.json` **(per-run, transient)** | `generated_at, proposals[]` | `proposals[]`: `id, kind, trigger, evidence, proposed_change, requires_operator_approval, created_at` (sampled run had **0 proposals**) |

**Path corrections vs the task brief:** `citation_convention.json` and `speech_acts_taxonomy.json`
live under `durable/learnings/`, not `config/`. The amendments master and `delta_proposals.json`
are **per-run artifacts under `output/runs/<run_id>/`**, not durable stores — see Open Question Q1.

---

## A. TIER 1 NODES (groundable now)

### A1. Document / Case
- **Source store:** `durable/learnings/document_dates.json` → `.documents[]` (durable, cross-run).
  Per-run case identity also appears as `document_id` in the amendments master.
- **Node id:** `filename` (stable across runs; `abs_path` is machine-specific — do NOT use as id).
- **Fields:**

  | Schema field | ← source field | RAW/SAFE |
  |---|---|---|
  | `doc_id` | `documents[].filename` | **RAW** (filename may encode a sensitive title/subject) |
  | `date` | `documents[].date` | SAFE |
  | `date_source` | `documents[].date_source` | SAFE |
  | `date_confidence` | `documents[].date_confidence` | SAFE |
  | `title` | `documents[].title` (often `null`) | **RAW** |
  | `abs_path` | `documents[].abs_path` | **RAW** (operator-machine filesystem path) — recommend excluding from the KG entirely; see Q7 |

### A2. Provision / REF
- **Source store:** amendments master `.amendments[]` (per-run, `output/runs/.../deliverables/<doc>__amendments.json`). Provisions are the `location` of each amendment, plus the REF ids appearing in `context_refs[]`.
- **Node id:** **composite `(document_id, ref_id)`** — REF ids (`location`) are per-document and collide across documents (Q2).
- **Fields:**

  | Schema field | ← source field | RAW/SAFE |
  |---|---|---|
  | `ref_id` | `amendments[].location` (e.g. `REF-0024`) | SAFE (structural id) |
  | `document_id` | master `.document_id` | SAFE |
  | `original_text` | `amendments[].original_text` | **RAW** (verbatim source provision) |
  | `proposed_text` | `amendments[].proposed_text` (often `null`) | **RAW** |
  | `comment` | `amendments[].comment` | **RAW** (analyst prose; quotes source) |
  | `finding_type` | `amendments[].finding_type` | SAFE |
  | `action` | `amendments[].action` | SAFE |
  | `severity` | `amendments[].severity` | SAFE |

### A3. Convention (CONV-*)
- **Source store:** `config/convention_registry.json` → `.conventions[]`.
- **Node id:** `id` (`CONV-001`…) — unique within a domain registry.
- **Fields:**

  | Schema field | ← source field | RAW/SAFE |
  |---|---|---|
  | `conv_id` | `conventions[].id` | SAFE |
  | `category` | `conventions[].category` | SAFE |
  | `rule` | `conventions[].rule` | SAFE for doc-sensitivity (operator-authored, not source content) — but operator IP; see Q5 |
  | `source_file` | `conventions[].source_file` | SAFE (operator-supplied convention filename) |
  | `source_location` | `conventions[].source_location` | SAFE |
  | `severity` | `conventions[].severity` | SAFE |
  | `action` | `conventions[].action` | SAFE |

### A4. CitationForm
- **Source store:** `durable/learnings/citation_convention.json` → `.rules[]`.
- **Node id:** `name` (the form label, e.g. "UN resolution symbol").
- **Fields:**

  | Schema field | ← source field | RAW/SAFE |
  |---|---|---|
  | `form_name` | `rules[].name` | SAFE |
  | `pattern` | `rules[].pattern` (regex) | SAFE |
  | `sample_count` | `rules[].sample_count` | SAFE |
  | `examples` | `rules[].examples[]` | **RAW (mild)** — corpus-derived citation tokens (e.g. `A/RES/70/1`); low sensitivity but from source; see Q6 |

### A5. SpeechAct
- **Source store:** `durable/learnings/speech_acts_taxonomy.json` → `.speech_acts[]`.
- **Node id:** `name` (the act, e.g. "decide").
- **Fields:**

  | Schema field | ← source field | RAW/SAFE |
  |---|---|---|
  | `act_name` | `speech_acts[].name` | SAFE |
  | `pattern` | `speech_acts[].pattern` (regex) | SAFE |
  | `evidence_count` | `speech_acts[].evidence_count` | SAFE |
  | `examples` | `speech_acts[].examples[]` | SAFE — generic verb forms ("decide/decides/decided"), not content (Q6 may revisit) |

---

## B. TIER 1 EDGES

Only edges with a **real stored linking field** are Tier 1. Edges that would require
computing a match (regex over text) are demoted to Tier 2 (B-derived) below.

| Edge | Source → Target | Established by (real field) | Direction / cardinality |
|---|---|---|---|
| **HAS_PROVISION** | Document → Provision | master `.document_id` ↔ `amendments[].location` | Document → Provision, 1 : N |
| **GOVERNED_BY** (flagged-under) | Provision → Convention | `amendments[].convention_ref` (`CONV-*`) ↔ Convention `.id` | Provision → Convention, N : 1 (per amendment; see Q4 on multi-conv) |
| **CROSS_REFERENCES** (context) | Provision → Provision | `amendments[].context_refs[]` (list of `REF-*`) ↔ Provision `ref_id` | Provision → Provision, N : N (may point to non-materialized REFs — Q3) |

**Tier-1 nodes, but EDGES not yet groundable (no stored link — DERIVABLE, see C5/C6):**
- `Provision —CITES→ CitationForm` and `Provision —EXHIBITS→ SpeechAct` have **no stored field**;
  they would be produced by matching `rules[].pattern` / `speech_acts[].pattern` against
  `original_text` at ingest. They are *computable from Tier-1 node data* (not awaiting task flow),
  but they are not present as stored links today → classified Tier 2 (derivable).

---

## C. TIER 2 NODES + EDGES (no backing store yet, or no stored link)

### C1. DeltaProposal (cross-run accumulator)
- **Why Tier 2:** `delta_proposals.json` exists **per-run** (`output/runs/<id>/audit/`), fields
  `id, kind, trigger, evidence, proposed_change, requires_operator_approval, created_at` — but it
  is transient (the sampled run had 0 proposals) and there is **no durable cross-run accumulator**.
- **What will populate it:** a durable append store (e.g. `ontology/` or `durable/`) that the
  synthesizer writes to across runs, adding what the per-run file lacks: **a stable dedup key**
  (so the same recurring proposal merges across runs), an **operator-decision status**
  (proposed / approved / rejected), and **occurrence count + first/last-seen**. The per-run record
  becomes a transient view; the accumulator becomes the node.

### C2. Finding (recurrence store)
- **Why Tier 2:** `AuditFinding{category, severity, summary, evidence}` is computed per-run inside
  the synthesizer and embedded in `summary["findings"]`; it is **never persisted standalone**.
- **What will populate it:** a durable findings store keyed by a recurrence signature (e.g.
  `(category, normalized-summary)`), so "this finding recurred N times across runs" becomes a node
  the GNN can weight. Today the synthesizer's `>=2`/`>=3` thresholds are the cold proto-version.

### C3. VerificationVerdict
- **Why Tier 2:** `durable/cache/verification_cache.json` and `durable/global/verification_cache_global.json`
  exist but are **empty (`entries:{}`) and intentionally disconnected** (re-verify-every-run is the
  defect-intolerant default). Shape (when wired): `dedup_key → {verdict, evidence, source_url, confidence, stored_at}`.
- **What will populate it:** only if the operator wires verification caching (a separate decision).
  **AT-RISK** — `dedup_key` is claim-derived and `evidence` is raw, so this node would carry RAW.

### C4. Precedent-Principle (`principle_id`)
- **Why Tier 2:** **no backing store at all.** The meta-precedent store is a deferred DELTA
  (noted in INFRA-040); today editorial observations carry only free-text `rationale`, no `principle_id`.
- **What will populate it:** operator-ratified, payload-free principles once that store is built. It
  **attaches** to recurring `Finding`→`DeltaProposal` clusters (C1/C2) via a `GENERALIZES` edge —
  i.e. a principle node generalizes the pattern that repeatedly triggered proposals.

### C5. Edge — Provision CITES CitationForm *(derivable)*
- **Why Tier 2:** no stored link; produced by `re.search(rules[].pattern, provision.original_text)` at ingest.
- **Populated by:** an ingest pass matching citation patterns against provision text. Computable now from Tier-1 data; not yet stored.

### C6. Edge — Provision EXHIBITS SpeechAct *(derivable)*
- **Why Tier 2:** no stored link; produced by matching `speech_acts[].pattern` against provision text.
- **Populated by:** the same ingest pass. Computable now; not yet stored.

### C7. Edge — Precedent-Principle GENERALIZES {DeltaProposal, Finding}
- **Why Tier 2:** depends on C1/C2/C4, none of which have durable stores yet.

---

## D. Masking surface summary (payload-free-under-sensitive-mode targets)

Every RAW-flagged field across all Tier-1 nodes (+ the one AT-RISK Tier-2 node). Under an active
masking layer these must hold masked/typed placeholders, never raw source text.

| Node | Field | Why RAW | Tier |
|---|---|---|---|
| Document | `doc_id` (filename) | filename may encode sensitive subject | 1 |
| Document | `title` | document title | 1 |
| Document | `abs_path` | operator-machine path | 1 (recommend exclude — Q7) |
| Provision | `original_text` | verbatim source provision | 1 |
| Provision | `proposed_text` | rewritten source text | 1 |
| Provision | `comment` | analyst prose quoting source | 1 |
| CitationForm | `examples` | corpus-derived citation tokens (mild) | 1 |
| VerificationVerdict | `dedup_key`, `evidence` | claim-derived key + raw evidence | 2 (note now) |

SAFE everywhere (no masking): all ids (`ref_id`, `conv_id`, `form_name`, `act_name`), `date*`,
`finding_type`, `action`, `severity`, `category`, all `pattern` regexes, all `*_count` fields,
`convention.rule`/`source_file`/`source_location` (operator-authored — pending Q5).

---

## E. Open questions for operator

- **Q1 — Provision/DeltaProposal provenance is per-run, not durable.** Provisions (amendments master)
  and DELTA proposals live under `output/runs/<run_id>/`, which is transient. Does the KG ingest
  directly from run outputs (transient, must be captured at run end), or only from a snapshot
  (`--save-snapshot` does **not** include `output/runs/`)? Without a decision, Provision and
  DeltaProposal nodes have no durable source.
- **Q2 — REF id collision.** `location` (`REF-0024`) is per-document; the same id recurs across
  documents. Confirm Provision node id is the composite `(document_id, ref_id)`.
- **Q3 — Dangling context refs.** `context_refs[]` point at REF ids that may not be the `location`
  of any amendment (they index into the source doc's REF map, which is not a stored node set).
  Materialize referenced-only REFs as stub Provision nodes, or drop edges to non-materialized REFs?
- **Q4 — Convention cardinality.** In the sample `convention_ref` is a single `CONV-*`. Confirm a
  provision is never flagged under multiple conventions in one amendment (if it can be a list,
  GOVERNED_BY becomes N:N).
- **Q5 — Is operator IP in scope for masking?** `convention.rule` is operator-authored (not source
  content). LAW-IV covers source/PII; does the operator also want convention rule text masked under
  sensitive mode, or only document-derived content?
- **Q6 — CitationForm/SpeechAct `examples`.** Citation examples are corpus tokens (mild RAW); speech-act
  examples are generic verb forms (SAFE). Confirm the masking line: mask citation examples, leave
  speech-act examples?
- **Q7 — `abs_path`.** Machine-specific and RAW. Recommend excluding from the KG entirely (store
  `filename` only). Confirm.
- **Q8 — Date as node vs attribute.** Date is modeled as a Document attribute here. If cross-document
  temporal reasoning is wanted (e.g. "provisions enacted before X"), promote Date to a Tier-2 node
  with `DATED_ON` edges.
- **Q9 — Where does the cross-run accumulator live?** C1/C2/C3 durable stores: under `ontology/`
  (new) or `durable/` (existing reset/snapshot machinery already covers `durable/learnings`)? This
  affects whether they are snapshot-portable.

---

*End of draft. Nothing built or wired. Operator ratifies the schema before any ingest is implemented.*

---

## RATIFIED DECISIONS (operator, post-draft)

These rulings settle Q1–Q9 from the draft above. The draft body is unchanged; these decisions
govern the build.

- **Q1 — RATIFIED.** The KG does NOT read transient `output/runs/` live. v1 adds a durable
  **CAPTURE-AT-RUN-END hook** that appends each run's provisions (from the amendments master) and
  DELTA proposals into a durable store **under `ontology/`**. This is the cross-run accumulator
  (C1) generalized to provisions, and the capture hook is **IN SCOPE for v1**. Provision and
  DeltaProposal nodes ingest from this durable `ontology/` store, never from transient run folders.
- **Q2 — RATIFIED.** Provision node id is the composite **`(document_id, ref_id)`**.
- **Q3 — RATIFIED.** Referenced-only REFs in `context_refs[]` that are not the `location` of any
  amendment are materialized as **STUB Provision nodes** (id only, no text, flagged incomplete).
  `CROSS_REFERENCES` edges are preserved, never dropped.
- **Q4 — RATIFIED (grep-settled).** Read-only grep of `output/runs/` found **106 occurrences of
  `convention_ref`, all single `CONV-*` strings, zero array forms** (`"convention_ref": [` matched
  nothing). Therefore **GOVERNED_BY stays N:1**. (If a future run ever emits an array form, revisit
  to N:N.)
- **Q5 — RATIFIED.** `convention.rule` is operator IP and **IS masked under sensitive mode**.
  `conv_id` + `category` are stored raw always; `rule` text is masked under sensitive mode.
  `convention.rule` is added to the masking surface as a **sensitive-mode-only RAW** field
  (see the masking-surface addendum below).
- **Q6 — RATIFIED.** Mask `CitationForm.examples` under sensitive mode; leave `SpeechAct.examples`
  unmasked (generic verb forms, SAFE).
- **Q7 — RATIFIED.** `abs_path` is **excluded from the KG entirely**. Store `filename` only.
- **Q8 — RATIFIED.** `date` stays a **Document attribute** for v1. Date-as-node + `DATED_ON` edges
  are deferred (promote only if cross-document temporal reasoning is later wanted).
- **Q9 — RATIFIED.** The cross-run accumulator + capture store live **under `ontology/`, NOT
  `durable/`**. The OGE owns `ontology/`, kept separate from the existing `durable/` reset/snapshot
  machinery.

### Masking-surface addendum (per Q5)

The table D masking surface gains one field:

| Node | Field | Why RAW | Masking |
|---|---|---|---|
| Convention | `rule` | operator-authored IP (Q5) | **sensitive-mode-only RAW** — masked under sensitive mode; `conv_id` + `category` always raw |

## BUILD INVARIANT (carried into the build)

- **Masked-write path from day one, not retrofitted.** Every RAW field in table D — now including
  `convention.rule` (Q5) — is written through a **mask-or-passthrough gate keyed on sensitive
  mode**: non-sensitive mode writes real content; sensitive mode writes a typed placeholder
  (`[REDACTED:TYPE]`). The gate is part of the write path, not a later add-on.
- **The Q1 capture hook is itself a cross-run-store write** and inherits this masked-write gate —
  capture-at-run-end never persists raw content under sensitive mode.
- **WIRE-AT-THE-END.** The OGE must be proven wired by **executed gate coverage**, never a dormant
  scaffold — i.e. the capture hook, the ingest, and the masked-write gate each carry a verify-gate
  check that executes the live path (the lesson from the D7 vacuous-gate / dormant-layer findings).

