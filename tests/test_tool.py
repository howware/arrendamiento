"""Tests of arrendamiento.py against a real, temporary memory. Synthetic data only.

The memory helper is found in HOWWARE_MEMORY_HELPER, in ../long-term-memory-for-AI or in the installed skill.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "skill" / "arrendamiento" / "scripts" / "arrendamiento.py"
sys.path.insert(0, str(TOOL.parent))
import arrendamiento as arr  # noqa: E402
import mxbank_records  # noqa: E402

BY = "person:test"
TODAY = "2026-03-10"


def find_helper() -> Path | None:
    for c in (os.environ.get("HOWWARE_MEMORY_HELPER"), ROOT.parent / "long-term-memory-for-AI" / "db" / "memory.py",
              Path.home() / ".claude/skills/project-memory/scripts/memory.py"):
        if c and Path(c).is_file():
            return Path(c)
    return None


HELPER = find_helper()

# A landlord's debit account (ACC_d1) and card (ACC_c1), as mxbank's common records would store them.
TRANSACTIONS = [
    # key, date, cents, type, account, description
    ("TX_nov", "2025-10-28", 1000000, "cash_deposit", "account:ACC_d1", "DEPOSITO EN EFECTIVO"),  # deposit + Nov
    ("TX_dec", "2025-12-05", 500000, "cash_deposit", "account:ACC_d1", "DEPOSITO EN EFECTIVO"),
    ("TX_jan", "2026-01-26", 500000, "cash_deposit", "account:ACC_d1", "DEPOSITO EN EFECTIVO"),   # late
    ("TX_feb", "2026-01-29", 500000, "cash_deposit", "account:ACC_d1", "DEPOSITO EN EFECTIVO"),   # early
    ("TX_mar", "2026-03-09", 200000, "cash_deposit", "account:ACC_d1", "DEPOSITO EN EFECTIVO"),   # partial
    ("TX_salary", "2026-02-15", 3000000, "spei_in", "account:ACC_d1", "SPEI RECIBIDO"),
    ("TX_tax", "2026-01-15", -320000, "card_purchase", "account:ACC_c1", "PAGO PREDIAL MUNICIPIO"),
    ("TX_boiler", "2026-02-20", -180000, "card_purchase", "account:ACC_c1", "FERRETERIA Y PLOMERIA"),
]


def bank_write() -> dict:
    return {"source": {"type": "import", "content": "synthetic statements", "provided_by": BY, "captured_at": "now"},
            "performed_by": BY,
            "entities": [{"key": "account:ACC_d1", "type": "account", "name": "Debit (0001)"},
                         {"key": "account:ACC_c1", "type": "account", "name": "Credit (0002)"}],
            "events": [{"key": k, "type": "transaction", "occurred_at": f"{d}T12:00:00-07:00", "summary": desc,
                        "attributes": {"amount": c, "tx_type": t, "bank_description": desc, "entry_source": "statement"},
                        "links": [{"predicate": "on_account", "entity": a}]}
                       for k, d, c, t, a, desc in TRANSACTIONS]}


class ExactHelpersTest(unittest.TestCase):
    def test_months_and_dates(self):
        self.assertEqual(arr.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(arr.months("2025-11", "2026-02"), ["2025-11", "2025-12", "2026-01", "2026-02"])
        self.assertEqual(arr.due_date("2026-02", 30), date(2026, 2, 28))
        self.assertEqual(arr.cents("5,000.50"), 500050)
        self.assertEqual(arr.money(-123456), "-$1,234.56")

    def test_payment_and_charge_rules(self):
        rule = arr.parse_rule(arr.rule_text("cash_deposit,spei_in", "ACC_d1", None))
        tx = {"tx_type": "cash_deposit", "account": "account:ACC_d1", "amount_cents": 500000}
        self.assertTrue(arr.matches_payment(rule, tx))
        self.assertFalse(arr.matches_payment(rule, {**tx, "account": "account:ACC_x"}))
        charge = arr.parse_rule(arr.charge_rule_text("predial", None))
        self.assertTrue(arr.matches_charge(charge, {"amount_cents": -1, "account": "a", "bank_description": "PAGO PREDIAL"}))
        self.assertFalse(arr.matches_charge(charge, {"amount_cents": 1, "account": "a", "bank_description": "PREDIAL"}))
        for bad in ("SPEI RECIBIDO", ""):
            with self.assertRaises(arr.ToolError):
                arr.rule_text(bad, None, None)


@unittest.skipUnless(HELPER, "project-memory is not installed")
class ToolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "memory.sqlite")
        self.mem("init", "--owner-name", "Test", "--owner-key", BY)
        self.assertTrue(self.tool("setup", "--by", BY)["ok"])
        self.mem("write", stdin=bank_write())
        self.tool("property", "--key", "casa", "--name", "Casa Tijuana", "--by", BY)
        self.tool("lease", "--key", "casa-2025", "--name", "Casa 2025", "--property", "casa", "--tenant", "Inquilino A",
                  "--start", "2025-11-01", "--rent", "5000", "--due-day", "7", "--deposit", "5000",
                  "--increase", "percent:5", "--match-types", "cash_deposit", "--match-account", "ACC_d1", "--by", BY,
                  "--source", "Le rento la casa desde noviembre, 5,000 al mes, paga del 1 al 7, depósito de un mes")

    def tearDown(self):
        self.tmp.cleanup()

    def mem(self, *args: str, stdin: dict | None = None) -> dict:
        proc = subprocess.run([sys.executable, str(HELPER), "--db", self.db, *args], capture_output=True, text=True,
                              encoding="utf-8", input=json.dumps(stdin) if stdin else None)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def tool(self, *args: str, code: int = 0, today: str = TODAY) -> dict:
        proc = subprocess.run([sys.executable, str(TOOL), "--mem", str(HELPER), "--db", self.db, "--tz=-07:00",
                               "--today", today, *args], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, code, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def months(self) -> dict:
        rows = self.tool("status", "--lease", "casa-2025")["leases"][0]["months"]
        return {r["month"]: r for r in rows}

    def collect(self) -> dict:
        self.tool("deposit", "--lease", "casa-2025", "--tx", "TX_nov", "--amount", "5000", "--by", BY)
        return self.tool("sync", "--by", BY)

    # -- rent -----------------------------------------------------------------------------
    def test_payments_go_to_the_oldest_month_pending(self):
        sync = self.collect()
        applied = {a["tx"]: [m["month"] for m in a["months"]] for a in sync["applied"]}
        self.assertEqual(applied, {"TX_nov": ["2025-11"], "TX_dec": ["2025-12"], "TX_jan": ["2026-01"],
                                   "TX_feb": ["2026-02"], "TX_mar": ["2026-03"]})
        self.assertNotIn("TX_salary", applied)
        m = self.months()
        self.assertEqual(m["2025-11"]["state"], "paid_early")
        self.assertEqual((m["2026-01"]["state"], m["2026-01"]["days_late"]), ("paid_late", 19))
        self.assertEqual(m["2026-02"]["state"], "paid_early")
        self.assertEqual((m["2026-03"]["state"], m["2026-03"]["balance"], m["2026-03"]["days_late"]),
                         ("partial_late", "$3,000.00", 3))
        self.assertEqual(self.tool("status", "--lease", "casa-2025")["leases"][0]["owed"], "$3,000.00")
        again = self.tool("sync", "--by", BY)
        self.assertEqual(again["applied"], [])

    def test_rent_paid_early_covers_the_next_month(self):
        """The case that gives two invoices in one month: paid on the 29th for the following month."""
        self.collect()
        rows = self.mem("list", "--event-type", "rent_applied", "--where", "link:paid_with/key = TX_feb",
                        "--column", "attr:rent_period", "--column", "occurred_at")["rows"]
        self.assertEqual([(r["attr:rent_period"], r["occurred_at"][:10]) for r in rows], [("2026-02", "2026-01-29")])

    def test_late_fee_only_when_the_lease_has_one(self):
        self.collect()
        self.assertNotIn("late_fee", self.months()["2026-01"])
        self.tool("lease", "--key", "casa-2025", "--late-fee-percent", "10", "--by", BY)
        m = self.months()
        self.assertEqual(m["2026-01"]["late_fee"], "$500.00")
        self.assertEqual(m["2026-03"]["late_fee"], "$500.00")

    def test_apply_unapply_ignore_and_cash(self):
        self.tool("ignore", "--tx", "TX_dec", "--reason", "Era un préstamo que me pagaron", "--by", BY)
        self.collect()
        self.assertEqual(self.months()["2025-12"]["state"], "paid_late")  # January's deposit went to December
        undone = self.tool("unapply", "--tx", "TX_jan", "--reason", "Era para enero", "--by", BY)
        self.assertEqual([u["month"] for u in undone["undone"]], ["2025-12"])
        again = self.tool("apply", "--tx", "TX_jan", "--lease", "casa-2025", "--period", "2026-03", "--by", BY)
        self.assertEqual(again["months"], [{"month": "2026-03", "amount": "$5,000.00"}])
        cash = self.tool("cash", "--lease", "casa-2025", "--amount", "5000", "--date", "2026-02-02", "--by", BY,
                         "--source", "Me pagó diciembre en efectivo")
        self.assertEqual(cash["months"], [{"month": "2025-12", "amount": "$5,000.00"}])
        self.assertTrue(self.tool("cash", "--lease", "casa-2025", "--amount", "5000", "--date", "2026-02-02",
                                  "--by", BY)["unchanged"])
        refused = self.tool("ignore", "--tx", "TX_jan", "--reason", "x", "--by", BY, code=2)
        self.assertIn("unapply", refused["error"]["message"])

    def test_increase_preview_and_apply(self):
        preview = self.tool("increase", "--lease", "casa-2025", "--percent", "5")
        self.assertEqual((preview["from"], preview["new"], preview["applied"]), ("2026-11-01", "$5,250.00", False))
        inpc = self.tool("increase", "--lease", "casa-2025", "--inpc-old", "135", "--inpc-new", "140")
        self.assertEqual(inpc["new"], "$5,185.19")
        rounded = self.tool("increase", "--lease", "casa-2025", "--inpc-old", "135", "--inpc-new", "140",
                            "--round-to", "100")
        self.assertEqual(rounded["new"], "$5,185.00")
        self.tool("increase", "--lease", "casa-2025", "--percent", "5", "--apply", "--by", BY)
        later = self.tool("status", "--lease", "casa-2025", today="2026-11-20")["leases"][0]["months"]
        self.assertEqual({r["month"]: r["rent"] for r in later}["2026-11"], "$5,250.00")
        self.tool("increase", "--lease", "casa-2025", "--percent", "5", "--inpc-old", "1", code=2)

    def test_deposit_and_settlement(self):
        dep = self.tool("deposit", "--lease", "casa-2025", "--tx", "TX_nov", "--amount", "5000", "--by", BY)
        self.assertEqual((dep["held"], dep["agreed"]), ("$5,000.00", "$5,000.00"))
        settle = self.tool("settle", "--lease", "casa-2025", "--deduct", "1200=pintura de la recámara")
        self.assertEqual((settle["refund"], settle["applied"]), ("$3,800.00", False))
        self.tool("settle", "--lease", "casa-2025", "--deduct", "nada", code=2)

    def test_new_lease_needs_its_terms_and_rent_changes_by_increase(self):
        missing = self.tool("lease", "--key", "otra", "--property", "casa", "--by", BY, code=2)
        self.assertIn("--start", missing["error"]["message"])
        refused = self.tool("lease", "--key", "casa-2025", "--rent", "6000", "--by", BY, code=2)
        self.assertIn("increase", refused["error"]["message"])
        lease = self.tool("leases")["leases"][0]
        self.assertEqual((lease["rent"], lease["next_anniversary"], lease["active"]), ("$5,000.00", "2026-11-01", True))

    # -- around the rent ---------------------------------------------------------------------
    def test_recurring_items_and_their_charges(self):
        self.tool("recurring", "--key", "predial", "--name", "Predial", "--property", "casa", "--kind", "property_tax",
                  "--payer", "owner", "--every", "12", "--next-due", "2026-03-31", "--notice-days", "90",
                  "--match-text", "PREDIAL", "--by", BY, "--source", "El predial se paga de enero a marzo")
        self.tool("recurring", "--key", "luz", "--name", "Luz (CFE)", "--property", "casa", "--kind", "service",
                  "--payer", "tenant", "--every", "2", "--next-due", "2026-03-15", "--notice-days", "10", "--by", BY)
        pending = self.tool("pending")["pending"]
        tax = next(p for p in pending if p.get("item") == "item:predial")
        self.assertEqual(tax["candidates"], [{"tx": "TX_tax", "date": "2026-01-15", "amount": "$3,200.00"}])
        light = next(p for p in pending if p.get("item") == "item:luz")
        self.assertIn("check the tenant paid", light["text"])
        done = self.tool("done", "--item", "predial", "--tx", "TX_tax", "--by", BY)
        self.assertEqual((done["amount"], done["next_due"]), ("$3,200.00", "2027-03-31"))
        self.assertTrue(self.tool("done", "--item", "predial", "--due", "2026-03-31", "--by", BY)["unchanged"])
        self.tool("done", "--item", "luz", "--by", BY, "--source", "Me mandó el recibo pagado")
        after = [p.get("item") for p in self.tool("pending")["pending"]]
        self.assertNotIn("item:predial", after)
        self.assertNotIn("item:luz", after)

    def test_work_order_with_provider_warranty_and_report(self):
        self.tool("provider", "--key", "plomero-juan", "--name", "Juan (plomero)", "--trade", "plomería",
                  "--rating", "5", "--by", BY)
        self.tool("work", "--key", "boiler", "--property", "casa", "--title", "Fuga en el boiler", "--payer", "owner",
                  "--reason", "Desgaste natural: plomería la pago yo", "--date", "2026-02-10", "--by", BY)
        refused = self.tool("work-update", "--key", "boiler", "--status", "reported", "--by", BY)
        self.assertTrue(refused["unchanged"])
        self.tool("work-update", "--key", "boiler", "--status", "quoted", "--quote", "1800", "--provider",
                  "plomero-juan", "--by", BY)
        self.tool("work-update", "--key", "boiler", "--status", "approved", "--by", BY)
        done = self.tool("work-update", "--key", "boiler", "--status", "done", "--tx", "TX_boiler",
                         "--warranty-months", "1", "--date", "2026-02-20", "--by", BY)["work"]
        self.assertEqual((done["cost"], done["warranty_until"], done["status"]), ("$1,800.00", "2026-03-20", "done"))
        bad = self.tool("work-update", "--key", "boiler", "--status", "quoted", "--by", BY, code=2)
        self.assertIn("cannot move", bad["error"]["message"])
        pending = self.tool("pending")["pending"]
        self.assertTrue(any(p["kind"] == "warranty_ending" for p in pending))
        self.assertEqual(self.tool("providers", "--trade", "plom")["providers"][0]["spent"], "$1,800.00")
        self.collect()
        report = self.tool("report", "--year", "2026")["properties"][0]
        self.assertEqual((report["rent_collected"], report["expenses"], report["net"]),
                         ("$12,000.00", "$1,800.00", "$10,200.00"))
        self.assertEqual(report["months_vacant"], [])

    def test_pending_puts_the_late_rent_first(self):
        self.collect()
        pending = self.tool("pending")
        first = pending["pending"][0]
        self.assertEqual((first["kind"], first["month"], first["balance"]), ("rent_late", "2026-03", "$3,000.00"))
        increase = self.tool("pending", today="2026-10-01")["pending"]
        self.assertTrue(any(p["kind"] == "increase" and p["when"] == "2026-11-01" for p in increase))

    def test_unknown_deposit_matching_two_leases_is_asked(self):
        self.tool("property", "--key", "depa", "--name", "Departamento", "--by", BY)
        self.tool("lease", "--key", "depa-2026", "--property", "depa", "--start", "2026-01-01", "--rent", "5000",
                  "--due-day", "5", "--match-types", "cash_deposit", "--match-account", "ACC_d1", "--by", BY)
        sync = self.tool("sync", "--dry-run", "--by", BY)
        self.assertEqual([a["tx"] for a in sync["ambiguous"]], ["TX_dec", "TX_jan", "TX_feb", "TX_mar"])
        self.assertTrue(any(p["kind"] == "payment_ambiguous" for p in self.tool("pending")["pending"]))

    # -- statements and shared memory --------------------------------------------------------------
    def test_import_statements_as_common_records(self):
        fixture = ROOT / "tests" / "fixtures" / "bbva_debit.json"
        first = self.tool("import", str(fixture), "--by", BY)["statements"][0]
        again = self.tool("import", str(fixture), "--by", BY)["statements"][0]
        self.assertEqual((first["transactions_existing"], again["transactions_new"]), (0, 0))
        self.assertEqual(again["transactions_existing"], first["transactions_new"])

    def test_records_module_is_mxbanks_copy(self):
        found = [p / "src" / "mxbank" / "records.py" for p in (ROOT.parent / "mx-bank-statement-reader",
                                                              ROOT / "mx-bank-statement-reader")]
        original = next((p for p in found if p.is_file()), None)
        if not original:
            self.skipTest("the mxbank repository is not checked out (../mx-bank-statement-reader)")
        self.assertEqual((TOOL.parent / "mxbank_records.py").read_text(encoding="utf-8").splitlines(),
                         original.read_text(encoding="utf-8").splitlines(),
                         "Copy src/mxbank/records.py from mxbank to mxbank_records.py again")


class ContractTest(unittest.TestCase):
    def test_version_and_no_network(self):
        out = subprocess.run([sys.executable, str(TOOL), "--version"], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0)
        manifest = json.loads((ROOT / "howware.json").read_text(encoding="utf-8"))
        self.assertEqual(out.stdout.split()[-1], manifest["version"])
        source = TOOL.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?m)^\s*(import|from)\s+(socket|urllib|http|requests)\b")
        self.assertEqual(mxbank_records.RECORDS_VERSION, "1")


if __name__ == "__main__":
    unittest.main()
