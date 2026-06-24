# INFRA-043 DELTA, ratified

**Status:** RATIFIED by the operator on 2026-06-24 (`operator_approved: true`). The object below is
appended to `config/constitution.json` `amendments[]` through the normal append-only DELTA path
(the INFRA-029 amendment tripwire permits adding a new id; it does not modify or delete any seed law
or existing amendment). This document remains the human-readable record; the canonical record is the
constitution entry. The build (OPT-3 + OPT-4 merged, PART 3.2) happens only after ratification (now
granted).

## Verification (re-checked against the repo, not recall)

- **Next free id:** `INFRA-043`. The roster ends at INFRA-042, the ids are contiguous with no gap,
  INFRA-043 is not in the roster, and a repo-wide grep finds INFRA-043 nowhere outside the job spec.
  Append-only, no-gap, never-reused satisfied.
- **`genesis_part: "XXVII"` verified against genesis.md:** the amendment tripwire and the numbering
  discipline both live in Part XXVII (Pipeline Hygiene Standard, line 1740). The durable-versus-
  disposable firewall is section B (line 1785), the amendment tripwire is cited at line 1825 and
  section B.2 at line 1918, and the append-only Numbering discipline is section H (line 1908).
  INFRA-029 (the firewall/tripwire this DELTA extends) is itself genesis_part XXVII.
- **Covers all three facets + the merge note:** `scope_extension` (genesis integrity), `signature_scan`
  (the flag), `verified_delta_sole_route` (the verified no-gap path), `operator_agent_asymmetry` (the
  LAW-0 correctness requirement), and `merge_note` (OPT-3 + OPT-4 merged into one build).

## Governance posture

Proposal-side, operator-ratified, does not self-apply (no agent has a write path to
`config/constitution.json`), under the meta-law tripwire it extends (`scripts/constitution_guard.py`).

## The DELTA object (appended to `amendments[]` on ratification)

```json
{
  "id": "INFRA-043",
  "created": "2026-06-24",
  "kind": "meta_law_tripwire_and_verified_delta_path",
  "title": "Meta-law tripwire (genesis + signature scan) + verified DELTA path as sole amend route",
  "genesis_part": "XXVII",
  "operator_approved": true,
  "change": {
    "scope_extension": "Extends the INFRA-029 amendment tripwire (constitution_guard.py, today guarding only modify/delete of config/constitution.json seed_laws and amendments) UP to the genesis/meta layer. genesis.md is not pipeline-written, so its immutable core is protected by an INTEGRITY CHECK consistent with the guard: check_genesis_integrity verifies that genesis Part I mirrors the guarded constitution seed_laws (each seed-law id present, immutability intact). A divergence is a protected violation surfaced for operator approval, and a verify-gate check asserts it. Only the seed-law region is cross-checked, so append-only Part growth never false-trips.",
    "signature_scan": "Adds scan_for_meta_signature(text), an auditable, operator-extensible signature set (one-time / just this once / reverse-engineer / lift the limits / bypass the rule|guard|law|constitution / ignore the rule|law|guard / disable the guard|tripwire / override LAW / rewrite the law|constitution|meta / edit the meta / meta-law editing). It scans the two live channels: pre-run operator input (run_objectives) and agent-proposed DELTA text (escalate_delta_proposals). The scan is a FLAG, not a complete semantic guard: it has false positives (legitimate text containing the phrasing) and false negatives (a bypass phrased differently), surfaces for operator attention, and fails toward flagging-for-review, never toward silently blocking legitimate work. No guarantee is claimed.",
    "operator_agent_asymmetry": "LAW-0 correctness, load-bearing. Agent path: refuse-and-route. Agents cannot amend governed structure; a signature-carrying agent-proposed DELTA is refused (default-deny holds) and routed to the operator, never auto-applied. Operator path: speed-bump-with-confirmation. A signature on operator run_objectives does NOT block; in INTERACTIVE mode it surfaces a conscious confirmation and PROCEEDS on confirmation. In NON-INTERACTIVE mode the operator-path signature scan LOGS AND PROCEEDS: it becomes an audit-log entry, not a confirmation gate, because blocking the operator would violate LAW-0 and a non-interactive operator has already declared intent by running the pipeline. This is intentional, not a gap. The operator path can NEVER be turned into a hard block: a guard that could cage the operator would invert LAW-0, the opposite of intent. The blocking behavior applies only to agents.",
    "verified_delta_sole_route": "The only legitimate route to change governed structure is the verified DELTA path. At record time the append is VERIFIED: append-only (no modify/delete, already guarded), the no-gap rule enforced (a new amendment id must be exactly prior_max + 1, never reused, never a gap; documented in Part XXVII H but not enforced in code today), operator_approved true, and the DELTA text signature-cleared or operator-confirmed. A verify-gate check asserts every constitution writer routes through check_constitution_change (no unguarded side-channel writer). Agents have no direct write path; this hardens the rule and makes it explicit.",
    "merge_note": "OPT-3 (meta-law tripwire) and OPT-4 (verify-and-preserve the DELTA path) are merged into this one amendment and one build because they share the constitution_guard and proposal-side DELTA machinery and are two facets of one protective structure; separate builds would duplicate the guard.",
    "scope": "Extends a governed protective guard. No seed law is modified (LAW-0 is cited and honored: the operator path is never a hard block). Pipeline plus guard behavior plus this governed extension."
  },
  "reason": "Today the INFRA-029 tripwire guards only modify/delete of constitution.json; genesis.md is unguarded at runtime, the no-gap numbering rule is documented but unenforced, and nothing scans for the lift-the-limits / reverse-engineer / one-time meta-law-editing signature. This DELTA extends the tripwire up to genesis's immutable core, adds the signature scan as an operator-surfacing flag (not a semantic guarantee), enforces the no-gap verified-DELTA path as the sole amend route, and encodes the load-bearing operator/agent asymmetry so the guard protects governed structure without ever caging the operator (LAW-0). OPT-3 and OPT-4 are merged because they are one protective structure. It extends governed protective structure, so it is ratified before it is built.",
  "note": "Append-only DELTA (allowed by the INFRA-029 amendment tripwire; no seed law or existing amendment modified or deleted). Extends the meta-law tripwire (constitution_guard.py, genesis Part XXVII) to genesis integrity + a signature scan + the verified no-gap DELTA path as sole route. The signature scan is a FLAG with false positives and false negatives, surfacing for operator attention, never a silent block of legitimate work. Operator/agent asymmetry is a LAW-0 correctness requirement: agents are refused-and-routed; the operator gets speed-bump-with-confirmation in interactive mode and LOGS-AND-PROCEEDS in non-interactive mode, and is never hard-blocked. Proposal-side, operator-ratified, does not self-apply, under the meta-law tripwire it extends. OPT-3 + OPT-4 merged into one build. Built only after this DELTA is ratified, with executed-coverage gate checks."
}
```

*End of draft. Nothing built, nothing appended to config/. The operator ratifies this object before the OPT-3 + OPT-4 merged build (PART 3.2).*
