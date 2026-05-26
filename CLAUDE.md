# Project Shimmer

Standalone, domain-agnostic document processing swarm governed by an adaptive constitution.

## Entry point

The founding specification is [genesis.md](genesis.md), Parts I-XVIII. All architectural decisions, the seven seed laws, the agent registry, the message bus protocol, the convention-driven review workflow, and the build sequence live there. When working on this project, read genesis.md before making any change.

## API keys

Stored outside the repository. The relative path to the local `config.py` is in `.env_path`. Never hardcode keys. Never echo key values to logs, output, or commit messages.

## Three-input-type model (Part XVIII Section A)

- `input/context/` — domain learning corpus. Read during BOOT by adaptive_spawn. Never receives deliverables.
- `input/operational/` — documents under review. Populated by the pipeline at runtime from `input/context/` based on the cutoff in `config/review_scope.json`. NOT manually populated.
- `input/conventions/` — institutional review framework. Parsed into `config/convention_registry.json` during BOOT.

## Rules that override everything

- LAW-IV (privacy) outranks LAW-0 (operator sovereignty) for sensitive-content handling. No exceptions.
- The operator decides every escalation. No silent self-modification.
- No domain-specific content in `scripts/`. Domain knowledge lives in `config/` and `reference/`, spawned from `input/context/`.
- Every convention review finding must cite at least one CONV-* and at least one REF-*.
- English only for code, config file names, and folder names. No spaces or unicode in paths.

## How to run

```
py -3.9 -X utf8 scripts/verify_session1.py        # verification gate (all sessions)
py -3.9 scripts/pipeline.py --non-interactive     # full pipeline
py -3.9 scripts/pipeline.py --list-ontologies     # list saved ontologies
py -3.9 scripts/pipeline.py --save-ontology NAME  # snapshot learned state
py -3.9 scripts/pipeline.py --load-ontology NAME  # restore saved snapshot
py -3.9 scripts/pipeline.py --reset-ontology      # strip back to seed defaults
py -3.9 scripts/bus_viewer.py --follow            # live bus + cost stream
```
