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

The bus is an append-only JSONL log at the run's
`output/runs/<run>/logs/agent_bus.jsonl` (per-run; Part XXVII §A).
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
model family than the drafter:

- Drafters run on Claude (per-agent model ids in `config/agent_registry.json`).
- Auditors run on GPT-4o (VERIFIER, FACT_CHECKER, PRACTICE_AUDITOR).

Backends are pluggable; the law, not the model id, is what is fixed. The
per-agent model assignments are listed under "Models and selection" below.

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

**Audit-only outputs (intentional).** INST_FINDER and CITATION_RESOLVER run at the
corpus level and post their findings to the bus for auditability, but those
outputs are intentionally **not consumed by any downstream agent or deliverable
yet** — this is by design, not a dropped handoff. They are candidate inputs for
future integration (an institution graph, a cross-document citation graph). The
same note is recorded in their `config/agent_contracts.json` entries.

### Models and selection

`config/agent_registry.json` is the sole source of each agent's backend and
exact model id (the key layer supplies API keys only, never a model):

| Backend      | Model id                     | Agents                                                  |
|--------------|------------------------------|--------------------------------------------------------|
| `claude_api` | `claude-opus-4-8`            | LEGAL_ANALYST, AMENDMENT_DRAFTER                        |
| `claude_api` | `claude-sonnet-4-6`          | PROCESSOR, ARCHIVIST, CITATION_RESOLVER                 |
| `claude_api` | `claude-haiku-4-5`           | STYLE_GUARDIAN, INST_FINDER, SPEECH_ACT_TAGGER          |
| `openai_api` | `gpt-4o`                     | VERIFIER, FACT_CHECKER, PRACTICE_AUDITOR                |
| `qwen_local` | `Qwen/Qwen2.5-7B-Instruct`   | REDACT_CLERK, REDACT_AUTHORITY, REDACT_GATE            |

At run start the pipeline resolves every assigned model against the provider's
current live model list and stops the run if any is retired. Replacements are
never automatic: the operator approves each one, and the approval is recorded in
`durable/governance/model_approvals.json`. Backends whose live list cannot be
queried (no key, or the local Qwen backend) are skipped with a note. Pass
`--skip-model-check` to bypass the gate (for example, offline runs).

### Redaction (always-on final pass)

The last pipeline phase always runs, every run, over the produced deliverables
(LAW-IV). The three Qwen agents screen each document's deliverables at the output
boundary and decide adaptively what, if anything, to redact — `REDACT_CLERK`
proposes tier 1-2 redactions, `REDACT_AUTHORITY` approves tier 3-4 with an
adversarial test, and `REDACT_GATE` gives the final pass/fail. An approved and
passed redaction is applied through the amendments master and the `.md`/`.docx`
are re-rendered from it, so the formats stay consistent (Part XXVII §E).
Redaction writes only inside the run folder and never touches `durable/`; every
decision is posted to the run bus.

**Qwen-required startup gate.** Because redaction always runs, the pipeline
checks at boot — before any agent runs — that the local Qwen backend is
reachable/configured. If it is not, the run **refuses to start**, unless the
operator declares this run non-sensitive with `--no-redaction-override` (a
per-run waiver, confirmed interactively when interactive). Each waiver is logged
to the governance ledger (`durable/governance/redaction_waivers.jsonl`, with
timestamp and run id); when waived, the redaction phase records
`REDACTION_SKIPPED (operator_waived)` on the bus. The pre-run check honestly
verifies only that `torch`/`transformers` are importable and a `qwen_local` model
id is configured; the actual model load is verified at first call (and the phase
degrades safely if that load fails). If Qwen is reachable but no GPU is detected,
the gate prints a soft "redaction will be slow on CPU" reminder — it never blocks
and is never recorded.

---

## Semantic retrieval

### Per-provision queries (Part XXI)

Whole-document retrieval averages over the n provisions an operational
document touches and starves provision-specific corpus passages. Part XXI
requires per-provision queries: for each section
$s_i$ of the operational document, top-k context passages are
retrieved by embedding similarity to $s_i$ alone, and the retrievals
are concatenated into a single agent call with provision-tagged
blocks. One agent call per agent, not n, but each provision sees its
own retrieval window.

### Embedding store

- **Per-document language → per-language model.** Each document's dominant
  language is detected (offline, via `langdetect`); English (and undetected)
  documents use the fast English `sentence-transformers/all-MiniLM-L6-v2`
  (384-dim, 256-token window), while a positively-detected non-English language
  uses the multilingual
  `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. The
  language→model map is a small registry, extensible per language; an
  unavailable model degrades to the multilingual or English default with a
  warning, never a silent failure.
- **Per-model sub-stores (correctness).** Passages embedded by different models
  are not numerically comparable, so the store keeps one sub-store per model and
  records which model embedded each passage. A query is embedded separately by
  each model and scored **only** against that model's passages, so every
  similarity is a valid same-model cosine; results are merged for the global
  top-n.
- Chunking: ~400-character windows.
- Store: pickle of per-model `(ref_id, vector, text)` sub-stores at
  `durable/cache/embedding_store.pkl`; it is copied into a snapshot when one is
  saved.
- **Staleness check.** The store records the source filename set, the
  per-document model assignment, and a signature of the language→model registry.
  It rebuilds when the `input/context/` filename set changes, when the registry
  changes (so the model used is part of the staleness decision), or when an
  older single-model store is loaded.

### Direction-aware output

The tracked-changes `.docx` renders each paragraph and run in its correct
reading direction, decided from the content's own script (no hardcoded
direction): RTL scripts (Arabic, Hebrew, …) get `w:bidi` paragraphs, `w:rtl`
runs, right justification, and a bidi language tag; LTR stays default.
Mixed-direction content is handled per run, so an RTL memo quoting an LTR case
name lays out correctly. This is language-agnostic — the implementation applies
the right direction per detected script.

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

## Structural inventory and absence detection (Parts XXVI and XXIII)

Most review systems criticize only what is present. Compliance work
also cares about what is missing.

### Structural inventory (Part XXVI)

During corpus-level processing, ARCHIVIST produces a
`structural_inventory`: for each governance element (risk
classification, conformity assessment, post-market monitoring,
redress, transparency obligations, human oversight, prohibited
practices, environmental provisions, cross-border data flow
provisions, definitions sections), how many documents contain it and
which. The inventory is not hardcoded; it is derived from the corpus.

### Absence detection (Part XXIII)

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

- `input/context/` — corpus to cite against
- `input/operational/` — document under review
- `input/conventions/` — operator-authored rules

All three input paths accept the same format family, extracted by the shared
`scripts/text_extract.py`: **`.pdf`, `.docx`, `.html`/`.htm`, `.txt`, `.md`,
`.rst`, `.log`, and `.json`**. Every reader — corpus loader, embedding store,
convention parser, and date cascade — uses this one extractor, so semantic
retrieval embeds every accepted format (not just PDF). An unsupported file
dropped into an input folder is logged with a warning and skipped, never
silently dropped. Optional libraries (`pypdf`, `python-docx`,
`beautifulsoup4`) are imported lazily; a missing one degrades to a warning for
that format rather than a crash.

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

Approved DELTAs (one-for-one with `config/constitution.json` `amendments[]`):

- **INFRA-017** — directory hygiene
- **INFRA-018** — agent hygiene
- **INFRA-019** — variable hygiene
- **INFRA-020** — domain-term purge
- **INFRA-021** — adaptive spawning
- **INFRA-022** — Shimmer UI
- **INFRA-023** — non-sibling topology
- **INFRA-024** — English module-name rules
- **INFRA-025** — verification-cache subsystem rename (`verification_memory`
  → `verification_cache`, `ontologies/` → `snapshots/`)
- **INFRA-026** — per-agent model selection (explicit current model ids per
  agent in `agent_registry.json`, `model_tier`/`context_tier` removed,
  key-layer model override removed, live deprecated-model gate with operator
  approval)
- **INFRA-027** — broad shared input-format family (`scripts/text_extract.py`
  gives every reader the same `.pdf`/`.docx`/`.html`/`.txt`/`.md`/`.rst`/
  `.log`/`.json` family; embedding store embeds all formats, not just PDF;
  unsupported types warn instead of silently skipping)
- **INFRA-028** — multilingual support (per-document language detection,
  per-language embedding model with per-model sub-stores keeping query/passage
  on the same model, and direction-aware RTL/LTR `.docx` output; agent layer
  and cross-family verification untouched)
- **INFRA-029** — protect cumulative learning: the durable-vs-disposable
  firewall (genesis Part XXVII §B) making the protected learning class
  impossible for any per-run cleanup, reset, load, or reorganization to destroy
  or destructively relocate. Enforced by a constitutional-amendment tripwire
  (`scripts/constitution_guard.py`) that stops any modify/delete of an existing
  amendment or seed law pending operator approval, and by a snapshot-first,
  governance-preserving `reset_snapshot`. (Ratified.)
- **INFRA-030** — relocate the protected durable/learning class into a
  top-level `durable/` tree (cache/global/learnings/reference/governance),
  outside the auto-cleaned `output/` tree, so the firewall is enforced by
  location; reset strips only the resettable durable subdirs and never touches
  `durable/global` or `durable/governance`. `config/constitution.json` stays put.
- **INFRA-031** — append-only numbering discipline (genesis Part XXVII §H): Part
  numbers must form an unbroken sequence with no gaps; new Parts are appended at
  the end only, never inserted or left as a reserved gap; a renumber happens only
  to close an accidental gap, with full upstream/downstream reference updates and
  through the amendment tripwire. `INFRA-0xx` amendment IDs are likewise
  append-only (never reused, inserted, or renumbered) and independent of Part
  numbers. (Recorded alongside closing the prior XXII→XXIV gap.)
- **INFRA-032** — per-run output isolation (genesis Part XXVII §A): every run
  writes into its own `output/runs/<UTC-timestamp>__<run-id>/` folder (run id =
  8 random hex), so runs never overwrite each other. A single source of truth
  (`scripts/run_context.py`) computes the run path once at boot; the bus, cost
  tracker, deliverables, reference index, audit synthesis, tier-1 cache, run
  summary, and the agent-layer contract-violation dumps all derive from it
  (run-awareness is threaded into every AgentWrapper). Deliverable keys are
  collision-safe (`<stem>__<ext>` on stem collision). `durable/` is never written
  into a run folder and per-run cleanup cannot reach it; the firewall is unchanged.
- **INFRA-033** — single canonical master with on-demand renders (genesis Part
  XXVII §E): the `amendments_payload` dict (written verbatim as
  `<doc>__amendments.json`) is the master, and the `.md` and tracked-changes
  `.docx` are pure renders of it through one entry point
  (`amendment_render.write_amendment_deliverables`), so the formats cannot drift.
  The `.docx` takes the original text only as a presentation canvas; a drift-guard
  assertion confirms each render reflects the master. `cost_tracker.json`
  (aggregate of the `.jsonl` event log) and `audit_synthesis.md`/`delta_proposals.json`
  (two views of one summary) are documented as already master-derived.
- **INFRA-034** — retire dead wiring and add the redaction phase (genesis Part XI):
  deleted the orphaned `scripts/agents/` per-agent subclass package (the pipeline
  drives every agent via `AgentWrapper` by registry name) and removed the
  never-written within-run tier-1 verification cache (the cache is now two durable
  tiers, project + global). Added an always-on final pipeline phase that screens
  the deliverables: `REDACT_CLERK`/`REDACT_AUTHORITY`/`REDACT_GATE` (Qwen) decide
  adaptively what to redact; an approved redaction flows through the amendments
  master and re-renders `.md`/`.docx`. Run-scoped, never touches `durable/`, posts
  to the bus, and degrades safely if Qwen is unreachable. INST_FINDER and
  CITATION_RESOLVER were flagged (bus-only output) but not deleted.
- **INFRA-035** — Qwen-required startup gate (genesis Part XI): redaction always
  runs on the local Qwen backend, so the pipeline confirms that backend is
  reachable/configured before any agent runs and **refuses** the run if not —
  unless the operator declares the run non-sensitive with `--no-redaction-override`
  (per-run only, confirmed interactively), each waiver logged to
  `durable/governance/redaction_waivers.jsonl`. When waived, the redaction phase
  records `REDACTION_SKIPPED (operator_waived)`. The pre-run check verifies
  libraries + model id; actual model load is verified at first call. Missing GPU
  is a soft printed reminder only — never a blocker, never recorded.
- **INFRA-036** — prompt caching on both cloud paths (genesis Part VII): every
  agent prompt is assembled stable-prefix-first (identity + DO/DO-NOT + contract +
  constitution + conventions, then the per-call dynamic suffix). Claude marks the
  prefix with explicit `cache_control` (5-min ephemeral, reads at 0.1x); GPT adds
  no `cache_control` but is structured stable-first for OpenAI's automatic prefix
  cache. The cost tracker logs each provider's cache fields per call (0 when
  absent) so a silent cache loss is visible. Rule: no dynamic content may enter
  the stable prefix. Same effective prompt, reordered; agent logic unchanged.

INFRA-017 through INFRA-024 predate the DELTA-recording convention and are
stored as pre-convention stubs (`pre_convention: true`, `created: "unknown"`);
their details were not captured and are not reconstructed.

### DELTA recording convention

Every numbered DELTA is recorded as an amendment in
`config/constitution.json` (`amendments[]`) — that is the canonical,
machine-readable log. This roster lists them all for humans, but **no DELTA
lives only in the roster: if it has a number, it is in the constitution.**
Future DELTAs follow the same path (record the amendment first, then add the
roster line). The `_GENESIS_CONSTITUTION` reset template in
`scripts/snapshot_manager.py` deliberately keeps an empty `amendments[]` so
`--reset-snapshot` still strips legislation back to the seven seed laws; the
canonical log is the live `config/constitution.json`.

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
input/context/        <- corpus (.pdf/.docx/.html/.txt/.md/.rst/.log/.json)
input/operational/    <- the document under review
input/conventions/    <- operator-authored *.md rules
```

**Run.**

```bash
py -3.9 scripts/pipeline.py
py -3.9 scripts/verify_session1.py
```

Outputs land under the run's own folder `output/runs/<UTC-timestamp>__<run-id>/`
(runs never overwrite each other): six deliverables per reviewed document in
`…/deliverables/`, the bus in `…/logs/agent_bus.jsonl`, cost and run logs in
`…/logs/`, and contract-failure raw text in `…/audit/contract_violations/`.

**Canonical master, on-demand renders (Part XXVII §E).** Each logical output has
one master format; other formats are pure renders of it, never written from
independent sources. For the amendments deliverable, `<doc>__amendments.json` is
the master and the `.md` and tracked-changes `.docx` are derived from that single
payload through one entry point (`amendment_render.write_amendment_deliverables`),
so the three files cannot drift. (Similarly, `cost_tracker.json` is a recomputed
aggregate of the `cost_tracker.jsonl` event log.)

---

## Commands and flags

`scripts/pipeline.py` is the entry point. With no flags it runs the full
pipeline interactively.

| Flag                    | Effect                                                            |
|-------------------------|------------------------------------------------------------------|
| `--non-interactive`     | Never prompt; operator escalations resolve to `DEFERRED`.        |
| `--skip-confirmation`   | Skip the pre-run cost-estimate confirmation prompt.              |
| `--max-docs N`          | Review at most N operational documents.                          |
| `--run-objectives TEXT` | Override the default run objectives string.                      |
| `--skip-model-check`    | Skip the live deprecated-model gate (e.g. offline runs).         |
| `--no-redaction-override` | Per-run waiver: declare THIS run non-sensitive and run with NO redaction (required to proceed when Qwen is unavailable; logged to the governance ledger). |
| `--reset-bus`           | Delete this run's bus before starting.                           |
| `--reset-cost`          | Delete this run's cost-tracker files before starting.            |
| `--save-snapshot NAME`  | Save the current learned state as a named snapshot, then exit.   |
| `--load-snapshot NAME`  | Restore a named snapshot, then exit.                             |
| `--reset-snapshot`      | Strip learned state back to seed defaults (snapshot-first), exit.|
| `--list-snapshots`      | List saved snapshots, then exit.                                 |
| `--overwrite-snapshot`  | Allow `--save-snapshot` to overwrite an existing name.           |

Other entry points:

```bash
py -3.9 -X utf8 scripts/verify_session1.py      # 39-check verification gate
py -3.9 scripts/bus_viewer.py --follow          # live bus + cost stream (latest run)
py -3.9 scripts/bus_viewer.py --run NAME        # view a specific run folder
```

`bus_viewer.py` reads the latest run under `output/runs/` by default; `--run NAME`
or `--path FILE` selects another. `recover_phase6.py` re-runs synthesis from a
run's already-paid-for agent outputs (`--run NAME`, default latest).

---

## Durable state and the firewall

Learned state that must survive across runs is a PROTECTED class and lives under
`durable/`, outside the disposable `output/` tree:

- `durable/cache/` — embedding store and the project (tier-2) verification cache.
- `durable/global/` — the cross-project (tier-3) verification cache.
- `durable/learnings/` — discovered institutions, citation conventions, speech-act
  taxonomy, search-strategy learnings, discovered APIs, document dates.
- `durable/reference/` — `LINGUISTIC_IDENTITY.md`, `situational_awareness.md`.
- `durable/governance/` — the operator-approval ledger and the amendment-guard log.

Because the protected class lives outside `output/`, per-run cleanup cannot reach
it. `--reset-snapshot` writes a backup snapshot first, then strips the resettable
durable subdirs (`cache`, `learnings`, `reference`) back to seed defaults; it
never touches `durable/global`, `durable/governance`, or
`config/constitution.json`. A snapshot copies the resettable durable subdirs
alongside the constitution, convention registry, and prompts.

The constitution carries an amendment tripwire (`scripts/constitution_guard.py`):
any attempt to modify or delete an existing seed law or amendment in
`config/constitution.json` stops and requires explicit operator approval.
Appending a new amendment — the normal DELTA path — is allowed. Agents have no
write path to the constitution.

---

## Domain switching

```bash
py -3.9 scripts/pipeline.py --save-snapshot domain_b
py -3.9 scripts/pipeline.py --reset-snapshot

# replace inputs
rm input/context/*.pdf
rm input/conventions/*.md
cp /path/to/new/corpus/*.pdf  input/context/
cp /path/to/new/conventions.md input/conventions/

py -3.9 scripts/pipeline.py
```

No code is edited. The `--reset-snapshot` strips back to seed defaults;
the new context corpus and conventions carry the domain. The
`snapshots/` directory is empty by default — no named snapshots ship
with the repo. It is populated only by an explicit
`--save-snapshot NAME` action; a normal run never writes here. Once you
save snapshots, they live under `snapshots/<name>/`, for example:

- `domain_a/`
- `domain_a_v2/` (corpus refresh)
- `domain_b/` (includes the embedding pickle)

---

## Prompt caching

Both cloud call paths cut input-token cost by reusing a cached stable prompt
prefix. Every agent prompt is assembled **stable-prefix-first**: the stable
prefix (agent identity + DO/DO-NOT + directives + output contract + constitution
+ compiled conventions) is identical across that agent's calls within a run; the
dynamic suffix (objectives, retrieved passages, recent bus, work payload) comes
last.

- **Claude (explicit):** `call_claude` marks the end of the stable prefix with
  `cache_control: {type: ephemeral}` (5-minute TTL — a run's agent calls fire
  within minutes). Cache reads bill at 0.1x input.
- **GPT (structure-and-log):** OpenAI caches automatically, so `call_gpt` adds no
  `cache_control` — it only structures the prompt stable-first so the automatic
  prefix cache catches, then verifies it via logging.
- **Measured, not trusted:** the cost tracker logs each provider's cache fields
  per call (Anthropic `cache_creation_input_tokens` / `cache_read_input_tokens`;
  OpenAI `cached_tokens`), defaulting to 0 when absent — so a silent provider-side
  cache loss shows up as the cached count dropping to zero, not hidden.
- **The rule:** no dynamic content (timestamp, run id, per-call text, retrieved
  passages, bus) may enter the stable prefix, or the prefix changes per call and
  the hit rate collapses. Caching applies only above each model's minimum
  cacheable size; small-prompt agents simply don't cache (nothing is padded).

---

## Cost analysis

Most recent EU AI Act review run, from
`output/runs/<run>/logs/cost_tracker.json`:

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

`scripts/verify_session1.py` runs 39 structural invariants. Examples:

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

Latest run: **PASS=39, WARN=0, FAIL=0**. The gate is a standalone harness; a
FAIL signals a regression to fix before relying on a run. PASS=39 is the
stability target; any drop flags regression before it leaves the local machine.
The gate is non-mutating: it exercises components against a throwaway temporary
run folder, so running it never writes into `output/runs/` or `durable/`.

---

## Evaluation design

The principal claim — that domain knowledge can live entirely in data
without leaking into framework code — is testable as a causal
statement:

> If the deliverable schema is invariant under a domain switch
> (`save_snapshot → reset_snapshot → swap input/ → run`) with zero
> changes to files under `scripts/`, and verify-gate check 22
> continues to pass, then domain knowledge does not reside in
> framework code.

The test has been run cleanly on one domain so far: EU AI Act
alignment (with a prior development iteration used for architecture
debugging). The EU run produced the six-file deliverable shape
(`*__amendments.docx/json/md`, `*__deliverable.md`,
`*__context_summary.md`, `*__operative_summary.md`), and check 22
passed. The contrapositive — a code change that
leaks domain-specific vocabulary — would fail check 22 immediately.
The verify gate is therefore the falsifier, not a passive log.

---

## Metadata hierarchy (Part XXIV)

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

## Uncertain findings (Part XXV)

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
├── durable/                         # PROTECTED class (Part XXVII §B / INFRA-030);
│   ├── cache/                       #   outside the auto-cleaned output tree
│   │   ├── embedding_store.pkl      #   embedding store + verification cache (tier-2)
│   │   └── verification_cache.json
│   ├── global/                      #   verification cache (tier-3, survives reset)
│   ├── learnings/                   #   institutions/citations/speech-acts/search/apis/dates
│   ├── reference/                   #   LINGUISTIC_IDENTITY.md, situational_awareness.md
│   └── governance/                  #   model_approvals.json, constitution_guard_log.jsonl
├── snapshots/                       # saved domain snapshots
├── output/                          # DISPOSABLE per-run artifacts (INFRA-032)
│   └── runs/<ts>__<run-id>/         # one folder per run; runs never overwrite
│       ├── deliverables/            # six artifacts per reviewed doc (<doc_id>__*)
│       ├── logs/                    # agent_bus.jsonl, cost_tracker.*, run_summary_*
│       └── audit/                   # reference_index, audit_synthesis,
│                                    #   delta_proposals, contract_violations/
├── presentations/                   # optional, manual: no decks ship
├── prompts/                         # per-agent prompt templates
├── reference/                       # static references
└── scripts/
    ├── pipeline.py                  # entry point
    ├── verify_session1.py           # 39-check gate
    ├── agent_wrapper.py             # the single agent driver (by registry name)
    ├── guard_secrets.py             # pre-commit scanner
    └── ...
```

Agents are driven entirely by `agent_wrapper.AgentWrapper`, instantiated by
registry name from `config/agent_registry.json`; there is no per-agent
implementation file.

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
| IX    | Verification cache layer                                 |
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
| XXIII | Absence detection                                        |
| XXIV  | Metadata hierarchy                                       |
| XXV   | Uncertain findings                                       |
| XXVI  | Structural inventory                                     |
| XXVII | Pipeline hygiene standard (per-run isolation, durable-vs-disposable firewall, naming, format-master, separation of concerns) |

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
