"""16688 open API client (supply side only).

Stdlib only. Credentials come from the environment, never from code:
    SIXTEEN688_APP_ID, SIXTEEN688_SECRET
    SIXTEEN688_GATEWAY (optional, default https://www.16688.com.cn/openApi)

Signing follows https://www.16688.com.cn/api/purchase/docs/ (read 2026-10-16):
    plain = METHOD \\n controller \\n action \\n k1=v1&k2=v2   (sign excluded, keys ASCII-sorted)
    sign  = hex(HMAC-SHA256(plain, secret))
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_GATEWAY = "https://www.16688.com.cn/openApi"

# purchase order status (docs: purchase/create)
STATUS = {0: "pending_payment", 1: "awaiting_delivery", 2: "closed", 3: "refunded", 4: "delivered", 5: "completed"}
DELIVERED = {4, 5}
TERMINAL_FAIL = {2, 3}


def load_dotenv(path: str | None = None) -> None:
    """Load SIXTEEN688_* keys from a local .env next to this file.

    Real environment variables win. Other keys are ignored on purpose.
    """
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key.startswith("SIXTEEN688_") and val and key not in os.environ:
            os.environ[key] = val


class ApiError(Exception):
    def __init__(self, msg: str, path: str = "", payload: Any = None):
        super().__init__(f"{path}: {msg}" if path else msg)
        self.msg = msg
        self.path = path
        self.payload = payload


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _normalize(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    return value


def _canonical(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(_normalize(value), ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, float) and value == int(value):
        # PHP (string)1.0 == "1"
        return str(int(value))
    return str(value)


def sign(params: dict[str, Any], controller: str, action: str, secret: str, method: str = "POST") -> str:
    parts = [f"{k}={_canonical(params[k])}" for k in sorted(params) if k != "sign"]
    plain = "\n".join([method.upper(), controller.lower(), action.lower(), "&".join(parts)])
    return hmac.new(secret.encode(), plain.encode(), hashlib.sha256).hexdigest()


def split_path(path: str) -> tuple[str, str]:
    """'/openApi/stockSecret/invalidateAll' -> ('stocksecret', 'invalidateall')"""
    segs = [s for s in path.strip("/").split("/") if s]
    if len(segs) != 3 or segs[0].lower() != "openapi":
        raise ValueError(f"unexpected API path: {path}")
    return segs[1].lower(), segs[2].lower()


@dataclass
class Quote:
    goods_no: str
    quantity: int
    unit_price: float
    goods_total: float
    fee: float
    total: float
    available_quantity: int
    available_money: float
    balance_enough: bool
    raw: dict


@dataclass
class Purchase:
    trade_no: str
    goods_no: str
    status: int
    total_amount: float
    cards: list[str]
    instruction: str
    raw: dict

    @property
    def status_name(self) -> str:
        return STATUS.get(self.status, f"unknown({self.status})")

    @property
    def delivered(self) -> bool:
        return self.status in DELIVERED and bool(self.cards)


class Client:
    def __init__(self, app_id: str | None = None, secret: str | None = None,
                 gateway: str | None = None, timeout: float = 20.0):
        if not (app_id and secret):
            load_dotenv()
        self.app_id = app_id or os.environ.get("SIXTEEN688_APP_ID", "")
        self.secret = secret or os.environ.get("SIXTEEN688_SECRET", "")
        self.gateway = (gateway or os.environ.get("SIXTEEN688_GATEWAY") or DEFAULT_GATEWAY).rstrip("/")
        self.timeout = timeout

    # ---- low level -------------------------------------------------
    def build(self, path: str, **biz: Any) -> dict[str, Any]:
        """Build the signed request body without sending it."""
        if not self.app_id or not self.secret:
            raise ApiError("missing SIXTEEN688_APP_ID / SIXTEEN688_SECRET")
        try:
            controller, action = split_path(path)
        except ValueError as e:
            raise ApiError(str(e)) from e
        body: dict[str, Any] = {k: v for k, v in biz.items() if v is not None}
        body["app_id"] = self.app_id
        body["timestamp"] = str(int(time.time()))
        body["nonce"] = secrets.token_hex(16)  # 32 hex chars, docs require 16-64 alnum
        body["sign"] = sign(body, controller, action, self.secret)
        return body

    def call(self, path: str, **biz: Any) -> Any:
        path = "/" + path.lstrip("/")
        body = self.build(path, **biz)
        req = urllib.request.Request(
            self.gateway.removesuffix("/openApi") + path,
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise ApiError(f"HTTP {e.code}", path) from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise ApiError(f"transport error: {e}", path) from e
        if payload.get("code") != 1:
            raise ApiError(str(payload.get("msg")), path, payload)
        return payload.get("data")

    # ---- supply-side endpoints ------------------------------------
    def supply_goods(self, keywords: str = "", page_no: int = 1, page_size: int = 20) -> dict:
        """Goods already proxied into this account (not the whole marketplace)."""
        return self.call("/openApi/goods/list", keywords=keywords, page_no=page_no,
                         page_size=page_size, source="supply")

    def goods_detail(self, goods_no: str) -> dict:
        return self.call("/openApi/goods/detail", goods_no=goods_no)

    def quote(self, goods_no: str, quantity: int = 1) -> Quote:
        d = self.call("/openApi/purchase/quotePrice", goods_no=goods_no, quantity=quantity)
        return Quote(goods_no=d["goods_no"], quantity=int(d["quantity"]), unit_price=float(d["unit_price"]),
                     goods_total=float(d["goods_total_amount"]), fee=float(d["fee"]),
                     total=float(d["total_amount"]), available_quantity=int(d["available_quantity"]),
                     available_money=float(d["available_money"]), balance_enough=bool(d["balance_enough"]),
                     raw=d)

    def purchase(self, goods_no: str, quantity: int = 1, remark: str = "") -> Purchase:
        """Spends operating-wallet balance. Callers should go through safe_purchase()."""
        d = self.call("/openApi/purchase/create", goods_no=goods_no, quantity=quantity, remark=remark or None)
        return self._purchase(d)

    def query(self, trade_no: str) -> Purchase:
        return self._purchase(self.call("/openApi/purchase/query", trade_no=trade_no))

    def complain(self, trade_no: str, reason: str, image_urls: list[str], description: str = "") -> dict:
        if not 1 <= len(image_urls) <= 6:
            raise ValueError("complaint needs 1-6 evidence image URLs")
        return self.call("/openApi/purchase/applyComplaint", trade_no=trade_no, reason=reason,
                         description=description or None, images=image_urls)

    @staticmethod
    def _purchase(d: dict) -> Purchase:
        cards = [c["code"] if isinstance(c, dict) else str(c) for c in (d.get("cards") or [])]
        return Purchase(trade_no=d["trade_no"], goods_no=d.get("goods_no", ""), status=int(d["status"]),
                        total_amount=float(d.get("total_amount") or 0), cards=cards,
                        instruction=d.get("instruction") or "", raw=d)


def safe_purchase(client: Client, goods_no: str, quantity: int, max_total: float,
                  ledger_path: str | None = None, remark: str = "") -> Purchase:
    """Quote first, refuse if the price exceeds max_total or stock/balance is short, then buy.

    max_total is the most you are willing to pay in yuan (goods + fee) for this order.
    Every attempt that reaches the purchase call is appended to the ledger, so a crash
    after the request does not lose the trade_no.
    """
    q = client.quote(goods_no, quantity)
    if q.available_quantity < quantity:
        raise ApiError(f"stock {q.available_quantity} < requested {quantity}")
    if not q.balance_enough:
        raise ApiError(f"operating wallet short: need {q.total}, have {q.available_money}")
    if q.total > max_total:
        raise ApiError(f"price {q.total} exceeds max_total {max_total}")
    p = client.purchase(goods_no, quantity, remark)
    if ledger_path:
        _ledger(ledger_path, {"ts": int(time.time()), "event": "purchase", "trade_no": p.trade_no,
                              "goods_no": goods_no, "quantity": quantity, "total": p.total_amount,
                              "status": p.status})
    return p


def wait_delivery(client: Client, trade_no: str, timeout: float = 120.0, interval: float = 3.0) -> Purchase:
    """Poll purchase/query until the cards arrive. The API has no callback."""
    deadline = time.time() + timeout
    while True:
        p = client.query(trade_no)
        if p.delivered:
            return p
        if p.status in TERMINAL_FAIL:
            raise ApiError(f"order {trade_no} ended as {p.status_name}")
        if time.time() >= deadline:
            raise ApiError(f"order {trade_no} not delivered within {timeout}s (status {p.status_name})")
        time.sleep(interval)


def _ledger(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
