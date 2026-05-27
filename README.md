![Project Shimmer](project_shimmer_cover.png)

# Project Shimmer

A constitutional multi-agent system for reviewing regulated documents.
Fourteen specialized LLM agents governed by a 27-Part constitutional
specification founded on seven seed laws, an append-only message bus,
cross-family verification, precision REF-* references, and
tracked-changes amendments cited back to convention rules. The
operator owns every escalation.

Author: Seckin Ozbek.

---

## The name

In *Annihilation* (Garland 2018, after VanderMeer 2014), the Shimmer is
a refracting boundary that recombines what passes through. The metaphor
here is narrow: the constitution defines a boundary between unaudited
model output and citation-backed analytical product. Inside the
boundary, claims must trace to a corpus passage; outside it, they are
rejected by a Verifier or escalated to the operator. The rest of this
README is the system.

---

## Architectural motivation: two neurons on a bicycle

Cook (2004), *It Takes Two Neurons to Ride a Bicycle*
([fermatslibrary.com/s/it-takes-two-neurons-to-ride-a-bicycle](https://fermatslibrary.com/s/it-takes-two-neurons-to-ride-a-bicycle)):
a two-neuron controller (one for steering, one for pedaling)
stabilizes a bicycle on a track that defeats learned policies of much
larger capacity. The bicycle's own dynamics carry most of the work; the
controller imposes a few hard constraints at the right places.
Generalization comes from structure, not parameter count.

Shimmer transposes this bet to document review. For a task with hard
structure — a finite rule set, a citable corpus, a fixed output schema
— mechanisms that match that structure (a written constitution, agent
contracts, validators) impose the right invariants directly. An
unconstrained agent swarm of similar parameter count must discover
those invariants statistically over many failed runs. For domains
where a missing citation is a defect, a statistical guarantee is the
wrong kind of guarantee.

The constitution is the controller — seven seed laws at the
foundation, expanded across 27 Parts that specify agents, governance,
conventions, corpus handling, semantic retrieval, and absence
detection. The agents are the bicycle.

---

## Architecture

### Four governance layers

| Layer | Name              | Source                                                                |
|-------|-------------------|-----------------------------------------------------------------------|
| 1     | Constitution      | 27-Part specification (`genesis.md`), founded on seven seed laws (Part I) |
| 2     | Task-force laws   | operator-ratified amendments                                          |
| 3     | Precedents        | accepted past decisions                                               |
| 4     | Conventions       | rules in `input/conventions/*.md`                                     |

Higher layers dominate. LAW-IV (privacy) outranks LAW-0 (operator
sovereignty) and is the only law that does.

### The foundation layer: seven seed laws (Part I)

Part I of `genesis.md` establishes the seven seed laws — the
minimum-viable governance that ships with every Shimmer project.
Everything below is the table; everything above the seven laws in
the rule hierarchy (task-force laws, precedents, conventions) and
everything beyond them in the constitutional specification (Parts
II–XXVII) is built on this foundation.

| Id      | Title                                |
|---------|--------------------------------------|
| LAW-0   | Operator sovereignty                 |
| LAW-I   | Do no harm to the source             |
| LAW-II  | Know your bounds                     |
| LAW-III | No self-audit                        |
| LAW-IV  | Protect what is private              |
| LAW-V   | Remember before you act              |
| LAW-VI  | Structure is earned, not assumed     |

### Message bus: formal properties

The bus is an append-only JSONL log at `output/bus/messages.jsonl`.
Each entry:

```
m = (id, from, to, type, payload, constitution_check, t, uncertain)
```

Runtime invariants:

- **Append-only.** The bus file is opened only with mode `a`. No
  rewrites, no deletes.
- **Total order.** Per-process write lock; on replay, `id` is the
  linear order.
- **Constitution coverage.** Every message carries a non-empty
  `constitution_check` naming one or more rule ids (LAW-*, TF-*,
  PREC-*, CONV-*) the action is consistent with. A Verifier rejects
  messages without one.
- **Replayability.** Given the bus and the input drop, the run is
  reproducible up to model non-determinism. The bus records the model
  id used for each call.

### Cross-family verification (LAW-III)

Same-family verification can collude on shared biases. LAW-III is the
formal guarantee against it: the auditor must come from a different
model family than the drafter. In the current configuration:

- Drafter: Claude (Sonnet 4, per cost ledger pricing label)
- Auditor: GPT-4o

Backends are pluggable; the law, not the model id, is what is fixed.

---

## The fourteen agents

Defined in `config/agent_registry.json` with DOES / DOES_NOT contracts
and `model` / `backend` assignments. Output schemas live in
`config/agent_contracts.json`.

| Group        | Agent              | DOES (summary)                                     | DOES_NOT (summary)                |
|--------------|--------------------|----------------------------------------------------|-----------------------------------|
| Read/extract | PROCESSOR          | parse documents into sections, assign REF-*        | infer claims, judge quality       |
|              | ARCHIVIST          | chronology, index, **structural inventory** of corpus | review provisions, draft amendments |
|              | CITATION_RESOLVER  | resolve cross-document references                  | verify the cited content          |
|              | INST_FINDER        | extract institutional actors                       | assess their legitimacy           |
|              | SPEECH_ACT_TAGGER  | classify utterances by force                       | judge truth value                 |
| Verify/audit | VERIFIER           | cross-family audit (GPT-4o checks Claude)          | re-draft; only accept or reject   |
|              | FACT_CHECKER       | claim-level verdicts                               | rewrite the claim                 |
|              | PRACTICE_AUDITOR   | procedure compliance, **absence detection**        | judge policy intent               |
|              | LEGAL_ANALYST      | legal grounding, **absence detection**             | offer legal advice                |
|              | STYLE_GUARDIAN     | register and tone                                  | change semantics                  |
| Redact       | REDACT_CLERK       | T1/T2 redaction drafts                             | release T3+ material              |
|              | REDACT_AUTHORITY   | T3/T4 approval, adversarial test                   | bypass adversarial test           |
|              | REDACT_GATE        | T5 final pass/fail                                 | revise; only pass or fail         |
| Amend        | AMENDMENT_DRAFTER  | tracked-changes .docx with ≥1 CONV-* and ≥1 REF-* per amendment | post amendments without citations |

Agents cannot grow new agents. The roster is fixed; expansion requires
an approved DELTA proposal.

---

## Semantic retrieval

### Per-provision queries (Part XXI)

Whole-document retrieval averages over the n provisions an operational
document touches and starves provision-specific corpus passages. The
amended Part XXI requires per-provision queries: for each section
$s_i$ of the operational document, top-k context passages are
retrieved by embedding similarity to $s_i$ alone, and the retrievals
are concatenated into a single agent call with provision-tagged
blocks. One agent call per agent, not n, but each provision sees its
own retrieval window.

### Embedding store

- Model: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, 256-token
  window).
- Chunking: ~400-character windows.
- Store: pickle of `(ref_id, vector, text)` under the active ontology
  directory; ~32 MB for the EU corpus.
- **Staleness check.** The store records the set of source filenames
  it was built from. On load, if those disagree with the current
  contents of `input/context/`, the store rebuilds before use.

### Zipfian fallback (no hardcoded stopwords)

When the embedding layer is unavailable (fresh domain, no
`sentence-transformers` installed), retrieval degrades silently to
term matching. Stopwords are not hardcoded:

1. Compute token frequency across the corpus.
2. Discard the top 20% most-frequent tokens (the Zipfian head). This
   approximates a stopword filter in any natural language.
3. If a document's CJK character ratio exceeds 30%, switch from
   whitespace tokenization to character bigrams.
4. Numerals: support Western 0–9, Eastern Arabic U+0660–U+0669, and
   other Unicode digit categories via `unicodedata`.

The REF-* citation format is identical regardless of which retrieval
method ran.

---

## Structural inventory and absence detection (Parts XXIV / XXVII)

Most review systems criticize only what is present. Compliance work
also cares about what is missing.

### Structural inventory (Part XXVII)

During corpus-level processing, ARCHIVIST produces a
`structural_inventory`: for each governance element (risk
classification, conformity assessment, post-market monitoring,
redress, transparency obligations, human oversight, prohibited
practices, environmental provisions, cross-border data flow
provisions, definitions sections), how many documents contain it and
which. The inventory is not hardcoded; it is derived from the corpus.

### Absence detection (Part XXIV)

PRACTICE_AUDITOR and LEGAL_ANALYST consult the inventory through
their context package. Any element present in more than half the
corpus documents but absent from the operational document is reported
as a document-level finding:

- `location`: the section where the element would logically belong, or
  the sentinel `"document-level"` (the validator accepts both forms)
- `verdict`: `VIOLATION` for PRACTICE_AUDITOR, `THIN` or
  `UNSUPPORTED` for LEGAL_ANALYST
- `ref_ids`: citations to the corpus documents that establish the
  element as standard practice

This activates from the directives in the PRACTICE_AUDITOR and
LEGAL_ANALYST contract entries (`config/agent_contracts.json`).

---

## Convention-driven review

The framework code carries no domain knowledge. Domain knowledge lives
in the operator's data:

- `input/context/` — corpus to cite against (PDFs, Markdown)
- `input/operational/` — document under review
- `input/conventions/*.md` — operator-authored rules

The convention compiler parses Markdown into typed `CONV-*` entries
with fields `identity`, `scope`, `rule_text`, `external_refs`. The
current EU configuration compiles
`input/conventions/ai_ethics_review_standards.md` into 10 `CONV-*`
rules. Convention drift between runs is visible as a diff of one file.

### Check 22: the discipline gate

`scripts/verify_session1.py` enforces this separation with check 22
("no domain-specific terms in framework scripts"). It scans every
`*.py` under `scripts/` (excluding `download_*` and `retry_*` corpus
helpers, exempted by Part XIX rule 6) for a regex of
domain-distinctive terms. Any hit fails the gate. The check is the
mechanical guarantee that a domain swap is a data change, not a code
change.

---

## Comparison to adjacent frameworks

| Property                       | CrewAI  | AutoGen | LangGraph | AgentCity | **Shimmer**  |
|--------------------------------|---------|---------|-----------|-----------|--------------|
| Written constitution           | no      | no      | no        | no        | **yes**      |
| Fixed-role agents w/ contract  | partial | no      | partial   | partial   | **yes**      |
| Mandatory cross-family audit   | no      | no      | no        | no        | **yes**      |
| Per-message rule citation      | no      | no      | no        | no        | **yes**      |
| Append-only auditable bus      | no      | no      | partial   | no        | **yes**      |
| Precision REF-* references     | no      | no      | no        | no        | **yes**      |
| Domain swap via data, not code | partial | no      | partial   | partial   | **yes**      |
| Operator-in-the-loop default   | opt     | opt     | opt       | opt       | **required** |

Shimmer is narrower in scope: it is built for review of regulated
documents, not for open-ended agent orchestration. Inside that scope
the audit guarantees are stronger.

---

## DELTA mechanism (self-modifying ontology)

Agents cannot edit the constitution or add new agents. The only path
to a permanent change is a DELTA proposal:

1. Any participant (agent or operator) drafts a `DELTA-NNN` describing
   the proposed change and the genesis Part it would amend.
2. The operator reviews. On accept, the change is applied and recorded
   in the constitution log.
3. Future runs load the amended constitution. Rules descended from a
   DELTA cite it.

Approved DELTAs include directory hygiene, agent hygiene, variable
hygiene, domain-term purge, adaptive spawning, Shimmer UI, non-sibling
topology, and English module-name rules (INFRA-017–024).

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # PowerShell on Windows
pip install -r requirements.txt
```

**API keys.** Loaded from an external `config.py` outside the
repository. The relative path is in `.env_path`. Keys never appear in
any tracked file. `scripts/guard_secrets.py` runs as a pre-commit hook
(see `.githooks/pre-commit`) and blocks any commit containing a
key-shaped string. Activate the hook after `git init`:

```bash
git config core.hooksPath .githooks
```

**Drop inputs.**

```
input/context/        <- corpus PDFs / Markdown
input/operational/    <- the document under review
input/conventions/    <- operator-authored *.md rules
```

**Run.**

```bash
py -3.9 scripts/pipeline.py
py -3.9 scripts/verify_session1.py
```

Outputs land under `output/`: six deliverables per reviewed document
in `output/deliverables/`, the bus in `output/bus/messages.jsonl`,
logs in `output/logs/`, contract-failure raw text in
`output/audit/contract_violations/`.

---

## Domain switching

```bash
py -3.9 scripts/pipeline.py --save-ontology domain_b
py -3.9 scripts/pipeline.py --reset-ontology

# replace inputs
rm input/context/*.pdf
rm input/conventions/*.md
cp /path/to/new/corpus/*.pdf  input/context/
cp /path/to/new/conventions.md input/conventions/

py -3.9 scripts/pipeline.py
```

No code is edited. The `--reset-ontology` strips back to seed defaults;
the new context corpus and conventions carry the domain. Three saved
snapshots ship in `ontologies/`:

- `domain_a/`
- `domain_a_v2/` (corpus refresh)
- `domain_b/` (includes the embedding pickle)

---

## Cost analysis

Most recent EU AI Act review run, from
`output/logs/cost_tracker.json`:

| Metric                | Value      |
|-----------------------|------------|
| Total cost            | $0.8484    |
| LLM calls             | 11         |
| Failed calls          | 0          |
| Claude calls (8)      | $0.7576    |
| Claude input tokens   | 197,920    |
| Claude output tokens  | 10,922     |
| GPT-4o calls (3)      | $0.0908    |
| GPT-4o input tokens   | 25,996     |
| GPT-4o output tokens  | 2,580      |

Per-agent breakdown:

| Agent              | Calls | Input tokens | Output tokens | Cost USD |
|--------------------|-------|--------------|---------------|----------|
| ARCHIVIST          | 1     | 42,064       | 3,501         | 0.1787   |
| INST_FINDER        | 1     | 41,929       | 1,052         | 0.1416   |
| CITATION_RESOLVER  | 1     | 42,069       | 175           | 0.1288   |
| AMENDMENT_DRAFTER  | 1     | 17,812       | 2,043         | 0.0841   |
| LEGAL_ANALYST      | 1     | 16,142       | 1,312         | 0.0681   |
| SPEECH_ACT_TAGGER  | 1     | 14,391       | 1,271         | 0.0622   |
| PROCESSOR          | 1     | 14,461       | 563           | 0.0518   |
| STYLE_GUARDIAN     | 1     | 9,052        | 1,005         | 0.0422   |
| PRACTICE_AUDITOR   | 1     | 13,676       | 756           | 0.0418   |
| FACT_CHECKER       | 1     | 5,816        | 1,437         | 0.0289   |
| VERIFIER           | 1     | 6,504        | 387           | 0.0201   |

Cost is dominated by the three corpus-level agents (ARCHIVIST,
INST_FINDER, CITATION_RESOLVER) reading the full context digest.
Per-provision-level agents are bounded by chunk-size, not corpus-size,
so they remain cheap as the corpus grows.

---

## Verify gate

`scripts/verify_session1.py` runs 39 invariants over a completed run.
Examples:

- bus parses as JSONL and is append-only
- every bus message has a non-empty `constitution_check`
- every amendment comment contains ≥1 `CONV-*` and ≥1 `REF-*`
- every `REF-*` cited in an amendment exists in the intake index
- ARCHIVIST produced a `structural_inventory` in
  `corpus_level_analysis` mode
- embedding store filename set equals `input/context/` filename set
- cost-tracker totals reconcile with the per-call ledger
- no domain-specific terms in framework scripts (check 22)
- API keys are not hardcoded in any file under `scripts/` or `config/`
  (check 23)

```bash
py -3.9 -X utf8 scripts/verify_session1.py
```

Latest run: **PASS=39, WARN=0, FAIL=0**. A FAIL blocks the deliverable
bundle from being produced. PASS=39 is the stability target; any drop
flags regression before it leaves the local machine.

---

## Evaluation design

The principal claim — that domain knowledge can live entirely in data
without leaking into framework code — is testable as a causal
statement:

> If the deliverable schema is invariant under a domain switch
> (`save_ontology → reset_ontology → swap input/ → run`) with zero
> changes to files under `scripts/`, and verify-gate check 22
> continues to pass, then domain knowledge does not reside in
> framework code.

The test has been run across two domains so far: AI ethics in
Pakistani law and EU AI Act alignment. Both produced the same six-file
deliverable shape (`*__amendments.docx/json/md`,
`*__deliverable.md`, `*__context_summary.md`, `*__operative_summary.md`),
and check 22 passed in each. The contrapositive — a code change that
leaks domain-specific vocabulary — would fail check 22 immediately.
The verify gate is therefore the falsifier, not a passive log.

---

## Metadata hierarchy (Part XXV)

Document attributes (dates, titles, authors, issuing bodies) are
extracted with content-derived signals prioritized over
container-derived signals. The date cascade is implemented in
`scripts/document_dating.py` with four tiers, highest priority first:

1. **filename** — operator-provided signal; a four-digit year
   parseable from the slug regardless of surrounding characters or
   language.
2. **content** — a four-digit numeric sequence in the range
   1990–2030 appearing on the first page. Both Western Arabic
   numerals (0–9) and Eastern Arabic numerals (U+0660–U+0669) are
   recognized.
3. **metadata** — PDF metadata creation date. Used but flagged
   low-confidence (artifacts of export tools).
4. **web** — search-based date lookup as last resort; low confidence.

The chosen tier is recorded as `date_source` alongside the value.
Downstream agents see `(date, source, confidence)` tuples, not bare
strings.

---

## Uncertain findings (Part XXVI)

Every agent finding carries a confidence marker:

- `CONFIDENT` — normal processing
- `UNCERTAIN` — posted to the bus with `uncertain: true`

Uncertain findings trigger an escalation cascade:

1. **Peer review.** Other agents in the same phase can corroborate or
   contradict.
2. **Orchestrator review.** If no peer resolves it, the orchestrator
   decides whether to spawn a task force.
3. **Operator escalation.** In interactive mode, the operator
   decides. In non-interactive mode, the finding is marked `DEFERRED`
   and surfaced in the deliverable prefixed `[UNCERTAIN]`.

Uncertain findings are never silently dropped. An unresolved
uncertainty is more useful to a reviewer than false confidence or
silent omission.

---

## Future research

- **Cumulative embedding overlay.** Across runs, the union of
  per-corpus embedding stores forms a multi-domain index. Co-citation
  patterns (passages cited together across domains) and cross-domain
  bridges (a single passage cited from corpora in different domains)
  become first-class objects, queryable independently of any single
  ontology.
- **Local-model training via PRefLexOR.** Once enough run history
  exists, the redacted bus + accepted amendments form a preference
  dataset suitable for PRefLexOR-style local fine-tuning of a small
  model that takes over a subset of agents (e.g. STYLE_GUARDIAN,
  SPEECH_ACT_TAGGER) at zero cloud cost while preserving the audit
  contract.
- **Confidence-weighted agent routing — Cook's third neuron.** The
  current two-neuron analogue is drafter + auditor. A third neuron
  routes by confidence: when both agents return CONFIDENT, the
  pipeline writes through; on UNCERTAIN, a third-family model arbitrates
  before escalating to the operator. This keeps the operator's time
  for the cases that genuinely need it.

---

## Directory structure (Part XII)

```
project_shimmer/
├── genesis.md                       # written spec, Parts I–XXVII
├── CLAUDE.md                        # operator memory for in-repo runs
├── README.md
├── .gitignore                       # excludes keys, PDFs, output/
├── .githooks/
│   └── pre-commit                   # runs guard_secrets.py
├── config/
│   ├── constitution.json
│   ├── agent_registry.json          # 14 agents, DOES / DOES_NOT
│   ├── agent_contracts.json         # output schemas
│   └── convention_registry.json     # compiled conventions
├── input/
│   ├── context/                     # corpus to cite against
│   ├── operational/                 # document under review
│   └── conventions/                 # operator rules (.md)
├── ontologies/                      # saved domain snapshots
├── output/
│   ├── deliverables/                # six artifacts per run
│   ├── bus/messages.jsonl
│   ├── logs/                        # cost, verify, run logs
│   └── audit/contract_violations/
├── presentations/                   # three Beamer decks
├── prompts/                         # per-agent prompt templates
├── reference/                       # static references
└── scripts/
    ├── pipeline.py                  # entry point
    ├── verify_session1.py           # 39-check gate
    ├── guard_secrets.py             # pre-commit scanner
    ├── agents/                      # agent implementations
    └── ...
```

The pipeline reads only from `input/`. Files elsewhere are ignored at
intake.

---

## Genesis index

The spec at `genesis.md` is the source of truth. All code changes cite
the Part they implement.

| Part  | Topic                                                    |
|-------|----------------------------------------------------------|
| I     | The seven seed laws                                      |
| II    | Agents                                                   |
| III   | Hierarchy and governance                                 |
| IV    | Constitution engine                                      |
| V     | Emergent task forces                                     |
| VI    | Message bus                                              |
| VII   | Multi-model architecture                                 |
| VIII  | Search stack                                             |
| IX    | Memory layer                                             |
| X     | Learning loop                                            |
| XI    | Pipeline lifecycle                                       |
| XII   | Directory structure                                      |
| XIII  | Dependencies                                             |
| XIV   | Build sequence                                           |
| XV    | Verification checklist                                   |
| XVI   | What this spec does not cover                            |
| XVII  | Lessons carried forward                                  |
| XVIII | Genesis amendment: convention-driven review architecture |
| XIX   | Corpus acquisition discipline                            |
| XX    | External reference discovery                             |
| XXI   | Semantic retrieval layer                                 |
| XXII  | Universal review principles                              |
| XXIII | *reserved*                                               |
| XXIV  | Absence detection                                        |
| XXV   | Metadata hierarchy                                       |
| XXVI  | Uncertain findings                                       |
| XXVII | Structural inventory                                     |

---

## Limitations and non-goals (Part XVI)

- **Not an open-ended chatbot.** Shimmer does not converse. It reviews
  documents.
- **Not a code-writing agent.** It produces tracked-changes prose, not
  source code.
- **Does not auto-publish.** Every output is a file the operator
  chooses to forward or not.
- **Does not modify the operator's input.** `input/` is read-only at
  runtime.
- **No silent self-modification.** The constitution and agent registry
  change only via approved DELTA.
- **Does not validate the operator's rules.** If a convention is
  wrong, the cited amendments will be wrong in a legible way; the
  operator decides whether to accept them.
- **Model non-determinism.** Two runs over identical inputs may
  produce different findings at the margin. The bus records exactly
  what was produced.
- **Coverage gap.** Absence detection sees only what `input/context/`
  contains.
- **Embedding-model swap is irreversible across runs.** If the
  operator changes the embedding model, the staleness check rebuilds
  the store, but cross-run comparison becomes apples-to-oranges.

---

## License / author / contact

Author: Seckin Ozbek.

This repository is a research artifact. License terms are at the
operator's discretion; no license file is committed by default.

References cited in this README:

- Cook, M. (2004). *It Takes Two Neurons to Ride a Bicycle*.
  fermatslibrary.com/s/it-takes-two-neurons-to-ride-a-bicycle
- Garland, A. (dir.) (2018). *Annihilation*. Paramount.
- VanderMeer, J. (2014). *Annihilation*. FSG.
- Regulation (EU) 2024/1689 — the EU AI Act.
- ISO/IEC JTC 1/SC 42 — AI standards.
