# INFRA-041 PART 5 -- masking proof fixture (PAID; run only on operator go)

Test scaffolding. NOT wired into the live pipeline, NOT imported by the verify gate, and NOT
placed in the live `input/` corpus. It proves the LAW-IV outbound masking protocol end-to-end
with the layer ACTIVATED, using the real operator convention and planted sentinels asserted by
exact string identity.

## Files
- `planted_context_doc.md` -- the planted document carrying the sentinels + negative control.
- `run_p5_masking_proof.py` -- the instrumented harness (flips `LAYER_ACTIVE` for its own duration,
  hooks the real send path, asserts (a) wire / (b) cross-run stores / (c) ledger / (d) negative control).

## Operator convention (already live)
`input/conventions/review_conventions.md` -> `## CONV-CONFIDENTIALITY` compiles to `CONV-006`
(category `conv-confidentiality`, action `redact`); its rule text names a company "turnover"
(figure cue) and an "identity number" / "identifier" (identifier cue), so it authorizes the
`identifier` and `figure` detectors. No synthetic test convention is introduced.

## Sentinels (exact-identity assertions)
- identifier: `19-0001-0002-0003`  -> masked to `[REDACTED:IDENTIFIER]`
- figure:     `88,000,777,001 EUR` -> masked to `[REDACTED:FIGURE]`
- negative control (must pass RAW): `NEGCTRL-PUBLIC-TOKEN-42`
- title sentinel (chokepoint-4 suppression): `P5-TITLE-SENTINEL-DOC`

## How to run (ONLY after operator go)
    py -3.9 -X utf8 tests/p5_masking/run_p5_masking_proof.py

Exit 0 = all assertions passed. The only paid call is one VERIFIER (gpt-4o) dispatch.
