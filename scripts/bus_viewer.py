"""Colorized terminal viewer for the Shimmer message bus + cost stream."""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path
from typing import Any


RESET = "\033[0m"; DIM = "\033[2m"; BOLD = "\033[1m"
FG = {"red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
      "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m", "white": "\033[37m",
      "bright_red": "\033[91m", "bright_green": "\033[92m",
      "bright_yellow": "\033[93m", "bright_magenta": "\033[95m", "bright_cyan": "\033[96m"}

ROLE_COLOR = {"orchestrator": FG["cyan"], "operator": FG["bright_magenta"],
              "supervisor": FG["yellow"], "agent": FG["white"]}
TYPE_COLOR = {
    "ESCALATE": FG["red"], "BLOCK": FG["bright_red"],
    "CHARTER_PROPOSE": FG["green"], "CHARTER_APPROVE": FG["bright_green"],
    "CHARTER_DENY": FG["red"], "DISSOLVE": DIM + FG["white"],
    "LAW_CREATED": FG["bright_green"] + BOLD, "CONFIRM": FG["green"],
    "INFORM": FG["blue"], "PROPOSE": FG["green"], "REQUEST": FG["blue"],
    "OFFER": FG["green"], "CHALLENGE": FG["yellow"], "YIELD": DIM + FG["white"],
    "MEMORY_HIT": FG["bright_cyan"], "DEDUP_ALERT": FG["yellow"],
    "PRECEDENT_APPLIED": FG["bright_cyan"], "API_DISCOVERED": FG["magenta"],
}


def _enable_utf8():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def _format(msg, *, use_color):
    sender = str(msg.get("sender", "?")); role = str(msg.get("sender_role", "?"))
    recipient = str(msg.get("recipient", "?")); channel = str(msg.get("channel", "?"))
    mtype = str(msg.get("type", "?")); ts = str(msg.get("timestamp", ""))[:19]
    body = msg.get("body", "")
    cc = msg.get("constitution_check", {}) or {}
    laws = ",".join(cc.get("laws_consulted") or []); result = cc.get("result", "?")
    body_str = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    body_str = body_str.replace("\n", " ")[:160]
    if use_color:
        role_c = ROLE_COLOR.get(role, ""); type_c = TYPE_COLOR.get(mtype, "")
        sender_block = f"{role_c}{sender:<14}{RESET}"
        type_block = f"{type_c}{mtype:<16}{RESET}"
        result_color = FG["green"] if result == "RESOLVED" else FG["yellow"]
        cc_block = f"{result_color}[{result}{':' + laws if laws else ''}]{RESET}"
    else:
        sender_block = f"{sender:<14}"; type_block = f"{mtype:<16}"
        cc_block = f"[{result}{':' + laws if laws else ''}]"
    return f"{ts}  {sender_block} -> {recipient:<14} ({channel:<24}) {type_block} {cc_block} {body_str}"


def _read_jsonl(path, *, offset_bytes=0):
    if not path.exists(): return [], offset_bytes
    with path.open("rb") as fh:
        fh.seek(offset_bytes); chunk = fh.read(); new_offset = fh.tell()
    msgs = []
    for line in chunk.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line: continue
        try: msgs.append(json.loads(line))
        except json.JSONDecodeError: continue
    return msgs, new_offset


def _format_cost_event(event, *, use_color):
    ts = str(event.get("timestamp", ""))[:19]
    agent = str(event.get("agent", "?")); family = str(event.get("family", "?"))
    cost = float(event.get("cost_usd", 0.0) or 0.0)
    in_tok = int(event.get("input_tokens", 0) or 0); out_tok = int(event.get("output_tokens", 0) or 0)
    ok = bool(event.get("ok", False)); err = str(event.get("error", ""))
    marker = "+" if ok else "x"
    base = (f"{ts}  [COST] {agent:<14} {family:<6} {marker}${cost:.4f} "
            f"(in={in_tok}, out={out_tok}){' ERR: ' + err if not ok and err else ''}")
    if use_color:
        return f"{DIM}{FG['yellow']}{base}{RESET}"
    return base


def _apply_filters(msgs, *, channel, msg_type, sender):
    out = msgs
    if channel: out = [m for m in out if m.get("channel") == channel]
    if msg_type: out = [m for m in out if m.get("type") == msg_type]
    if sender: out = [m for m in out if m.get("sender") == sender]
    return out


def main(argv=None):
    _enable_utf8()
    p = argparse.ArgumentParser(description="Colorized Shimmer bus viewer")
    p.add_argument("--path")
    p.add_argument("--run", help="run folder name under output/runs/ (default: latest)")
    p.add_argument("--follow", action="store_true")
    p.add_argument("--channel"); p.add_argument("--type", dest="msg_type"); p.add_argument("--sender")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--tail", type=int, default=0)
    args = p.parse_args(argv)

    use_color = (not args.no_color) and sys.stdout.isatty()
    # Target resolution (Part XXVII §A). Explicit target wins and stays fixed:
    #   --path FILE  -> that exact bus file
    #   --run NAME   -> output/runs/<NAME>/logs/agent_bus.jsonl
    # With neither, auto-latest tracks the newest run under output/runs/. In
    # --follow auto-latest mode the viewer waits for the first run if none exists
    # yet and switches to a newer run if one appears after launch.
    root = Path(__file__).resolve().parent.parent
    import run_context as run_context_mod
    explicit = bool(args.path or getattr(args, "run", None))

    if args.path:
        path = Path(args.path)
    elif getattr(args, "run", None):
        path = run_context_mod.for_run_dir(root, run_context_mod.runs_root(root) / args.run).bus_path()
    else:
        rc = run_context_mod.latest_run(root)
        if rc is None and not args.follow:
            print("[bus_viewer] no run folder under output/runs/. Pass --path or --run.",
                  file=sys.stderr)
            return 2
        path = rc.bus_path() if rc is not None else None

    auto_latest = args.follow and not explicit
    # Auto-latest + follow with no run yet: wait for the first run rather than error.
    if path is None:
        print("[bus_viewer] waiting for the first run under output/runs/ ...", file=sys.stderr)
        while path is None:
            time.sleep(1.0)
            rc = run_context_mod.latest_run(root)
            if rc is not None:
                path = rc.bus_path()
        print(f"[bus_viewer] following run {path.parent.parent.name}", file=sys.stderr)

    cost_path = path.parent / "cost_tracker.jsonl"
    # Initial history dump (the bus file may not exist yet; _read_jsonl returns []).
    msgs, offset = _read_jsonl(path)
    msgs = _apply_filters(msgs, channel=args.channel, msg_type=args.msg_type, sender=args.sender)
    if args.tail > 0: msgs = msgs[-args.tail:]
    for m in msgs: print(_format(m, use_color=use_color))
    if not args.follow: return 0
    cost_msgs, cost_offset = _read_jsonl(cost_path)
    if args.tail > 0: cost_msgs = cost_msgs[-args.tail:]
    for ev in cost_msgs: print(_format_cost_event(ev, use_color=use_color))
    print("--- following (Ctrl-C to stop) ---", file=sys.stderr)
    try:
        while True:
            time.sleep(0.5)
            # Auto-latest only: if a newer run folder appeared, switch to it.
            if auto_latest:
                rc = run_context_mod.latest_run(root)
                if rc is not None and rc.bus_path() != path:
                    path = rc.bus_path()
                    cost_path = path.parent / "cost_tracker.jsonl"
                    offset = 0; cost_offset = 0
                    print(f"--- switched to newer run {path.parent.parent.name} ---",
                          file=sys.stderr)
            new_msgs, offset = _read_jsonl(path, offset_bytes=offset)
            new_msgs = _apply_filters(new_msgs, channel=args.channel, msg_type=args.msg_type, sender=args.sender)
            for m in new_msgs: print(_format(m, use_color=use_color)); sys.stdout.flush()
            new_cost, cost_offset = _read_jsonl(cost_path, offset_bytes=cost_offset)
            for ev in new_cost: print(_format_cost_event(ev, use_color=use_color)); sys.stdout.flush()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
