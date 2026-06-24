# Procedural Regulation (P5 masking-proof fixture, NOT a real corpus document)

This document exists ONLY to prove the LAW-IV outbound masking protocol (INFRA-041)
end-to-end. It carries deterministic, non-natural SENTINEL tokens so every assertion is
by exact string identity. It is test scaffolding under tests/ and is never placed in the
live input/context/ corpus by this fixture.

## Sentinels (operator-marked sensitive content, authorized by CONV-CONFIDENTIALITY / CONV-006)

The applicant's national identity number on file is 19-0001-0002-0003 and must not appear in
any published output.

The named company reported a turnover of 88,000,777,001 EUR in the relevant review period.

## Negative control (non-sensitive; MUST pass through raw)

This clause is public and carries the marker NEGCTRL-PUBLIC-TOKEN-42, which is not an
authorized sensitive shape and must reach the wire unchanged.

## Filler

Article 5 shall apply. The authority must state written reasons for any decision that
adversely affects a party.
