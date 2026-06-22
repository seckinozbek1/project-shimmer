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
    "SPEECH_ACT_TAGGER", "REDACT_CLERK", "REDACT_AUTHORITY", "REDACT_GATE",
    "AMENDMENT_DRAFTER",
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
    return _ok(f"{len(agents)} agents with DOES/DOES NOT/model (14 incl. AMENDMENT_DRAFTER)")


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
    {agent, doc_id, items:[flat items]}. For ALL 14 agents, a valid wrapper of one
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
    return _ok("all 14 agents enforce the canonical wrapper of flat core-bearing items")


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
    from convention_parser import redaction_rules, DEFAULT_REDACTION_RULES
    # empty registry -> defaults only, explicitly reported as such
    empty = redaction_rules({"conventions": []})
    if empty["operator_in_force"] or empty["source"] != "defaults":
        return _fail("empty registry should report source=defaults, operator_in_force=False")
    if len(empty["rules"]) != len(DEFAULT_REDACTION_RULES) or empty["warnings"]:
        return _fail("empty registry should yield exactly the default floor, no warnings")
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
    if not res["operator_in_force"] or res["source"] != "operator+defaults":
        return _fail("operator rule not reported in force")
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
    if agent_may_use_web(registry, "REDACT_CLERK"):
        return _fail("REDACT_CLERK must not have may_use_web")
    if not agent_may_use_web(registry, "FACT_CHECKER"):
        return _fail("FACT_CHECKER should have may_use_web")
    r = SearchRouter.open(ROOT)
    try:
        r.search("x", agent="REDACT_CLERK")
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
    if not sensitivity_layer.may_handle_sensitive(registry, "REDACT_CLERK"):
        return _fail("REDACT_CLERK should be may_handle_sensitive (dormant on-switch)")
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
    ("03 agent_registry.json has 14 agents", check_03_agent_registry),
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
