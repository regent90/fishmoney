"""Offline tests. No network, no real credentials. Run: python -I -m unittest -v"""
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from unittest import mock

import client
from client import ApiError, Client, safe_purchase, sign, split_path, wait_delivery


class SignTests(unittest.TestCase):
    def test_split_path_lowercases_controller_and_action(self):
        self.assertEqual(split_path("/openApi/order/list"), ("order", "list"))
        self.assertEqual(split_path("/openApi/stockSecret/invalidateAll"), ("stocksecret", "invalidateall"))
        self.assertEqual(split_path("/openApi/goodsCategory/changeStatus"), ("goodscategory", "changestatus"))
        with self.assertRaises(ValueError):
            split_path("/other/x/y")

    def test_plain_text_and_hmac_match_docs_algorithm(self):
        params = {"app_id": "A", "timestamp": "1710000000", "nonce": "n" * 16, "goods_no": "SG1", "quantity": 2}
        plain = "POST\npurchase\nquoteprice\napp_id=A&goods_no=SG1&nonce=" + "n" * 16 + "&quantity=2&timestamp=1710000000"
        want = hmac.new(b"sek", plain.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(sign(params, "purchase", "quotePrice", "sek"), want)

    def test_sign_field_is_ignored(self):
        p = {"a": "1", "sign": "old"}
        self.assertEqual(sign(p, "x", "y", "k"), sign({"a": "1"}, "x", "y", "k"))

    def test_bool_none_and_nested_values(self):
        p = {"b": True, "c": False, "d": None, "e": ["中", "/x"], "f": {"z": 1, "a": 2}}
        plain = 'POST\nx\ny\nb=true&c=false&d=&e=["中","/x"]&f={"a":2,"z":1}'
        want = hmac.new(b"k", plain.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(sign(p, "x", "y", "k"), want)

    def test_whole_float_matches_php_string_cast(self):
        self.assertEqual(sign({"p": 10.0}, "x", "y", "k"), sign({"p": 10}, "x", "y", "k"))


class BuildTests(unittest.TestCase):
    def test_build_shape_and_nonce_uniqueness(self):
        c = Client("APP", "SECRET")
        a = c.build("/openApi/purchase/quotePrice", goods_no="SG1", quantity=1)
        b = c.build("/openApi/purchase/quotePrice", goods_no="SG1", quantity=1)
        self.assertEqual(a["app_id"], "APP")
        self.assertRegex(a["nonce"], r"^[0-9a-f]{16,64}$")
        self.assertNotEqual(a["nonce"], b["nonce"])
        self.assertEqual(len(a["sign"]), 64)
        self.assertNotIn("SECRET", json.dumps(a))

    def test_none_params_are_dropped(self):
        c = Client("APP", "SECRET")
        body = c.build("/openApi/purchase/create", goods_no="SG1", remark=None)
        self.assertNotIn("remark", body)

    def test_missing_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(client, "load_dotenv"):
            with self.assertRaises(ApiError):
                Client().build("/openApi/goods/list")

    def test_dotenv_loads_only_our_keys_and_env_wins(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".env")
            with open(p, "w", encoding="utf-8") as f:
                f.write('# c\nSIXTEEN688_APP_ID="from-file"\nSIXTEEN688_SECRET=s3\nOTHER=x\n')
            with mock.patch.dict(os.environ, {"SIXTEEN688_SECRET": "from-env"}, clear=True):
                client.load_dotenv(p)
                self.assertEqual(os.environ["SIXTEEN688_APP_ID"], "from-file")
                self.assertEqual(os.environ["SIXTEEN688_SECRET"], "from-env")
                self.assertNotIn("OTHER", os.environ)


def quote_data(**over):
    d = {"goods_no": "SG1", "quantity": 1, "unit_price": 5.5, "goods_total_amount": 5.5, "rate": 0.6,
         "fee": 0.03, "total_amount": 5.53, "available_quantity": 50, "available_money": 100,
         "balance_enough": True}
    d.update(over)
    return d


def order_data(status=4, cards=("https://example.invalid/x",)):
    return {"trade_no": "T1", "goods_no": "SG1", "status": status, "total_amount": 5.53,
            "cards": [{"code": c} for c in cards], "instruction": "use within 1h"}


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.c = Client("APP", "SECRET")

    def test_safe_purchase_buys_and_writes_ledger_without_cards(self):
        calls = []

        def fake(path, **biz):
            calls.append(path)
            return quote_data() if path.endswith("quotePrice") else order_data()

        with mock.patch.object(self.c, "call", side_effect=fake), tempfile.TemporaryDirectory() as d:
            ledger = os.path.join(d, "l.jsonl")
            p = safe_purchase(self.c, "SG1", 1, max_total=6.0, ledger_path=ledger)
            with open(ledger, encoding="utf-8") as f:
                text = f.read()
        self.assertEqual(calls, ["/openApi/purchase/quotePrice", "/openApi/purchase/create"])
        self.assertTrue(p.delivered)
        self.assertIn('"trade_no": "T1"', text)
        self.assertNotIn("example.invalid", text)

    def test_price_above_cap_never_reaches_purchase(self):
        calls = []

        def fake(path, **biz):
            calls.append(path)
            return quote_data(total_amount=9.0)

        with mock.patch.object(self.c, "call", side_effect=fake):
            with self.assertRaises(ApiError):
                safe_purchase(self.c, "SG1", 1, max_total=6.0)
        self.assertEqual(calls, ["/openApi/purchase/quotePrice"])

    def test_low_stock_and_low_balance_block_purchase(self):
        for over in ({"available_quantity": 0}, {"balance_enough": False}):
            with mock.patch.object(self.c, "call", return_value=quote_data(**over)) as m:
                with self.assertRaises(ApiError):
                    safe_purchase(self.c, "SG1", 1, max_total=99)
                self.assertEqual(m.call_count, 1)

    def test_wait_delivery_polls_until_cards_arrive(self):
        seq = [order_data(status=1, cards=()), order_data(status=1, cards=()), order_data()]
        with mock.patch.object(self.c, "call", side_effect=seq), mock.patch.object(client.time, "sleep"):
            p = wait_delivery(self.c, "T1", timeout=60, interval=0)
        self.assertTrue(p.delivered)

    def test_wait_delivery_stops_on_refund(self):
        with mock.patch.object(self.c, "call", return_value=order_data(status=3, cards=())):
            with self.assertRaises(ApiError):
                wait_delivery(self.c, "T1", timeout=60, interval=0)

    def test_complaint_requires_evidence_images(self):
        with self.assertRaises(ValueError):
            self.c.complain("T1", "link invalid", [])
        with self.assertRaises(ValueError):
            self.c.complain("T1", "link invalid", ["u"] * 7)


if __name__ == "__main__":
    unittest.main()
