"""Command line for the 16688 supply client.

Read-only commands: detail, list, quote, query, dry-run
Spending command:   buy  (needs --max-total and --yes)
"""
from __future__ import annotations

import argparse
import json
import sys

from client import ApiError, Client, safe_purchase, wait_delivery

LEDGER = "ledger.jsonl"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="16688")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="goods already proxied into your account")
    s.add_argument("--keywords", default="")

    s = sub.add_parser("detail")
    s.add_argument("goods_no")

    s = sub.add_parser("quote", help="price, fee, stock and wallet check; spends nothing")
    s.add_argument("goods_no")
    s.add_argument("-n", "--quantity", type=int, default=1)

    s = sub.add_parser("query", help="look up a purchase order")
    s.add_argument("trade_no")
    s.add_argument("--show-cards", action="store_true", help="print card codes (secrets)")

    s = sub.add_parser("dry-run", help="print the signed request body for an endpoint; sends nothing")
    s.add_argument("path", help="e.g. /openApi/purchase/quotePrice")
    s.add_argument("params", nargs="*", help="key=value pairs")

    s = sub.add_parser("buy", help="REAL PURCHASE from your operating wallet")
    s.add_argument("goods_no")
    s.add_argument("-n", "--quantity", type=int, default=1)
    s.add_argument("--max-total", type=float, required=True, help="refuse if goods+fee exceeds this (yuan)")
    s.add_argument("--yes", action="store_true", help="confirm that you really want to spend money")
    s.add_argument("--remark", default="")
    s.add_argument("--wait", type=float, default=120.0, help="seconds to wait for delivery")
    s.add_argument("--show-cards", action="store_true")

    a = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy codepage
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    c = Client()
    try:
        if a.cmd == "list":
            print(json.dumps(c.supply_goods(a.keywords), ensure_ascii=False, indent=2))
        elif a.cmd == "detail":
            print(json.dumps(c.goods_detail(a.goods_no), ensure_ascii=False, indent=2))
        elif a.cmd == "quote":
            q = c.quote(a.goods_no, a.quantity)
            print(json.dumps(q.raw, ensure_ascii=False, indent=2))
        elif a.cmd == "query":
            o = c.query(a.trade_no)
            _show(o, a.show_cards)
        elif a.cmd == "dry-run":
            biz = dict(kv.split("=", 1) for kv in a.params)
            print(json.dumps(c.build(a.path, **biz), ensure_ascii=False, indent=2))
        elif a.cmd == "buy":
            if not a.yes:
                print("refusing: pass --yes to confirm a real purchase (try `quote` first)", file=sys.stderr)
                return 2
            o = safe_purchase(c, a.goods_no, a.quantity, a.max_total, ledger_path=LEDGER, remark=a.remark)
            if not o.delivered:
                o = wait_delivery(c, o.trade_no, timeout=a.wait)
            _show(o, a.show_cards)
    except ApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _show(o, show_cards: bool) -> None:
    print(f"trade_no={o.trade_no} goods_no={o.goods_no} status={o.status_name} total={o.total_amount}")
    print(f"cards={len(o.cards)}")
    if show_cards:
        for code in o.cards:
            print(code)
    if o.instruction:
        print(f"instruction: {o.instruction}")


if __name__ == "__main__":
    sys.exit(main())
