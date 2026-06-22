# Project Shimmer

Standalone, domain-agnostic document processing swarm governed by an adaptive constitution.

## Entry point

The founding specification is [genesis.md](genesis.md), Parts I–XXVII. All architectural decisions, the seven seed laws, the agent registry, the message bus protocol, the convention-driven review workflow, and the build sequence live there. When working on this project, read genesis.md before making any change.

## API keys

Stored outside the repository. The relative path to the local `config.py` is in `.env_path`. Never hardcode keys. Never echo key values to logs, output, or commit messages. The key reader (`load_api_keys`) reads **API-key values only** from that file via a fixed allowlist; any model variable in it (e.g. a `model = ...` line) is ignored and never affects model selection. Model choice is owned solely by `config/agent_registry.json` (`spec.model`).

## Three-input-type model (Part XVIII Section A)

- `input/context/` — domain learning corpus. Read during BOOT by adaptive_spawn. Never receives deliverables.
- `input/operational/` — documents under review. Populated by the pipeline at runtime from `input/context/` based on the cutoff in `config/review_scope.json`. NOT manually populated.
- `input/conventions/` — institutional review framework. Parsed into `config/convention_registry.json` during BOOT.

## Rules that override everything

- LAW-IV (privacy) outranks LAW-0 (operator sovereignty) for sensitive-content handling. No exceptions.
- The operator decides every escalation. No silent self-modification.
- No domain-specific content in `scripts/`. Domain knowledge lives in `config/` (compiled conventions) and `durable/` (learned assets spawned from `input/context/`: `durable/learnings/` and `durable/reference/`).
- Every convention review finding must cite at least one CONV-* and at least one REF-*.
- English only for code, config file names, and folder names. No spaces or unicode in paths.
- Every numbered DELTA is recorded as an amendment in `config/constitution.json` (`amendments[]`) — that is the single canonical record. The README no longer carries a per-amendment roster (removed in the docs cleanup); no DELTA lives only in prose.

## First-time setup

Install the base dependencies manually, *before* running `setup.bat`:

```
py -3.9 -m pip install -r requirements.txt
```

`setup.bat` does NOT install the base dependencies — it only ensures the two
optional libraries (`beautifulsoup4`, `langdetect`) are importable. First-time
setup can take a while and this is expected, not a fault: installing dependencies
and pulling the Qwen model weights (several gigabytes, on first setup / first run)
can take several minutes or longer. Do not interrupt them; subsequent runs reuse
the installed packages and cached weights.

## How to run

```
py -3.9 -X utf8 scripts/verify_session1.py        # verification gate (all sessions)
py -3.9 scripts/pipeline.py --non-interactive     # full pipeline
py -3.9 scripts/pipeline.py --list-snapshots      # list saved snapshots
py -3.9 scripts/pipeline.py --save-snapshot NAME  # snapshot learned state
py -3.9 scripts/pipeline.py --load-snapshot NAME  # restore saved snapshot
py -3.9 scripts/pipeline.py --reset-snapshot      # strip back to seed defaults
py -3.9 scripts/bus_viewer.py --follow            # live bus + cost stream
```
