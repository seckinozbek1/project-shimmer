"""Project Shimmer verification gate.

Runs 39 checks total: check 00 (ast.parse smoke) + Part XV checks 1-30
(Sessions 1-3) + Part XVIII Section F checks 31-37 (Session 4+) + check 38
(embedding store build/query, Part XXI). ALL must PASS.
"""

from __future__ import annotations

import ast
import io
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CONFIG = ROOT / "config"
SELF_PATH = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPTS))

import durable_paths as _dp  # after sys.path setup; used by non-mutation guards


REQUIRED_DIRS = [
    "config", "input", "input/context", "input/operational", "input/conventions",
    # Per-run output isolation (INFRA-032): per-run artifacts live under
    # output/runs/<run>/ now, not in fixed output/{deliverables,audit,logs}.
    "output", "output/runs",
    # Learned reference assets moved to durable/reference/ in the durable refactor
    # (snapshot_manager actively clears any legacy top-level reference/); the old
    # top-level "reference" dir is no longer required.
    "prompts", "scripts", "snapshots",
    # Protected durable tree (INFRA-030) — lives outside the auto-cleaned output tree.
    "durable", "durable/cache", "durable/global", "durable/learnings",
    "durable/reference", "durable/governance",
]

EXPECTED_AGENTS = {
    "PROCESSOR", "VERIFIER", "FACT_CHECKER", "PRACTICE_AUDITOR", "LEGAL_ANALYST",
    "STYLE_GUARDIAN", "ARCHIVIST", "INST_FINDER", "CITATION_RESOLVER",
    "SPEECH_ACT_TAGGER", "REDACTOR",
    "AMENDMENT_DRAFTER", "EDITOR_CLERK",
    "EDITOR_HEAD_OF_UNIT", "EDITOR_HEAD_OF_SECTION", "EDITOR_HEAD_OF_DEPARTMENT",
    "EDITOR_DEPUTY_DG", "EDITOR_DG",
}

SEED_LAW_IDS = {"LAW-0", "LAW-I", "LAW-II", "LAW-III", "LAW-IV", "LAW-V", "LAW-VI"}

DOMAIN_TERMS = re.compile(
    r"\b(islamic|islamabad|pakistan|sharia|maslaha|maqasid|peca|moitt|niti|sdaia|"
    r"bakanlik|turkish|dishisleri)\b",
    re.IGNORECASE,
)


# Per-run isolation (INFRA-032): the gate boots orchestrators and opens buses.
# To stay strictly non-mutating w.r.t. the repo (Pass B-4 discipline) AND to never
# collide with a real run's output, the gate runs every orchestrator/bus against a
# THROWAWAY run folder in the system temp dir (outside the repo). project_root
# stays ROOT (so durable/config are read from the real repo); only per-run output
# is redirected here.
import tempfile as _tempfile
import run_context as _run_context_mod
_VERIFY_RUN = _run_context_mod.RunContext(
    project_root=ROOT, run_id="verify",
    run_dir=Path(_tempfile.mkdtemp(prefix="shimmer_verify_run_")) / "run",
).ensure()


def _ok(detail="ok"): return ("PASS", detail)
def _fail(detail): return ("FAIL", detail)


def _nonmutating(*paths):
    """Decorator: snapshot the on-disk bytes (or absence) of the given tracked
    files before the check runs, and restore them afterward (even on return or
    exception). This lets a check genuinely exercise spawn/parse/save against the
    real ROOT while guaranteeing it leaves NO tracked file under config/,
    reference/, or prompts/ mutated. The verify gate must never modify working
    files; runtime artifacts belong under output/ (gitignored)."""
    def deco(fn):
        def wrapped(*a, **k):
            snap = {p: (p.read_bytes() if p.exists() else None) for p in paths}
            try:
                return fn(*a, **k)
            finally:
                for p, data in snap.items():
                    if data is None:
                        if p.exists(): p.unlink()
                    else:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_bytes(data)
        wrapped.__name__ = fn.__name__
        wrapped.__doc__ = fn.__doc__
        return wrapped
    return deco


def check_01_directory():
    missing = [d for d in REQUIRED_DIRS if not (ROOT / d).is_dir()]
    if missing: return _fail(f"missing dirs: {missing}")
    allowed_root_files = {
        "genesis.md", "CLAUDE.md", "README.md", "requirements.txt",
        ".gitignore", "project_shimmer_cover.png", ".env_path",
        "setup.bat",
    }
    extras = [p.name for p in ROOT.iterdir()
              if p.is_file() and p.name not in allowed_root_files]
    return ("PASS" if not extras else "WARN",
            f"{len(REQUIRED_DIRS)} dirs present" + (f"; loose: {extras}" if extras else ""))


def check_02_constitution():
    p = CONFIG / "constitution.json"
    if not p.exists(): return _fail("constitution.json missing")
    try: data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e: return _fail(f"invalid JSON: {e}")
    ids = {law.get("id") for law in data.get("seed_laws", [])}
    missing = SEED_LAW_IDS - ids
    if missing: return _fail(f"missing seed laws: {missing}")
    if len(data.get("seed_laws", [])) != 7: return _fail(f"expected 7, got {len(data.get('seed_laws', []))}")
    return _ok("7 seed laws, valid JSON")


def check_03_agent_registry():
    data = json.loads((CONFIG / "agent_registry.json").read_text(encoding="utf-8"))
    agents = data.get("agents", {})
    if set(agents.keys()) != EXPECTED_AGENTS:
        return _fail(f"extras={set(agents)-EXPECTED_AGENTS} missing={EXPECTED_AGENTS-set(agents)}")
    for name, spec in agents.items():
        for k in ("does", "does_not", "model"):
            if k not in spec: return _fail(f"{name} missing {k!r}")
    return _ok(f"{len(agents)} agents with DOES/DOES NOT/model (18 incl. AMENDMENT_DRAFTER + EDITOR_CLERK + 5 board ranks)")


def check_04_contracts():
    data = json.loads((CONFIG / "agent_contracts.json").read_text(encoding="utf-8"))
    contracts = data.get("contracts", {})
    missing = EXPECTED_AGENTS - set(contracts)
    if missing: return _fail(f"contracts missing for: {missing}")
    for name, c in contracts.items():
        if "fields" not in c or "required" not in c: return _fail(f"{name} contract missing fields/required")
    return _ok(f"{len(contracts)} contracts including AMENDMENT_DRAFTER")


def check_05_constitution_check():
    from constitution import Constitution
    c = Constitution.load(CONFIG / "constitution.json")
    r = c.check({"agent": "PROCESSOR", "action": "draft", "tags": ["content_production"]})
    return _ok(f"check() returned {'resolved' if r.resolved else 'UNRESOLVED'} (expected for fresh seed)")


def check_06_match_tf_law():
    from constitution import Constitution
    c = Constitution.load(CONFIG / "constitution.json")
    m = c.match_tf_law({"mission": "verify outputs against source",
                        "members": [{"agent": "VERIFIER"}, {"agent": "PROCESSOR"}]})
    if not isinstance(m.confidence, float): return _fail(f"non-float: {m.confidence!r}")
    if not 0.0 <= m.confidence <= 1.0: return _fail(f"out of range: {m.confidence}")
    return _ok(f"match_tf_law returned confidence={m.confidence}")


def check_07_message_bus():
    from message_bus import MessageBus, ProtocolViolation
    bus_path = _VERIFY_RUN.logs_dir() / "_verify_bus.jsonl"
    if bus_path.exists(): bus_path.unlink()
    bus = MessageBus.open(bus_path)
    msg = {"sender": "ORCHESTRATOR", "sender_role": "orchestrator", "recipient": "PROCESSOR",
           "channel": "main", "type": "INFORM", "body": {"hello": "world"},
           "constitution_check": {"laws_consulted": ["LAW-0"], "result": "RESOLVED", "resolution": "smoke"}}
    posted = bus.post(msg)
    if "timestamp" not in posted: bus_path.unlink(); return _fail("no timestamp")
    all_msgs = bus.read_all(); found = bus.query(sender="ORCHESTRATOR", msg_type="INFORM"); summary = bus.summarize()
    try: bus.post({**msg, "constitution_check": {"result": "RESOLVED"}, "type": "BOGUS"})
    except ProtocolViolation: bad = "rejected bogus type"
    else: bus_path.unlink(); return _fail("accepted invalid type")
    try: bus.post({k: v for k, v in msg.items() if k != "constitution_check"})
    except ProtocolViolation: bad2 = "rejected missing constitution_check"
    else: bus_path.unlink(); return _fail("accepted message w/o check")
    bus_path.unlink()
    return _ok(f"post/read/query/summarize ok; {bad}; {bad2}")


def check_08_bus_reader():
    from bus_reader import BACKEND_BUDGETS, assemble_context
    from constitution import Constitution
    from message_bus import MessageBus
    bus_path = _VERIFY_RUN.logs_dir() / "_verify_bus.jsonl"
    if bus_path.exists(): bus_path.unlink()
    bus = MessageBus.open(bus_path)
    c = Constitution.load(CONFIG / "constitution.json")
    sizes = {}
    for backend in BACKEND_BUDGETS:
        pkg = assemble_context(backend=backend, constitution=c, bus=bus,
                               work_payload={"doc": "test"}, run_objectives="Process test")
        t = pkg.token_estimate(); sizes[backend] = (sum(t.values()), t)
    bus_path.unlink()
    if sizes["qwen_local"][1]["governance"] >= sizes["claude_api"][1]["governance"]:
        return _fail("qwen governance not smaller than claude")
    return _ok(f"claude={sizes['claude_api'][0]}, gpt={sizes['openai_api'][0]}, qwen={sizes['qwen_local'][0]} tokens")


def check_09_agent_wrapper_callers():
    from agent_wrapper import AgentWrapper
    methods = ("call_claude", "call_gpt", "call_qwen", "post_to_bus", "check_constitution", "dispatch", "run_task")
    missing = [m for m in methods if not callable(getattr(AgentWrapper, m, None))]
    if missing: return _fail(f"missing: {missing}")
    return _ok("all 7 backend/dispatch/run_task methods present")


def check_10_orchestrator_deliberation():
    from orchestrator import TopOrchestrator
    bus_path = _VERIFY_RUN.bus_path()
    if bus_path.exists(): bus_path.unlink()
    orch = TopOrchestrator.boot(interactive=False, run_adaptive_spawn=False, run_context=_VERIFY_RUN)
    wrappers = orch.deliberation_round({"phase": "test", "docs": []})
    if set(wrappers.keys()) != EXPECTED_AGENTS:
        return _fail(f"deliberation wrappers: {set(wrappers) ^ EXPECTED_AGENTS}")
    msgs = orch.bus.query(sender="ORCHESTRATOR", msg_type="REQUEST")
    if len(msgs) != len(EXPECTED_AGENTS):
        return _fail(f"expected {len(EXPECTED_AGENTS)} REQUEST, got {len(msgs)}")
    return _ok(f"deliberation issued {len(msgs)} self-assess requests")


def check_11_orchestrator_evaluate_charter():
    from orchestrator import TopOrchestrator
    orch = TopOrchestrator.boot(interactive=False, run_adaptive_spawn=False, run_context=_VERIFY_RUN)
    decision, match, details = orch.evaluate_charter({
        "id": "TF-test-1", "mission": "verify outputs against source documents",
        "members": [{"agent": "VERIFIER"}, {"agent": "PROCESSOR"}], "proposed_by": "VERIFIER",
    })
    if decision == "DENY": return _fail(f"valid charter denied: {details}")
    return _ok(f"decision={decision}, match={match.confidence}")


def check_12_orchestrator_escalation():
    from orchestrator import OperatorDecision, TopOrchestrator
    captured = []
    def handler(topic, payload):
        captured.append((topic, payload)); return OperatorDecision(decision="DEFER", rationale="harness")
    orch = TopOrchestrator.boot(interactive=False, run_adaptive_spawn=False, operator_handler=handler,
                                run_context=_VERIFY_RUN)
    decision, _m, _d = orch.evaluate_charter({
        "id": "TF-test-2", "mission": "totally novel mission with no overlap whatsoever",
        "members": [{"agent": "ARCHIVIST"}, {"agent": "SPEECH_ACT_TAGGER"}], "proposed_by": "ARCHIVIST",
    })
    if not captured: return _fail("handler not invoked")
    if captured[0][0] != "charter_silent_in_constitution": return _fail(f"unexpected topic: {captured[0][0]}")
    if "charter" not in captured[0][1]: return _fail(f"payload missing charter: {sorted(captured[0][1])}")
    if not orch.bus.query(channel="escalation", msg_type="ESCALATE"):
        return _fail("no ESCALATE on bus")
    return _ok(f"escalation mechanism fired; topic captured; orchestrator returned {decision}")


@_nonmutating(CONFIG / "constitution.json")
def check_13_tf_formation_endtoend():
    from orchestrator import OperatorDecision, TopOrchestrator
    bus_path = _VERIFY_RUN.bus_path()
    if bus_path.exists(): bus_path.unlink()
    orch = TopOrchestrator.boot(interactive=False, run_adaptive_spawn=False,
                                 operator_handler=lambda t, p: OperatorDecision("APPROVE", "verification"),
                                 run_context=_VERIFY_RUN)
    before = len(orch.constitution.task_force_laws())
    charter = {"mission": "verify outputs against source documents",
               "members": [{"agent": "VERIFIER", "role_in_tf": "lead"},
                           {"agent": "PROCESSOR", "role_in_tf": "draft"}],
               "proposed_by": "VERIFIER", "confirmations": ["VERIFIER", "PROCESSOR"],
               "completion_criteria": "all paragraphs reviewed"}
    decision, _m, tf = orch.propose_charter(charter)
    if tf is None or tf.state != "ACTIVE":
        return _fail(f"task force not formed; decision={decision}")
    if not tf.channel.startswith("tf_"): return _fail(f"scope: {tf.channel!r}")
    if not orch.bus.recent(limit=20, channel=tf.channel): return _fail("no traffic on scoped channel")
    law = orch.dissolve_task_force(tf.id, completion_report={"summary": "test"},
                                   learnings={"reuse": "verifier+processor"})
    after = len(orch.constitution.task_force_laws())
    if after != before + 1: return _fail("dissolve did not codify TF-law")
    orch.constitution._data["task_force_laws"] = orch.constitution._data["task_force_laws"][:before]
    orch.constitution.save()
    return _ok(f"propose->form->dissolve->codify works (TF={tf.id}, law={law.get('id')})")


@_nonmutating(CONFIG / "constitution.json")
def check_14_tf_dissolution():
    from constitution import Constitution
    c = Constitution.load(CONFIG / "constitution.json")
    before = len(c.task_force_laws())
    law = c.add_tf_law({"id": "TF-verify-14", "mission": "test", "members": [{"agent": "VERIFIER"}]},
                       {"learning": "test"})
    after = len(c.task_force_laws())
    if after != before + 1: return _fail(f"before={before} after={after}")
    c._data["task_force_laws"] = c._data["task_force_laws"][:before]; c.save()
    return _ok(f"add_tf_law works (id={law.get('id')})")


@_nonmutating(_dp.search_strategy_learnings_path(ROOT),
              _dp.discovered_apis_path(ROOT),
              _dp.institution_registry_path(ROOT))
def check_15_search():
    """Live DDG smoke test. Cached for 24h to keep repeat runs fast.

    Cache lives in the gate's throwaway temp run (audit/verify_check15_cache.json,
    outside the repo). First run of the
    day hits DDG live; subsequent runs within 24h return the cached verdict.
    """
    from search_router import SearchRouter

    cache_path = _VERIFY_RUN.audit_dir() / "verify_check15_cache.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(cached["cached_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - ts
            age_hours = age.total_seconds() / 3600.0
            if age_hours < 24.0:
                return _ok(
                    f"DDG cascade (cached, age={age_hours:.1f}h); "
                    f"strategy={cached.get('strategy_used')}, "
                    f"hits={cached.get('hit_count')}, "
                    f"verdict={cached.get('verdict')}"
                )
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # fall through and re-run live

    router = SearchRouter.open(ROOT)
    result = router.search("United Nations General Assembly", claim_type="institutional")
    if result.strategy_used not in {"ddg", "brave", "api", "direct", "exhausted"}:
        return _fail(f"strategy: {result.strategy_used!r}")
    if result.verdict not in {"FOUND", "UNVERIFIABLE"}:
        return _fail(f"verdict: {result.verdict!r}")
    if not router.learnings_path.exists():
        return _fail("learnings.json not created")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "strategy_used": result.strategy_used,
        "hit_count": len(result.hits),
        "verdict": result.verdict,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return _ok(
        f"DDG cascade (live); strategy={result.strategy_used}, "
        f"hits={len(result.hits)}, verdict={result.verdict}"
    )


def check_16_claim_classifier():
    from claim_classifier import ClaimExtractor, dedup_claims
    sample = ("The General Assembly adopted resolution A/RES/78/1 on September 21, 2023. "
              "Article 25 of the Charter binds all Members. Global GDP grew 3.2% in 2024. "
              "ISO 27001 is the standard reference for information security.")
    extractor = ClaimExtractor(openai_key="")
    claims = extractor.extract(sample, use_gpt=False)
    if len(claims) < 2: return _fail(f"too few: {len(claims)}")
    types = {c.type for c in claims}
    if not types.intersection({"institutional", "legal_regulatory", "statistic", "standard_ref", "date_event"}):
        return _fail(f"types={types}")
    if len(dedup_claims(claims + claims)) != len(claims): return _fail("dedup failed")
    return _ok(f"{len(claims)} claims, types={sorted(types)}")


@_nonmutating(_dp.verification_cache_path(ROOT), _dp.verification_cache_global_path(ROOT))
def check_17_memory():
    from verification_cache import TTL_DAYS, VerificationCache
    mem = VerificationCache.open(ROOT)
    mem.store("verify_test_key", claim_type="statistic", verdict="CONFIRMED",
              evidence="unit test", source_url="https://example.com", confidence=0.95)
    hit = mem.lookup("verify_test_key", "statistic")
    if hit is None: return _fail("lookup miss")
    if hit.tier != 2: return _fail(f"tier {hit.tier}")
    if hit.ttl_days != TTL_DAYS["statistic"]: return _fail(f"ttl {hit.ttl_days}")
    if mem.lookup("nonexistent_key_xyz", "statistic") is not None: return _fail("false hit")
    for ap in ("tier2_path", "tier3_path"):
        path = getattr(mem, ap); data = mem._load(path)
        if "verify_test_key" in (data.get("entries") or {}):
            del data["entries"]["verify_test_key"]; mem._save(path, data)
    return _ok(f"two durable tiers ok; ttl statistic={TTL_DAYS['statistic']}, institutional={TTL_DAYS['institutional']}")


def check_18_contract_validation():
    from agent_wrapper import AgentWrapper
    from constitution import Constitution
    from message_bus import MessageBus
    c = Constitution.load(CONFIG / "constitution.json")
    bus_path = _VERIFY_RUN.logs_dir() / "_verify_bus.jsonl"
    if bus_path.exists(): bus_path.unlink()
    bus = MessageBus.open(bus_path)
    registry = json.loads((CONFIG / "agent_registry.json").read_text())["agents"]
    contracts = json.loads((CONFIG / "agent_contracts.json").read_text())["contracts"]
    from agent_wrapper import decode_items, is_envelope
    w = AgentWrapper(name="FACT_CHECKER", constitution=c, bus=bus, registry=registry,
                     contracts=contracts, keys={"OPENAI_API_KEY": "stub"},
                     run_context=_VERIFY_RUN)
    # Canonical envelope (INFRA-037): a valid wrapper with one flat core-bearing item.
    good = json.dumps({"agent": "FACT_CHECKER", "doc_id": "verify_doc", "items": [
        {"ref": "REF-0001", "kind": "finding", "confidence": "CONFIDENT", "verdict": "CONFIRMED",
         "claim_id": "C-1", "original_text": "test", "search_method": "test", "ref_ids": ["REF-0001"]}]})
    obj, missing = w.parse_contract_output(good)
    if missing: return _fail(f"valid envelope rejected: {missing}")
    if not is_envelope(obj): return _fail("parser did not return the canonical wrapper")
    items = decode_items(obj)
    if not items or items[0].get("verdict") != "CONFIRMED": return _fail("verdict lost")
    if not all(k in items[0] for k in ("item_id", "revision", "ts")):
        return _fail("runtime fields (item_id/revision/ts) not stamped")
    # a bare list / bare dict is NOT the wrapper and must be rejected
    _, m_list = w.parse_contract_output(json.dumps(
        [{"ref": "R", "kind": "finding", "confidence": "CONFIDENT",
          "claim_id": "C", "verdict": "CONFIRMED", "search_method": "t"}]))
    _, m_dict = w.parse_contract_output(json.dumps({"claim_id": "C", "verdict": "CONFIRMED"}))
    bus_path.unlink()
    if not m_list or not m_dict: return _fail("bare list/dict accepted (not the wrapper)")
    return _ok("parser enforces canonical wrapper + per-item core; bare list/dict rejected")


def check_19_bus_constitution_field():
    bus_path = _VERIFY_RUN.bus_path()
    if not bus_path.exists(): return _fail("no bus log")
    lines = [json.loads(ln) for ln in bus_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    missing = [i for i, m in enumerate(lines) if "constitution_check" not in m]
    if missing: return _fail(f"missing at {missing[:5]}")
    return _ok(f"all {len(lines)} bus messages have constitution_check")


def check_20_run_summary():
    from orchestrator import TopOrchestrator
    orch = TopOrchestrator.boot(interactive=False, run_adaptive_spawn=False, run_context=_VERIFY_RUN)
    summary = orch.run_summary()
    needed = {"total", "by_type", "by_sender", "by_channel", "constitution", "input_documents"}
    missing = needed - set(summary)
    if missing: return _fail(f"missing keys: {missing}")
    summaries = sorted(_VERIFY_RUN.logs_dir().glob("run_summary_*.md"))
    if not summaries: return _fail("no summary .md")
    return _ok(f"summary ok; latest={summaries[-1].name}; docs={summary['input_documents']}")


def check_21_no_hardcoded_paths():
    pattern = re.compile(r"[A-Za-z]:\\\\|/Users/|/home/|C:/Users", re.IGNORECASE)
    bad = []
    for p in SCRIPTS.rglob("*.py"):
        if p.resolve() == SELF_PATH: continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(ln):
                bad.append(f"{p.relative_to(ROOT)}:{i}: {ln.strip()[:80]}")
    if bad: return _fail(f"{len(bad)} hardcoded: {bad[:3]}")
    return _ok("no hardcoded absolute paths in scripts/")


def check_22_no_domain_terms():
    # Per genesis Part XIX rule 6: any script whose name starts with
    # "download_" or "retry_" is a scenario-specific corpus helper and is
    # exempt from this discipline gate. Exemption is by naming convention,
    # not by hardcoded list — scales across domain switches without manual
    # maintenance.
    def _is_exempt(name: str) -> bool:
        return name.startswith("download_") or name.startswith("retry_")
    bad = []
    for p in SCRIPTS.rglob("*.py"):
        if p.resolve() == SELF_PATH: continue
        if _is_exempt(p.name): continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if DOMAIN_TERMS.search(ln):
                bad.append(f"{p.relative_to(ROOT)}:{i}: {ln.strip()[:80]}")
    if bad: return _fail(f"{len(bad)} domain terms: {bad[:3]}")
    return _ok("no domain-specific terms in framework scripts/ (exempt: download_*/retry_* helpers)")


def check_23_keys_not_hardcoded():
    keylike = re.compile(r"sk-(ant-|proj-|[A-Za-z0-9]{20,})")
    # The secret-scanner (guard_secrets.py) and this gate necessarily carry the
    # detection pattern literals themselves (e.g. "sk-ant-"). Skip them the same
    # way check_22 skips SELF_PATH, so the gate does not match its own / the
    # scanner's pattern strings. Real detection is unaffected: every other file
    # under scripts/ and config/ is still scanned.
    def _is_pattern_owner(path):
        return path.resolve() == SELF_PATH or path.name == "guard_secrets.py"
    bad = []
    for p in SCRIPTS.rglob("*.py"):
        if _is_pattern_owner(p): continue
        if keylike.search(p.read_text(encoding="utf-8")):
            bad.append(str(p.relative_to(ROOT)))
    for p in CONFIG.rglob("*"):
        if p.is_file():
            try:
                if keylike.search(p.read_text(encoding="utf-8", errors="ignore")):
                    bad.append(str(p.relative_to(ROOT)))
            except (OSError, UnicodeError): pass
    if bad: return _fail(f"key-like in: {bad}")
    return _ok("no hardcoded API keys (exempt: guard_secrets.py scanner + verify gate)")


def check_24_qwen_minimal_context():
    from bus_reader import QWEN_ALLOWED_LAW_IDS, assemble_context
    from constitution import Constitution
    from message_bus import MessageBus
    c = Constitution.load(CONFIG / "constitution.json")
    bus_path = _VERIFY_RUN.logs_dir() / "_verify_bus.jsonl"
    if bus_path.exists(): bus_path.unlink()
    bus = MessageBus.open(bus_path)
    pkg = assemble_context(backend="qwen_local", constitution=c, bus=bus, work_payload="x")
    bus_path.unlink()
    if pkg.recent_bus_text: return _fail("qwen included bus history")
    for law in c.seed_laws():
        word = re.compile(rf"\b{re.escape(law['id'])}\b")
        present = bool(word.search(pkg.governance_text))
        if law["id"] in QWEN_ALLOWED_LAW_IDS:
            if not present: return _fail(f"qwen missing {law['id']}")
        else:
            if present: return _fail(f"qwen has forbidden {law['id']}")
    return _ok("qwen receives only LAW-II + LAW-IV, no bus")


def check_25_async():
    import time
    from orchestrator import TopOrchestrator
    bus_path = _VERIFY_RUN.bus_path()
    if bus_path.exists(): bus_path.unlink()
    orch = TopOrchestrator.boot(interactive=False, run_adaptive_spawn=False, run_context=_VERIFY_RUN)
    def task(label, delay):
        def inner():
            time.sleep(delay); return label
        return inner
    delay = 0.4
    ga = [task("a1", delay), task("a2", delay)]; gb = [task("b1", delay), task("b2", delay)]
    t0 = time.monotonic()
    results = orch.execute_parallel_sync([ga, gb])
    elapsed = time.monotonic() - t0
    if results != [["a1", "a2"], ["b1", "b2"]]: return _fail(f"results: {results}")
    if elapsed >= 4 * delay: return _fail(f"no parallelism: {elapsed:.2f}s")
    return _ok(f"4 tasks in {elapsed:.2f}s vs {4 * delay}s serial (~{(4 * delay) / max(elapsed, 0.01):.2f}x)")


def check_26_block_interrupt():
    import threading
    import time
    from orchestrator import TopOrchestrator
    bus_path = _VERIFY_RUN.bus_path()
    if bus_path.exists(): bus_path.unlink()
    orch = TopOrchestrator.boot(interactive=False, run_adaptive_spawn=False, run_context=_VERIFY_RUN)
    handle = orch.raise_block(raised_by="VERIFIER", channel="main", reason="harness interrupt")
    if not orch.block_gate.is_blocked("main"): return _fail("not blocked")
    release_at = time.monotonic() + 0.3
    def releaser():
        while time.monotonic() < release_at: time.sleep(0.05)
        orch.release_block(handle.id, reason="harness lift")
    t = threading.Thread(target=releaser, daemon=True); t.start()
    def quick(): return "ok"
    t0 = time.monotonic()
    results = orch.execute_parallel_sync([[quick]], group_channels=["main"], timeout_per_group=5.0)
    elapsed = time.monotonic() - t0
    t.join(timeout=2.0)
    if results != [["ok"]]: return _fail(f"results: {results}")
    if elapsed < 0.2: return _fail(f"completed too fast: {elapsed:.3f}s")
    if not handle.released: return _fail("not released")
    if not orch.bus.query(msg_type="BLOCK"): return _fail("no BLOCK msg")
    return _ok(f"BLOCK gated ({elapsed:.2f}s), release={handle.release_reason!r}")


import durable_paths as _dp


@_nonmutating(
    _dp.linguistic_identity_path(ROOT),
    _dp.institution_registry_path(ROOT),
    _dp.speech_acts_taxonomy_path(ROOT),
    _dp.citation_convention_path(ROOT),
    _dp.situational_awareness_path(ROOT),
    _dp.spawn_log_path(ROOT),
)
def check_27_adaptive_spawn():
    """For Part XVIII Section F: adaptive_spawn reads from input/context/. We
    require LINGUISTIC_IDENTITY only when input/context/ has documents; in
    a structural verification pass we just confirm the helper is callable
    and produces a report (empty corpus -> empty actions is acceptable).
    Spawned assets now live in the protected durable/ tree (INFRA-030)."""
    from adaptive_spawn import spawn_all
    for p in [
        _dp.linguistic_identity_path(ROOT),
        _dp.institution_registry_path(ROOT),
        _dp.speech_acts_taxonomy_path(ROOT),
        _dp.citation_convention_path(ROOT),
        _dp.situational_awareness_path(ROOT),
    ]:
        if p.exists(): p.unlink()
    report = spawn_all(ROOT, overwrite=False)
    li_path = _dp.linguistic_identity_path(ROOT)
    if not li_path.exists():
        return _fail("LINGUISTIC_IDENTITY.md not created")
    second = spawn_all(ROOT, overwrite=False)
    if second.as_dict()["created_count"] != 0:
        return _fail("adaptive_spawn not idempotent on rerun")
    return _ok(f"spawn ok; {len(report.corpus_files)} corpus files; idempotent on rerun")


def check_28_input_dir():
    in_dir = ROOT / "input"
    if not in_dir.exists(): return _fail("input/ missing")
    return _ok("input/ exists and accepts documents")


def check_29_claude_md():
    p = ROOT / "CLAUDE.md"
    if not p.exists(): return _fail("CLAUDE.md missing")
    text = p.read_text(encoding="utf-8")
    if "genesis.md" not in text: return _fail("does not reference genesis.md")
    return _ok("CLAUDE.md points to genesis.md")


def check_30_pipeline_smoke():
    from orchestrator import TopOrchestrator
    bus_path = _VERIFY_RUN.bus_path()
    if bus_path.exists(): bus_path.unlink()
    orch = TopOrchestrator.boot(interactive=False, run_adaptive_spawn=False, run_context=_VERIFY_RUN)
    docs = orch.list_input_documents()
    payload = {"document_names": [d.name for d in docs], "document_count": len(docs),
               "phase": "situation_assessment"}
    orch.deliberation_round(payload)
    summary = orch.run_summary()
    if summary["total"] < len(EXPECTED_AGENTS) + 1:
        return _fail(f"too few bus messages: {summary['total']}")
    return _ok(f"boot+deliberate+summary on {len(docs)} docs ({summary['total']} msgs)")


def check_31_three_input_subdirs():
    """Part XVIII Section F: input/ has context/, operational/, conventions/."""
    base = ROOT / "input"
    for sub in ("context", "operational", "conventions"):
        if not (base / sub).is_dir():
            return _fail(f"input/{sub}/ missing")
    return _ok("input/{context,operational,conventions}/ present")


@_nonmutating(CONFIG / "convention_registry.json")
def check_32_convention_parser():
    """Part XVIII Section F: convention_parser produces valid convention_registry.json."""
    from convention_parser import parse_conventions, write_registry
    # Seed a temp conventions file so the parser has something to work on.
    conv_dir = ROOT / "input" / "conventions"
    conv_dir.mkdir(parents=True, exist_ok=True)
    seed_path = conv_dir / "_verify_seed.md"
    seed_text = (
        "# Terminology\n\n"
        "- Documents must use the term 'algorithmic system' instead of 'AI' in formal contexts.\n"
        "- Reviewers should prefer 'human oversight' over 'human-in-the-loop'.\n\n"
        "# Red flags\n\n"
        "- Reject claims of system autonomy without an accountability mechanism.\n"
    )
    seed_path.write_text(seed_text, encoding="utf-8")
    try:
        registry = parse_conventions(ROOT)
        path = write_registry(ROOT, registry)
        if not path.exists():
            return _fail("convention_registry.json not written")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("conventions"):
            return _fail("no conventions parsed from seed file")
        ids = {c["id"] for c in data["conventions"]}
        severities = {c["severity"] for c in data["conventions"]}
        if not ids:
            return _fail("conventions missing ids")
        return _ok(f"{len(data['conventions'])} conventions parsed; severities={sorted(severities)}")
    finally:
        seed_path.unlink(missing_ok=True)


def check_33_reference_builder():
    from reference_builder import ReferenceIndex
    idx_path = _VERIFY_RUN.reference_index_path()
    if idx_path.exists(): idx_path.unlink()
    idx = ReferenceIndex.open(ROOT, index_path=idx_path)
    sample_text = (
        "Article 1. This is the first paragraph of a sample document.\n\n"
        "Article 2. This is the second paragraph, which contains a verifiable claim.\n\n"
        "Article 3. The third paragraph closes the sample."
    )
    entries = idx.index_document(
        input_type="operational", document_id="verify_doc",
        document_name="verify_doc.txt", text=sample_text,
    )
    if len(entries) != 3:
        return _fail(f"expected 3 paragraphs, got {len(entries)}")
    idx.cite(entries[0].ref_id, "VERIFIER")
    idx.save()
    re_idx = ReferenceIndex.open(ROOT, index_path=idx_path)
    if re_idx.by_id[entries[0].ref_id].cited_by != ["VERIFIER"]:
        return _fail("cited_by lost on reload")
    idx_path.unlink(missing_ok=True)
    return _ok(f"reference index 3 entries with stable REF-* ids; reload preserved cited_by")


def check_34_amendment_drafter_contract():
    """Under the canonical envelope (INFRA-037) each AMENDMENT_DRAFTER item IS one
    amendment. The contract must require the traceability fields per item and
    define the amendment fields per Part XVIII Section D."""
    contracts = json.loads((CONFIG / "agent_contracts.json").read_text(encoding="utf-8"))
    c = contracts.get("contracts", {}).get("AMENDMENT_DRAFTER")
    if not c: return _fail("AMENDMENT_DRAFTER contract missing")
    req = set(c.get("required", []))
    needed_req = {"location", "convention_ref", "original_text", "action", "comment", "ref_ids"}
    if not needed_req <= req:
        return _fail(f"required missing {sorted(needed_req - req)}")
    fields = c.get("fields", {})
    needed = {"location", "convention_ref", "context_refs", "comment",
              "original_text", "proposed_text", "action", "severity"}
    missing = needed - set(fields)
    if missing: return _fail(f"missing fields: {sorted(missing)}")
    return _ok("AMENDMENT_DRAFTER amendment item requires location/convention_ref/comment/action/ref_ids")


def check_35_amendment_comment_citation_format():
    """Part XVIII Section F #35: every amendment.comment contains >=1 CONV-* and >=1 REF-*.
    Verified by exercising the amendment validator from pipeline (see pipeline._validate_amendment_comment).
    """
    try:
        from pipeline_amendment_validator import validate_amendment_comment
    except ImportError:
        return _fail("pipeline_amendment_validator.validate_amendment_comment missing")
    ok_comment = "[CONV-001] requires X. The operational text at [REF-0042] states Y."
    bad_comments = [
        "X requires Y but no reference is given.",
        "Only [CONV-001] referenced.",
        "Only [REF-0042] referenced.",
        "Random text with no brackets at all.",
    ]
    if not validate_amendment_comment(ok_comment):
        return _fail("validator rejected valid comment")
    for bc in bad_comments:
        if validate_amendment_comment(bc):
            return _fail(f"validator accepted invalid: {bc!r}")
    # INFRA-037: the flat citation array (ref_ids) is required on amendment items.
    contracts = json.loads((CONFIG / "agent_contracts.json").read_text(encoding="utf-8"))
    ad = contracts.get("contracts", {}).get("AMENDMENT_DRAFTER", {})
    if "ref_ids" not in set(ad.get("required", [])):
        return _fail("AMENDMENT_DRAFTER must require ref_ids (the flat citation array)")
    return _ok("validator enforces >=1 CONV-* and >=1 REF-*; ref_ids required per amendment item")


def check_36_summaries_for_cutoff_docs():
    """Part XVIII Section F #36: context_summary.md and operative_summary.md
    produced for cutoff docs. This is a structural check that the helpers
    exist; the actual content is exercised by the live pipeline."""
    try:
        from summary_generators import render_context_summary, render_operative_summary
    except ImportError:
        return _fail("summary_generators module missing")
    text = render_context_summary(document_id="x", document_name="x.pdf",
                                  context_refs=[{"ref_id": "REF-0001", "document_name": "ctx.pdf",
                                                 "location": {"page": 1, "paragraph": 1},
                                                 "text_excerpt": "sample"}],
                                  topics=["topic A"])
    if "REF-0001" not in text: return _fail("context summary missing ref")
    text2 = render_operative_summary(document_id="x", document_name="x.pdf",
                                     conventions_by_category={"terminology": [{"id": "CONV-001", "rule": "r"}]},
                                     findings=[])
    if "CONV-001" not in text2: return _fail("operative summary missing conv")
    return _ok("context_summary + operative_summary generators present and reference-bearing")


def check_37_review_scope_cutoff():
    """Part XVIII Section F #37: review_scope.json cutoff respected
    (pre-cutoff docs not amended)."""
    try:
        from review_scope import apply_cutoff
    except ImportError:
        return _fail("review_scope module missing")
    dated = [
        {"filename": "early.pdf", "date": "2020-01-01"},
        {"filename": "middle.pdf", "date": "2023-06-15"},
        {"filename": "recent.pdf", "date": "2024-09-09"},
        {"filename": "newest.pdf", "date": "2025-02-02"},
    ]
    op = apply_cutoff(dated, {"cutoff_type": "date", "cutoff_date": "2024-01-01"})
    if [d["filename"] for d in op] != ["recent.pdf", "newest.pdf"]:
        return _fail(f"date cutoff wrong: {[d['filename'] for d in op]}")
    op = apply_cutoff(dated, {"cutoff_type": "document_number", "cutoff_document_number": 3})
    if [d["filename"] for d in op] != ["recent.pdf", "newest.pdf"]:
        return _fail(f"doc# cutoff wrong: {[d['filename'] for d in op]}")
    op = apply_cutoff(dated, {"cutoff_type": "all"})
    if len(op) != 4: return _fail(f"'all' cutoff wrong: {len(op)}")
    op = apply_cutoff(dated, {"cutoff_type": "both", "cutoff_date": "2024-01-01",
                              "cutoff_document_number": 2})
    if len(op) != 3:
        return _fail(f"'both' cutoff wrong: {len(op)} (expected 3: whichever cuts more wins)")
    return _ok("cutoff respected across date, document_number, all, both")


def check_38_embedding_store():
    """Genesis Part XXI: the embedding store can build and query when
    sentence-transformers is installed; otherwise the verify passes with a
    WARN noting that the pipeline operates in Zipfian fallback mode. This
    check MUST NOT FAIL on machines without the library — Part XXI mandates
    graceful degradation, and the verify gate must respect that.
    """
    import tempfile

    try:
        import embedding_store
    except ImportError as e:
        return _fail(f"embedding_store module import failed: {e}")

    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return ("WARN",
                "sentence-transformers not installed; pipeline runs in Zipfian fallback mode")

    # Build a tiny store from a synthetic single-page PDF and query it.
    try:
        import pypdf  # noqa: F401
        from fpdf import FPDF
    except ImportError as e:
        return ("WARN",
                f"fpdf2/pypdf not installed; cannot exercise full store build ({e})")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        for line in (
            "Algorithmic systems require human oversight under all circumstances.",
            "Transparency and accountability are the foundations of trustworthy review.",
            "Risk classification distinguishes unacceptable, high, limited and minimal.",
        ):
            pdf.cell(0, 8, line, ln=1)
        pdf_path = tmp_path / "synthetic_test.pdf"
        pdf.output(str(pdf_path))
        store_path = tmp_path / "store.pkl"
        n = embedding_store.build_store(tmp_path, store_path)
        if n == 0:
            return ("WARN", "build_store returned 0 (graceful degradation path)")
        store = embedding_store.load_store(store_path)
        # Schema 2: passages live in per-model sub-stores, not a top-level list.
        n_passages = (sum(len(b.get("passages") or [])
                          for b in (store.get("models") or {}).values())
                      if store else 0)
        if store is None or n_passages == 0:
            return _fail("store loaded empty")
        hits = embedding_store.query_store(store, "human oversight of algorithmic systems", n=2)
        if not hits or "similarity" not in hits[0]:
            return _fail("query_store returned no usable hits")
        if hits[0]["similarity"] < 0.2:
            return _fail(f"top hit similarity too low: {hits[0]['similarity']:.3f}")
    return _ok(
        f"embedding store build+query ok ({n} passages, top sim={hits[0]['similarity']:.3f})"
    )


def check_39_canonical_envelope():
    """INFRA-037: every agent's output payload is the canonical wrapper
    {agent, doc_id, items:[flat items]}. For ALL 18 agents, a valid wrapper of one
    flat core-bearing item validates; a bare list, a bare dict, and an item with a
    nested object are all rejected; an empty items list is valid."""
    from agent_wrapper import AgentWrapper, is_envelope, decode_items
    from constitution import Constitution
    from message_bus import MessageBus
    c = Constitution.load(CONFIG / "constitution.json")
    bus_path = _VERIFY_RUN.logs_dir() / "_verify_env_bus.jsonl"
    if bus_path.exists(): bus_path.unlink()
    bus = MessageBus.open(bus_path)
    registry = json.loads((CONFIG / "agent_registry.json").read_text())["agents"]
    contracts = json.loads((CONFIG / "agent_contracts.json").read_text())["contracts"]
    for name in registry:
        w = AgentWrapper(name=name, constitution=c, bus=bus, registry=registry,
                         contracts=contracts, keys={"stub": "1"}, run_context=_VERIFY_RUN)
        item = {"ref": "REF-0001", "kind": "finding", "confidence": "CONFIDENT"}
        for rk in contracts.get(name, {}).get("required", []):
            item.setdefault(rk, "x")
        good = json.dumps({"agent": name, "doc_id": "d", "items": [item]})
        obj, missing = w.parse_contract_output(good)
        if missing: return _fail(f"{name}: valid wrapper rejected: {missing}")
        if not is_envelope(obj): return _fail(f"{name}: parser did not return the wrapper")
        if not all(k in decode_items(obj)[0] for k in ("item_id", "revision", "ts")):
            return _fail(f"{name}: runtime fields not stamped")
        _, m_bare = w.parse_contract_output(json.dumps(item))           # bare dict
        _, m_list = w.parse_contract_output(json.dumps([item]))         # bare list
        if not m_bare or not m_list:
            return _fail(f"{name}: bare dict/list accepted (not the wrapper)")
        nested = dict(item); nested["bad"] = {"nested": 1}              # not flat
        _, m_nest = w.parse_contract_output(json.dumps({"agent": name, "doc_id": "d", "items": [nested]}))
        if not any("flat" in str(x) for x in m_nest):
            return _fail(f"{name}: nested object accepted (flatness not enforced)")
    # empty items list is a valid 'nothing to report' result
    _, m_empty = w.parse_contract_output(json.dumps({"agent": name, "doc_id": "d", "items": []}))
    bus_path.unlink(missing_ok=True)
    if m_empty: return _fail(f"empty items rejected: {m_empty}")
    return _ok("all 18 agents enforce the canonical wrapper of flat core-bearing items")


def check_40_highest_revision():
    """INFRA-037 version guardrail: current_items / decode_items select the highest
    revision per item_id (tie-break latest ts), so a superseded value is never read."""
    from agent_wrapper import current_items, decode_items
    items = [
        {"item_id": "a", "revision": 1, "ts": "2026-01-01T00:00:00Z", "v": "old"},
        {"item_id": "a", "revision": 3, "ts": "2026-01-02T00:00:00Z", "v": "mid"},
        {"item_id": "a", "revision": 3, "ts": "2026-01-03T00:00:00Z", "v": "newest"},  # tie -> latest ts
        {"item_id": "b", "revision": 1, "ts": "2026-01-01T00:00:00Z", "v": "b"},
    ]
    cur = {it["item_id"]: it["v"] for it in current_items(items)}
    if cur.get("a") != "newest": return _fail(f"highest-revision wrong: {cur}")
    if cur.get("b") != "b": return _fail("dropped a distinct item_id")
    d = {it["item_id"]: it["v"] for it in decode_items({"agent": "X", "doc_id": "d", "items": items})}
    if d.get("a") != "newest": return _fail("decode_items did not apply current-revision selection")
    return _ok("current revision selected per item_id (tie-break latest ts)")


def check_41_redaction_rules():
    """INFRA-038 (parser widened): conventions compile into operator REDACTION
    RULES the redactors APPLY (no model sensitivity judgment). Recognition is by
    KEYWORD category (confiden/redact/privacy/pii in category OR id) and by
    redaction PHRASING (redact verbs OR prohibition phrasing). redaction_rules
    REPORTS operator-in-force vs defaults and never silently drops a redaction-
    intent convention that fails to compile."""
    from sensitivity_layer import redaction_rules, DEFAULT_REDACTION_RULES
    # empty registry -> NO rules + source 'none' (1c: no silent default floor)
    empty = redaction_rules({"conventions": []})
    if empty["operator_in_force"] or empty["source"] != "none":
        return _fail("empty registry should report source=none, operator_in_force=False (1c)")
    if empty["rules"] or empty["warnings"]:
        return _fail("empty registry should yield NO rules (no default floor) and no warnings")
    # the real failure case from the field: CONV-CONFIDENTIALITY (category slug
    # "conv-confidentiality") + prohibition phrasing "must not contain ..." must now
    # COMPILE as an operator rule (keyword category + prohibition phrasing).
    reg = {"conventions": [
        {"id": "CONV-CONFIDENTIALITY", "category": "conv-confidentiality",
         "rule": "must not contain confidential business figures (a named company's turnover) "
                 "or personal identifiers (an individual's name together with an identity number)",
         "action": "flag", "severity": "required"},
        {"id": "CONV-001", "category": "identity", "rule": "use formal register", "action": "flag"}]}
    res = redaction_rules(reg)
    op_ids = {r["id"] for r in res["operator_rules"]}
    if "CONV-CONFIDENTIALITY" not in op_ids:
        return _fail(f"CONV-CONFIDENTIALITY did not compile as an operator rule: {op_ids}")
    if "CONV-001" in op_ids:
        return _fail("a non-redaction convention leaked into operator redaction rules")
    if not res["operator_in_force"] or res["source"] != "operator":
        return _fail("operator rule not reported in force (source must be 'operator', no floor)")
    # no silent fallback: redaction-intent (privacy category) with no rule text WARNS
    res2 = redaction_rules({"conventions": [{"id": "CONV-PRIV", "category": "privacy", "rule": "", "action": "flag"}]})
    if not any(w["id"] == "CONV-PRIV" for w in res2["warnings"]):
        return _fail("redaction-intent convention with no rule text was silently dropped (no warning)")
    if res2["operator_in_force"]:
        return _fail("an uncompilable redaction-intent convention must not count as in force")
    return _ok("widened compiler: keyword category + prohibition phrasing compile; "
               "operator-vs-defaults reported; uncompilable redaction-intent warns (no silent fallback)")


def check_42_may_use_web_enforced():
    """INFRA-038: may_use_web is a REAL, consumed control. search_router refuses a
    roster agent whose flag is false, permits a web-enabled agent past the guard,
    and permits a system/intake caller (agent=None). Confirms redactors (false)
    can never be routed to the web."""
    from search_router import SearchRouter, agent_may_use_web
    registry = json.loads((CONFIG / "agent_registry.json").read_text())["agents"]
    if agent_may_use_web(registry, "REDACTOR"):
        return _fail("REDACTOR must not have may_use_web")
    if not agent_may_use_web(registry, "FACT_CHECKER"):
        return _fail("FACT_CHECKER should have may_use_web")
    r = SearchRouter.open(ROOT)
    try:
        r.search("x", agent="REDACTOR")
        return _fail("non-web agent was NOT refused at the search boundary")
    except PermissionError:
        pass
    # the guard for a web-enabled agent must pass (we do not run the live query here)
    if not agent_may_use_web(r.registry, "FACT_CHECKER"):
        return _fail("router registry not loaded / FACT_CHECKER not web-enabled")
    return _ok("may_use_web enforced at the search boundary (redactors refused; web agents allowed)")


def check_43_sensitivity_layer_gate():
    """INFRA-038: the full LAW-IV sensitivity layer is BUILT BUT UNWIRED (inactive),
    and its inactive-state override is recorded to the governance ledger — mirroring
    the redaction-waiver pattern. The masking hook is inert (pass-through) while
    inactive and never invoked by control flow."""
    import sensitivity_layer
    if sensitivity_layer.is_active():
        return _fail("sensitivity layer must be INACTIVE in Stage 3a (built-but-unwired)")
    # inert masking hook is a transparent pass-through while inactive
    sentinel = {"x": 1}
    if sensitivity_layer.mask_for_external(sentinel) is not sentinel:
        return _fail("inactive masking hook must be a pass-through")
    # dormant routing predicate reads the registry flag
    registry = json.loads((CONFIG / "agent_registry.json").read_text())["agents"]
    if not sensitivity_layer.may_handle_sensitive(registry, "REDACTOR"):
        return _fail("REDACTOR should be may_handle_sensitive (dormant on-switch)")
    if sensitivity_layer.may_handle_sensitive(registry, "PROCESSOR"):
        return _fail("PROCESSOR should not be may_handle_sensitive")
    # logged override writes to the governance ledger (write to a throwaway run root)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = sensitivity_layer.record_sensitivity_override(Path(tmp), "verify-run", reason="test")
        if not p.exists() or "sensitivity_overrides" not in p.name:
            return _fail("override not written to the governance ledger")
        rec = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
        if rec.get("event") != "SENSITIVITY_LAYER_INACTIVE_OVERRIDE":
            return _fail("override ledger record malformed")
    return _ok("sensitivity layer inactive; inert masking + dormant routing; override logged to ledger")


def check_44_redactor_contract_pins():
    """Redaction silent-pass fix: the REDACTOR contract pins kind=redaction and
    carries a rule_id attribution field, and the per-agent worked example is
    redaction-shaped (not the generic kind='finding' example that bled in)."""
    contracts = json.loads((CONFIG / "agent_contracts.json").read_text(encoding="utf-8"))["contracts"]
    c = contracts.get("REDACTOR", {})
    if not str(c.get("item_kind", "")).strip().lower().startswith("redaction"):
        return _fail("REDACTOR item_kind does not pin 'redaction'")
    fields = c.get("fields", {})
    if "rule_id" not in fields:
        return _fail("REDACTOR contract has no rule_id attribution field")
    if "redaction" not in str(fields.get("kind", "")).lower():
        return _fail("REDACTOR contract field 'kind' does not pin the value redaction")
    # the worked example the clerk actually receives must be redaction-shaped
    from agent_wrapper import AgentWrapper
    class _S: pass
    s = _S(); s.name = "REDACTOR"; s.contract = {"fields": {}, "required": []}
    s._worked_item_example = AgentWrapper._worked_item_example.__get__(s)
    ex = s._worked_item_example()
    if '"kind": "redaction"' not in ex or "rule_id" not in ex:
        return _fail("REDACTOR worked example is not redaction-shaped (kind=redaction + rule_id)")
    # a non-redaction agent still gets the generic finding example
    s2 = _S(); s2.name = "FACT_CHECKER"; s2.contract = {"fields": {}, "required": []}
    s2._worked_item_example = AgentWrapper._worked_item_example.__get__(s2)
    if '"kind": "finding"' not in s2._worked_item_example():
        return _fail("non-redaction agent lost its finding example")
    return _ok("REDACTOR pins kind=redaction + rule_id; worked example is redaction-shaped")


def check_45_redaction_structural_no_silent_none():
    """Redaction silent-pass fix: phase_9 detects redactions STRUCTURALLY (span +
    replacement/method/redaction-category), not by the kind tag alone, and never
    silently resolves a non-empty-but-unresolved clerk result to NONE."""
    from sensitivity_layer.redaction_stage import (_is_redaction_proposal,
        _classify_redactor_items, _norm_redaction_category)
    # the exact rehearsal failure: a real redaction MIS-TAGGED kind='finding' is detected
    mistag = {"kind": "finding", "span": "رقم الهوية 0000-1111-2222", "category": "confidentiality",
              "replacement": "[REDACTED]", "method": "REDACT", "rule_id": "CONV-006"}
    if not _is_redaction_proposal(mistag):
        return _fail("structural detection missed a redaction mis-tagged kind='finding'")
    # a plain finding (no span / no redaction signal) is NOT a redaction
    if _is_redaction_proposal({"kind": "finding", "ref": "R", "reasoning": "x"}):
        return _fail("a non-redaction finding was treated as a redaction")
    # classify: empty -> NONE; non-empty-unresolved -> BLOCK; mis-tagged -> PROPOSE
    if _classify_redactor_items([])[0] != "NONE":
        return _fail("empty items must be a legitimate NONE")
    if _classify_redactor_items([{"kind": "finding", "ref": "R"}])[0] != "BLOCK":
        return _fail("non-empty-but-unresolved must BLOCK, never silent NONE")
    outcome, reds = _classify_redactor_items([mistag])
    if outcome != "PROPOSE" or not reds:
        return _fail("a structurally-valid redaction did not resolve to PROPOSE")
    # category normalized: conv-confidentiality == confidentiality
    if _norm_redaction_category("conv-confidentiality") != "confidentiality":
        return _fail("category normalization failed (conv-confidentiality != confidentiality)")
    if reds[0]["category"] != "confidentiality":
        return _fail("classified redaction did not carry a normalized category")
    return _ok("structural redaction detection + category normalization; non-empty-unresolved BLOCKS, empty is NONE")


def check_46_redaction_applies_to_all_artifacts():
    """Redaction APPLICATION fix (defect A + C): approved spans are scrubbed from
    EVERY operator-facing artifact (not only the amendments master), and the matcher
    tolerates benign Arabic variation (ال-prefix, intervening connective, whitespace)
    so the literal-match miss from the paid run can no longer drop a span."""
    import inspect
    from sensitivity_layer.scrub import (_sub_span, _count_span, _redact_obj,
                                         scrub_text_artifacts_and_verify)
    from sensitivity_layer.redaction_stage import run_redaction_phase
    import pipeline
    # (C) the EXACT paid-run mismatch: clerk merged span vs document text with the
    # ال prefix and the "، رقم الهوية" connective between name and id.
    clerk_span = "سيد/ خالد المنصور 0000-1111-2222"
    doc_text = ("ويتولى ملف هذا التركز السيد/ خالد المنصور، رقم الهوية 0000-1111-2222.")
    if clerk_span in doc_text:
        return _fail("test premise broken: the merged span should NOT match literally")
    new, n = _sub_span(doc_text, clerk_span, "[REDACTED]")
    if n < 1 or "خالد المنصور" in new or "0000-1111-2222" in new:
        return _fail("normalized matcher failed to locate/scrub the merged ال+connective span")
    # atomic spans (post clerk-nudge) match literally too
    for s in ("خالد المنصور", "0000-1111-2222", "الواحة القابضة", "4.2 مليار"):
        if _count_span(doc_text + " الواحة القابضة 4.2 مليار", s) < 1:
            return _fail(f"atomic span not matched: {s!r}")
    # (A-master) the master scrub covers EVERY string leaf, not just 3 fields
    master = {"amendments": [{"original_text": "x الواحة القابضة y",
                              "nested": {"deep": "الواحة القابضة"}}]}
    sm, nn = _redact_obj(master, [{"span": "الواحة القابضة"}])
    if nn < 2 or "الواحة القابضة" in json.dumps(sm, ensure_ascii=False):
        return _fail("master scrub did not cover all string leaves (defect A on master)")
    # (A-artifacts) shape (a) split (1c relocation): the privacy verify targets the
    # INDEPENDENT text artifacts; the editorial RENDER stays pipeline-side and is
    # injected into the relocated privacy stage as the render_deliverable callback.
    # Assert (i) the privacy verify still targets every artifact, (ii) the relocated
    # stage invokes the injected render callback between produce and verify, and
    # (iii) the pipeline wires write_amendment_deliverables as that callback. So the
    # render is editorial-side and there is no privacy->editorial edge.
    vsrc = inspect.getsource(scrub_text_artifacts_and_verify)
    for key in ("per_agent_deliverable", "context_summary", "operative_summary"):
        if key not in vsrc:
            return _fail(f"verify path does not target {key} (defect A: master-only apply)")
    if "render_deliverable(" not in inspect.getsource(run_redaction_phase):
        return _fail("relocated stage no longer invokes the injected render callback")
    # the real edge test: the privacy stage MODULE must not import the editorial
    # render/pipeline (a comment mention is fine; an import is the forbidden edge).
    import ast as _ast
    from sensitivity_layer import redaction_stage as _stage_mod
    _imports = set()
    for _n in _ast.walk(_ast.parse(inspect.getsource(_stage_mod))):
        if isinstance(_n, _ast.Import):
            _imports.update(a.name.split(".")[0] for a in _n.names)
        elif isinstance(_n, _ast.ImportFrom) and _n.module:
            _imports.add(_n.module.split(".")[0])
    if {"amendment_render", "pipeline"} & _imports:
        return _fail("privacy stage imports editorial render/pipeline (privacy->editorial edge)")
    if "write_amendment_deliverables" not in inspect.getsource(pipeline):
        return _fail("pipeline no longer wires write_amendment_deliverables as the render callback")
    return _ok("approved spans scrubbed from every artifact; render stays editorial via injected callback (no privacy->editorial edge)")


def check_47_redaction_outcome_verified():
    """Redaction APPLICATION fix (defect B + D + the real gate): the LIVE survivor path
    `scrub_text_artifacts_and_verify` is EXECUTED (no longer a dead fossil) on three
    scenarios — it scrubs the on-disk text artifacts then re-greps EVERY artifact:
    (a) all-clean -> applied == proposed, zero dropped, zero survivors;
    (b) located-nowhere -> the span is reported in `dropped` (no silent zero-match);
    (c) planted-survivor (a replacement that re-introduces the span) -> reported in
    `survivors` and BLOCKS. This FAILS if the live survivor grep (scrub.py ~314-316) is
    removed or neutered. Uses throwaway temp files (the live fn writes the scrubbed
    artifact to disk); makes no repo mutation."""
    import tempfile
    from sensitivity_layer.scrub import scrub_text_artifacts_and_verify, _span_list
    from sensitivity_layer.redaction_stage import (build_redaction_escalation,
                          _REDACTION_FAILURE, _REDACTION_PUBLIC_KINDS)

    def _run(artifact_text, reds):
        # Drive the LIVE function on a throwaway on-disk text artifact (it scrubs in
        # place, then re-greps). Seed located/by_artifact exactly as the live caller does.
        d = Path(tempfile.mkdtemp(prefix="shimmer_v47_"))
        p = d / "x__deliverable.md"
        p.write_text(artifact_text, encoding="utf-8")
        info = {"per_agent_deliverable": str(p)}
        located = {span: 0 for span, _ in _span_list(reds)}
        return scrub_text_artifacts_and_verify(reds, info, located, {})

    # (a) all-clean: both spans present and cleanly scrubbed
    clean = _run("x خالد المنصور y 0000-1111-2222 z",
                 [{"span": "خالد المنصور", "replacement": "[REDACTED]"},
                  {"span": "0000-1111-2222", "replacement": "[REDACTED]"}])
    if clean["dropped"] or clean["survivors"] or clean["applied"] != clean["proposed"]:
        return _fail(f"clean apply misreported: dropped={clean['dropped']} survivors={clean['survivors']} "
                     f"applied={clean['applied']}/{clean['proposed']}")
    # (D) counts are span-based ACTUAL substitutions, never the proposal count
    if clean["by_artifact"].get("per_agent_deliverable") != 2:
        return _fail(f"by_artifact counts are not span-based actual substitutions: {clean['by_artifact']}")
    # (b) a span located NOWHERE -> dropped (no silent zero-match)
    drop = _run("nothing here", [{"span": "غير موجود", "replacement": "[REDACTED]"}])
    if not drop["dropped"] or drop["applied"] != 0:
        return _fail(f"a span located nowhere must be 'dropped' (no silent zero-match): {drop}")
    # (c) planted survivor: the replacement re-introduces the span -> the re-grep must
    # catch it. THIS is what fails if the survivor grep is removed.
    surv = _run("خالد المنصور",
                [{"span": "خالد المنصور", "replacement": "خالد المنصور (kept)"}])
    if not surv["survivors"]:
        return _fail("LIVE survivor grep did not catch a surviving span (real gate inert)")
    # the two application-layer BLOCK kinds exist and surface to the operator
    for fk in ("span_dropped", "pii_survives_in_deliverable"):
        if fk not in _REDACTION_FAILURE or fk not in _REDACTION_PUBLIC_KINDS:
            return _fail(f"failure_kind {fk} missing from taxonomy / not operator-visible")
        esc = build_redaction_escalation(doc_id="d", document_name="d", stage="REDACT_APPLY",
                                         failure_kind=fk, raw_output_path=None,
                                         detail={"survivors": {"s": ["x"]}})
        if esc["failure_kind"] != fk or "detail" not in esc:
            return _fail(f"escalation for {fk} not surfaced with detail")
    return _ok("LIVE survivor path executed (scrub_text_artifacts_and_verify): clean OK, "
               "located-nowhere -> dropped, planted survivor -> survivors+BLOCK")


def check_48_qwen_shared_model_cache():
    """Shared local-model load: qwen_local agents reuse ONE resident instance per
    model_id (multiple qwen_local agents on the same model_id share a single 7B
    instead of each loading its own, which is what broke the old tier ladder).
    Verifies the cache returns the SAME object on repeat
    and that call_qwen routes through the shared loader — without loading a real 7B."""
    import inspect
    from agent_wrapper import _load_qwen, _QWEN_MODELS, _QWEN_LOAD_LOCK, AgentWrapper
    # the cache must be keyed and lock-guarded
    if not hasattr(_QWEN_LOAD_LOCK, "acquire"):
        return _fail("no load lock guarding the shared qwen model cache")
    # fast path: a pre-seeded model_id returns the SAME instance on every call (no reload)
    key = "__verify_sentinel_model__"
    sentinel = (object(), object())
    _QWEN_MODELS.pop(key, None)
    _QWEN_MODELS[key] = sentinel
    try:
        a = _load_qwen(key)
        b = _load_qwen(key)
        if a is not sentinel or b is not sentinel or a is not b:
            return _fail("shared cache did not return the one resident instance for a model_id")
    finally:
        _QWEN_MODELS.pop(key, None)            # leave module state as we found it
    # call_qwen must route loads through the shared loader (no inline second copy)
    src = inspect.getsource(AgentWrapper.call_qwen)
    if "_load_qwen" not in src:
        return _fail("call_qwen does not load via the shared _load_qwen cache")
    if "from_pretrained" in src:
        return _fail("call_qwen still loads its own model copy (from_pretrained inline)")
    return _ok("qwen_local shares one resident instance per model_id (lock-guarded); call_qwen uses it")


def check_49_no_silent_default_floor():
    """1c (operator-sovereignty): redaction_rules() has NO automatic engine-default
    floor. With no operator rule in force, rules is EMPTY (caller hard-stops); the
    built-in ruleset applies ONLY on conscious opt-in; the no_operator_rule BLOCK is
    wired and operator-visible."""
    from sensitivity_layer import redaction_rules, DEFAULT_REDACTION_RULES
    from sensitivity_layer.redaction_stage import _REDACTION_FAILURE, _REDACTION_PUBLIC_KINDS, build_redaction_escalation
    op_reg = {"conventions": [{"id": "CONV-X", "category": "conv-confidentiality", "action": "flag",
              "rule": "must not contain an individual's identity number or turnover figures"}]}
    rr = redaction_rules(op_reg)
    if not rr["operator_in_force"] or rr["rules"] != rr["operator_rules"]:
        return _fail("operator-in-force rules must be exactly the operator rules (no default floor)")
    none = redaction_rules({"conventions": []})
    if none["operator_in_force"] or none["rules"] or none["source"] != "none":
        return _fail("no-operator-rule must yield EMPTY rules + source 'none' (no silent default floor)")
    optin = redaction_rules({"conventions": []}, opt_in_default_ruleset=True)
    if optin["rules"] != list(DEFAULT_REDACTION_RULES):
        return _fail("conscious opt-in must apply exactly the named default ruleset")
    if "no_operator_rule" not in _REDACTION_FAILURE or "no_operator_rule" not in _REDACTION_PUBLIC_KINDS:
        return _fail("no_operator_rule BLOCK not wired / not operator-visible")
    esc = build_redaction_escalation(doc_id="d", document_name="d", stage="REDACT_RULES",
                                     failure_kind="no_operator_rule", raw_output_path=None)
    if esc["failure_kind"] != "no_operator_rule":
        return _fail("no_operator_rule escalation not surfaced")
    return _ok("no silent default floor; empty rules + hard-stop when no operator rule; defaults opt-in only")


def check_50_deterministic_detection_language_neutral():
    """1b: deterministic detectors fire ONLY for operator-authorized categories, emit
    canonical INFRA-037 items, merge/de-dupe with model proposals, load vocabulary
    from the DATA resource, and contain ZERO language literals + no network import."""
    import inspect, ast as _ast
    from sensitivity_layer import redaction_detect as D
    from sensitivity_layer.scrub import (_merge_redaction_proposals, _redaction_span_regex,
                                         _norm_span_key, _norm_classes)
    cues = D.load_cues(str(ROOT))
    if not cues:
        return _fail("language DATA resource (config/language_redaction_cues.json) missing/empty")
    op_rules = [{"id": "CONV-006", "category": "confidentiality",
                 "rule": "must not contain a turnover figure or an identity number for a named individual"}]
    # authorized -> detectors fire; unauthorized (no operator rule) -> nothing fires
    txt = "ref 0000-1111-2222 and 4.2 million reported"
    fired = D.detect(str(ROOT), txt, op_rules)
    if not any(it["detector"] == "identifier" for it in fired):
        return _fail("identifier detector did not fire for an operator-authorized category")
    for it in fired:  # canonical INFRA-037 shape + rule attribution
        for k in ("span", "category", "replacement", "method", "kind", "rule_id"):
            if k not in it:
                return _fail(f"deterministic item missing canonical field {k}")
        if it["kind"] != "redaction" or it["rule_id"] != "CONV-006":
            return _fail("deterministic item not canonical redaction / wrong rule attribution")
    if D.detect(str(ROOT), txt, []):
        return _fail("detector fired with NO operator rule (engine asserting sensitivity)")
    # merge de-dupes by normalized span (deterministic attribution wins)
    merged = _merge_redaction_proposals([{"span": "0000-1111-2222", "rule_id": "DET"}],
                                        [{"span": "0000-1111-2222", "rule_id": "MODEL"}])
    if len(merged) != 1 or merged[0]["rule_id"] != "DET":
        return _fail("merge did not de-dupe by normalized span / lost deterministic attribution")
    # LANGUAGE-NEUTRAL: detector + cue/normalizer code carries no non-ASCII char and
    # no multi-word DATA cue phrase; vocabulary lives only in the resource.
    srcs = [inspect.getsource(D)]
    for fn in (_redaction_span_regex, _norm_span_key, _norm_classes):
        srcs.append(inspect.getsource(fn))
    blob = "\n".join(srcs)
    nonascii = [c for c in blob if ord(c) > 127]
    if nonascii:
        return _fail(f"language literal (non-ASCII) in detector/cue code: {sorted(set(nonascii))[:8]}")
    phrases = []
    for entry in cues.values():
        for key in ("titles", "magnitude_words", "currency_words", "connectives", "definite_articles"):
            phrases += [w for w in (entry.get(key) or [])]
        for vals in (entry.get("shape_cues") or {}).values():
            phrases += list(vals)
    leaked = [p for p in phrases if " " in p and p in blob]
    if leaked:
        return _fail(f"multi-word DATA vocabulary appears as a literal in code: {leaked[:5]}")
    # no network/translation import in the detector module
    tree = _ast.parse(inspect.getsource(D))
    mods = set()
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Import):
            mods.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, _ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    banned = {"socket", "requests", "urllib", "http", "httpx", "openai", "anthropic", "googletrans"}
    if mods & banned:
        return _fail(f"detector module imports a network/translation library: {mods & banned}")
    return _ok("deterministic detection authorized-only, canonical, merged/de-duped, DATA-driven, no literals/network")


def check_51_editorial_structural():
    """INFRA-040 BUILD C: the SIX-RANK editorial review board is privacy-free and FAMILY-SPLIT.
    For ALL SIX ranks (EDITOR_CLERK, EDITOR_HEAD_OF_UNIT, EDITOR_HEAD_OF_SECTION,
    EDITOR_HEAD_OF_DEPARTMENT, EDITOR_DEPUTY_DG, EDITOR_DG): present in registry + contracts +
    EXPECTED_AGENTS; category editorial; may_use_web false; may_handle_sensitive false; contract
    verdict constrained to EXACTLY {sound, concern, serious_concern} with required
    ref+verdict+rationale; worked example a valid INFRA-037 envelope carrying a verdict in the
    set and free of 'redact' in any spelling; and the rank NAME carries no 'redact'/'rédact'.
    FAMILY SPLIT (the assertion that makes 'gate green' mean the 3/3 decorrelated split is
    real): the bottom three ranks are backend claude_api, the top three are backend openai_api.
    Plus the runtime structural detector + valid-verdict set, and no sensitivity_layer reference
    anywhere in the board (phase + dispatch helper)."""
    from agent_wrapper import AgentWrapper, is_envelope, decode_items
    reg = json.loads((CONFIG / "agent_registry.json").read_text(encoding="utf-8"))["agents"]
    con = json.loads((CONFIG / "agent_contracts.json").read_text(encoding="utf-8"))["contracts"]
    claude_ranks = ("EDITOR_CLERK", "EDITOR_HEAD_OF_UNIT", "EDITOR_HEAD_OF_SECTION")
    gpt_ranks = ("EDITOR_HEAD_OF_DEPARTMENT", "EDITOR_DEPUTY_DG", "EDITOR_DG")
    expected_backend = {**{r: "claude_api" for r in claude_ranks},
                        **{r: "openai_api" for r in gpt_ranks}}
    valid_set = {"sound", "concern", "serious_concern"}
    for rank, want_backend in expected_backend.items():
        if "redact" in rank.lower() or "rédact" in rank.lower():
            return _fail(f"{rank}: editorial rank NAME contains 'redact' (editorial house must be redaction-free)")
        if rank not in reg or rank not in con:
            return _fail(f"{rank} missing from registry/contracts")
        if rank not in EXPECTED_AGENTS:
            return _fail(f"{rank} missing from EXPECTED_AGENTS")
        spec = reg[rank]
        if spec.get("category") != "editorial":
            return _fail(f"{rank} must be category editorial")
        if spec.get("may_use_web") or spec.get("may_handle_sensitive"):
            return _fail(f"{rank} must be may_use_web false and may_handle_sensitive false (privacy-free)")
        if spec.get("backend") != want_backend:
            return _fail(f"FAMILY SPLIT broken: {rank} backend={spec.get('backend')!r} (expected {want_backend})")
        c = con[rank]
        vfield = str(c.get("fields", {}).get("verdict", "")).lower()
        for v in valid_set:
            if v not in vfield:
                return _fail(f"{rank} contract verdict field does not document '{v}'")
        if not {"ref", "verdict", "rationale"} <= set(c.get("required", [])):
            return _fail(f"{rank} contract required must include ref, verdict, rationale")
        # worked example: valid canonical envelope, verdict in the set, redaction-free
        class _S: pass
        s = _S(); s.name = rank; s.contract = {"fields": {}, "required": []}
        s._worked_item_example = AgentWrapper._worked_item_example.__get__(s)
        ex = s._worked_item_example()
        if "redact" in ex.lower():
            return _fail(f"{rank} worked example contains 'redact' (editorial house must be redaction-free)")
        obj = json.loads(ex)
        if not is_envelope(obj):
            return _fail(f"{rank} worked example is not the canonical INFRA-037 envelope")
        its = decode_items(obj)
        if not its or str(its[0].get("verdict", "")).lower() not in valid_set:
            return _fail(f"{rank} worked example verdict is not in the valid set")
    # runtime structural detector + valid-verdict set + the ladder order (editorial house)
    from pipeline import _is_editorial_observation, _EDITORIAL_VALID_VERDICTS, _EDITORIAL_RANKS
    if set(_EDITORIAL_VALID_VERDICTS) != valid_set:
        return _fail("editorial valid-verdict set is not exactly {sound, concern, serious_concern}")
    if tuple(_EDITORIAL_RANKS) != claude_ranks + gpt_ranks:
        return _fail(f"_EDITORIAL_RANKS ladder mismatch: {tuple(_EDITORIAL_RANKS)}")
    if not _is_editorial_observation({"ref": "REF-1", "verdict": "concern", "rationale": "x"}):
        return _fail("structural detection missed a ref+verdict+rationale observation")
    if _is_editorial_observation({"ref": "R", "verdict": "concern"}):
        return _fail("structural detection accepted an observation missing rationale")
    import inspect
    from pipeline import phase_6_5_editorial_review, _dispatch_rank
    board_src = inspect.getsource(phase_6_5_editorial_review) + inspect.getsource(_dispatch_rank)
    if "sensitivity_layer" in board_src:
        return _fail("editorial board references sensitivity_layer (must reuse no privacy mechanic)")
    return _ok("six-rank board privacy-free; FAMILY SPLIT verified (3 claude_api: CLERK/UNIT/SECTION + "
               "3 openai_api: DEPARTMENT/DEPUTY_DG/DG); verdict set {sound,concern,serious_concern}; "
               "envelopes valid; redaction-free")


def check_52_editorial_ordering():
    """INFRA-039 ordering guarantee: EDITOR_CLERK (phase 6.5) runs in execution order AFTER
    phase_6_synthesis (which runs AMENDMENT_DRAFTER, the last editorial producer) and
    BEFORE phase 7 and BEFORE the phase 9 privacy scrub, reading the CLEAN pre-scrub
    master. Enforced by source-order introspection of pipeline.main plus the editorial
    phase reading the assembled master and never mutating/scrubbing it (advisory only)."""
    import inspect
    import pipeline
    src = inspect.getsource(pipeline.main)
    i_syn = src.find("phase_6_synthesis(")
    i_ed = src.find("phase_6_5_editorial_review(")
    i_red = src.find("run_redaction_phase(")
    if not (0 <= i_syn < i_ed < i_red):
        return _fail(f"execution order wrong: synthesis={i_syn} editorial={i_ed} redaction={i_red} "
                     f"(must be synthesis < editorial < redaction)")
    esrc = inspect.getsource(pipeline.phase_6_5_editorial_review)
    if "amendments_json" not in esrc or "read_text" not in esrc:
        return _fail("editorial phase does not read the assembled master (pre-scrub)")
    # Advisory: the editorial phase must not MUTATE the master (the privacy scrub does
    # master.clear()/master.update(); the editorial phase must do neither, and must not
    # write the master file). Checked on real mutation patterns, not on docstring words.
    if "master.clear" in esrc or "master.update" in esrc or ".write_text" in esrc:
        return _fail("editorial phase mutates the master (must be advisory: clean read, no master write)")
    return _ok("EDITOR_CLERK ordered after synthesis (AMENDMENT_DRAFTER) and before phase 7 + phase 9 scrub; reads clean master; advisory")


def check_53_editorial_board_bounded():
    """INFRA-040: the rank-to-rank escalation loop is PROVABLY bounded. By source inspection,
    phase_6_5_editorial_review reads max_rounds from the resolved board tunables and breaks
    at/over the cap (rounds >= max_rounds -> terminal) BEFORE incrementing the rank, so the
    climb can never run forever. The operator config carries max_rounds (default 5),
    confidence_threshold, and out_of_mandate_trigger, and the resolver default for max_rounds
    is 5. Removing the cap guard (or moving it after the increment) FAILS this check."""
    import inspect
    from pipeline import phase_6_5_editorial_review, _EDITORIAL_BOARD_DEFAULTS
    src = inspect.getsource(phase_6_5_editorial_review)
    if 'tunables.get("max_rounds"' not in src and "tunables.get('max_rounds'" not in src:
        return _fail("loop does not read max_rounds from the resolved board tunables")
    if "rounds >= max_rounds" not in src:
        return _fail("loop has no `rounds >= max_rounds` cap guard (unbounded climb risk)")
    # the cap guard must PRECEDE the rank increment (guard before climb, never after)
    i_guard = src.find("rounds >= max_rounds")
    i_climb = src.find("rank_idx += 1")
    if not (0 <= i_guard < i_climb):
        return _fail("cap guard does not precede the rank increment (a climb could bypass the cap)")
    # operator config present + carries the three tunables; resolver default max_rounds is 5
    cfg_path = CONFIG / "editorial_board.json"
    if not cfg_path.exists():
        return _fail("config/editorial_board.json missing (operator tunables)")
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return _fail(f"editorial_board.json invalid JSON: {e}")
    for k in ("max_rounds", "confidence_threshold", "out_of_mandate_trigger"):
        if k not in cfg:
            return _fail(f"editorial_board.json missing tunable {k!r}")
    if not isinstance(cfg["max_rounds"], int) or cfg["max_rounds"] < 1:
        return _fail(f"editorial_board.json max_rounds must be a positive int, got {cfg['max_rounds']!r}")
    if _EDITORIAL_BOARD_DEFAULTS.get("max_rounds") != 5:
        return _fail(f"resolver default max_rounds expected 5, got {_EDITORIAL_BOARD_DEFAULTS.get('max_rounds')!r}")
    return _ok(f"bounded loop: `rounds>=max_rounds` cap before the climb; config max_rounds="
               f"{cfg['max_rounds']} (default 5), confidence_threshold={cfg['confidence_threshold']}, "
               f"out_of_mandate_trigger={cfg['out_of_mandate_trigger']}")


def check_54_editorial_board_no_operator_escalate():
    """INFRA-040: rank-to-rank escalation is intra-phase on the bus and must NEVER use the
    operator-escalation path (orchestrator.escalate_to_operator / _collect_operator_decision /
    escalate_delta_proposals), which blocks on a human. By AST inspection of the board (phase +
    its helpers), assert NO actual call to those names. AST (not substring) so a comment or
    docstring mentioning the avoidance is fine; only a real call FAILS."""
    import inspect
    import pipeline
    targets = ("phase_6_5_editorial_review", "_dispatch_rank", "_observation_triggers_escalation",
               "_consolidate_board", "_rank_run_objectives", "_resolve_editorial_board")
    forbidden = {"escalate_to_operator", "_collect_operator_decision", "escalate_delta_proposals"}
    for name in targets:
        fn = getattr(pipeline, name)
        tree = ast.parse(inspect.getsource(fn))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                return _fail(f"{name} calls operator-escalation '.{node.attr}()' (must stay intra-phase on the bus)")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden:
                return _fail(f"{name} calls operator-escalation '{node.func.id}()'")
    return _ok("editorial board uses NO operator ESCALATE path (rank-to-rank stays intra-phase on the bus; "
               "AST-checked across the phase + 5 board helpers)")


def check_55_editorial_board_output_budget():
    """INFRA-040 Build F: the board's per-rank output budget is CONFIG-RESOLVED, not a hardcoded
    2048. Upper ranks re-review all accumulated lower-rank observations, so their output grows
    with rank; the stage-1 single-reviewer budget (2048) truncated them -> contract_violation ->
    loud EDITORIAL_FAILED on every escalation. This check makes a regression to the hardcoded
    value FAIL the gate: _dispatch_rank must pass `max_tokens=max_tokens` (the resolved budget)
    and must NOT contain `max_tokens=2048`; the phase must resolve it from the tunables; and
    config/editorial_board.json + the resolver default must carry a max_tokens above the old
    2048. (The silent-pass guard still fires on genuine truncation; this only proves the budget
    is no longer hardcoded.)"""
    import inspect
    from pipeline import _dispatch_rank, phase_6_5_editorial_review, _EDITORIAL_BOARD_DEFAULTS
    dsrc = inspect.getsource(_dispatch_rank)
    if "max_tokens=2048" in dsrc:
        return _fail("_dispatch_rank still hardcodes max_tokens=2048 (board will truncate on escalation)")
    if "max_tokens=max_tokens" not in dsrc:
        return _fail("_dispatch_rank does not pass the resolved board budget (max_tokens=max_tokens)")
    psrc = inspect.getsource(phase_6_5_editorial_review)
    if 'tunables.get("max_tokens"' not in psrc and "tunables.get('max_tokens'" not in psrc:
        return _fail("phase does not resolve max_tokens from the board tunables")
    cfg_path = CONFIG / "editorial_board.json"
    if not cfg_path.exists():
        return _fail("config/editorial_board.json missing")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if "max_tokens" not in cfg:
        return _fail("editorial_board.json missing tunable 'max_tokens'")
    if not isinstance(cfg["max_tokens"], int) or cfg["max_tokens"] <= 2048:
        return _fail(f"editorial_board.json max_tokens must be an int > 2048, got {cfg['max_tokens']!r}")
    dflt = _EDITORIAL_BOARD_DEFAULTS.get("max_tokens")
    if not isinstance(dflt, int) or dflt <= 2048:
        return _fail(f"resolver default max_tokens must be an int > 2048, got {dflt!r}")
    return _ok(f"board output budget is config-resolved (no hardcoded 2048): config max_tokens="
               f"{cfg['max_tokens']}, resolver default={dflt}; silent-pass guard still fires on genuine truncation")


def check_56_audit_synthesizer_wired():
    """Cross-run learning loop (genesis Part X): the AUDIT SYNTHESIZER converts recurring
    failures into DELTA proposals. It is WIRED but was previously UNGATED (a D7-class blind
    spot: future decay would pass green). This check asserts, by source/AST inspection:
    (1) AuditSynthesizer is imported and CALLED in the live pipeline inside the `if op_docs:`
    block (synthesize + escalate_delta_proposals), not orphaned/commented; (2) it READS a
    live source (bus.read_all) and WRITES via run_context (audit_synthesis + delta_proposals
    paths), not a relocated/dead path; (3) proposals are PROPOSAL-SIDE ONLY —
    DeltaProposal.requires_operator_approval defaults True, escalation routes through
    escalate_delta_proposals, and the synthesizer never self-applies (no Constitution.save /
    check_constitution_change call). FAILS if the call site is removed or it self-applies."""
    import inspect, dataclasses
    import pipeline, audit_synthesizer
    from audit_synthesizer import DeltaProposal
    msrc = inspect.getsource(pipeline.main)
    for needle in ("AuditSynthesizer(", ".synthesize(", "escalate_delta_proposals("):
        if needle not in msrc:
            return _fail(f"audit synthesizer call site missing from pipeline.main: {needle!r}")
    i_op = msrc.find("if op_docs:")
    i_syn = msrc.find("AuditSynthesizer(")
    if i_op < 0 or not (0 <= i_op < i_syn):
        return _fail("AuditSynthesizer is not inside the live `if op_docs:` block")
    ssrc = inspect.getsource(audit_synthesizer)
    if "self.bus.read_all()" not in ssrc:
        return _fail("synthesizer no longer reads the live bus (self.bus.read_all)")
    if "audit_synthesis_path" not in ssrc or "delta_proposals_path" not in ssrc:
        return _fail("synthesizer output not wired to run_context audit_synthesis/delta_proposals paths")
    flds = {f.name: f for f in dataclasses.fields(DeltaProposal)}
    if "requires_operator_approval" not in flds or flds["requires_operator_approval"].default is not True:
        return _fail("DeltaProposal.requires_operator_approval default is not True (proposals must be operator-gated)")
    forbidden = {"check_constitution_change", "save"}  # self-apply paths
    for node in ast.walk(ast.parse(ssrc)):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            return _fail(f"synthesizer calls '.{node.attr}()' — must be proposal-side only, never self-apply")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in forbidden:
            return _fail(f"synthesizer calls '{node.func.id}()' — must be proposal-side only, never self-apply")
    return _ok("audit synthesizer WIRED + proposal-side: called in `if op_docs:`, reads bus.read_all, writes "
               "delta_proposals/audit_synthesis via run_context, requires_operator_approval=True, no self-apply path")


def check_57_oge_capture_wired():
    """OGE build B1 (ontology/SCHEMA.md Q1): the capture-at-run-end hook is WIRED into the live
    pipeline AND works. WIRED: pipeline.main imports ontology_capture and calls capture_run at
    run-end (source check, so it is not a dormant scaffold). WORKS (executed coverage, the D7
    lesson): capture_run runs against a synthetic finalized run writing to a TEMP store, and the
    provisions + proposal accumulator receive the run's records with the right shapes (composite
    id Q2, dedup-merge C1). Non-mutating: writes only to a tempdir, never the real ontology/stores."""
    import inspect, tempfile
    import pipeline, ontology_capture
    msrc = inspect.getsource(pipeline.main)
    for needle in ("ontology_capture", "capture_run("):
        if needle not in msrc:
            return _fail(f"capture hook not wired into pipeline.main: {needle!r} absent (dormant scaffold)")
    d = Path(tempfile.mkdtemp(prefix="shimmer_oge57_"))
    deliv = d / "deliv"; deliv.mkdir()
    doc_id = "testdoc"
    master = {"document_id": doc_id, "amendments": [
        {"location": "REF-0001", "convention_ref": "CONV-001", "context_refs": ["REF-0009"],
         "finding_type": "factual", "original_text": "raw provision text", "proposed_text": None,
         "action": "flag", "comment": "analyst comment", "severity": "high"}]}
    (deliv / f"{doc_id}__amendments.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
    (d / "delta_proposals.json").write_text(json.dumps({"generated_at": "t", "proposals": [
        {"id": "DELTA-1", "kind": "reduce_ttl", "trigger": "x", "evidence": {"k": "v"},
         "proposed_change": {"target": "T", "action": "A"}, "requires_operator_approval": True,
         "created_at": "t"}]}, ensure_ascii=False), encoding="utf-8")

    class _RC:
        run_id = "RUN-TEST-57"
        def deliverables_dir(_self): return deliv
        def delta_proposals_path(_self): return d / "delta_proposals.json"

    op_docs = [{"id": doc_id, "name": doc_id}]
    deliverables = {doc_id: {"amendments_json": str(deliv / f"{doc_id}__amendments.json")}}
    res = ontology_capture.capture_run(_RC(), op_docs, deliverables, sensitive=False, stores_dir=str(d / "stores"))
    if res.get("provisions_appended", 0) < 1:
        return _fail(f"capture wrote no provisions: {res}")
    if res.get("accumulator_size", 0) < 1:
        return _fail(f"proposal accumulator empty after capture: {res}")
    prov_lines = (d / "stores" / "provisions.jsonl").read_text(encoding="utf-8").strip().splitlines()
    prop_lines = (d / "stores" / "delta_proposals.jsonl").read_text(encoding="utf-8").strip().splitlines()
    if not prov_lines or not prop_lines:
        return _fail("temp OGE stores did not receive records (capture inert)")
    prov0 = json.loads(prov_lines[0])
    if prov0.get("id") != f"{doc_id}::REF-0001":
        return _fail(f"provision composite id wrong (Q2): {prov0.get('id')!r}")
    if not any(json.loads(l).get("stub") for l in prov_lines):
        return _fail("referenced-only REF not materialized as a stub node (Q3)")
    prop0 = json.loads(prop_lines[0])
    if prop0.get("occurrence_count") != 1 or prop0.get("status") != "proposed":
        return _fail(f"accumulator fields missing (C1): {prop0}")
    # dedup-merge: re-run the same proposal -> count increments, no duplicate line
    ontology_capture.capture_run(_RC(), op_docs, deliverables, sensitive=False, stores_dir=str(d / "stores"))
    prop2 = (d / "stores" / "delta_proposals.jsonl").read_text(encoding="utf-8").strip().splitlines()
    if len(prop2) != 1 or json.loads(prop2[0]).get("occurrence_count") != 2:
        return _fail(f"dedup merge failed (C1): {len(prop2)} line(s), "
                     f"counts {[json.loads(l).get('occurrence_count') for l in prop2]}")
    return _ok("OGE capture hook WIRED into pipeline.main + EXECUTED: provisions appended (composite id Q2, "
               "stub Q3), proposal accumulator merges by dedup key (count 1->2), status 'proposed'")


def check_58_oge_masked_write_gate():
    """OGE build B1 BUILD INVARIANT: the masked-write gate is keyed on sensitive mode.
    Non-sensitive writes real content; sensitive writes a typed placeholder [REDACTED:TYPE].
    Proven on the mask_field primitive AND end-to-end by capturing the same synthetic provision
    under both modes: RAW fields (original_text/proposed_text/comment per SCHEMA table D) land
    raw vs masked, while SAFE structural fields are never masked. Non-mutating (pure fn / no store write)."""
    import ontology_capture
    from ontology_capture import mask_field
    if mask_field("secret", "PROVISION_TEXT", sensitive=False) != "secret":
        return _fail("mask_field leaked: non-sensitive must pass real content through")
    if mask_field("secret", "PROVISION_TEXT", sensitive=True) != "[REDACTED:PROVISION_TEXT]":
        return _fail("mask_field did not emit a typed placeholder under sensitive mode")
    if mask_field(None, "PROVISION_TEXT", sensitive=True) is not None:
        return _fail("mask_field must pass None through (no placeholder for absent content)")
    master = {"document_id": "doc", "amendments": [
        {"location": "REF-1", "original_text": "RAW SOURCE TEXT", "proposed_text": "RAW PROPOSED",
         "comment": "RAW COMMENT", "finding_type": "factual", "action": "flag", "severity": "high"}]}
    clear = ontology_capture.capture_provisions(master, "RUN-CLEAR", sensitive=False)[0]
    sens = ontology_capture.capture_provisions(master, "RUN-SENS", sensitive=True)[0]
    if clear["original_text"] != "RAW SOURCE TEXT" or clear["comment"] != "RAW COMMENT":
        return _fail("non-sensitive capture did not write real content")
    for fld, typ in (("original_text", "PROVISION_TEXT"), ("proposed_text", "PROVISION_TEXT"),
                     ("comment", "ANALYST_COMMENT")):
        if sens[fld] != f"[REDACTED:{typ}]":
            return _fail(f"sensitive capture did not mask RAW field {fld}: {sens[fld]!r}")
    if sens["ref_id"] != "REF-1" or sens["document_id"] != "doc" or sens["severity"] != "high":
        return _fail("sensitive mode masked a SAFE structural field (must not)")
    return _ok("masked-write gate proven: non-sensitive writes real content; sensitive writes "
               "[REDACTED:TYPE] for RAW fields (original_text/proposed_text/comment); SAFE fields untouched")


def _oge59_fixture(d):
    """Write a synthetic source set into tempdir `d` for the B2 ingest checks. Returns a
    sources dict for build_graph. Includes abs_path in document_dates (to prove exclusion),
    a provision with a citation token + a speech-act verb, a convention, and a referenced-only
    REF (REF-9) that is NOT a provision record (so B2 must materialize it as a stub)."""
    (d / "document_dates.json").write_text(json.dumps({"documents": [
        {"filename": "docA", "date": "2024-01-01", "date_source": "filename",
         "date_confidence": "high", "title": None, "abs_path": "C:/secret/path/docA.md"}]},
        ensure_ascii=False), encoding="utf-8")
    (d / "conventions.json").write_text(json.dumps({"conventions": [
        {"id": "CONV-001", "category": "review", "rule": "operator rule text",
         "source_file": "f.md", "source_location": "line 1", "severity": "required", "action": "flag"}]},
        ensure_ascii=False), encoding="utf-8")
    (d / "citation.json").write_text(json.dumps({"rules": [
        {"name": "UN_RES", "pattern": r"[ASE]/RES/\d+", "sample_count": 1, "examples": ["A/RES/70/1"]}]},
        ensure_ascii=False), encoding="utf-8")
    (d / "speech.json").write_text(json.dumps({"speech_acts": [
        {"name": "decide", "pattern": r"\bdecides?\b", "evidence_count": 1, "examples": ["decides"]}]},
        ensure_ascii=False), encoding="utf-8")
    prov = [
        {"node": "Provision", "id": "docA::REF-1", "document_id": "docA", "ref_id": "REF-1",
         "finding_type": "factual", "action": "flag", "severity": "high", "convention_ref": "CONV-001",
         "context_refs": ["REF-9"], "original_text": "Article 5 cites A/RES/70/1 and decides the matter.",
         "proposed_text": None, "comment": "c", "stub": False, "run_id": "R1", "captured_at": "t1"},
    ]
    (d / "provisions.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in prov) + "\n",
                                        encoding="utf-8")
    return {"document_dates": d / "document_dates.json", "conventions": d / "conventions.json",
            "citation_forms": d / "citation.json", "speech_acts": d / "speech.json",
            "provisions": d / "provisions.jsonl"}


def check_59_oge_ingest_executed():
    """OGE build B2 (ontology/SCHEMA.md A/B/C5-C6): the Tier-1 graph ingest is EXECUTED on a
    synthetic fixture in a tempdir and asserted (executed coverage, the D7 lesson; non-mutating,
    never writes the real graph.json). Asserts all five node types; HAS_PROVISION / GOVERNED_BY /
    CROSS_REFERENCES edges; the referenced-only REF materialized as a stub (incomplete=true); at
    least one CITES and one EXHIBITS derived edge; and NO abs_path anywhere in graph.json (Q7)."""
    import tempfile
    import ontology_graph
    d = Path(tempfile.mkdtemp(prefix="shimmer_oge59_"))
    sources = _oge59_fixture(d)
    out = d / "graph.json"
    g = ontology_graph.build_graph(sources=sources, out_path=str(out))
    types = {n["type"] for n in g["nodes"]}
    for t in ("Document", "Provision", "Convention", "CitationForm", "SpeechAct"):
        if t not in types:
            return _fail(f"node type missing from graph: {t} (have {sorted(types)})")
    etypes = {e["type"] for e in g["edges"]}
    for et in ("HAS_PROVISION", "GOVERNED_BY", "CROSS_REFERENCES", "CITES", "EXHIBITS"):
        if et not in etypes:
            return _fail(f"edge type missing: {et} (have {sorted(etypes)})")

    def has_edge(t, s, tg):
        return any(e["type"] == t and e["source"] == s and e["target"] == tg for e in g["edges"])
    if not has_edge("HAS_PROVISION", "docA", "docA::REF-1"):
        return _fail("HAS_PROVISION docA -> docA::REF-1 missing")
    if not has_edge("GOVERNED_BY", "docA::REF-1", "CONV-001"):
        return _fail("GOVERNED_BY docA::REF-1 -> CONV-001 missing")
    if not has_edge("CROSS_REFERENCES", "docA::REF-1", "docA::REF-9"):
        return _fail("CROSS_REFERENCES docA::REF-1 -> docA::REF-9 missing")
    stub = next((n for n in g["nodes"] if n["type"] == "Provision" and n["id"] == "docA::REF-9"), None)
    if not stub or not stub.get("stub") or not stub.get("incomplete"):
        return _fail(f"referenced-only REF-9 not materialized as an incomplete stub (Q3): {stub}")
    if not any(e["type"] == "CITES" for e in g["edges"]) or not any(e["type"] == "EXHIBITS" for e in g["edges"]):
        return _fail("derivable CITES/EXHIBITS edges not produced")
    if "abs_path" in out.read_text(encoding="utf-8"):
        return _fail("graph.json contains abs_path (Q7 violation)")
    return _ok(f"OGE Tier-1 ingest EXECUTED: 5 node types, edges {sorted(etypes)}; referenced-only "
               f"REF-9 stub (incomplete); CITES+EXHIBITS derived; no abs_path "
               f"({g['stats']['nodes_total']} nodes, {g['stats']['edges_total']} edges)")


def check_60_oge_ingest_payload_free():
    """OGE build B2 BUILD INVARIANT: ingest is payload-free. A provision stored masked
    ([REDACTED:PROVISION_TEXT], as B1 writes under a sensitive run) yields a node carrying the
    placeholder AS STORED (never unmasked) and ZERO CITES/EXHIBITS matches (a regex cannot match
    a placeholder). Non-mutating (tempdir only)."""
    import tempfile
    import ontology_graph
    d = Path(tempfile.mkdtemp(prefix="shimmer_oge60_"))
    (d / "document_dates.json").write_text(json.dumps({"documents": []}), encoding="utf-8")
    (d / "conventions.json").write_text(json.dumps({"conventions": []}), encoding="utf-8")
    # patterns that WOULD match real text but must NOT match a placeholder
    (d / "citation.json").write_text(json.dumps({"rules": [
        {"name": "UN_RES", "pattern": r"[ASE]/RES/\d+"}]}), encoding="utf-8")
    (d / "speech.json").write_text(json.dumps({"speech_acts": [
        {"name": "decide", "pattern": r"\bdecides?\b"}]}), encoding="utf-8")
    prov = [{"node": "Provision", "id": "docA::REF-1", "document_id": "docA", "ref_id": "REF-1",
             "finding_type": "factual", "action": "flag", "severity": "high", "convention_ref": None,
             "context_refs": [], "original_text": "[REDACTED:PROVISION_TEXT]",
             "proposed_text": "[REDACTED:PROVISION_TEXT]", "comment": "[REDACTED:ANALYST_COMMENT]",
             "stub": False, "run_id": "R1", "captured_at": "t1"}]
    (d / "provisions.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in prov) + "\n",
                                        encoding="utf-8")
    sources = {"document_dates": d / "document_dates.json", "conventions": d / "conventions.json",
               "citation_forms": d / "citation.json", "speech_acts": d / "speech.json",
               "provisions": d / "provisions.jsonl"}
    out = d / "graph.json"
    g = ontology_graph.build_graph(sources=sources, out_path=str(out))
    node = next((n for n in g["nodes"] if n["id"] == "docA::REF-1"), None)
    if node is None:
        return _fail("provision node not built")
    if node.get("original_text") != "[REDACTED:PROVISION_TEXT]":
        return _fail(f"ingest did not carry the stored placeholder verbatim: {node.get('original_text')!r}")
    cites = [e for e in g["edges"] if e["type"] == "CITES"]
    exhibits = [e for e in g["edges"] if e["type"] == "EXHIBITS"]
    if cites or exhibits:
        return _fail(f"regex matched a placeholder (must not): CITES={cites} EXHIBITS={exhibits}")
    if "[REDACTED:[REDACTED" in out.read_text(encoding="utf-8"):
        return _fail("graph.json contains a nested placeholder")
    return _ok("ingest payload-free: masked provision carried as the stored placeholder; "
               "zero CITES/EXHIBITS matched against a placeholder; no unmasking, no nesting")


def check_61_oge_graph_rebuilt_at_run_end():
    """OGE build B2 wiring: the Tier-1 graph is rebuilt at run-end, right after the capture hook.
    WIRED (not dormant): pipeline.main imports ontology_graph and calls build_graph at run-end,
    inside the same post-capture block as capture_run (source check). WORKS end-to-end (executed
    coverage, the D7 lesson): the run-end SEQUENCE is reproduced on a tempdir -- capture_run writes
    a provision to a temp store, then build_graph rebuilds graph.json from that store, and the
    captured provision appears as a node. Non-mutating: tempdir only, never the real graph.json."""
    import inspect, tempfile
    import pipeline, ontology_capture, ontology_graph
    msrc = inspect.getsource(pipeline.main)
    if "ontology_graph" not in msrc or "build_graph(" not in msrc:
        return _fail("graph rebuild not wired into pipeline.main (build_graph absent -> dormant)")
    # the rebuild must sit AFTER the capture call (run-end, post-capture), not before it
    i_cap = msrc.find("capture_run(")
    i_build = msrc.find("build_graph(")
    if not (0 <= i_cap < i_build):
        return _fail("build_graph is not called after capture_run at run-end")

    # executed: reproduce the run-end sequence (capture -> rebuild) on a tempdir
    d = Path(tempfile.mkdtemp(prefix="shimmer_oge61_"))
    deliv = d / "deliv"; deliv.mkdir()
    doc_id = "docX"
    master = {"document_id": doc_id, "amendments": [
        {"location": "REF-1", "convention_ref": "CONV-001", "context_refs": [],
         "finding_type": "factual", "original_text": "some provision text", "proposed_text": None,
         "action": "flag", "comment": "c", "severity": "high"}]}
    (deliv / f"{doc_id}__amendments.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
    (d / "delta_proposals.json").write_text(json.dumps({"generated_at": "t", "proposals": []}),
                                            encoding="utf-8")

    class _RC:
        run_id = "RUN-TEST-61"
        def deliverables_dir(_self): return deliv
        def delta_proposals_path(_self): return d / "delta_proposals.json"

    op_docs = [{"id": doc_id, "name": doc_id}]
    deliverables = {doc_id: {"amendments_json": str(deliv / f"{doc_id}__amendments.json")}}
    stores = d / "stores"
    cap = ontology_capture.capture_run(_RC(), op_docs, deliverables, sensitive=False, stores_dir=str(stores))
    if cap.get("provisions_appended", 0) < 1:
        return _fail(f"capture step wrote no provisions: {cap}")
    out = d / "graph.json"
    g = ontology_graph.build_graph(sources={"provisions": stores / "provisions.jsonl"}, out_path=str(out))
    if not out.exists():
        return _fail("graph.json not produced by the run-end rebuild")
    if not any(n["type"] == "Provision" and n["id"] == f"{doc_id}::REF-1" for n in g["nodes"]):
        return _fail("rebuilt graph does not reflect the captured provision (docX::REF-1 absent)")
    return _ok("run-end rebuild WIRED + EXECUTED: pipeline.main calls build_graph after capture_run; "
               "capture->rebuild sequence yields graph.json reflecting the captured provision")


def _oge_gnn_graph(nodes, edges):
    """A minimal graph.json dict for the GNN checks (build_features/build_adjacency consume it)."""
    return {"schema": "oge_graph/v1", "tier": 1, "generated_at": "t", "nodes": nodes, "edges": edges,
            "stats": {}}


def check_62_oge_gnn_executed():
    """OGE build B3: the GNN engine is EXECUTED end-to-end on a synthetic seeded graph (executed
    coverage, the D7 lesson; tempdir only; CPU-deterministic: device=cpu + fixed seed so the result
    does NOT depend on GPU presence). Proves MACHINERY, NOT LEARNING -- one fwd + one delta-only
    backprop runs without error, the weights MOVE after backward, state persists, and a SECOND
    invocation trains only over newly-added delta nodes (incremental, not full retrain). The learning
    signal is Tier 2 (empty until task flow), so nothing is asserted to have been *learned*."""
    import tempfile
    import ontology_gnn
    d = Path(tempfile.mkdtemp(prefix="shimmer_oge62_"))
    nodes = [
        {"type": "Document", "id": "docA", "date_confidence": "high", "stub": False},
        {"type": "Provision", "id": "docA::REF-1", "document_id": "docA", "ref_id": "REF-1",
         "finding_type": "factual", "action": "flag", "severity": "high",
         "context_refs": ["REF-9"], "original_text": "Article 5 text", "stub": False},
        {"type": "Convention", "id": "CONV-001", "category": "review", "severity": "required",
         "action": "flag", "rule": "operator rule"},
    ]
    edges = [
        {"type": "HAS_PROVISION", "source_type": "Document", "source": "docA",
         "target_type": "Provision", "target": "docA::REF-1"},
        {"type": "GOVERNED_BY", "source_type": "Provision", "source": "docA::REF-1",
         "target_type": "Convention", "target": "CONV-001"},
    ]
    gpath = d / "graph.json"
    spath = d / "gnn_state.json"
    gpath.write_text(json.dumps(_oge_gnn_graph(nodes, edges)), encoding="utf-8")

    s1 = ontology_gnn.gnn_update(graph_path=str(gpath), state_path=str(spath), device="cpu",
                                 seed=7, log=False)
    if s1["nodes"] != 3 or s1["delta_size"] != 3:
        return _fail(f"first run delta should equal all 3 nodes: {s1}")
    if not (s1["weight_delta_norm"] > 0):
        return _fail(f"weights did not move after backward (machinery did not run): {s1}")
    if not spath.exists():
        return _fail("gnn_state.json not persisted after first run")
    st1 = json.loads(spath.read_text(encoding="utf-8"))
    if st1.get("trained_count") != 3 or st1.get("n_updates") != 1:
        return _fail(f"high-water mark not persisted correctly after first run: {st1.get('trained_count')}, "
                     f"n_updates={st1.get('n_updates')}")

    # SECOND invocation: add ONE new node. Delta must be exactly that node (incremental, not retrain).
    nodes2 = nodes + [{"type": "SpeechAct", "id": "decide", "evidence_count": 2}]
    edges2 = edges + [{"type": "EXHIBITS", "source_type": "Provision", "source": "docA::REF-1",
                       "target_type": "SpeechAct", "target": "decide"}]
    gpath.write_text(json.dumps(_oge_gnn_graph(nodes2, edges2)), encoding="utf-8")
    s2 = ontology_gnn.gnn_update(graph_path=str(gpath), state_path=str(spath), device="cpu",
                                 seed=7, log=False)
    if s2["delta_size"] != 1:
        return _fail(f"second run must train only the 1 newly-added node (got delta={s2['delta_size']})")
    st2 = json.loads(spath.read_text(encoding="utf-8"))
    if st2.get("trained_count") != 4 or st2.get("n_updates") != 2:
        return _fail(f"incremental high-water mark wrong after second run: trained={st2.get('trained_count')}, "
                     f"n_updates={st2.get('n_updates')}")
    return _ok("OGE GNN EXECUTED (MACHINERY not learning): fwd+delta-backprop ran on CPU, weights moved "
               f"(|dW|={s1['weight_delta_norm']:.4f}), state persisted; 2nd run trained only the 1 new "
               "delta node (incremental, not full retrain)")


def check_63_oge_gnn_payload_free():
    """OGE build B3 BUILD INVARIANT: the GNN is payload-free. The feature matrix is built ONLY from
    the SAFE allowlist; RAW fields never enter X or gnn_state. Proven three ways: (1) the SAFE
    allowlist and the RAW field set are disjoint; (2) two provisions differing ONLY in RAW text
    produce IDENTICAL feature rows (RAW does not affect features); (3) feeding a provision whose text
    is [REDACTED:...] leaves the placeholder absent from both the feature matrix and the persisted
    state. CPU-deterministic, tempdir only."""
    import tempfile
    import ontology_gnn
    if ontology_gnn.SAFE_FEATURE_FIELDS & ontology_gnn.RAW_FIELDS:
        return _fail(f"SAFE allowlist overlaps RAW fields: {ontology_gnn.SAFE_FEATURE_FIELDS & ontology_gnn.RAW_FIELDS}")

    secret = "TOP SECRET provision body that must never enter features"
    n_real = {"type": "Provision", "id": "p1", "document_id": "docA", "ref_id": "REF-1",
              "finding_type": "factual", "action": "flag", "severity": "high",
              "context_refs": [], "original_text": secret, "comment": secret, "stub": False}
    n_masked = dict(n_real, id="p2", original_text="[REDACTED:PROVISION_TEXT]",
                    comment="[REDACTED:ANALYST_COMMENT]")
    g = _oge_gnn_graph([n_real, n_masked], [])
    X, ids, _ = ontology_gnn.build_features(g)
    # (2) identical SAFE features despite different RAW text
    i1, i2 = ids.index("p1"), ids.index("p2")
    import numpy as _np
    if not _np.array_equal(X[i1], X[i2]):
        return _fail("RAW text changed the SAFE feature row (payload leaked into features)")

    d = Path(tempfile.mkdtemp(prefix="shimmer_oge63_"))
    gpath = d / "graph.json"
    spath = d / "gnn_state.json"
    gpath.write_text(json.dumps(g), encoding="utf-8")
    ontology_gnn.gnn_update(graph_path=str(gpath), state_path=str(spath), device="cpu", seed=3, log=False)
    state_text = spath.read_text(encoding="utf-8")
    for needle in (secret, "REDACTED", "original_text", "comment"):
        if needle in state_text:
            return _fail(f"payload/RAW token leaked into gnn_state.json: {needle!r}")
    return _ok("OGE GNN payload-free: SAFE/RAW disjoint; RAW text does not change feature rows; "
               "no raw or placeholder token in gnn_state (weights + structural metadata only)")


def check_64_oge_gnn_wired_at_run_end():
    """OGE build B3 wiring: the GNN runs at run-end, AFTER build_graph. WIRED (not dormant):
    pipeline.main calls gnn_update after build_graph after capture_run (source-order check). WORKS
    end-to-end (executed coverage): the full run-end sequence capture_run -> build_graph -> gnn_update
    is reproduced on a tempdir and gnn_state.json is produced. CPU-deterministic, tempdir only,
    non-mutating (never the real ontology/stores/*)."""
    import inspect, tempfile
    import pipeline, ontology_capture, ontology_graph, ontology_gnn
    msrc = inspect.getsource(pipeline.main)
    if "ontology_gnn" not in msrc or "gnn_update(" not in msrc:
        return _fail("gnn_update not wired into pipeline.main (dormant)")
    i_cap, i_build, i_gnn = msrc.find("capture_run("), msrc.find("build_graph("), msrc.find("gnn_update(")
    if not (0 <= i_cap < i_build < i_gnn):
        return _fail(f"run-end order must be capture_run < build_graph < gnn_update "
                     f"(got {i_cap}, {i_build}, {i_gnn})")

    # executed: reproduce the run-end sequence on a tempdir
    d = Path(tempfile.mkdtemp(prefix="shimmer_oge64_"))
    deliv = d / "deliv"; deliv.mkdir()
    doc_id = "docX"
    master = {"document_id": doc_id, "amendments": [
        {"location": "REF-1", "convention_ref": "CONV-001", "context_refs": [],
         "finding_type": "factual", "original_text": "some provision text", "proposed_text": None,
         "action": "flag", "comment": "c", "severity": "high"}]}
    (deliv / f"{doc_id}__amendments.json").write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
    (d / "delta_proposals.json").write_text(json.dumps({"generated_at": "t", "proposals": []}), encoding="utf-8")

    class _RC:
        run_id = "RUN-TEST-64"
        def deliverables_dir(_self): return deliv
        def delta_proposals_path(_self): return d / "delta_proposals.json"

    op_docs = [{"id": doc_id, "name": doc_id}]
    deliverables = {doc_id: {"amendments_json": str(deliv / f"{doc_id}__amendments.json")}}
    stores = d / "stores"
    ontology_capture.capture_run(_RC(), op_docs, deliverables, sensitive=False, stores_dir=str(stores))
    out = d / "graph.json"
    ontology_graph.build_graph(sources={"provisions": stores / "provisions.jsonl"}, out_path=str(out))
    spath = d / "gnn_state.json"
    s = ontology_gnn.gnn_update(graph_path=str(out), state_path=str(spath), device="cpu", seed=5, log=False)
    if not spath.exists():
        return _fail("run-end GNN sequence did not persist gnn_state.json")
    if s["nodes"] < 1:
        return _fail(f"run-end GNN saw no nodes from the rebuilt graph: {s}")
    return _ok("run-end GNN WIRED + EXECUTED: pipeline.main calls gnn_update after build_graph after "
               f"capture_run; reproduced sequence persisted gnn_state.json over {s['nodes']} nodes")


def _p1_masking_fixture(d):
    """Write a hermetic operator-convention fixture into tempdir project_root `d`: a minimal
    language_redaction_cues.json authorizing the 'identifier' shape, plus an operator rule whose
    text mentions the 'identifier' cue (so authorized_shapes authorizes the identifier detector).
    Returns (operator_rules, envelope) where the envelope has one SENSITIVE item (a grouped-digit
    identifier) and one CLEAN item. No real config/store is touched (tempdir only)."""
    cfg = d / "config"; cfg.mkdir(parents=True, exist_ok=True)
    cues = {"languages": {"en": {"shape_cues": {"identifier": ["identifier"]},
            "digit_class_ext": "", "decimal_ext": "", "separator_ext": "", "letter_class": "",
            "titles": [], "magnitude_words": [], "currency_words": [], "connectives": []}}}
    (cfg / "language_redaction_cues.json").write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")
    operator_rules = [{"id": "CONV-RED-1", "category": "confidentiality", "action": "redact",
                       "severity": "required", "rule": "redact any identifier number in the document"}]
    envelope = {"agent": "PROCESSOR", "doc_id": "docA", "items": [
        {"item_id": "i-sensitive", "revision": 1, "ts": "t1", "kind": "finding", "confidence": "CONFIDENT",
         "ref": "REF-1", "original_text": "Citizen ID 12-345-6789 applies.", "comment": "see ID 12-345-6789"},
        {"item_id": "i-clean", "revision": 1, "ts": "t1", "kind": "finding", "confidence": "CONFIDENT",
         "ref": "REF-2", "original_text": "This provision is clear and public."}]}
    return operator_rules, envelope


def check_65_masking_engine_splits():
    """INFRA-041 P1: the outbound masking engine performs the x/y split with typed placeholders
    and writes the per-item exposure ledger. EXECUTED (the WIRE-AT-THE-END discipline) on a hermetic
    operator-convention fixture in a tempdir; non-mutating (never the real config or governance ledger).
    Sensitivity is OPERATOR-CONVENTION-driven (redaction_detect over operator rules), never model-judged."""
    import tempfile
    import sensitivity_layer as S
    d = Path(tempfile.mkdtemp(prefix="shimmer_p1_65_"))
    rules, env = _p1_masking_fixture(d)
    ledger = d / "exposure_ledger.jsonl"
    res = S.mask_exchange(env, sensitive=True, operator_rules=rules, project_root=str(d),
                          run_id="RUN-P1", ledger_path=str(ledger))
    out = {it["item_id"]: it for it in res["outbound"]["items"]}
    # y item: content fields are typed placeholders; the raw id span is GONE from outbound
    sens = out["i-sensitive"]
    if sens.get("original_text") != "[REDACTED:ORIGINAL_TEXT]" or sens.get("comment") != "[REDACTED:COMMENT]":
        return _fail(f"sensitive item content not masked to typed placeholders: {sens}")
    if "12-345-6789" in json.dumps(res["outbound"], ensure_ascii=False):
        return _fail("raw identifier span survived in the outbound payload")
    if sens.get("kind") != "finding" or sens.get("item_id") != "i-sensitive":
        return _fail("structural keys (kind/item_id) must be preserved on a masked item")
    # x item: passed through raw
    if out["i-clean"].get("original_text") != "This provision is clear and public.":
        return _fail("non-sensitive item must pass through unchanged")
    # held local: the original sensitive item is held (not sent)
    if ("i-sensitive", 1) not in res["held"] or res["held"][("i-sensitive", 1)].get("original_text") != "Citizen ID 12-345-6789 applies.":
        return _fail("original sensitive item not held local")
    # tags: one masked, one passed
    by = {t["item_id"]: t for t in res["tags"]}
    if by["i-sensitive"]["exposure"] != "masked" or by["i-clean"]["exposure"] != "passed":
        return _fail(f"exposure tags wrong: {res['tags']}")
    if "CONV-RED-1" not in by["i-sensitive"]["rule_ids"]:
        return _fail("masked item did not record the authorizing operator rule id")
    # ledger: one record per item, NO raw content
    lines = ledger.read_text(encoding="utf-8").splitlines()
    if len(lines) != 2:
        return _fail(f"exposure ledger must hold one record per item (got {len(lines)})")
    if "12-345-6789" in ledger.read_text(encoding="utf-8") or "Citizen ID" in ledger.read_text(encoding="utf-8"):
        return _fail("raw content leaked into the exposure ledger")
    rec = json.loads(lines[0])
    if rec.get("schema") != "exposure_ledger/v1" or "exposure" not in rec:
        return _fail("ledger record malformed")
    return _ok("masking engine SPLITS x/y: sensitive item -> typed placeholders + held local; clean item "
               "passes; per-item exposure ledger written (no raw content); operator-rule-driven, not model-judged")


def check_66_masking_rejoin_dedupe():
    """INFRA-041 P1: rejoin restores held-local y content by (item_id, revision) and dedupes to the
    current revision per item_id (INFRA-037). Executed, tempdir, non-mutating."""
    import tempfile
    import sensitivity_layer as S
    d = Path(tempfile.mkdtemp(prefix="shimmer_p1_66_"))
    rules, env = _p1_masking_fixture(d)
    res = S.mask_exchange(env, sensitive=True, operator_rules=rules, project_root=str(d),
                          run_id="RUN-P1", ledger_path=str(d / "ledger.jsonl"))
    # rejoin the masked outbound with the held map -> originals restored
    rejoined = S.rejoin_after_external(res["outbound"], res["held"])
    by = {it["item_id"]: it for it in rejoined}
    if by["i-sensitive"].get("original_text") != "Citizen ID 12-345-6789 applies.":
        return _fail("rejoin did not restore the held-local original content")
    if by["i-clean"].get("original_text") != "This provision is clear and public.":
        return _fail("rejoin altered the passed-through item")
    # dedupe: a higher-revision duplicate of i-clean supersedes the original
    bumped = list(res["outbound"]["items"]) + [
        {"item_id": "i-clean", "revision": 2, "ts": "t2", "kind": "finding",
         "confidence": "CONFIDENT", "ref": "REF-2", "original_text": "Revised public text."}]
    deduped = S.rejoin_after_external(bumped, res["held"])
    clean = [it for it in deduped if it["item_id"] == "i-clean"]
    if len(clean) != 1 or clean[0].get("revision") != 2:
        return _fail(f"rejoin must dedupe to the highest revision per item_id: {clean}")
    return _ok("rejoin restores held-local y content by (item_id, revision) and dedupes to the current "
               "revision per item_id (INFRA-037)")


def check_67_masking_idempotent_and_inert():
    """INFRA-041 P1: the engine is idempotent on already-masked input, inert under non-sensitive mode,
    and refuses (no silent passthrough) when the operator-convention inputs are missing under sensitive
    mode. Executed, tempdir, non-mutating."""
    import tempfile
    import sensitivity_layer as S
    d = Path(tempfile.mkdtemp(prefix="shimmer_p1_67_"))
    rules, env = _p1_masking_fixture(d)
    # (a) idempotent: re-masking an already-masked outbound is a no-op (no nested placeholders, no re-hold)
    once = S.mask_exchange(env, sensitive=True, operator_rules=rules, project_root=str(d),
                           ledger_path=str(d / "a.jsonl"))
    twice = S.mask_exchange(once["outbound"], sensitive=True, operator_rules=rules, project_root=str(d),
                            ledger_path=str(d / "b.jsonl"))
    sens2 = {it["item_id"]: it for it in twice["outbound"]["items"]}["i-sensitive"]
    if sens2.get("original_text") != "[REDACTED:ORIGINAL_TEXT]":
        return _fail(f"not idempotent: placeholder changed on re-mask ({sens2.get('original_text')!r})")
    if twice["held"]:
        return _fail("already-masked item must not be re-held (nothing sensitive remains to hold)")
    # (b) inert under non-sensitive: payload returned unchanged, no ledger written
    sentinel = {"agent": "PROCESSOR", "doc_id": "docA", "items": [dict(env["items"][0])]}
    inert_ledger = d / "inert.jsonl"
    if S.mask_for_external(sentinel, sensitive=False, ledger_path=str(inert_ledger)) is not sentinel:
        return _fail("non-sensitive mode must return the payload unchanged (inert)")
    if inert_ledger.exists():
        return _fail("non-sensitive mode must not write the exposure ledger")
    # (c) no silent passthrough: sensitive mode without operator inputs RAISES
    try:
        S.mask_exchange(env, sensitive=True)
        return _fail("sensitive mode without operator_rules/project_root must RAISE, not pass raw")
    except ValueError:
        pass
    return _ok("engine idempotent on already-masked input; inert + ledger-free under non-sensitive mode; "
               "raises (no silent passthrough) when operator-convention inputs are missing under sensitive mode")


def check_68_chokepoint_prompt_masked():
    """INFRA-041 P2 chokepoint 1: the per-agent prompt egress is masked. WIRED: run_task calls
    outbound_masker BEFORE dispatch (source-order). EXECUTED: the injected masker masks a NETWORK
    prompt under sensitive mode (raw operator span gone), EXEMPTS qwen_local (local handler), passes
    raw under non-sensitive, and RAISES for a network agent flagged may_handle_sensitive (LAW-IV
    misconfig). may_handle_sensitive is consumed live here. CPU-only, tempdir, non-mutating."""
    import tempfile, inspect
    import sensitivity_layer as S
    import agent_wrapper
    src = inspect.getsource(agent_wrapper.AgentWrapper.run_task)
    i_mask, i_disp = src.find("outbound_masker("), src.find("self.dispatch(")
    if not (0 <= i_mask < i_disp):
        return _fail("run_task must call outbound_masker BEFORE dispatch")
    d = Path(tempfile.mkdtemp(prefix="shimmer_p2_68_"))
    rules, _ = _p1_masking_fixture(d)
    registry = {"NETAGENT": {"backend": "claude_api", "may_handle_sensitive": False},
                "LOCALAGENT": {"backend": "qwen_local", "may_handle_sensitive": True},
                "BADNET": {"backend": "openai_api", "may_handle_sensitive": True}}
    ledger = d / "ledger.jsonl"
    masker = S.make_outbound_prompt_masker(sensitive=True, operator_rules=rules, project_root=str(d),
                                           registry=registry, run_id="R", ledger_path=str(ledger))
    sp_raw, ds_raw = "Citizen ID 12-345-6789 must be reviewed.", "Public clause text."
    saved = S.LAYER_ACTIVE
    try:
        S.LAYER_ACTIVE = True
        sp, ds = masker(sp_raw, ds_raw, backend="claude_api", agent="NETAGENT")
        if "12-345-6789" in sp or "[REDACTED" not in sp:
            return _fail(f"network prompt not masked: {sp!r}")
        if masker(sp_raw, ds_raw, backend="qwen_local", agent="LOCALAGENT")[0] != sp_raw:
            return _fail("qwen_local must be EXEMPT (local handler; prompt unchanged)")
        try:
            masker(sp_raw, ds_raw, backend="openai_api", agent="BADNET")
            return _fail("network may_handle_sensitive agent must RAISE (LAW-IV misconfig)")
        except PermissionError:
            pass
    finally:
        S.LAYER_ACTIVE = saved
    off = S.make_outbound_prompt_masker(sensitive=False, operator_rules=rules, project_root=str(d),
                                        registry=registry)
    if off(sp_raw, ds_raw, backend="claude_api", agent="NETAGENT")[0] != sp_raw:
        return _fail("non-sensitive run must pass the prompt unchanged")
    if "12-345-6789" in ledger.read_text(encoding="utf-8"):
        return _fail("raw operator span leaked into the exposure ledger")
    return _ok("chokepoint 1 prompt masked: wired before dispatch; network masked, qwen_local exempt, "
               "non-sensitive raw, network+may_handle_sensitive raises; ledger payload-free")


def check_69_chokepoint_query_masked():
    """INFRA-041 P2 chokepoint 2: the web-query egress is masked. WIRED: search() calls the injected
    query masker before any engine call (source). EXECUTED: with the layer active + sensitive, a query
    carrying an operator span reaches the (stubbed) engine MASKED; inert when inactive. No network,
    tempdir, non-mutating."""
    import tempfile, inspect
    import sensitivity_layer as S
    import search_router as SR
    if "self.query_masker" not in inspect.getsource(SR.SearchRouter.search):
        return _fail("search() must call self.query_masker before egress")
    d = Path(tempfile.mkdtemp(prefix="shimmer_p2_69_"))
    rules, _ = _p1_masking_fixture(d)
    masker = S.make_query_masker(sensitive=True, operator_rules=rules, project_root=str(d),
                                 run_id="R", ledger_path=str(d / "l.jsonl"))
    saved = S.LAYER_ACTIVE
    try:
        S.LAYER_ACTIVE = True
        router = SR.SearchRouter(project_root=d, keys={}, registry={}, query_masker=masker)
        seen = {}
        router._ddg_search = lambda q, max_results=5: (seen.update(ddg=q) or ([], ""))
        router._brave_search = lambda q: (seen.update(brave=q) or ([], ""))
        router.search("lookup ID 12-345-6789 today", agent=None, claim_type="x")
        recorded = seen.get("ddg", "")
        if "12-345-6789" in recorded or "[REDACTED" not in recorded:
            return _fail(f"query reached the engine unmasked: {recorded!r}")
        inert = masker  # same masker, but layer flips back below
    finally:
        S.LAYER_ACTIVE = saved
    if masker("ID 12-345-6789 today") != "ID 12-345-6789 today":
        return _fail("query masker must be inert when the layer is inactive")
    return _ok("chokepoint 2 query masked: wired at search() top; operator span masked before the "
               "engine under sensitive mode; inert when the layer is inactive")


def check_70_chokepoint_date_web_suppressed():
    """INFRA-041 P2 chokepoint 4: the BOOT date-web egress is SUPPRESSED (not masked) under sensitive
    mode -- no document title is sent to the web. EXECUTED: date_from_web makes no search call and
    returns None under sensitive mode, calls search under non-sensitive. WIRED: resolve_dates threads
    sensitive, and pipeline.main passes it to _populate_operational (source). No network."""
    import inspect
    import document_dating as DD
    from search_router import SearchResult

    class _Rec:
        def __init__(self): self.calls = []
        def search(self, q, **k):
            self.calls.append(q)
            return SearchResult(query=q, hits=[], strategy_used="x", verdict="UNVERIFIABLE", diagnostic={})

    r = _Rec()
    if DD.date_from_web("Confidential Merger File 2024", search_router=r, sensitive=True) is not None:
        return _fail("date_from_web must return None (suppressed) under sensitive mode")
    if r.calls:
        return _fail("date_from_web must NOT call search under sensitive mode (raw title would egress)")
    r2 = _Rec()
    DD.date_from_web("Public Title 2024", search_router=r2, sensitive=False)
    if not r2.calls:
        return _fail("date_from_web must call search under non-sensitive mode")
    if "sensitive=sensitive" not in inspect.getsource(DD.resolve_dates):
        return _fail("resolve_dates must thread sensitive to date_from_web")
    import pipeline
    if "sensitive=sensitivity_layer.is_active() and redaction_enabled" not in inspect.getsource(pipeline.main):
        return _fail("pipeline.main must pass sensitive to _populate_operational")
    return _ok("chokepoint 4 date-web SUPPRESSED under sensitive mode (no title to the web); "
               "non-sensitive still searches; resolve_dates + pipeline thread the sensitive flag")


def check_71_boot_stores_payload_free():
    """INFRA-041 P3: the adaptive_spawn BOOT stores are payload-free BY CONSTRUCTION. EXECUTED:
    spawn_all runs on a synthetic corpus carrying a planted operator span; the citation store keeps
    pattern+count but DROPS verbatim examples, situational stores institution CATEGORIES not names,
    and linguistic DROPS the verbatim representative sentences. No planted operator span survives in
    any of the three stores, in any mode (not mode-gated). Tempdir, non-mutating."""
    import tempfile
    import adaptive_spawn, durable_paths
    d = Path(tempfile.mkdtemp(prefix="shimmer_p3_71_"))
    ctx = d / "input" / "context"; ctx.mkdir(parents=True)
    planted = "The secret applicant codename is Bluebird."
    corpus = ("United Nations Security Council resolution A/RES/70/1 decides the matter. " + planted +
              " Citizen identifier 12-345-6789 is on file. The Council requests a report. "
              "Article 5 shall apply pursuant to the regulation.")
    (ctx / "doc1.md").write_text(corpus, encoding="utf-8")
    adaptive_spawn.spawn_all(d, overwrite=True)

    cit_text = durable_paths.citation_convention_path(d).read_text(encoding="utf-8")
    cit = json.loads(cit_text)
    if not cit["rules"]:
        return _fail("citation rules not produced on the synthetic corpus")
    for r in cit["rules"]:
        if "examples" in r:
            return _fail(f"citation rule still carries verbatim examples: {r}")
        if "sample_count" not in r or "pattern" not in r:
            return _fail("citation rule lost its useful pattern/count")
    if "A/RES/70/1" in cit_text:
        return _fail("verbatim citation token leaked into the citation store")

    sit = durable_paths.situational_awareness_path(d).read_text(encoding="utf-8")
    if "Council" not in sit:
        return _fail("situational lost the institution category")
    if "Security Council" in sit:
        return _fail("verbatim institution NAME leaked into situational")
    if planted in sit or "Bluebird" in sit or "12-345-6789" in sit:
        return _fail("operator content span leaked into situational")

    ling = durable_paths.linguistic_identity_path(d).read_text(encoding="utf-8")
    if "Representative sentences" in ling:
        return _fail("linguistic still emits verbatim representative sentences")
    if planted in ling or "Bluebird" in ling or "12-345-6789" in ling:
        return _fail("operator content span leaked into linguistic_identity")
    return _ok("BOOT stores payload-free by construction: citation drops examples (pattern+count kept); "
               "situational stores institution categories not names; linguistic drops quoted sentences; "
               "no planted operator span in any store")


def check_72_document_dates_payload_free_and_ingest():
    """INFRA-041 P3: document_dates is payload-free (filename + date only; title-from-content,
    abs_path, and the validation first-page excerpt are DROPPED on write, by construction). EXECUTED:
    write_dates persists a projection; the dropped fields and a planted span are absent. Downstream:
    the OGE Tier-1 ingest still BUILDS a Document node from the abstracted store. Tempdir, non-mutating."""
    import tempfile
    import document_dating, durable_paths, ontology_graph
    d = Path(tempfile.mkdtemp(prefix="shimmer_p3_72_"))
    excerpt = "first page secret text Bluebird"
    records = [{"filename": "merger_x_2026.md", "date": "2026-01-01", "date_source": "filename",
                "date_confidence": "high", "title": "Confidential Merger of AcmeCo and BetaCo",
                "abs_path": "C:/Users/secret/input/merger_x_2026.md", "content_validated": True,
                "validation_note": f"matched=['merger']; first_page_excerpt={excerpt!r}"}]
    document_dating.write_dates(d, records)
    raw = durable_paths.document_dates_path(d).read_text(encoding="utf-8")
    stored = json.loads(raw)["documents"][0]
    if "title" in stored or "abs_path" in stored or "validation_note" in stored:
        return _fail(f"document_dates store still carries dropped fields: {list(stored)}")
    for leak in ("Confidential Merger", "AcmeCo", "C:/Users/secret", "Bluebird", "first_page_excerpt"):
        if leak in raw:
            return _fail(f"operator content/path leaked into document_dates store: {leak!r}")
    if stored.get("filename") != "merger_x_2026.md" or stored.get("date") != "2026-01-01":
        return _fail("document_dates store lost its useful filename/date")
    out = d / "graph.json"
    g = ontology_graph.build_graph(sources={"document_dates": durable_paths.document_dates_path(d)},
                                   out_path=str(out))
    docnode = next((n for n in g["nodes"] if n["type"] == "Document" and n["id"] == "merger_x_2026.md"), None)
    if not docnode:
        return _fail("OGE ingest did not build a Document node from the abstracted store")
    if docnode.get("title"):
        return _fail("OGE Document node carries a title from the abstracted store (should be None)")
    return _ok("document_dates payload-free (filename+date only; title/abs_path/excerpt dropped); "
               "OGE ingest still builds a Document node (title None) from the abstracted store")


def ast_parse_all_modules():
    bad = []
    for p in SCRIPTS.rglob("*.py"):
        try: ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e: bad.append(f"{p.relative_to(ROOT)}: {e}")
    if bad: return _fail(f"syntax errors: {bad}")
    return _ok(f"ast.parse() ok on {sum(1 for _ in SCRIPTS.rglob('*.py'))} modules")


CHECKS = [
    ("00 ast.parse on all modules", ast_parse_all_modules),
    ("01 Directory structure", check_01_directory),
    ("02 constitution.json has 7 seed laws", check_02_constitution),
    ("03 agent_registry.json has 18 agents", check_03_agent_registry),
    ("04 agent_contracts.json has schemas", check_04_contracts),
    ("05 constitution.check() against 4 layers", check_05_constitution_check),
    ("06 match_tf_law() returns confidence", check_06_match_tf_law),
    ("07 message_bus post/read/query/summarize", check_07_message_bus),
    ("08 bus_reader assembles per-backend context", check_08_bus_reader),
    ("09 agent_wrapper has all callers + run_task", check_09_agent_wrapper_callers),
    ("10 orchestrator full deliberation round", check_10_orchestrator_deliberation),
    ("11 orchestrator evaluates a charter", check_11_orchestrator_evaluate_charter),
    ("12 orchestrator escalates when silent", check_12_orchestrator_escalation),
    ("13 Task force formation end-to-end", check_13_tf_formation_endtoend),
    ("14 Charter dissolution codifies TF-law", check_14_tf_dissolution),
    ("15 search_router executes DDG", check_15_search),
    ("16 claim_classifier extracts/types claims", check_16_claim_classifier),
    ("17 memory three tiers with TTL", check_17_memory),
    ("18 agent output validates against contract", check_18_contract_validation),
    ("19 Every bus message has constitution_check", check_19_bus_constitution_field),
    ("20 run_summary generates with stats", check_20_run_summary),
    ("21 No hardcoded paths in scripts/", check_21_no_hardcoded_paths),
    ("22 No domain-specific terms in scripts/", check_22_no_domain_terms),
    ("23 API keys load from external", check_23_keys_not_hardcoded),
    ("24 Qwen agents receive only LAW-II+IV", check_24_qwen_minimal_context),
    ("25 asyncio parallel execution", check_25_async),
    ("26 Mid-execution BLOCK pauses agents", check_26_block_interrupt),
    ("27 Adaptive spawn creates LINGUISTIC_IDENTITY", check_27_adaptive_spawn),
    ("28 input/ exists and accepts documents", check_28_input_dir),
    ("29 CLAUDE.md points to genesis", check_29_claude_md),
    ("30 Full pipeline runs on test doc no crash", check_30_pipeline_smoke),
    ("31 input/ has context/, operational/, conventions/", check_31_three_input_subdirs),
    ("32 convention_parser produces valid registry", check_32_convention_parser),
    ("33 reference_builder produces valid index", check_33_reference_builder),
    ("34 AMENDMENT_DRAFTER contract has ref-bearing fields", check_34_amendment_drafter_contract),
    ("35 amendment.comment requires >=1 CONV-* and >=1 REF-*", check_35_amendment_comment_citation_format),
    ("36 context_summary + operative_summary generators present", check_36_summaries_for_cutoff_docs),
    ("37 review_scope cutoff respected", check_37_review_scope_cutoff),
    ("38 embedding store build + query (Part XXI graceful)", check_38_embedding_store),
    ("39 canonical inter-agent envelope enforced (INFRA-037)", check_39_canonical_envelope),
    ("40 highest-revision item selection (INFRA-037)", check_40_highest_revision),
    ("41 conventions compile to operator redaction rules (INFRA-038)", check_41_redaction_rules),
    ("42 may_use_web enforced at search boundary (INFRA-038)", check_42_may_use_web_enforced),
    ("43 sensitivity layer built-but-inactive + logged override (INFRA-038)", check_43_sensitivity_layer_gate),
    ("44 REDACTOR contract pins kind=redaction + rule_id", check_44_redactor_contract_pins),
    ("45 redaction detected structurally; no silent NONE", check_45_redaction_structural_no_silent_none),
    ("46 redaction scrubs ALL artifacts + normalized matching", check_46_redaction_applies_to_all_artifacts),
    ("47 redaction outcome verified (survivor BLOCKS; span counts)", check_47_redaction_outcome_verified),
    ("48 qwen_local shares one resident model per model_id", check_48_qwen_shared_model_cache),
    ("49 no silent default redaction floor (operator-sovereignty)", check_49_no_silent_default_floor),
    ("50 deterministic detection, authorized-only + language-neutral", check_50_deterministic_detection_language_neutral),
    ("51 editorial board structural: six ranks + FAMILY SPLIT (3 claude/3 gpt), verdict set, redaction-free", check_51_editorial_structural),
    ("52 EDITOR_CLERK ordering: after AMENDMENT_DRAFTER, before phase 9 scrub (clean master)", check_52_editorial_ordering),
    ("53 editorial board escalation loop is bounded (max_rounds cap before climb)", check_53_editorial_board_bounded),
    ("54 editorial board uses no operator ESCALATE path (intra-phase on the bus)", check_54_editorial_board_no_operator_escalate),
    ("55 editorial board output budget is config-resolved (no hardcoded 2048)", check_55_editorial_board_output_budget),
    ("56 audit synthesizer wired + proposal-side (cross-run learning loop)", check_56_audit_synthesizer_wired),
    ("57 OGE capture hook wired + executed (provisions + proposal accumulator)", check_57_oge_capture_wired),
    ("58 OGE masked-write gate (sensitive -> [REDACTED:TYPE], non-sensitive -> real)", check_58_oge_masked_write_gate),
    ("59 OGE Tier-1 ingest executed (nodes + edges + stub + derivable + no abs_path)", check_59_oge_ingest_executed),
    ("60 OGE ingest payload-free (masked text carried as-is; regex cannot match a placeholder)", check_60_oge_ingest_payload_free),
    ("61 OGE graph rebuilt at run-end (build_graph wired after capture_run)", check_61_oge_graph_rebuilt_at_run_end),
    ("62 OGE GNN executed end-to-end (MACHINERY not learning: fwd+delta-backprop, weights move, incremental)", check_62_oge_gnn_executed),
    ("63 OGE GNN payload-free (SAFE-only features; no RAW/placeholder in state)", check_63_oge_gnn_payload_free),
    ("64 OGE GNN wired at run-end (gnn_update after build_graph after capture_run)", check_64_oge_gnn_wired_at_run_end),
    ("65 masking engine x/y split + typed placeholders + exposure ledger (INFRA-041 P1)", check_65_masking_engine_splits),
    ("66 masking rejoin restores held-local y + dedupes by item_id/revision (INFRA-041 P1)", check_66_masking_rejoin_dedupe),
    ("67 masking idempotent + inert under non-sensitive + no silent passthrough (INFRA-041 P1)", check_67_masking_idempotent_and_inert),
    ("68 chokepoint 1 prompt egress masked (network) / exempt (qwen_local) (INFRA-041 P2)", check_68_chokepoint_prompt_masked),
    ("69 chokepoint 2 web query masked before egress (INFRA-041 P2)", check_69_chokepoint_query_masked),
    ("70 chokepoint 4 BOOT date-web suppressed under sensitive mode (INFRA-041 P2)", check_70_chokepoint_date_web_suppressed),
    ("71 BOOT stores payload-free by construction (citation/situational/linguistic) (INFRA-041 P3)", check_71_boot_stores_payload_free),
    ("72 document_dates payload-free + OGE ingest still builds (INFRA-041 P3)", check_72_document_dates_payload_free_and_ingest),
]


def main():
    results = []
    for title, fn in CHECKS:
        try:
            status, detail = fn()
        except Exception as e:
            status, detail = "ERROR", f"{type(e).__name__}: {e}\n{traceback.format_exc().splitlines()[-2]}"
        results.append((title, status, detail))
    title_w = max(len(t) for t, _, _ in results); status_w = 8
    print(f"\n{'Check'.ljust(title_w)}  {'Status'.ljust(status_w)}  Detail")
    print("-" * (title_w + status_w + 60))
    for title, status, detail in results:
        print(f"{title.ljust(title_w)}  {status.ljust(status_w)}  {detail}")
    print()
    passed = sum(1 for _, s, _ in results if s == "PASS")
    warned = sum(1 for _, s, _ in results if s == "WARN")
    failed = sum(1 for _, s, _ in results if s in ("FAIL", "ERROR"))
    print(f"PASS={passed}  WARN={warned}  FAIL/ERROR={failed}  TOTAL={len(results)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
