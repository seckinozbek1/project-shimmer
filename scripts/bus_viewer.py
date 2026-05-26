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
    p.add_argument("--follow", action="store_true")
    p.add_argument("--channel"); p.add_argument("--type", dest="msg_type"); p.add_argument("--sender")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--tail", type=int, default=0)
    args = p.parse_args(argv)

    use_color = (not args.no_color) and sys.stdout.isatty()
    path = (Path(args.path) if args.path
            else Path(__file__).resolve().parent.parent / "output" / "logs" / "agent_bus.jsonl")
    cost_path = path.parent / "cost_tracker.jsonl"
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
            new_msgs, offset = _read_jsonl(path, offset_bytes=offset)
            new_msgs = _apply_filters(new_msgs, channel=args.channel, msg_type=args.msg_type, sender=args.sender)
            for m in new_msgs: print(_format(m, use_color=use_color)); sys.stdout.flush()
            new_cost, cost_offset = _read_jsonl(cost_path, offset_bytes=cost_offset)
            for ev in new_cost: print(_format_cost_event(ev, use_color=use_color)); sys.stdout.flush()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
