# PROJECT SHIMMER — Unified Genesis
# Location: project_shimmer/genesis.md
# Trigger: "Read project_shimmer/genesis.md and execute it."
#
# This is the founding document of Project Shimmer — a standalone,
# domain-agnostic document processing swarm governed by an adaptive
# constitution. It is not dependent on any prior project. It carries
# forward lessons learned from earlier work but shares no code, no
# paths, no structural dependency with any predecessor.
#
# WHAT SHIMMER IS:
# Drop documents into input/. The swarm discovers the domain —
# language, institutions, citation conventions, format rules — and
# bootstraps all reference assets from scratch. Agents self-organize
# into task forces, verify every claim against external sources,
# and produce audited deliverables. The constitution grows from
# operational experience. By the tenth run, the system self-governs.
#
# WHAT SHIMMER IS NOT:
# Not a chatbot. Not a RAG pipeline. Not a fixed-step processor.
# It is a constitutional deliberative swarm with institutional memory.

---

## Part I — THE SEVEN SEED LAWS

These laws are the initial constitution of every Shimmer project.
They are ordered by priority — a lower law cannot override a higher
one. They are the minimum viable governance needed for the first run.
Everything else — task force laws, precedents, amendments — emerges
from operation.

Store in config/constitution.json under "seed_laws".

## LAW-0 — Operator sovereignty

The operator is the sole source of constitutional authority. No agent,
task force, supervisor, or orchestrator may create, amend, or repeal
a law without operator approval. The constitution governs all agent
behavior. Silence in the constitution means escalate — never assume
permission. Every operator decision on an escalation is recorded as
legislation (precedent, task force law, or amendment) for future runs.

## LAW-I — Do no harm to the source

No agent may alter, fabricate, or suppress information from source
documents. An agent may flag, annotate, footnote, and warn — but the
source record is sacred. When source content conflicts with external
evidence, both are preserved and the operator decides. No agent may
resolve a factual conflict by choosing one version over another.

## LAW-II — Know your bounds

Each agent has a fixed capability set defined in the agent registry.
An agent may request another agent's service but may not perform
another agent's function. An agent that detects itself reasoning
outside its defined scope must stop and yield to the appropriate
agent. The capability boundary is the agent's identity — crossing
it is not initiative, it is malfunction.

## LAW-III — No self-audit

No model may verify, fact-check, or audit output that was generated
by the same model family. Claude-generated content is audited by GPT
or local models. GPT-generated content is audited by Claude or local
models. Local model output is audited by cloud models. The audit
trail must show which model produced and which model verified every
output segment.

## LAW-IV — Protect what is private

Sensitive content — PII, classified material, institutional secrets,
content marked for redaction — must be processed exclusively by
offline agents running on local hardware. No sensitive content may
traverse a network, enter an API call, or leave the operator's
machine. This law cannot be overridden by any subsequent legislation,
precedent, amendment, or operator instruction. It outranks Law 0 for
this specific scope. A single leak is irreversible.

## LAW-V — Remember before you act

Before executing any search, verification, or computation, an agent
must check in order: (a) the constitution for governing law, (b) the
precedent registry for prior rulings, (c) the verification memory
for cached results, (d) the run objectives for alignment. Act on
the first match found. Only when all four are silent may the agent
proceed with a novel action — and that action's outcome must be
recorded for future consultation.

## LAW-VI — Structure is earned, not assumed

All organizational structure below the Top Orchestrator emerges from
identified work. Agents form task forces by drafting charters.
Charters require constitutional approval from the Top Orchestrator,
which checks against existing legislation. If the constitution is
silent on the proposed pattern, the Top Orchestrator escalates to
the operator. Approved charters become task force laws upon
dissolution. No structure persists beyond its purpose — a task force
with no remaining work must dissolve. No agent may invent work to
justify its existence.

---

## Part II — AGENTS

## Agent registry

Every agent has a fixed identity: a name, a capability set (DOES),
a boundary set (DOES NOT), and a model assignment. The registry is
the source of truth for Law II enforcement.

Store in config/agent_registry.json.

### The 13 agents

| Agent | DOES | DOES NOT | Model |
|-------|------|----------|-------|
| PROCESSOR | Extract, draft, compile — the primary content worker | Verify its own work, override other agents, correct source data | Claude API |
| VERIFIER | Cross-check outputs against source documents, flag divergence | Fix problems (only report), search the web, draft content | GPT-4o |
| FACT_CHECKER | Extract verifiable claims, search external sources, produce factual verdicts | Judge procedures, draft content, check style, correct source | GPT-4o + web |
| PRACTICE_AUDITOR | Check procedures against current best practice, flag anti-patterns | Verify raw facts, draft content, assess legal basis | GPT-4o + web |
| LEGAL_ANALYST | Assess legal basis, evaluate precedent, analyze regulatory framework | Draft correspondence, make policy judgments, search the web independently | Claude API |
| STYLE_GUARDIAN | Enforce linguistic register, check style consistency, build register profiles | Change content (only style), draft, verify facts | Qwen local |
| ARCHIVIST | Index documents, establish chronology, maintain reference chains | Draft, analyze, recommend | Claude API |
| INST_FINDER | Map topics to institutions, build institution registries | Draft correspondence, make policy judgments | Claude API |
| CITATION_RESOLVER | Build cross-document reference graphs, map citation chains | Interpret citations (that is PROCESSOR), search external | Claude API |
| SPEECH_ACT_TAGGER | Classify pragmatic intent of utterances, build speech act taxonomy | Make policy judgments from speech acts | Claude API |
| REDACT_CLERK (T1-T2) | Apply tier 1-2 redaction (pattern-based PII, named entities) | Add content, make judgment calls on borderline cases | Qwen local |
| REDACT_AUTHORITY (T3-T4) | Review and approve redaction decisions, adversarial re-identification testing | Draft, search, verify facts | Qwen local |
| REDACT_GATE (T5) | Final existential gate — can any output be reconstructed to reveal redacted content? | Any function other than binary pass/fail on output safety | Qwen local |

### Agent activation

Not every run activates every agent. During the situation assessment
phase, agents self-assess whether they have work to do. Agents with
nothing to contribute go dormant — they produce no output and consume
no tokens. The Top Orchestrator confirms activation based on the
agent proposals.

### Adding agents

The registry is extensible. To add a new agent:
1. Define it in config/agent_registry.json with name, DOES, DOES NOT
2. Assign a model
3. Add its output schema to config/agent_contracts.json (agent_wrapper.AgentWrapper
   drives every agent by its registry name — there is no per-agent code file)
4. Log as a DELTA
5. Never combine it with an existing agent — if the role is distinct
   enough to need an agent, it stays separate

---

## Part III — HIERARCHY AND GOVERNANCE

## Top Orchestrator

The Top Orchestrator is the sole interface between the swarm and
the operator. It does not draft, verify, search, or perform any
agent function. It is implemented as pure Python logic — not an
LLM call. Its responsibilities:

- Open deliberation rounds
- Evaluate proposed task force charters against the constitution
- Approve or escalate task force formation
- Route escalations through the decision chain
- Enforce budget limits
- Produce the run summary
- Record new legislation from operator decisions

When task forces exist, the Top Orchestrator communicates through
Task Supervisors, not directly with agents. When no task forces
exist, it manages all agents directly.

## Task supervisors

When a task force forms, the member whose core capability is most
central to the task force's mission becomes its Task Supervisor.
The Top Orchestrator confirms the election. The Task Supervisor:

- Coordinates work within the group
- Communicates with the Top Orchestrator on behalf of the group
- Applies the constitution within the group's scope
- Reports completion and requests dissolution

A Task Supervisor has no authority outside its task force. It is
not a separate entity — it is an agent with an additional role.

## Decision chain

No entity may consult the operator without first consulting the
constitution. The chain is:

1. Agent checks constitution + precedents + memory + run objectives
2. If resolved: agent acts. No escalation.
3. If unresolved and in a task force: escalate to Task Supervisor
4. Task Supervisor runs the same four checks
5. If unresolved: escalate to Top Orchestrator
6. Top Orchestrator runs the same four checks
7. If unresolved: flag to operator
8. Operator decides. Decision becomes new legislation.

Skipping a level is a constitutional violation.

---

## Part IV — CONSTITUTION ENGINE

## The four layers of legislation

The constitution has four layers, in order of authority:

1. **Seed laws** (Law 0 through Law VI): Foundational. Immutable.
   Only exception: Law IV outranks Law 0 for data sovereignty.

2. **Task force laws**: Codified from successful task force charters.
   Govern how agents may self-organize. Grow with every novel task
   force pattern approved by the operator.

3. **Precedents**: Case law from resolved disputes and operator
   decisions. Govern how agents handle specific decision types.

4. **Operator amendments**: Direct operator rules — domain-specific
   instructions, project preferences, behavioral overrides.

## Constitution file

```json
{
  "seed_laws": [
    {
      "id": "LAW-0",
      "title": "Operator sovereignty",
      "text": "...",
      "immutable": true
    }
  ],
  "task_force_laws": [],
  "precedents": [],
  "amendments": []
}
```

Location: config/constitution.json

## Constitution API

```python
class Constitution:
    def check(self, situation: dict) -> CheckResult:
        """Check all four layers for a governing rule.
        Returns RESOLVED with the rule, or UNRESOLVED."""

    def add_precedent(self, precedent: dict) -> None:
        """Record an operator decision as case law."""

    def add_tf_law(self, charter: dict, learnings: dict) -> None:
        """Codify a dissolved task force charter as law."""

    def add_amendment(self, amendment: dict) -> None:
        """Record a direct operator rule."""

    def match_tf_law(self, charter: dict) -> MatchResult:
        """Check if a proposed charter matches existing TF law.
        Returns match confidence 0.0-1.0 and the matching law."""
```

---

## Part V — EMERGENT TASK FORCES

## Charter schema

When agents identify shared work during deliberation, they draft a
charter — a founding document for the task force:

```json
{
  "id": "TF-{run_date}-{sequence}",
  "mission": "What this task force exists to accomplish",
  "members": [
    {"agent": "AGENT_NAME", "role_in_tf": "description"}
  ],
  "supervisor": "AGENT_NAME",
  "supervisor_rationale": "Why this agent leads",
  "division_of_labor": "Who does what, no overlaps",
  "internal_protocol": "How members coordinate",
  "completion_criteria": "When is the work done",
  "dissolution_trigger": "What causes dissolution",
  "proposed_by": "AGENT_NAME",
  "confirmations": ["AGENT_NAME", "..."]
}
```

## Formation protocol

1. During deliberation, agents read each other's proposals and
   identify dependencies and shared work.
2. Any agent drafts a charter and posts CHARTER_PROPOSE to
   the Top Orchestrator. Named members must CONFIRM or REJECT.
3. Top Orchestrator evaluates the charter:
   a. Law VI: is this emergent from identified work? Not invented?
   b. Law II: does the division of labor respect agent boundaries?
   c. Existing TF-laws: does a matching pattern exist?
      - Confidence > 0.8: auto-approve per existing law
      - Confidence 0.5-0.8: approve, flag for operator review
      - No match: constitution silent — escalate to operator
   d. Any conflicts with existing laws or precedents?
4. Approved: CHARTER_APPROVE on bus. Task force operates on
   scoped channel. Denied: CHARTER_DENY with reason.

## Charter amendment during execution

If a task force discovers its charter is insufficient mid-run,
the Task Supervisor proposes an amendment. Same approval flow:
check constitution, escalate if silent.

## Dissolution and law codification

When a task force completes its work:
1. Task Supervisor posts DISSOLVE with completion report
2. Top Orchestrator confirms dissolution
3. Charter guidelines are codified as a task force law:
   pattern, division of labor, protocol, learnings, reuse count
4. TF-law added to constitution.json
5. Next matching charter auto-approves

---

## Part VI — MESSAGE BUS

## Implementation

The bus is a JSONL file at the run's logs/agent_bus.jsonl
(output/runs/<UTC-timestamp>__<run-id>/logs/agent_bus.jsonl; Part XXVII §A).
One JSON line per message. Append-only. Never truncated, never
edited. This is the permanent audit trail.

## Message schema

```json
{
  "timestamp": "ISO-8601",
  "sender": "AGENT_NAME",
  "sender_role": "agent | supervisor | orchestrator | operator",
  "recipient": "AGENT_NAME | TF_ID | BROADCAST | ORCHESTRATOR | OPERATOR",
  "channel": "main | tf_{id} | escalation",
  "type": "PROPOSE | REQUEST | OFFER | CHALLENGE | INFORM | YIELD | BLOCK | CONFIRM | ESCALATE | MEMORY_HIT | DEDUP_ALERT | CHARTER_PROPOSE | CHARTER_APPROVE | CHARTER_DENY | DISSOLVE | PRECEDENT_APPLIED | LAW_CREATED",
  "body": "structured content",
  "constitution_check": {
    "laws_consulted": ["LAW-II", "PREC-003"],
    "result": "RESOLVED | UNRESOLVED",
    "resolution": "description if resolved"
  }
}
```

Every message includes a constitution_check field showing which
laws the sender consulted. A message without it is a protocol
violation.

## Context assembly for agent calls

Agents do not read the raw bus. They receive a curated context
package assembled by the orchestrator:

1. Full constitution text (~800-2000 tokens depending on growth)
2. Run objectives (~100 tokens)
3. Relevant precedents filtered by domain + claim types (~200-500)
4. Task force charter if applicable (~200)
5. Sliding window of recent relevant bus messages (~1000-2000)
6. Rolling summary of older messages (~300)
7. The actual work payload (document chunk, draft, claims)

Token budget per backend:
- Claude (200K): governance ~3000, bus ~2000, work ~8000
- GPT-4o (128K): governance ~2000, bus ~1500, work ~6000
- Qwen 7B (32K): Laws II and IV only ~200, no bus, work only.
  Qwen does style/redaction — no deliberation participation.

---

## Part VII — MULTI-MODEL ARCHITECTURE

## Model routing

| Role | Model | Rationale |
|------|-------|-----------|
| Content production agents | Claude API | Primary reasoning |
| Verification/audit agents | GPT-4o | Cross-family audit (Law III) |
| Privacy-critical agents | Qwen 7B local | Offline only (Law IV) |
| Top Orchestrator | Python logic | No LLM, deterministic |
| Audit synthesis | Claude API | Merge reports, single voice |

## Structured output contracts

All agents produce structured JSON, not free-form prose. This
solves cross-model coherence. Store schemas in
config/agent_contracts.json.

**Canonical inter-agent envelope (INFRA-037).** Every agent's structured output
is ONE wrapper, carried as `body.payload` inside the message bus's (unchanged)
transport envelope: `{"agent": str, "doc_id": str, "items": [ flat item, ... ]}`.
`items` is always a list (a singleton is a one-element list; nothing to report is
`[]`; never a bare list or bare dict). Each item is FLAT — scalars or arrays of
scalars only, no nested objects (structure is expressed as MORE items) — and
carries the per-item core fields `ref`, `kind`, `confidence` (optional `verdict`),
the flat citation array `ref_ids`, plus the runtime-stamped `item_id`/`revision`/
`ts`. A consumer reads the current value of an item by selecting the highest
`revision` per `item_id` (tie-break latest `ts`). The per-agent schemas below
define each agent's flat item fields (carried inside `items[]`).

```json
{
  "FACT_CHECKER": {
    "claim_id": "string",
    "original_text": "string",
    "verdict": "CONFIRMED | DISPUTED | OUTDATED | UNVERIFIABLE",
    "evidence": "string",
    "source_url": "string | null",
    "confidence": "float 0-1",
    "search_method": "string"
  },
  "VERIFIER": {
    "paragraph": "int",
    "finding": "MATCH | DIVERGENCE | ADDITION | OMISSION",
    "original": "string",
    "output": "string",
    "severity": "low | medium | high",
    "reasoning": "string"
  }
}
```

Final prose synthesis is always done by a single model (Claude)
to ensure consistent voice in deliverables.

## API batching

Agents sharing a backend are batched into a single API call
during deliberation rounds. One Claude call carries multiple
agent prompts separated by role markers. Same for GPT-4o.
Cloud calls (Claude + GPT) run in parallel via asyncio.gather()
alongside local Qwen calls.

## Prompt caching (INFRA-036)

Both cloud call paths reuse a cached stable prompt prefix to cut input-token
cost. Every agent prompt is assembled stable-prefix-first: a STABLE PREFIX
(agent identity + DO/DO-NOT + directives + output contract + constitution +
compiled conventions) that is identical across that agent's calls within a run,
followed by a DYNAMIC SUFFIX (run objectives, precedents, retrieved passages,
recent bus, work payload).

- **Claude path — EXPLICIT.** call_claude marks the end of the stable prefix with
  `cache_control: {type: ephemeral}` (5-minute TTL — a run fires its agent calls
  back-to-back within minutes, so the 5-min window covers reuse without the 2x
  one-hour write premium). Cache reads bill at 0.1x input; the 5-min write at
  1.25x. Anthropic requires an EXACT prefix match, so the prefix must contain NO
  dynamic content.
- **GPT path — STRUCTURE-AND-LOG.** OpenAI caches automatically with no
  cache_control; call_gpt does NOT add one. It only structures the prompt
  stable-prefix-first so OpenAI's automatic prefix cache catches, then verifies it
  via logging.
- **Measured, not trusted.** The cost tracker logs each provider's cache fields
  per call (Anthropic `cache_creation_input_tokens` / `cache_read_input_tokens`;
  OpenAI `prompt_tokens_details.cached_tokens`), defaulting to 0 when absent. A
  silent provider-side cache loss shows up as the cached count dropping to zero in
  the cost log, not hidden.
- **THE RULE:** no dynamic content (timestamp, run id, per-call text, retrieved
  passages, bus) may enter the stable prefix — doing so changes the prefix per
  call and drops the hit rate to near zero. Caching only takes effect above each
  model's minimum cacheable prefix size; a small-prompt agent that does not meet
  it simply does not cache. Never pad to reach the threshold.

## Hardware constraints

Target hardware: NVIDIA RTX 3070 Ti (8GB VRAM), Windows, py -3.9.

- Qwen 2.5-7B at nf4: 5.9GB VRAM, stays loaded throughout
- EasyOCR: 0.5GB, loaded on demand (unloads Qwen temporarily)
- Sentence transformer: 0.1GB, coexists with Qwen
- single_model_at_a_time: true on GPU
- empty_cache_between_models: true
- Cloud calls: network only, covered by subscriptions
- Top Orchestrator + bus + constitution: pure Python, ~50MB RAM
- API keys: stored in local config.py outside repo (never committed)

---

## Part VIII — SEARCH STACK

## Free search cascade

1. **Discovered APIs** — check durable/learnings/discovered_apis.json first.
   If a known free API serves this institution, use it.
2. **Direct site fetch** — for claims referencing known institutions
   (UN, WTO, World Bank, ISO), HTTP fetch the official page.
3. **DuckDuckGo** — via duckduckgo-search package. No API key,
   no limits. The workhorse.
4. **Brave Search API** — free tier (2000/month). Fallback when
   DDG returns fewer than 2 relevant results.
5. If all insufficient: verdict UNVERIFIABLE (not CONFIRMED).

## Claim classifier

Before searching, GPT-4o extracts and classifies verifiable claims:

```json
{
  "claim_id": "C-007",
  "text": "Turkey's GDP grew 4.5% in 2025",
  "type": "statistic",
  "entities": ["Turkey", "GDP"],
  "temporal": true,
  "searchable": true,
  "dedup_key": "turkey_gdp_2025",
  "query_plan": {
    "primary": {"engine": "api", "url": "api.worldbank.org/..."},
    "fallback": {"engine": "ddg", "query": "Turkey GDP growth 2025"}
  }
}
```

Claim types: statistic, date_event, attribution, status,
legal_regulatory, institutional, procedure, standard_ref,
convention, currency, anti_pattern.

Claims marked searchable: false skip search. Claims sharing
a dedup_key are searched once.

## API discovery

During search, the router watches for free API patterns. When found:
1. Log to durable/learnings/discovered_apis.json as PENDING
2. Post API_DISCOVERED to bus
3. Orchestrator escalates to operator for approval
4. If approved: becomes top-priority tier for that institution
5. Safety: only free APIs, only from official pages, operator
   approves each one, health check before use

---

## Part IX — VERIFICATION CACHE LAYER

## Two durable tiers

Both tiers live under the protected durable/ tree (INFRA-030). The numbering
keeps tier-2 and tier-3 (the prior within-run tier-1 session cache was retired by
INFRA-034: it was opened but never written).

### Tier 2 — Cross-run project cache
Location: durable/cache/verification_cache.json
Persists across runs. Claims stored with verdict, source,
date, and TTL.

TTL by claim type:
- legal/regulatory, status: 365 days
- institutional, convention: 180 days
- standard_ref: 90 days
- statistic, date_event: 30 days
- attribution: 60 days

Expired claims are re-verified on next encounter.

### Tier 3 — Cross-project global cache
Location: durable/global/verification_cache_global.json
Shared across Shimmer projects (if multiple exist).

## Verification cache protocol (implements Law V)

Before any search: check tier 2 (project), then tier 3 (global). First valid
(within-TTL) hit wins. Post MEMORY_HIT to bus. Store new results
at all applicable tiers.

---

## Part X — LEARNING LOOP

## Search strategy learnings

Location: durable/learnings/search_strategy_learnings.json

Tracks which query strategies succeed per claim type. If
site:worldbank.org fails but site:imf.org works for GDP data,
the routing table updates automatically.

## DELTA proposals from audit

After each run, the audit synthesis identifies failure patterns
and proposes DELTAs:
- Consistent DISPUTED claims from a source type → reduce TTL
- Repeated convention violations → add to project rules
- Repeated escalation patterns → propose constitutional amendment

All proposals go through the operator (Law 0). No silent
self-modification.

## Adaptive asset spawning

When a project runs for the first time with empty reference/ and
no config assets, the pipeline discovers and generates:

a. Language, institutions, format conventions → situational_awareness.md
b. Linguistic register identity → durable/reference/LINGUISTIC_IDENTITY.md
c. Citation conventions → durable/learnings/citation_convention.json
d. Speech act taxonomy → durable/learnings/speech_acts_taxonomy.json
e. Institution registry → durable/learnings/institution_registry.json
f. Per-run spawn statistics → durable/learnings/spawn_log.jsonl (durable runtime
   log; gitignored). adaptive_spawn does NOT write prompts/project_rules.md — that
   file is the tracked operator/DELTA rules template.

After the first run, the project has everything it needs.
No manual seeding required.

---

## Part XI — PIPELINE LIFECYCLE

```
BOOT
  Load constitution
  Load verification cache (durable tiers 2-3)
  Load search strategy learnings
  Load discovered APIs
  Initialize message bus
  Initialize Top Orchestrator
  Deprecated-model gate + family-key self-resolution (per-agent live model check,
    INFRA-026). The tracked registry (config/agent_registry.json) stores each
    agent's model as a FAMILY+VERSION key only (e.g. claude-haiku-4-5); concrete
    dated ids (e.g. claude-haiku-4-5-20251001) are NEVER written to a tracked
    file. At run start each key is resolved against the provider's live model
    list, by exact family+version prefix, on both the Claude producer and GPT
    auditor sides:
      - exactly one live id matches -> bind to that concrete id automatically
        (resolution, not a swap); the binding is in-memory only and logged to the
        run record (output/runs/<run>/logs/model_bindings.json);
      - the key is itself a live id -> use as-is;
      - ZERO live ids match (gone/deprecated), OR more than one snapshot matches
        and none is exact (ambiguous) -> the firewall holds: do NOT auto-pick;
        STOP and require explicit operator approval / a pinned snapshot. No silent
        swap to a different model, ever.
  Qwen-required startup gate (INFRA-035): confirm the local Qwen redaction
    backend is reachable/configured BEFORE any agent runs. If it is not, REFUSE
    the run — unless the operator waives redaction for THIS run only via
    --no-redaction-override (and an interactive confirmation when interactive),
    which is logged to the governance ledger (durable/governance/, with timestamp
    + run id). Pre-run the gate verifies torch+transformers importable + a
    qwen_local model id configured; the actual model load is verified at first
    redaction call. GPU absence is a SOFT printed reminder only — never a blocker,
    never recorded.

PHASE 1 — SITUATION ASSESSMENT
  Orchestrator broadcasts input to all agents.
  Each agent assesses and posts PROPOSE with constitution_check.
  Agents with no work go dormant.

PHASE 2 — TASK FORCE EMERGENCE
  Agents identify clusters and draft charters.
  Members CONFIRM or REJECT.
  Orchestrator evaluates charters against constitution.
  Approved forces begin operating. Others work solo.

PHASE 3 — PARALLEL EXECUTION
  Task forces on scoped channels. Solo agents under orchestrator.
  Independent groups run in parallel (asyncio).
  Mid-execution: agents can BLOCK or trigger re-negotiation.
  Orchestrator checks bus between every call for interrupts.

PHASE 4 — CONTENT PRODUCTION
  PROCESSOR drafts with all gathered context.
  STYLE_GUARDIAN checks register.
  (Redaction is a dedicated final pass — see REDACTION below.)

PHASE 5 — VERIFICATION AND AUDIT
  VERIFIER (GPT-4o): output vs source consistency.
  FACT_CHECKER (GPT-4o + web): external claim verification.
  PRACTICE_AUDITOR (GPT-4o + web): best practice compliance.
  Structured JSON verdicts.

PHASE 6 — SYNTHESIS
  Claude merges structured findings into:
    audit_synthesis.md, fact_check_report.md,
    practice_audit_report.md, verification_report.md
  Escalation flags block output until operator sign-off.

PHASE 7 — LEARN
  Task forces dissolve. Charters become TF-laws.
  Verification cache updated.
  Search strategy learnings updated.
  Discovered APIs logged (pending approval).
  DELTAs proposed from audit patterns.
  Constitution updated with new legislation.

REDACTION — FINAL PASS, ALWAYS RUNS (pipeline phase 9; after synthesis, before persist; LAW-IV)
  The three Qwen redaction agents (REDACT_CLERK proposes tier 1-2,
  REDACT_AUTHORITY approves tier 3-4 + adversarial test, REDACT_GATE final
  pass/fail) screen each document's deliverables at the output boundary and
  decide ADAPTIVELY what, if anything, to redact. An approved + passed redaction
  is applied THROUGH the amendments master and the md/docx are re-rendered from
  it, so the formats stay consistent (Part XXVII §E). Run-scoped only — never
  touches durable/. Every decision is posted to the run bus. Degrades safely if
  the local Qwen backend is unreachable (skip-with-warning, no crash).

PHASE 8 — PERSIST
  All learnings written to config.
  Bus log finalized with run summary.
  Next run starts with richer constitution.
```

---

## Part XII — DIRECTORY STRUCTURE

```
project_shimmer/
  genesis.md                          ← THIS FILE
  CLAUDE.md                           ← project entry point
  config/
    constitution.json                 ← seed laws + emergent legislation (governance)
    agent_registry.json               ← agent definitions (DOES/DOES NOT/model)
    agent_contracts.json              ← structured output schemas per agent
    gpu_config.json                   ← hardware configuration
    convention_registry.json          ← compiled CONV-* rules (regenerated each run)
    review_scope.json                 ← operator cutoff config
  durable/                            ← PROTECTED class (Part XXVII §B / INFRA-030);
                                        outside any auto-cleaned tree; never wiped
                                        by per-run cleanup. Survives reset by location.
    cache/
      embedding_store.pkl             ← semantic store (tier-2 retrieval)
      verification_cache.json         ← cross-run claim cache (tier 2)   [resettable]
    global/
      verification_cache_global.json  ← cross-project cache (tier 3)     [survives reset]
    learnings/
      institution_registry.json       ← auto-built from documents        [resettable]
      citation_convention.json        ← auto-discovered citation rules    [resettable]
      speech_acts_taxonomy.json       ← auto-built pragmatic taxonomy     [resettable]
      search_strategy_learnings.json  ← query routing optimization        [resettable]
      discovered_apis.json            ← free APIs found during search     [resettable]
      document_dates.json             ← resolved document dates           [resettable]
    reference/
      LINGUISTIC_IDENTITY.md          ← auto-generated register profile   [resettable]
      situational_awareness.md        ← auto-generated domain profile     [resettable]
    governance/
      model_approvals.json            ← operator model-approval ledger   [survives reset]
      constitution_guard_log.jsonl    ← amendment-guard decision log     [survives reset]
  input/                              ← drop documents here
  output/                             ← DISPOSABLE per-run artifacts (INFRA-032)
    runs/
      <UTC-timestamp>__<run-id>/      ← one folder per run; runs never overwrite
        deliverables/                 ← final processed outputs (per doc_id key)
        audit/
          reference_index.json        ← REF-* index (per-run, regenerated)
          audit_synthesis.md
          delta_proposals.json
          contract_violations/        ← <agent>_<ts>.txt raw outputs
        logs/
          agent_bus.jsonl             ← this run's message bus
          cost_tracker.{jsonl,json}
          run_summary_{date}.md
  reference/                          ← static operator references (learned
                                        register/awareness assets now live under
                                        durable/reference/, see above)
  prompts/
    project_rules.md                  ← operator rules + approved project DELTAs (tracked template)
  scripts/
    orchestrator.py                   ← Top Orchestrator
    constitution.py                   ← constitution engine
    message_bus.py                    ← bus read/write/query
    bus_reader.py                     ← context package assembly
    search_router.py                  ← DDG/Brave/API cascade
    verification_cache.py             ← three-tier verification cache
    claim_classifier.py               ← claim extraction and typing
    agent_wrapper.py                  ← base class for agent API calls
    agents/                           ← one file per agent wrapper
      processor.py
      verifier.py
      fact_checker.py
      practice_auditor.py
      legal_analyst.py
      style_guardian.py
      archivist.py
      inst_finder.py
      citation_resolver.py
      speech_act_tagger.py
      redact.py
```

## Directory discipline

- All outputs go to output/ subdirectories
- All config goes to config/
- All learned reference material goes to durable/reference/ (the old top-level
  reference/ was retired in the durable refactor)
- No loose files at project root except genesis.md, CLAUDE.md, README.md,
  requirements.txt, .gitignore, project_shimmer_cover.png, the external-key
  pointer .env_path, and the operator setup launcher setup.bat
- No scripts in config/, no config in scripts/
- No output files in input/, no input files in output/
- No hardcoded paths — everything relative to project root
- No domain-specific content in scripts/ — domain knowledge
  lives exclusively in config/ and durable/
- No spaces in paths. No unicode in folder names.
- English only for all code and config file names.
- Per-run isolation, the durable-vs-disposable firewall, naming, format-master,
  and separation-of-concerns rules are governed in full by Part XXVII
  (Pipeline Hygiene Standard), which is the single source of truth for file
  organization across the entire pipeline. Where this list and Part XXVII
  overlap, Part XXVII governs.

---

## Part XIII — DEPENDENCIES

## Python (py -3.9, Anaconda)

```
# Core (likely already installed)
torch, transformers, bitsandbytes, sentence-transformers, easyocr

# New for swarm
pip install duckduckgo-search --break-system-packages
pip install openai --break-system-packages
pip install anthropic --break-system-packages

# Optional
pip install brave-search --break-system-packages
```

## API keys (in local config.py, never committed)

```python
ANTHROPIC_API_KEY = "..."    # Claude Max subscription
OPENAI_API_KEY = "..."       # ChatGPT Pro / OpenAI API
BRAVE_API_KEY = "..."        # Optional, free tier
```

The external `config.py` lives **outside** the repo. `load_api_keys`
(`scripts/agent_wrapper.py`) resolves it at runtime in this fixed order, with no
absolute path or username baked into any tracked file:

1. `$SHIMMER_CONFIG_PATH` — explicit override (a `config.py` file, or a directory
   containing one); wins if set and the target exists.
2. `../api_keys/config.py` — sibling folder one level above the repo root.
3. `.env_path` — legacy repo-root pointer holding a relative path (fallback).

The reader copies out **API-key values only** (fixed allowlist); any `model = …`
line in that file is ignored and can never influence model selection
(`config/agent_registry.json` owns model choice). `.gitignore` blocks
`**/config.py` and `api_keys*/`, so neither the config nor the external keys
folder can ever be tracked or pushed.

## Operator setup tool (setup.bat -> scripts/preflight.py)

**Install the base dependencies first (manual, before `setup.bat`):**

```
py -3.9 -m pip install -r requirements.txt
```

`setup.bat` does NOT install the base dependencies. It only ensures the two
optional libraries (`beautifulsoup4`, `langdetect`) are importable; the base set
in `requirements.txt` must be installed manually with the command above first.

**First-time setup can take a while — this is expected, not a fault.** Installing
the base dependencies and pulling the Qwen model weights (several gigabytes,
downloaded on the first run that needs redaction) happen once, on first setup /
first run, and can take several minutes or longer. Do not interrupt them; let each
finish. Subsequent runs reuse the installed packages and cached weights.

`setup.bat` at the repo root is a thin double-click launcher: it runs
`scripts/preflight.py` and pauses so the operator reads the report. ALL logic
lives in the Python module (a future `setup.sh` / `setup.command` is the same
thin wrapper). Preflight, in order: (a) locates/loads the config per the order
above — scaffolding a clearly-marked template and failing cleanly if none is
found, never fabricating or printing key values; (b) installs `beautifulsoup4` +
`langdetect` if missing; (c) **reuses** the INFRA-035 Qwen reachability gate
(`redaction_gate.qwen_backend_status`), deploy-if-missing, and — if still
unreachable — requires a per-run operator override logged to the governance
ledger rather than silently bypassing; (d) **reuses** the same gate's GPU
soft-check (warn-only, never blocks, never records); (e) queries each provider's
live `models.list()` (**reuses** `model_registry`), reports the exact Claude
producer and GPT auditor ids, confirms none are deprecated and that `gpt-4o` is
present, and lists any stronger reasoning-grade auditor as an approval candidate
**without swapping**. It never runs the paid pipeline and ends with an honest
bill of health separating what is ready from what stays unproven until a paid run.

---

## Part XIV — BUILD SEQUENCE

## Session 1: Foundation (3-4 hours)

Build in order:

1. Create the full directory structure from Part XII
2. Write config/constitution.json with the seven seed laws
3. Write config/agent_registry.json with the 13 agents
4. Write config/agent_contracts.json with output schemas
5. Write config/gpu_config.json (from existing)
6. Write CLAUDE.md (project entry point)
7. Write prompts/project_rules.md (clean template)
8. Build scripts/constitution.py — Constitution class
9. Build scripts/message_bus.py — MessageBus class
10. Build scripts/bus_reader.py — context package assembly
11. Build scripts/agent_wrapper.py — base AgentWrapper class
     with call_claude(), call_gpt(), call_qwen(), post_to_bus(),
     check_constitution()
12. Build scripts/orchestrator.py — TopOrchestrator class
     with run(), deliberation_round(), evaluate_charter(),
     escalate_to_operator()
13. (No per-agent files: agent_wrapper.AgentWrapper drives every agent by its
    registry name, using config/agent_registry.json + config/agent_contracts.json)

Test: place a single test document in input/. Run orchestrator.
Agents should assess, propose, and execute sequentially. Bus
should log everything with constitution checks.

## Session 2: Search + memory + task forces (2-3 hours)

1. Build scripts/search_router.py — DDG/Brave/API cascade
2. Build scripts/claim_classifier.py — claim extraction and typing
3. Build scripts/verification_cache.py — three-tier cache with TTL
4. Add charter proposal/approval/dissolution flow to orchestrator
5. Add task force formation and scoped channels to bus
6. Add TF-law codification to constitution engine
7. Initialize empty JSON files: verification_cache,
   discovered_apis, search_strategy_learnings

Test: place a document with statistics in input/. Watch agents
form a task force, search with dedup, cache results in memory.

## Session 3: Parallel execution + monitoring (2-3 hours)

1. Add asyncio parallel execution to orchestrator
2. Add mid-execution interrupt handling
3. Add charter amendment flow
4. Build colorized terminal log viewer (formatted JSONL tail)
5. Add run_summary generation
6. Add DELTA proposal logic in audit synthesis
7. Add adaptive asset spawning (LINGUISTIC_IDENTITY,
   institution_registry, speech_acts from documents)

Test: place 3+ documents in input/. Watch task forces form
and execute in parallel, agents coordinate on the bus,
precedents get created from operator decisions.

---

## Part XV — VERIFICATION CHECKLIST

Before declaring complete, ALL must PASS:

| # | Check |
|---|-------|
| 1 | Directory structure matches Part XII exactly |
| 2 | config/constitution.json has 7 seed laws, valid JSON |
| 3 | config/agent_registry.json has 14 agents with DOES/DOES NOT/model |
| 4 | config/agent_contracts.json has output schemas for all agents |
| 5 | constitution.py loads and check() works against all 4 layers |
| 6 | constitution.py match_tf_law() returns confidence scores |
| 7 | message_bus.py post/read/query/summarize all work |
| 8 | bus_reader.py assembles correct context per backend |
| 9 | agent_wrapper.py can call Claude, GPT-4o, and Qwen |
| 10 | orchestrator.py runs a full deliberation round |
| 11 | orchestrator.py evaluates a charter against constitution |
| 12 | orchestrator.py escalates when constitution is silent |
| 13 | Task force formation works end-to-end |
| 14 | Charter dissolution codifies TF-law in constitution |
| 15 | search_router.py executes DDG search |
| 16 | claim_classifier.py extracts and types claims |
| 17 | verification_cache.py checks all three tiers with TTL |
| 18 | Agent output matches contract schema (valid JSON) |
| 19 | Every bus message has constitution_check field |
| 20 | run_summary generates with correct statistics |
| 21 | No hardcoded paths in scripts/ |
| 22 | No domain-specific terms in scripts/ |
| 23 | API keys load from config.py, not hardcoded |
| 24 | Qwen agents receive Laws II and IV only (no bus history) |
| 25 | asyncio parallel execution runs independent groups |
| 26 | Mid-execution BLOCK pauses affected agents |
| 27 | Adaptive asset spawning creates LINGUISTIC_IDENTITY.md |
| 28 | input/ exists and accepts documents |
| 29 | CLAUDE.md points to this genesis file |
| 30 | Full pipeline completes on a test document without crash |

The implemented gate (`scripts/verify_session1.py`) runs **41** checks
total, not 30: check 00 (`ast.parse` smoke over all modules) + checks
1-30 above + checks 31-37 (Part XVIII Section F) + check 38 (embedding
store build/query, Part XXI) + checks 39-40 (canonical inter-agent
envelope invariant + highest-revision selection, INFRA-037).
Arithmetic: 1 + 30 + 7 + 1 + 2 = 41.

Print the table with Status and Detail columns. ALL must be PASS.

---

## Part XVI — WHAT THIS SPEC DOES NOT COVER

Deliberate non-goals for this genesis. May become future work
after the swarm has been operational for several runs:

- VS Code live dashboard (terminal viewer for now)
- Sophisticated UI for operator escalations (terminal prompts)
- Automated DELTA enactment (always requires operator approval)
- Fine-tuning models on pipeline outputs
- Persistent agent memory between runs (agents start fresh;
  the constitution and verification memory persist)
- Integration with external project management tools
- Web interface for the Shimmer control panel
- Multi-user support

---

## Part XVII — LESSONS CARRIED FORWARD

These lessons come from prior work. They are encoded in the
architecture, not as dependencies:

- DOMAIN PURGE: The framework contains zero domain-specific terms.
  Domain knowledge lives exclusively in config/ and reference/,
  spawned from whatever documents are placed in input/.

- DUAL-MODEL INTEGRITY: Drafting and verification use different
  model families. This is not a guideline — it is Law III.

- ADAPTIVE SPAWNING: First run with empty config/ bootstraps
  everything from the documents. No manual seeding.

- AGENT DISCIPLINE: Agents have fixed roles. Blurring boundaries
  is not initiative — it is malfunction. This is Law II.

- DIRECTORY DISCIPLINE: Every file has exactly one correct location.
  Misplaced files are bugs. (Codified in full by Part XXVII — Pipeline
  Hygiene Standard, including per-run isolation and the durable-vs-disposable
  firewall that protects cumulative learning.)

- IN-PLACE REDACTION: Sensitive content is handled by offline
  agents only. No copies, no backups of unredacted content.
  This is Law IV.

- SELF-MODIFYING ONTOLOGY: The system learns from operation through
  DELTAs — proposed behavioral changes that require operator
  approval. The constitution is the persistent form of this.

- OPERATOR PRIMACY: The pipeline proposes, the operator decides.
  No automated self-modification. This is Law 0.

## Part XVIII — GENESIS AMENDMENT: Convention-driven review architecture

# Append this to genesis.md after Part XVII.
# This amendment adds four capabilities to the Shimmer architecture:
#   A. Three-input-type model (context, operational, conventions)
#   B. Precision reference system (source-located citations)
#   C. Convention-driven review workflow
#   D. Amendment output format (tracked changes with referenced comments)
#
# No domain-specific content. No case-specific language.
# Every concept is defined at the meta level.
# The seven seed laws remain unchanged and govern everything below.

---

## A. Three-input-type model

### Rationale

The original genesis treats all documents in input/ identically.
In practice, documents serve three distinct roles in a review
workflow, and the pipeline must handle each differently.

### The three types

**Context inputs** teach the system about a domain. They are the
reference corpus from which the pipeline learns vocabulary,
institutional structures, citation patterns, and substantive
norms. The pipeline reads them but does not produce deliverables
for them. They feed adaptive spawning (Part X) and become the
knowledge base that agents reference during processing.

**Operational inputs** are the documents under review. These are
what the pipeline processes, evaluates, and produces deliverables
for. Each operational document receives the full treatment:
extraction, analysis, verification, convention review, and
amendment proposals.

**Convention inputs** define the institutional review framework.
They encode the operator's organization's standards: terminology
preferences, red-flag patterns, rephrasing guidelines, citation
and borrowing rules, structural expectations, and value-alignment
criteria. Convention inputs are binding rules that agents evaluate
operational documents against. They are not optional. A project
without conventions has no review criteria and cannot produce
amendment proposals.

### Directory structure (amends Part XII)

```
input/
  context/        <- domain learning corpus
  operational/    <- documents under review
  conventions/    <- institutional review framework
```

Replace the flat input/ directory with three subdirectories.
The pipeline refuses to run the convention review workflow
(Section C below) if input/conventions/ is empty.

### Supported input formats (INFRA-027)

All three input paths accept the same format family, extracted by one shared
utility (scripts/text_extract.py): .pdf, .docx, .html/.htm, .txt, .md, .rst,
.log, and .json. Every reader — the corpus/operational loader, the embedding
store (Part XXI), the convention parser (Section E), the date cascade
(Part XXIV), and adaptive spawn (Part X) — routes through this one extractor, so
the accepted family is identical everywhere and semantic retrieval embeds every
accepted format, not just PDF. Optional libraries (pypdf, python-docx,
beautifulsoup4) are imported lazily; a missing one degrades to a clear warning
for that format rather than a crash. A file whose extension is outside the
family is logged with a warning and skipped — never silently dropped. (The
Part XIX corpus-acquisition validator remains PDF-specific by design: it
guards files DOWNLOADED from the web, distinct from operator-supplied inputs.)

### How each type flows through the pipeline

Context inputs:
  - Read during BOOT by adaptive_spawn
  - Text extracted and indexed by ARCHIVIST
  - Used to build LINGUISTIC_IDENTITY, institution_registry,
    citation_convention, speech_acts_taxonomy, situational_awareness
  - Available to all agents as part of the reference/ assets
  - NOT processed through phases 3-8
  - Included in the reference index (Section B) so other agents
    can cite specific passages from context documents

Operational inputs:
  - Processed through the full pipeline (phases 1-8)
  - Each produces a deliverable in output/deliverables/
  - Evaluated against conventions during the review phase
  - Receive tracked-change amendment proposals

Convention inputs:
  - Parsed during BOOT into a structured convention registry
    at config/convention_registry.json
  - Each convention becomes a named, citable rule with an ID
  - Convention rules are injected into the context package of
    agents that perform evaluation (PRACTICE_AUDITOR, VERIFIER,
    STYLE_GUARDIAN, and the new AMENDMENT_DRAFTER)
  - Conventions are never modified by the pipeline. They are
    operator-supplied constants for the duration of a run.

### Convention registry schema

```json
{
  "schema_version": "1.0.0",
  "source_files": ["style_guide.md", "review_standards.pdf"],
  "conventions": [
    {
      "id": "CONV-001",
      "category": "terminology",
      "rule": "the rule text as parsed from source",
      "source_file": "style_guide.md",
      "source_location": "section 2, paragraph 3",
      "severity": "required | recommended | advisory",
      "action": "flag | rephrase | reject | annotate"
    }
  ]
}
```

Categories are not predefined. The parser discovers them from
the convention documents. Common categories include but are not
limited to: terminology, red_flags, rephrasing, citation_style,
structural, borrowing, value_alignment. The pipeline does not
constrain what categories exist. The conventions define them.

---

## B. Precision reference system

### Rationale

Current agent output includes evidence as free-text strings.
For a review deliverable to be credible, every finding must
cite the exact source: which document, which section, which
paragraph, which sentence. This is the "NotebookLM precision"
standard: if a comment says "this conflicts with convention X,"
the reader can trace it to the specific rule and the specific
passage in the operational document.

### Reference index

During processing, the pipeline builds a reference index at
output/audit/reference_index.json. Every passage that any agent
reads, cites, or evaluates gets an entry:

```json
{
  "ref_id": "REF-0042",
  "input_type": "context | operational | convention",
  "document_id": "doc_stem",
  "document_name": "original_filename",
  "location": {
    "page": 3,
    "paragraph": 7,
    "sentence": 2,
    "char_start": 4521,
    "char_end": 4698
  },
  "text_excerpt": "the exact quoted passage (max 200 chars)",
  "cited_by": ["FACT_CHECKER", "AMENDMENT_DRAFTER"],
  "first_indexed": "ISO-8601"
}
```

### How agents use references

When an agent produces a finding, it must include a ref_ids
field listing the reference index entries that support the
finding. The agent contract (Part VII) is extended:

Every agent contract gains an optional field:
  "ref_ids": "array of REF-* strings from reference_index.json"

For agents in the convention review workflow (Section C), this
field is required, not optional. A convention review finding
without a reference is a protocol violation.

### Reference builder

A new utility module scripts/reference_builder.py handles:
  - Splitting documents into paragraphs and sentences
  - Assigning stable reference IDs
  - Maintaining the index across pipeline phases
  - Looking up references by document, location, or text match

The reference builder is called during document loading (before
phase 1) and produces the initial index. Agents append to it
during processing when they identify new citable passages.

---

## C. Convention-driven review workflow

### Rationale

The current pipeline verifies factual accuracy (FACT_CHECKER)
and procedural compliance (PRACTICE_AUDITOR). It does not
evaluate operational documents against an operator-supplied
institutional framework. The convention review workflow adds
this capability as a new pipeline phase.

### New pipeline phase: PHASE 5.5 — Convention review

Inserted between PHASE 5 (verification) and PHASE 6 (synthesis).

For each operational document:

1. PRACTICE_AUDITOR receives the convention registry as part of
   its context package. It evaluates each section of the
   operational document against each applicable convention rule.
   For every match or violation, it produces a finding with:
   - The convention rule ID (CONV-*)
   - The reference ID of the flagged passage (REF-*)
   - A verdict: COMPLIANT | VIOLATION | AMBIGUOUS
   - The severity from the convention rule
   - A recommended action from the convention rule

2. STYLE_GUARDIAN receives the convention registry filtered to
   terminology, rephrasing, and borrowing categories. It evaluates
   linguistic compliance and produces findings in the same format.

3. Results from both agents feed into AMENDMENT_DRAFTER (new agent,
   see below) which produces the tracked-changes output.

### Context and operative summaries

After the convention review phase, but before the amendment
draft, the pipeline produces two summary documents:

**Context summary** (output/deliverables/{doc_id}__context_summary.md):
  A synthesis of what the context corpus establishes about the
  domain relevant to this operational document. Cites specific
  context documents and passages via reference IDs. Answers:
  "What does the reference corpus say about the topics this
  document addresses?"

**Operative summary** (output/deliverables/{doc_id}__operative_summary.md):
  A synthesis of what the operational document contains, structured
  by the convention categories. For each category, it lists what
  the document says and how it relates to the convention rules.
  Cites both operational and convention references. Answers:
  "What does this document do, and how does it align or conflict
  with our institutional standards?"

These summaries are produced by PROCESSOR (Claude, frontier tier)
with the full reference index and convention registry in context.

### Cutoff mechanism

The operator can specify a cutoff in the run objectives or in a
config file at config/review_scope.json:

```json
{
  "cutoff_type": "document_number | date | all",
  "cutoff_value": "3",
  "scope_note": "Produce summaries and amendments only for
                 documents after the 3rd in chronological order"
}
```

Documents before the cutoff are treated as additional context
(even if placed in input/operational/). Documents at or after
the cutoff receive the full review treatment including summaries
and amendment proposals. If cutoff_type is "all", every
operational document gets the full treatment.

This allows the operator to say: "the first N documents are
background reading; start the actual review from document N+1."

---

## D. Amendment output format

### New agent: AMENDMENT_DRAFTER

Added to the agent registry:

```json
{
  "AMENDMENT_DRAFTER": {
    "does": [
      "Compile findings from PRACTICE_AUDITOR, STYLE_GUARDIAN,
       VERIFIER, and FACT_CHECKER into a tracked-changes document",
      "Produce margin comments with precision references to
       conventions, context documents, and operational passages",
      "Propose rephrased text for flagged passages per convention
       guidelines"
    ],
    "does_not": [
      "Invent findings (compiles only what other agents reported)",
      "Override convention rules",
      "Make value judgments beyond what conventions specify",
      "Produce content without a reference citation"
    ],
    "model": "claude",
    "backend": "claude_api",
    "model_tier": "frontier",
    "context_tier": "full",
    "category": "amendment",
    "may_use_web": false,
    "may_handle_sensitive": false
  }
}
```

### Output contract for AMENDMENT_DRAFTER

Under the canonical envelope (INFRA-037) AMENDMENT_DRAFTER emits one wrapper whose
`items` are amendments — ONE item per amendment, each carrying the `amendment.*`
fields below as flat per-item fields (the `document_id` is the wrapper's `doc_id`;
there is no nested `amendments` array). The field meanings are unchanged:

```json
{
  "fields": {
    "document_id": "string",
    "amendments": "array of amendment objects",
    "amendment.location": "reference ID (REF-*) of the flagged passage",
    "amendment.convention_ref": "convention ID (CONV-*) that triggers this",
    "amendment.context_refs": "array of REF-* from context corpus supporting the amendment",
    "amendment.finding_type": "terminology | red_flag | rephrasing | citation_style | structural | borrowing | value_alignment | factual | procedural",
    "amendment.original_text": "the exact text being amended",
    "amendment.proposed_text": "the proposed replacement (null if action is flag-only)",
    "amendment.action": "flag | rephrase | reject | annotate",
    "amendment.comment": "human-readable justification citing all references",
    "amendment.severity": "required | recommended | advisory"
  },
  "required": ["document_id", "amendments"]
}
```

Each amendment.comment must follow this citation format:

  "[CONV-003] requires X. The operational text at [REF-0042]
   states Y. Context document [REF-0015] establishes Z as the
   domain standard. Proposed amendment aligns the text with
   [CONV-003] while preserving the original intent per [REF-0042]."

Every claim in the comment must have a bracketed reference.
An amendment without at least one CONV-* and one REF-* is a
contract violation.

### Direction-aware output (INFRA-028)

The tracked-changes `.docx` renders each paragraph and run in its correct
reading direction, decided from the content's own script with no hardcoded
direction assumption: right-to-left scripts (Arabic, Hebrew, and any other RTL
script) receive bidi paragraphs, RTL runs, right justification, and a bidi
language tag; left-to-right content stays default. Direction is applied per run,
so mixed-direction content (for example an RTL passage quoting an LTR case name)
lays out correctly. The design is language-agnostic; the implementation applies
the right direction per detected script.

### Deliverable structure (amends Part XII)

For each operational document at or after the cutoff:

```
output/deliverables/
  {doc_id}__context_summary.md
  {doc_id}__operative_summary.md
  {doc_id}__amendments.json
  {doc_id}__amendments.md        (human-readable version)
  {doc_id}__deliverable.md       (existing per-agent findings)
```

The amendments.md file presents each amendment as:

```
## Amendment 1 [CONV-003] — terminology (required)

**Location:** [REF-0042] Section 3, paragraph 2

**Original:** "the exact flagged text"

**Proposed:** "the proposed replacement text"

**Justification:** [CONV-003] requires X. The operational text
at [REF-0042] states Y. Context document [REF-0015] establishes
Z as the domain standard.

**References:**
- Convention: [CONV-003] source_file.md, section 2, para 3
- Operational: [REF-0042] doc_name.pdf, page 3, para 2
- Context: [REF-0015] reference_doc.pdf, page 7, para 1
```

---

## E. Convention parser

### Implementation

A new module scripts/convention_parser.py handles:

- Reading all files in input/conventions/
- Extracting individual rules from prose, lists, or structured
  formats (markdown headers, numbered lists, JSON, YAML)
- Assigning each rule a CONV-* ID
- Classifying rules into categories (discovered from the
  document structure, not predefined)
- Determining severity (required/recommended/advisory) from
  language cues ("must", "should", "may", "consider")
- Determining action type (flag/rephrase/reject/annotate)
  from the rule's stated remedy
- Writing config/convention_registry.json

The parser runs during BOOT, after adaptive_spawn.
Convention parsing is deterministic (regex + heuristic).
It does not require an LLM call.

If the conventions are ambiguous or the parser cannot classify
a rule, it assigns category "unclassified" and severity
"advisory" and logs a warning. The operator can manually
edit convention_registry.json to correct classifications.

---

## F. Amendments to existing parts

### Part II (Agents) — add AMENDMENT_DRAFTER

Add the agent definition from Section D above to the agent
registry. Total agent count: 14.

### Part VII (Multi-model architecture) — extend contracts

Add ref_ids as a required field for all agents participating
in the convention review workflow (PRACTICE_AUDITOR,
STYLE_GUARDIAN, VERIFIER, FACT_CHECKER, AMENDMENT_DRAFTER).
For other agents, ref_ids remains optional.

### Part X (Adaptive spawning) — split input sources

Adaptive spawn reads from input/context/ instead of input/.
Convention parsing (Section E) reads from input/conventions/.
Neither reads from input/operational/.

### Part XI (Pipeline lifecycle) — insert phase 5.5

After PHASE 5 (verification) and before PHASE 6 (synthesis),
insert PHASE 5.5 (convention review) as described in Section C.

Update PHASE 6 to produce context_summary.md and
operative_summary.md in addition to the existing deliverable.

### Part XII (Directory structure) — three-folder input

Replace input/ with input/context/, input/operational/,
input/conventions/. Add output/audit/reference_index.json
and config/convention_registry.json to the file topology.

### Part XV (Verification checklist) — new checks

Add:
| 31 | input/ has context/, operational/, conventions/ subdirs |
| 32 | convention_parser produces valid convention_registry.json |
| 33 | reference_builder produces valid reference_index.json |
| 34 | AMENDMENT_DRAFTER output has ref_ids on every amendment |
| 35 | Every amendment.comment contains at least one CONV-* and one REF-* |
| 36 | context_summary.md and operative_summary.md produced for cutoff docs |
| 37 | review_scope.json cutoff respected (pre-cutoff docs not amended) |

---

## G. What this amendment does NOT change

- The seven seed laws remain unchanged
- The constitution engine, message bus, and bus protocol are unchanged
- The task force emergence mechanism is unchanged
- The three-tier verification memory is unchanged
- The search stack (DDG/Brave/API) is unchanged
- The cost tracker is unchanged
- The audit synthesizer and DELTA proposal mechanism are unchanged
- Cross-model verification (Law III) applies to the new workflow:
  AMENDMENT_DRAFTER (Claude) compiles findings from VERIFIER and
  FACT_CHECKER (GPT), maintaining the cross-family guarantee
- Law I (do no harm to the source) governs the amendment output:
  amendments are proposals with tracked changes, never silent edits
- Law IV (protect what is private) governs convention documents
  the same way it governs all other inputs

---

## H. Build sequence for this amendment

### Session 4: Convention + reference infrastructure (2-3 hours)

1. Restructure input/ into context/, operational/, conventions/
2. Build scripts/convention_parser.py
3. Build scripts/reference_builder.py
4. Update adaptive_spawn.py to read from input/context/
5. Add config/review_scope.json with cutoff mechanism
6. Update agent_registry.json with AMENDMENT_DRAFTER
7. Update agent_contracts.json with AMENDMENT_DRAFTER contract
   and ref_ids field on review-workflow agents
8. Extend verify_session1.py with checks 31-37
9. Verify: PASS on all structural checks

### Session 5: Review workflow + amendment output (2-3 hours)

1. Build the convention review phase (phase 5.5) in pipeline.py
2. Build the context_summary and operative_summary generators
3. Define AMENDMENT_DRAFTER in config/agent_registry.json + config/agent_contracts.json
   (driven by agent_wrapper.AgentWrapper; no per-agent file)
4. Wire AMENDMENT_DRAFTER output into the deliverable structure
5. Implement the citation format enforcement in contract validation
6. Test with a constructed convention set and operational document
7. Verify: full pipeline produces all three deliverable types
   with precision references

---

## Part XIX — Corpus Acquisition Discipline

These rules were derived from operational experience and apply to all future corpus acquisition regardless of domain.

1. VALIDATE BEFORE TRUSTING. Every downloaded file must pass binary validation before entering input/context/. A file is valid only if: (a) it is larger than 10KB, (b) its first 4 bytes are %PDF, and (c) its first 100 bytes contain no HTML markers (<!DOCTYPE, <html, <head). Government portals frequently serve HTML landing pages at URLs that appear to be direct PDF links.

2. IDENTIFY BEFORE SPENDING. After download and before any pipeline run, every file in input/context/ must pass a content-vs-filename validation. Extract the document's own distinctive terms from its first page and compare against the filename slug. Flag mismatches as potential misclassification. This catches wrong-document downloads before API money is spent processing them.

3. NEVER USE DEFAULT USER-AGENT. Government and institutional servers routinely reject requests from Python's default urllib User-Agent. All corpus download functions must present a browser-like User-Agent string.

4. ASSUME MIRRORS EXIST. For any document that fails to download from its primary URL, a fallback chain of alternative sources (institutional mirrors, OECD repositories, EU policy archives, academic hosts) should be attempted before marking the document as failed. The download function must support ordered URL lists per document.

5. RETRY ON INFRASTRUCTURE FRAGILITY. Government infrastructure in many countries is intermittently slow. A single timeout is not a definitive failure. Retry once after a brief pause before moving to the next fallback URL.

6. EXEMPT DOWNLOAD HELPERS BY CONVENTION. Any script in scripts/ whose filename starts with "download_" or "retry_" is a scenario-specific corpus helper and is exempt from the domain-term discipline gate (Part XV). This exemption is by naming convention, not by hardcoded list, so it scales across domain switches without manual maintenance.

These rules are implemented in scripts/corpus_validator.py as permanent framework infrastructure.

---

## Part XX — External Reference Discovery

When conventions instruct agents to review a provision against a specific policy domain, agents are not limited to the context corpus. If the search router is available, agents should search for additional authoritative frameworks, guidelines, codes of practice, or legal instruments relevant to the provision under review. Discovered references are cited with full URL, document title, issuing body, and year, and marked as [WEB-REF] to distinguish them from corpus references [REF-*].

This behavior is activated by convention rules, not by default. A convention set that does not include an external reference discovery rule will produce no web discovery searches. This keeps the operator in control of whether agents reach beyond the corpus.

The search targets authoritative sources only: official government publications, international organization documents, peer-reviewed policy analyses, and legal instruments. Blog posts, news articles, and opinion pieces are not authoritative sources for governance review.

This rule is implemented through the existing search_router.py infrastructure. No new agent is required. The FACT_CHECKER and PRACTICE_AUDITOR agents already have search capability; this rule authorizes them to use it for discovery, not just verification, when a convention explicitly requests it.

---

## Part XXI — Semantic Retrieval Layer

The reference index supports a vector embedding layer for context filtering. When an embedding store is available, agent context assembly uses cosine similarity retrieval instead of Zipfian term matching. The embedding store is part of the snapshot and persists across runs via save/load. The REF-* citation format remains identical regardless of which retrieval method is active — agents and deliverables do not know or care whether a REF was found via string matching or semantic similarity. If no embedding store exists (fresh domain, no sentence-transformers installed), the pipeline falls back to Zipfian filtering silently. This is a graceful degradation, not an error.

### Per-document language and per-language embedding model (INFRA-028)

Each context document's dominant language is detected (offline, per document — one dominant language per document, not per passage). A small language→model registry selects the embedding model: English (and undetected) documents use the fast English-centric model; a positively-detected non-English language uses a multilingual model (extensible with a language-specialized model where clearly better). An unavailable model degrades to the multilingual or English default with a warning, never silently.

Passages embedded by different models are not numerically comparable. The store therefore keeps one sub-store per model and records which model embedded each passage; a query is embedded separately by each model and compared only against that model's passages, so every similarity is a valid same-model cosine, and results are merged for the global top-k. Staleness accounts for the model used: a rebuild is triggered by a change to the context filename set OR to the language→model registry. Direction-aware deliverable output (RTL/LTR) is covered in Part XVIII Section D.

Semantic retrieval must be granular. A single per-document query does not produce sufficiently diverse context for agents reviewing multiple provisions within that document. When an agent reviews a specific provision, the embedding query should be derived from that provision's text, not from the document's first page. This ensures that an agent reviewing a biometric identification clause retrieves passages about biometric identification from the corpus, not generic passages about the document's overall topic. The pipeline achieves this by running per-provision queries during context assembly, not per-document queries at boot time. The per-document query remains as a fallback when provision-level text is not available.

---

## Part XXII — Universal Review Principles

These principles apply to all document review operations regardless of domain. They are the framework-level standards that every convention set inherits automatically.

### Citation Discipline
- Every reference to an external legal instrument must include the full official title, year, and document number on first mention.
- References to the operative legal framework should follow the citation format native to that framework's jurisdiction.
- Source documents should be cited with issuing authority, title, and year.

### Borrowing Integrity
- Institutional names, treaty titles, and established framework names must be preserved verbatim. A convention rule that targets generic terminology does not override the proper name of an institution or legal instrument.
- When a document adopts definitions from another framework, the source must be explicitly attributed.
- Provisions borrowed from foundational documents in the context corpus should be cross-referenced to the current operative document's corresponding provisions where alignment exists.

### Value Alignment Detection
- Documents should be assessed for alignment with foundational documents in the context corpus that signal principled values or norms. Principal foundation signals can be identified when witnessing convergent reference to meta-level concepts across multiple context documents (e.g. dignity, equity, sustainability, non-discrimination, transparency, accountability).
- Any divergences between the reviewed document and these convergent signals should be flagged and surfaced to the agentic bureaucracy for assessment.

### Structural Completeness
- Every framework reviewed must be assessed for whether it includes a methodological approach comparable to the operative document or the dominant framework in the context corpus.
- Documents must be checked for provisions addressing foundational obligations that the context corpus establishes as standard practice in the relevant domain.

These principles are not convention rules. They do not carry CONV-* identifiers. They inform how agents interpret and apply whatever convention set the operator provides. An operator's conventions add domain-specific requirements on top of these universal principles.

---

## Part XXIII — Absence Detection

Agents must not limit their review to provisions present in the reviewed document. The context corpus and conventions together define what a complete document in this domain should contain. When the context corpus shows that a structural element, safeguard, mechanism, or provision is standard practice across multiple reference documents, its absence from the reviewed document is a finding.

The process: after reviewing what the document contains, agents should compare the document's structural inventory against a checklist derived from the context corpus. The checklist is not hardcoded — it is built dynamically by identifying provisions that appear in a threshold number of context documents (e.g., present in more than half the corpus). If such a provision is absent from the reviewed document, the agent posts a finding with action "flag" and a reference to the context documents where the provision does appear.

Absence findings carry REF-* citations to the context documents that establish the norm, not to the reviewed document (which by definition lacks the provision). The finding's location field should reference the section of the reviewed document where the provision would logically belong, or "document-level" if no natural location exists. For the AMENDMENT_DRAFTER contract specifically (Part XVIII Section D), absence findings may set `location` to the sentinel string `"document-level"` instead of a REF-*; the validator accepts both forms.

This principle is implemented through the existing agent contracts. PRACTICE_AUDITOR and LEGAL_ANALYST are the primary agents responsible for absence detection. Structural completeness checks in Part XXII activate this behavior.

Absence detection is not self-activating from genesis alone. It requires explicit instruction in agent contracts. The PRACTICE_AUDITOR and LEGAL_ANALYST contracts must include an absence detection directive: after completing their review of what the document contains, these agents must compare the document's structural inventory against elements that appear in a threshold number of context documents. The threshold is configurable but defaults to the majority (more than half) of context documents. The agent's context package must include a structural inventory of the corpus (a list of structural elements and how many context documents contain each) so the agent can perform the comparison. This inventory is assembled during the corpus-level phases (ARCHIVIST / INST_FINDER / CITATION_RESOLVER) and passed through the bus.

---

## Part XXIV — Metadata Hierarchy

When extracting document attributes (date, title, author, issuing body), the pipeline prioritizes content-derived signals over container-derived signals:

1. Operator-provided signals (filename conventions, manual overrides). The operator's naming is intentional and authoritative.
2. Content-derived signals (first-page text extraction, header parsing, document self-identification). What the document says about itself.
3. Container-derived signals (PDF metadata fields, file system timestamps). What the file wrapper says about the container. These are frequently artifacts of export tools, format conversions, or download pipelines and do not reliably reflect the document's actual attributes.

When signals conflict, the higher-priority source wins. When a container-derived signal is the only source available, it is used but marked as low-confidence so that downstream consumers can apply appropriate skepticism.

This hierarchy applies to all document attributes, not just dates. Extraction methods must not depend on any specific language, script, or naming convention. This hierarchy supersedes any cascade order implied by earlier Parts; implementations must reorder filename/content above metadata.

For date extraction specifically: years are numeric, not linguistic. The content-derived date signal is a four-digit sequence (or its script-equivalent) in the range 1990-2030 appearing on the first page. The implementation must recognize both Western Arabic numerals (0-9) and Eastern Arabic numerals (٠-٩). No keyword matching ("adopted", "published", "dated") is required or permitted as a primary detection method — the numeric pattern alone is sufficient. When multiple year candidates appear on the first page, prefer the most recent one, as documents typically state their own date prominently.

The filename-derived date signal is a four-digit numeric sequence parseable from the slug regardless of surrounding characters or language.

---

## Part XXV — Uncertain Findings

When an agent produces a finding but cannot determine its correctness with confidence, it must not silently commit or silently discard. The agent posts the finding to the bus with a confidence marker:

- CONFIDENT: the agent is certain. Normal processing.
- UNCERTAIN: the agent found something but the evidence is ambiguous. The finding is posted to the bus with flag "uncertain": true.

Uncertain findings trigger an escalation cascade:
1. First, other agents in the same phase can resolve the uncertainty by corroborating or contradicting the finding (bus-mediated peer review).
2. If no peer resolves it, the orchestrator evaluates whether a task force should be formed to investigate.
3. If the orchestrator cannot resolve it, it is escalated to the operator (in interactive mode) or marked as DEFERRED (in non-interactive mode) and included in the deliverable with an explicit "[UNCERTAIN]" tag so the operator sees it in the output.

Uncertain findings must never be silently dropped. An unresolved uncertainty is more useful to the operator than a false confidence or a silent omission.

This applies to all agent outputs, not just metadata extraction. For metadata specifically: when the date cascade finds multiple candidate years or a single candidate with low confidence, it records the finding as uncertain and proceeds with the best candidate while flagging the ambiguity in document_dates.json with "date_confidence": "uncertain" alongside all candidates found.

---

## Part XXVI — Structural Inventory

During corpus-level processing (the phases where ARCHIVIST, INST_FINDER, and CITATION_RESOLVER run against the full context corpus), the pipeline must also produce a structural inventory: a list of structural elements, mechanisms, safeguards, and provisions that appear across the context corpus, along with the count of how many documents contain each element. Examples of structural elements include but are not limited to: risk classification systems, conformity assessment procedures, post-market monitoring provisions, redress mechanisms, transparency obligations, human oversight requirements, prohibited practices lists, environmental sustainability provisions, cross-border data flow provisions, and definitions sections.

The inventory is not hardcoded. It is derived dynamically from the corpus by the corpus-level agents. The ARCHIVIST agent is responsible for producing the inventory as part of its output. The inventory is stored on the bus and included in the context package for PRACTICE_AUDITOR and LEGAL_ANALYST when they review operational documents.

When PRACTICE_AUDITOR or LEGAL_ANALYST reviews an operational document, they compare the document's contents against the structural inventory. Any element present in more than half the corpus documents but absent from the operational document is posted as an absence finding with action "flag", location "document-level", and REF-* citations to the corpus documents where the element does appear.

---

## Part XXVII — Pipeline Hygiene Standard

This Part is the single source of truth for how the pipeline organizes files,
names things, and protects what it learns. It consolidates and supersedes the
scattered hygiene rules in Part XII (Directory discipline), Part XVII (Directory
discipline lesson), and the pre-convention hygiene DELTAs (INFRA-017 directory
hygiene, INFRA-018 agent hygiene, INFRA-019 variable hygiene). Where an earlier
Part states a narrower rule, this Part governs. Every future change to the
pipeline — cosmetic or internal — must conform to this standard.

The firewall in §B is in force as ratified DELTA INFRA-029 (operator-approved;
see config/constitution.json). It is enforced by the constitutional-amendment
tripwire in scripts/constitution_guard.py and by a snapshot-first,
governance-preserving reset_snapshot in scripts/snapshot_manager.py.

### A. Per-run isolation

Every run writes the artifacts it produces into its own run-scoped folder keyed
by a run id and timestamp (`output/runs/<UTC-timestamp>__<run-id>/`, run id =
8 random hex chars so two runs in the same second never collide). Runs never
overwrite one another: two runs over the same corpus produce two distinct run
folders. The folder's internal structure is:

```
output/runs/<UTC-timestamp>__<run-id>/
  deliverables/   per-document deliverables (<doc_id>__*.md/.json/.docx)
  logs/           agent_bus.jsonl, cost_tracker.{jsonl,json}, run_summary_*.md
  audit/          reference_index.json, audit_synthesis.md, delta_proposals.json,
                  contract_violations/
```

Within a run folder, per-document artifacts are keyed so that two operational
documents sharing a filename stem cannot collide (the doc key keeps the bare stem
when unique and qualifies it as `<stem>__<ext>` on collision, so `policy.pdf` and
`policy.docx` become `policy__pdf` / `policy__docx`). The run path is computed
once at boot in `scripts/run_context.py` (a single source of truth modeled on
`durable_paths.py`); every per-run writer — the bus, cost tracker, deliverables,
reference index, audit synthesis, and the agent-layer
contract-violation dumps — derives its path from that RunContext rather than
hardcoding an `output/` subpath. Run-awareness reaches the agents because the
orchestrator threads the RunContext into every AgentWrapper. Per-run isolation
applies ONLY to what a run produces — never to what the pipeline accumulates (§B);
the protected durable class lives under `durable/` and is structurally
unreachable from any per-run cleanup of `output/runs/`.

### B. The durable-versus-disposable firewall (the protected class)

Cumulative, learned, and durable assets are a PROTECTED class. No per-run
cleanup, no automatic reorganization, and no normal pipeline operation may
delete, truncate, or destructively relocate any member of this class. The
mechanisms that exist to discard learning (snapshot reset / load) are the only
exception, and only under the constraints in §B.2.

**B.1 — The protected class (explicit):**

- the embedding store / semantic cache;
- the verification cache, both project (tier 2) and global cross-project
  (tier 3);
- discovered/learned assets: institution registry, citation conventions, speech
  act taxonomy, search-strategy learnings, discovered APIs, document dates;
- the linguistic identity and situational-awareness reference assets;
- the constitution AND its accumulated legislation — seed laws, amendments
  (the operator-decision/DELTA ledger), precedents, task-force laws;
- the governance ledger of operator approvals (e.g. model-approval records);
- saved snapshots;
- the reserved cross-run knowledge-graph / GNN ontology area.

**B.2 — Rules of the firewall:**

1. Per-run cleanup, per-run folders, and any reorganization act ONLY on a run's
   own produced artifacts. They must be structurally incapable of reaching the
   protected class — the protected class must not live inside any per-run or
   otherwise auto-cleaned tree.
2. Snapshot reset/load are the sole authorized way to discard or replace learned
   state, and only as an EXPLICIT operator action. Reset is non-destructive by
   construction: it ALWAYS writes a backup snapshot before stripping anything,
   and aborts the reset rather than strip if the backup fails. Reset never
   silently destroys an unrecoverable asset.
3. The governance history — the constitution's amendments[]/precedents/task-force
   laws and the operator-approval ledger — survives reset entirely, untouched.
   Reset strips resettable DOMAIN LEARNING (discovered institutions/citations/
   speech-acts/search learnings/per-domain caches, embeddings, reference assets,
   project_rules), not the audit record of operator decisions.
4. Any attempt to MODIFY or DELETE an existing entry in the constitution's
   amendments[] or seed_laws — from ANY code path (Constitution.save,
   reset/load/snapshot, or any agent) — is intercepted by the amendment tripwire
   (scripts/constitution_guard.py): it STOPS and requires explicit operator
   approval before proceeding; without approval it does not happen. Appending a
   NEW amendment (the normal DELTA path) is allowed. Agents cannot bypass it —
   they have no direct write path to constitution.json, and the guard denies any
   protected change lacking an approving operator decision. This approval must
   also surface in any future UI.
5. Absence of a protected asset is NOT a failure signal (see §D); it is created
   on demand and reused. Its destruction, however, is a defect.

### C. Naming conventions

Names state purpose. No vague names. Patterns are consistent across the whole
pipeline (files and folders, not just `output/`):

- A name says what the thing is and, where relevant, what produced it and when.
- One canonical, documented pattern per artifact family; do not invent ad-hoc
  variants. Per-run folders carry the run id + timestamp; per-document artifacts
  carry a collision-safe document key (§A).
- English only; no spaces, no unicode in path components (carried from Part XII).
- A renamed or re-homed identifier updates every reference in both directions
  (the rename-hygiene discipline used throughout this project).

### D. Folder-purpose signaling and emptiness-as-signal

Each folder's purpose is unambiguous from its name and this standard. Emptiness
is a diagnostic signal, read against the artifact's class:

- A missing or empty PER-RUN artifact that a healthy run always produces (e.g. a
  run's deliverables, run summary, audit synthesis) signals that a phase failed
  or was skipped.
- Absence of a CONDITIONAL artifact (contract-violation dumps, redaction
  outputs, within-run search cache, operator-approval records) is normal — it
  means that path did not trigger.
- Absence of a DURABLE/protected asset (embedding store, caches) is normal — it
  is built on demand.

The standard must make these three cases distinguishable by where the artifact
lives, so that "missing = broken" holds only for the per-run always-produced
class.

### E. Format-master rule

Each logical output has ONE canonical master format. Other formats are rendered
or derived from that master on demand, not written independently. The amendments
output is the model and is implemented this way (INFRA-033): the
`amendments_payload` dict — serialized verbatim as `<doc_id>__amendments.json` —
is the MASTER, and the Markdown and tracked-changes `.docx` are PURE FUNCTIONS of
that one payload (master in → format out). All three are written by a single
entry point, `amendment_render.write_amendment_deliverables(payload, …)`; no
render reads amendment content from any other source, so the files cannot drift.
A render may take presentation-only inputs that cannot change which amendments
appear — e.g. the `.docx` takes the original document text as the *canvas* it
anchors tracked-change marks into; amendments that do not anchor still render in
an "Additional amendments" section, so the `.docx` always reflects the full
master set. A cheap drift-guard assertion in the entry point confirms each render
reflects the master's amendment count before the files are returned.

The same discipline governs other multi-form outputs: the cost tracker's
`cost_tracker.jsonl` is the append-only event master and `cost_tracker.json` is a
recomputed aggregate view of those events (two legitimate purposes — audit trail
vs. fast-read totals — never independent sources); audit synthesis writes
`audit_synthesis.md` and `delta_proposals.json` as two views of one `summary`
object. New outputs follow the same shape — never generate the "same" result
twice through independent code paths that can drift.

### F. Separation of concerns

Durable, transient, reports, governance, and failure-dumps must not be
intermixed in one folder. The present `output/audit/` junk-drawer — which mixes a
durable binary cache, a transient within-run cache, audit reports, a governance
ledger, failure dumps, and verify-gate test caches — is the anti-pattern this
standard exists to end. Each concern gets its own clearly-named home; durable
assets live OUTSIDE the per-run / disposable tree (§B).

### G. Universality

These rules apply across the entire pipeline, to both cosmetic and internal
hygiene. Every writer, every cleanup, every reorganization, and every future
feature must conform. A change that cannot conform must be escalated to the
operator, not worked around. "Every file has exactly one correct location;
misplaced files are bugs" (Part XVII) is the spirit; this Part is the letter.

### H. Numbering discipline (append-only)

Part numbers must form an unbroken sequence with no gaps. New Parts are added
ONLY by appending the next sequential number at the end of the document; a Part
is never inserted mid-sequence, never given an out-of-order number, and never
left as a reserved or skipped slot that opens a gap. A renumber (shifting Parts
to close a gap) is performed ONLY to repair an accidental gap, and only with full
upstream/downstream reference updates in lockstep (every "see Part N" cross-
reference, the README index/tree, the verify gate, and every `genesis_part` field
in config/constitution.json), and any edit to a `genesis_part` value inside an
existing amendment must go THROUGH the constitutional-amendment tripwire (§B.2)
with explicit operator approval — never bypassed.

The same append-only discipline governs amendment IDs: the `INFRA-0xx` DELTA
identifiers in config/constitution.json `amendments[]` are already append-only and
must remain so — an ID is never reused, never inserted between existing IDs, and
never renumbered. Amendment IDs are independent of Part numbers; a Part renumber
never moves an amendment ID.

Rationale: append-only numbering keeps every existing reference stable and
prevents breakage; gaps and insertions are how cross-references silently rot.