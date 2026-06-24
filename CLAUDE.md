# Project Shimmer, agent operating contract

This file is the operating contract for an AI coding agent (Claude Code) working in
this repository. It is terse and rule-shaped, not a tutorial (the newcomer guide is
README.md). The founding specification is [genesis.md](genesis.md), Parts I to XXVII:
read it before making any change. Shimmer is a standalone, domain-agnostic document
processing swarm governed by an append-only constitution.

## Hard rules

- No em dashes anywhere. Use commas, colons, periods, or parentheses.
- LAW-IV (privacy) is never edited. It outranks LAW-0 (operator sovereignty) for
  sensitive-content handling, with no exceptions. A single leak is irreversible.
- The constitution is append-only. The INFRA-029 amendment-guard tripwire
  (`scripts/constitution_guard.py`) intercepts any attempt to modify or delete an
  existing `amendments[]` entry or seed law from any code path; adding a new id is the
  only allowed change. No-gap rule: an amendment id is never reused, never inserted
  between existing ids, never renumbered. Every numbered DELTA is recorded in
  `config/constitution.json` `amendments[]`, the single canonical record; no DELTA
  lives only in prose.
- Model ids are read live from the provider, never hardcoded. A deprecated model STOPS
  the run for operator approval; there is no auto-swap. Model choice is owned solely by
  `config/agent_registry.json` (`spec.model`); the key layer never sets a model.
- API keys live OUTSIDE the repository, located via `$SHIMMER_CONFIG_PATH`, then a
  sibling `../api_keys/config.py`, then the repo-root `.env_path` pointer. Never
  hardcode, log, echo, or commit a key value. `load_api_keys` reads key values only via
  a fixed allowlist.
- No domain-specific content in `scripts/`. Domain knowledge lives in `config/`
  (compiled conventions) and `durable/` (learned assets spawned from `input/context/`,
  under `durable/learnings/` and `durable/reference/`).
- English only for code, config file names, and folder names. No spaces or unicode in
  paths.
- Every convention review finding cites at least one CONV-* and at least one REF-*.

## Change discipline

- Read-only trace before any structural change. Trace to the point where the decision
  is mechanical.
- Full upstream and downstream hygiene for every change: all writers, all importers,
  string literals, path constructions, genesis.md, README.md, CLAUDE.md, .gitignore,
  the verify gate, hardcoded lists, and CLI flags.
- The gate stays green and non-mutating at every commit. Commit each coherent unit
  standalone.

## The verify gate

- The gate is `scripts/verify_session1.py`. Its total is the length of its CHECKS list,
  not a hardcoded number.
- Checks must prove behavior with EXECUTED coverage: run the live path on fixtures.
  Source inspection alone, or a zero-caller scaffold, is not proof. No
  dormant-but-claimed-built scaffold is acceptable: every part (function, flag, field,
  branch, store) must have a live duty or an executed gate path.
- Gate checks are non-mutating: they use tempdirs and never write the real
  `durable/`, `ontology/`, or `config/` stores.

## Governed structure

- Changes to the constitution or to governed inter-agent structure require an
  operator-ratified DELTA. Agents propose; the operator ratifies; agents never
  self-apply. The operator decides every escalation. No silent self-modification.
- The meta-law tripwire (INFRA-043) extends the constitution guard
  (`scripts/constitution_guard.py`) to the genesis/meta layer. `check_genesis_integrity`
  requires genesis Part I to mirror the guarded `seed_laws` (a missing seed law flags a
  tampered immutable core). The VERIFIED no-gap DELTA path is the SOLE route to change
  governed structure: `verify_amendment_append` (enforced inside `check_constitution_change`)
  requires a new amendment to carry the next id (`prior_max + 1`, never reused, never a gap),
  be `operator_approved`, and clear the signature scan. Never bypass this path to change
  governed structure.
- The LAW-0 asymmetry is load-bearing, not a preference. The guard refuses AGENTS (they can
  never amend governed structure; a signature-carrying agent DELTA is refused and routed to
  the operator), but it NEVER hard-blocks the OPERATOR, who is sovereign under LAW-0:
  operator input gets confirm-and-proceed in interactive mode and log-and-proceed in
  non-interactive mode (`operator_input_verdict` returns proceed, or the operator's own
  abort, never a block). Never build anything that could hard-block the operator on the
  signature scan: a guard that cages the operator inverts LAW-0.
- The signature scan (`scan_for_meta_signature`) is a FLAG for operator attention, not a
  complete semantic guarantee: it has false positives and false negatives. Do not overclaim
  it or rely on it as a complete bypass guard.

## The canonical envelope (INFRA-037)

- Agents emit and consume ONE flat per-item envelope: `{agent, doc_id, items[]}`. Each
  item is strictly flat (every value a scalar or an array of scalars; no nested objects).
  Consumers read by reference from the append-only message bus, and a higher `revision`
  per `item_id` supersedes an earlier one.

## Findings, citations, and grounding

- The verifiability gate (`scripts/verifiability_gate.py`) is pipeline behavior, not a
  governed change: an affirmative finding that cites nothing is downgraded to UNCERTAIN,
  flagged-and-kept (never dropped). It reuses the UNCERTAIN channel (genesis Part XXV) and
  INFRA-037 supersession (a `revision + 1` item). The fire-set is an explicit per-agent
  constant (LEGAL_ANALYST GROUNDED; PRACTICE_AUDITOR ALIGNED/COMPLIANT/VIOLATION/ANTI_PATTERN;
  FACT_CHECKER CONFIRMED); self-hedging verdicts never fire. Do not remove or weaken it.
- WEB-REF is a real citation form (`WEB-REF-NNNN`), minted by
  `reference_builder.add_web_reference` from the three structured web-source fields
  (FACT_CHECKER `source_url`, PRACTICE_AUDITOR `reference_url` and `reference_source`) and
  cited in `ref_ids` exactly like a REF-*. The corpus-REF regex uses the `(?<!WEB-)`
  disambiguation so a WEB-REF id is never miscounted as a REF. Inline free-text URL
  extraction is out of scope (convention-activated, deferred).
- The empty-convention carve-out (INFRA-042): the CONV-* requirement is relaxed ONLY when
  the convention registry is empty (an amendment then grounds on a REF-* or a WEB-REF-*).
  NEVER relax it when conventions exist; the rule is state-gated, not blanket.

## The sensitivity boundary

- `scripts/sensitivity_layer/` is the privacy home (a package, not a single module). It
  imports nothing editorial; only orchestration imports it.
- Sensitivity is operator-convention-defined, never model-judged. The operator declares
  a `confidentiality` or `redaction` convention category (CONV-*); the local Qwen
  redactor applies those rules to spans. Regular-shaped PII the operator authorizes
  (grouped-digit identifiers, number-plus-magnitude figures) is caught deterministically
  and merged with model proposals. The detector carries no language literals: all
  vocabulary lives in `config/language_redaction_cues.json` (operator-extensible per
  language).
- There is no engine-side default-categories floor. Redaction acts only on compiled
  operator rules; with none in force the run HARD-STOPS for a conscious operator choice
  (supply a compiling rule, or pass `--no-redaction-override` to declare the run
  redact-nothing, logged to the governance ledger). Never a silent default, never a
  silent ship. An approved span is scrubbed from every operator-facing artifact and
  "applied" means VERIFIED ABSENT by a post-apply grep gate (a surviving or unlocatable
  span BLOCKs).
- The full LAW-IV outbound masking layer is BUILT and WIRED (INFRA-041) and is
  OPERATOR-ACTIVATED: `LAYER_ACTIVE` defaults to False. When the operator activates a
  sensitive run, operator-marked spans are held local and replaced by typed placeholders
  before any network or API call, and every masking is appended to the exposure ledger
  (`durable/governance/exposure_ledger.jsonl`). Nothing sensitive reaches the live
  network flow without explicit operator activation; while the layer is inactive the run
  hard-gates and refuses to start unless the operator passes
  `--sensitivity-layer-inactive-override` (logged). `may_use_web` is an enforced control:
  an agent reaches the web only if its registry flag permits it.

## Three-input-type model (genesis Part XVIII)

- `input/context/`: the domain learning corpus. Read at BOOT by adaptive_spawn. Never
  receives deliverables.
- `input/operational/`: the documents under review. Populated by the pipeline at runtime
  from `input/context/` based on the cutoff in `config/review_scope.json`. Not manually
  populated.
- `input/conventions/`: the operator review framework. Parsed into
  `config/convention_registry.json` at BOOT.

## Key paths

- `config/`: governance and compiled config (`constitution.json`, `agent_registry.json`,
  `agent_contracts.json`, `convention_registry.json`, `review_scope.json`,
  `editorial_board.json`).
- `scripts/`: the pipeline, the agent modules, `sensitivity_layer/`, and `ontology_*`.
- `input/`: `context/`, `conventions/`, `operational/` (see above).
- `output/runs/<id>/`: per-run artifacts (deliverables, the bus log, audit and proposal
  files, the run summary). Runs never overwrite each other.
- `durable/`: learned and governance state that survives reset: `learnings/`, `cache/`,
  `global/`, `governance/`, `reference/`.
- `ontology/stores/`: the cross-run learning graph (capture, graph, GNN state).

## Commands

```
py -3.9 -X utf8 scripts/verify_session1.py        # verification gate (run every session)
py -3.9 scripts/pipeline.py --non-interactive     # full pipeline
py -3.9 scripts/pipeline.py --list-snapshots      # list saved snapshots
py -3.9 scripts/pipeline.py --save-snapshot NAME  # snapshot learned state
py -3.9 scripts/pipeline.py --load-snapshot NAME  # restore a snapshot
py -3.9 scripts/pipeline.py --reset-snapshot      # strip back to seed defaults
py -3.9 scripts/bus_viewer.py --follow            # live bus and cost stream
```
