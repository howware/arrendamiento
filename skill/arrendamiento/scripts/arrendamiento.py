"""arrendamiento — the exact operations of the rentals howware (landlords, without an app).

The rent deposits in the bank statements (read by the mxbank adapter and stored as the common records that every
howware sharing the memory imports the same way) are applied to the months of rent they pay, oldest pending month
first. Around the rent: services and property tax, maintenance and warranties, providers, the security deposit
and the yearly increase, all in one list of what is pending.

Commands (JSON on stdout; errors as {"ok": false, "error": {"code", "message"}}):
  setup           load the predicates into the memory
  import          store mxbank statements in the memory as common records (shared with other howwares)
  property        add or rename a property
  lease           add a lease or change its terms (dates, due day, deposit, increase, late fee, payment rule)
  leases          the leases, with the rent in force and the next anniversary
  sync            apply the deposits that match a lease's payment rule to the oldest months pending
  apply           apply one payment to a lease (optionally to one month), when no rule matches it
  cash            record rent received outside the bank, and apply it
  ignore          mark a deposit as not rent, with the owner's reason
  unapply         undo the application of one payment (it can then be applied again)
  status          month by month: rent due, paid, balance, days late, late fee if the lease has one
  increase        compute the new rent (percent or INPC) and, with --apply, put it in force from a date
  deposit         record the security deposit received
  settle          compute (and with --apply record) the deposit returned at the end of a lease
  recurring       add or change a recurring item: a service, property tax, insurance, condo fee, preventive task
  done            record that a recurring item was paid, verified or done; its next due date moves forward
  work            report a maintenance job (work order)
  work-update     move a work order forward: quoted, approved, in_progress, done (with warranty) or cancelled
  works           the work orders, open ones first
  provider        add or change a provider in the directory
  providers       the directory, with the jobs each provider did
  pending         everything the owner has to do or check, soonest first (also the session brief)
  report          a year per property: rent collected, expenses, net, months without a tenant

Exit codes: 0 ok · 2 invalid input · 3 memory problem.
No network, no prompts, standard library only. Money in integer cents; dates at noon local time.
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mxbank_records  # noqa: E402  (verbatim copy from mxbank: the common form of a statement in the memory)

__version__ = "0.1.1"
HERE = Path(__file__).resolve().parent
SEED = HERE / "seed.json"
MIN_MEMORY = (0, 4, 0)
OK, BAD_INPUT, MEMORY_ERROR = 0, 2, 3
INCOME_TYPES = ("spei_in", "transfer_in", "cash_deposit", "deposit", "check_deposit")
RECURRING_KINDS = ("service", "property_tax", "insurance", "condo_fee", "preventive", "other")
PAYERS = ("owner", "tenant")
WORK_FLOW = {
    "reported": ("quoted", "approved", "in_progress", "done", "cancelled"),
    "quoted": ("quoted", "approved", "cancelled"),
    "approved": ("in_progress", "done", "cancelled"),
    "in_progress": ("done", "cancelled"),
    "done": ("in_progress",),  # reopened, e.g. under warranty
    "cancelled": (),
}
OPEN_WORK = ("reported", "quoted", "approved", "in_progress")
FUTURE_MONTHS = 12  # an open-ended lease takes payments up to this many months ahead
SOON_DAYS = {"increase": 45, "lease_end": 60, "warranty": 30}


class ToolError(Exception):
    def __init__(self, message: str, code: int = BAD_INPUT):
        super().__init__(message)
        self.code = code


# -- memory adapter -----------------------------------------------------------------------
def find_helper(explicit: str | None) -> Path:
    for c in (explicit, os.environ.get("HOWWARE_MEMORY_HELPER"),
              Path.home() / ".claude/skills/project-memory/scripts/memory.py",
              Path.home() / ".codex/skills/project-memory/scripts/memory.py"):
        if c and Path(c).is_file():
            return Path(c)
    raise ToolError("project-memory is not installed (or pass --mem / HOWWARE_MEMORY_HELPER).", MEMORY_ERROR)


class Memory:
    def __init__(self, helper: Path, db: str | None):
        self.helper, self.db = helper, db

    def run(self, *args: str, stdin: dict | None = None) -> Any:
        for attempt in (1, 2):
            cmd = [sys.executable, str(self.helper)] + (["--db", self.db] if self.db else []) + list(args)
            proc = subprocess.run(cmd, input=json.dumps(stdin, ensure_ascii=False) if stdin is not None else None,
                                  capture_output=True, text=True, encoding="utf-8")
            if proc.returncode == 0:
                return json.loads(proc.stdout) if proc.stdout.strip() else None
            message = (proc.stderr or proc.stdout).strip()
            if attempt == 1 and "at least one second" in message:
                time.sleep(1.1)
                continue
            raise ToolError(f"memory {args[0]} failed: {message[-600:]}", MEMORY_ERROR)

    def check_version(self) -> None:
        out = subprocess.run([sys.executable, str(self.helper), "--version"], capture_output=True, text=True).stdout
        found = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
        if not found or tuple(int(x) for x in found.groups()) < MIN_MEMORY:
            raise ToolError(f"project-memory >= {'.'.join(map(str, MIN_MEMORY))} is required (found: {out.strip()}).",
                            MEMORY_ERROR)

    def rows(self, *args: str) -> list[dict]:
        return self.run("list", *args, "--limit", "5000")["rows"]

    def count(self, event_type: str) -> int:
        return self.run("aggregate", "--event-type", event_type)["total_rows"]

    def write(self, by: str, content: str, kind: str = "user_statement", **sections) -> dict:
        return self.run("write", stdin={"source": {"type": kind, "content": content, "provided_by": by,
                                                   "captured_at": "now"},
                                        "performed_by": by, **sections})


# -- exact helpers ------------------------------------------------------------------------
def cents(value: Any, what: str = "amount") -> int:
    try:
        return int((Decimal(str(value).replace(",", "").replace("$", "")) * 100).quantize(Decimal(1),
                                                                                       rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as error:
        raise ToolError(f"Not an {what}: {value!r}") from error


def money(c: int | None) -> str | None:
    if c is None:
        return None
    return f"{'-' if c < 0 else ''}${abs(c) // 100:,}.{abs(c) % 100:02d}"


def parse_offset(text: str) -> timezone:
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", text.strip())
    if not m:
        raise ToolError(f"Time zone offset must look like -07:00, not {text!r}")
    minutes = int(m.group(2)) * 60 + int(m.group(3))
    return timezone(timedelta(minutes=minutes if m.group(1) == "+" else -minutes))


def local_offset() -> str:
    z = datetime.now().astimezone().strftime("%z")
    return f"{z[:3]}:{z[3:]}"


def parse_day(text: str, what: str = "date") -> date:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise ToolError(f"{what} must be YYYY-MM-DD, not {text!r}") from None


def parse_month(text: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", text or ""):
        raise ToolError(f"A month is YYYY-MM, not {text!r}")
    return text


def noon(day: date, tz: str) -> str:
    return datetime(day.year, day.month, day.day, 12, tzinfo=parse_offset(tz)).isoformat(timespec="seconds")


def day_of(value: Any) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def month_of(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def first_of(month: str) -> date:
    return date(int(month[:4]), int(month[5:7]), 1)


def add_months(day: date, n: int) -> date:
    i = day.year * 12 + day.month - 1 + n
    year, month = divmod(i, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def months(first: str, last: str) -> list[str]:
    out, d = [], first_of(first)
    while month_of(d) <= last:
        out.append(month_of(d))
        d = add_months(d, 1)
    return out


def due_date(month: str, due_day: int) -> date:
    d = first_of(month)
    return d.replace(day=min(due_day, calendar.monthrange(d.year, d.month)[1]))


def key_part(text: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", text or ""):
        raise ToolError(f"Not a valid id: {text!r} (letters, digits, - _ . : only)")
    return text


def entity_key(prefix: str, text: str) -> str:
    text = key_part(text)
    return text if text.startswith(prefix + ":") else f"{prefix}:{text}"


def stable_key(prefix: str, *parts: str) -> str:
    return f"{prefix}_" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


def choice(value: str, allowed: tuple, what: str) -> str:
    if value not in allowed:
        raise ToolError(f"{what} must be one of {', '.join(allowed)}, not {value!r}")
    return value


# -- payment rules ------------------------------------------------------------------------
def rule_text(types: str, account: str | None, amount: int | None) -> str:
    kinds = [t.strip() for t in (types or "").split(",") if t.strip()]
    if not kinds or any(not re.fullmatch(r"[a-z_]{2,40}", t) for t in kinds):
        raise ToolError(f"--match-types are transaction types such as cash_deposit,spei_in, not {types!r}")
    parts = [f"types={','.join(kinds)}"]
    if account:
        parts.append(f"account={entity_key('account', account)}")
    if amount is not None:
        if amount <= 0:
            raise ToolError("--match-amount must be positive")
        parts.append(f"amount={amount}")
    return ";".join(parts)


def parse_rule(text: str | None) -> dict:
    rule: dict[str, Any] = {}
    for part in (p.strip() for p in (text or "").split(";") if p.strip()):
        name, _, value = part.partition("=")
        if name == "types":
            rule["types"] = value.split(",")
        elif name in ("account", "text"):
            rule[name] = value
        elif name == "amount":
            rule["amount"] = int(value)
    return rule


def matches_payment(rule: dict, tx: dict) -> bool:
    if not rule.get("types") or tx["tx_type"] not in rule["types"]:
        return False
    if rule.get("account") and rule["account"] != tx["account"]:
        return False
    return not (rule.get("amount") is not None and rule["amount"] != tx["amount_cents"])


def charge_rule_text(text: str, account: str | None) -> str:
    text = (text or "").strip()
    if not (2 <= len(text) <= 60) or ";" in text or "=" in text:
        raise ToolError("--match-text is a piece of the bank description (2 to 60 characters, no ; or =)")
    return f"text={text}" + (f";account={entity_key('account', account)}" if account else "")


def matches_charge(rule: dict, tx: dict) -> bool:
    if not rule.get("text") or tx["amount_cents"] >= 0:
        return False
    if rule.get("account") and rule["account"] != tx["account"]:
        return False
    return rule["text"].upper() in (tx["bank_description"] or "").upper()


# -- reading the memory ---------------------------------------------------------------------
LEASE_FACTS = ("tenant_label", "lease_start", "lease_end", "due_day", "deposit_amount", "increase_rule",
               "late_fee_amount", "late_fee_basis_points", "payment_match")
TX_COLUMNS = ("--column", "key", "--column", "occurred_at", "--column", "attr:amount", "--column", "attr:tx_type",
              "--column", "link:on_account/key", "--column", "attr:bank_description")


def load_properties(mem: Memory) -> dict[str, str]:
    return {r["key"]: r["name"] for r in mem.rows("--entity-type", "property", "--column", "key", "--column", "name")}


def load_leases(mem: Memory) -> list[dict]:
    cols = ["--column", "key", "--column", "name", "--column", "fact:lease_property/key"]
    for f in LEASE_FACTS:
        cols += ["--column", f"fact:{f}"]
    out = []
    for r in mem.rows("--entity-type", "lease", *cols):
        out.append({"key": r["key"], "name": r["name"], "property": r["fact:lease_property/key"],
                    "tenant": r["fact:tenant_label"], "start": day_of(r["fact:lease_start"]),
                    "end": day_of(r["fact:lease_end"]), "due_day": r["fact:due_day"],
                    "deposit": r["fact:deposit_amount"], "increase": r["fact:increase_rule"] or "none",
                    "late_fee_amount": r["fact:late_fee_amount"], "late_fee_bp": r["fact:late_fee_basis_points"],
                    "rule_text": r["fact:payment_match"], "rule": parse_rule(r["fact:payment_match"])})
    return sorted(out, key=lambda x: (x["start"] or date.min, x["key"]))


def find_lease(leases: list[dict], ref: str) -> dict:
    key = entity_key("lease", ref) if not ref.startswith("lease:") else key_part(ref)
    found = [x for x in leases if x["key"] == key or (x["name"] or "").lower() == ref.lower()]
    if len(found) != 1:
        raise ToolError(f"No lease {ref!r} (leases: {', '.join(x['key'] for x in leases) or 'none yet'}).")
    return found[0]


def events(mem: Memory, event_type: str, *columns: str, voided: bool = False) -> list[dict]:
    if not mem.count(event_type) and not voided:
        return []
    cols = [x for c in ("key", "occurred_at", *columns) for x in ("--column", c)]
    try:
        return mem.rows("--event-type", event_type, *cols, *(["--include-voided"] if voided else []))
    except ToolError:
        if voided:  # nothing of that type yet: its predicates may not exist
            return []
        raise


def rent_sets(mem: Memory) -> dict[str, list[tuple[date, int]]]:
    out: dict[str, list[tuple[date, int]]] = {}
    for r in events(mem, "rent_set", "attr:monthly_rent", "attr:effective_from", "link:under_lease/key"):
        out.setdefault(r["link:under_lease/key"], []).append((day_of(r["attr:effective_from"]), r["attr:monthly_rent"]))
    return {k: sorted(v) for k, v in out.items()}


def rent_on(sets: list[tuple[date, int]], day: date) -> int | None:
    found = [amount for start, amount in sets if start <= day]
    return found[-1] if found else None


def applications(mem: Memory) -> list[dict]:
    return [{"key": r["key"], "date": day_of(r["occurred_at"]), "period": r["attr:rent_period"],
             "amount": r["attr:applied_amount"], "source": r["link:paid_with/key"], "lease": r["link:under_lease/key"]}
            for r in events(mem, "rent_applied", "attr:rent_period", "attr:applied_amount", "link:paid_with/key",
                            "link:under_lease/key")]


def deposits_received(mem: Memory) -> list[dict]:
    return [{"key": r["key"], "date": day_of(r["occurred_at"]), "amount": r["attr:applied_amount"],
             "source": r["link:paid_with/key"], "lease": r["link:under_lease/key"]}
            for r in events(mem, "deposit_received", "attr:applied_amount", "link:paid_with/key", "link:under_lease/key")]


def bank_transactions(mem: Memory, first: date, last: date, sign: str = "> 0") -> list[dict]:
    if not mem.count("transaction"):
        return []
    rows = mem.rows("--event-type", "transaction", "--where", f"attr:amount {sign}", "--since", first.isoformat(),
                    "--until", (last + timedelta(days=1)).isoformat(), *TX_COLUMNS)
    return sorted(({"tx": r["key"], "date": day_of(r["occurred_at"]), "amount_cents": r["attr:amount"],
                    "tx_type": r["attr:tx_type"], "account": r["link:on_account/key"],
                    "bank_description": r["attr:bank_description"]} for r in rows), key=lambda t: (t["date"], t["tx"]))


def cash_receipts(mem: Memory) -> list[dict]:
    return [{"tx": r["key"], "date": day_of(r["occurred_at"]), "amount_cents": r["attr:amount"], "tx_type": "cash",
             "account": None, "bank_description": None, "lease": r["link:under_lease/key"]}
            for r in events(mem, "rent_received", "attr:amount", "link:under_lease/key")]


def ignored_sources(mem: Memory) -> set[str]:
    return {r["link:paid_with/key"] for r in events(mem, "not_rent", "link:paid_with/key")}


# -- rent: what is due and what was paid --------------------------------------------------------
class Book:
    """Every lease with its months, the payments applied to them, and what is still unapplied."""

    def __init__(self, mem: Memory, today: date):
        self.today = today
        self.leases = load_leases(mem)
        self.sets = rent_sets(mem)
        self.applied = applications(mem)
        self.deposits = deposits_received(mem)
        self.ignored = ignored_sources(mem)
        self.used: dict[str, int] = {}
        for a in [*self.applied, *self.deposits]:
            if a["source"]:
                self.used[a["source"]] = self.used.get(a["source"], 0) + a["amount"]
        self.mem = mem

    def last_month(self, lease: dict) -> str:
        if lease["end"]:
            return month_of(lease["end"])
        return month_of(add_months(self.today, FUTURE_MONTHS))

    def ledger(self, lease: dict) -> list[dict]:
        """One row per month from the start, through this month (and later months already paid)."""
        sets = self.sets.get(lease["key"], [])
        mine = [a for a in self.applied if a["lease"] == lease["key"]]
        by_period: dict[str, list[dict]] = {}
        for a in mine:
            by_period.setdefault(a["period"], []).append(a)
        last = max([min(month_of(self.today), self.last_month(lease))] + [a["period"] for a in mine])
        rows = []
        for m in months(month_of(lease["start"]), last):
            expected = rent_on(sets, first_of(m)) or 0
            paid = sum(a["amount"] for a in by_period.get(m, []))
            due = due_date(m, lease["due_day"] or 1)
            row = {"month": m, "rent_cents": expected, "rent": money(expected), "paid_cents": paid,
                   "paid": money(paid), "balance_cents": expected - paid, "balance": money(expected - paid),
                   "due": due.isoformat()}
            if paid >= expected and expected and all(a["source"].startswith("OPEN_") for a in by_period[m]):
                row.update(state="paid_before_records")
            elif paid >= expected and expected:
                paid_on = max(a["date"] for a in by_period[m])
                row.update(state="paid_early" if paid_on < first_of(m) else "paid", paid_on=paid_on.isoformat())
                if paid_on > due:
                    row.update(state="paid_late", days_late=(paid_on - due).days)
            elif self.today > due:
                row.update(state="partial_late" if paid else "late", days_late=(self.today - due).days)
            elif m <= month_of(self.today):
                row.update(state="partial" if paid else "due", days_left=(due - self.today).days)
            else:
                row.update(state="partial_ahead" if paid else "ahead")
            fee = self.late_fee(lease, expected) if row.get("days_late") else None
            if fee:
                row.update(late_fee_cents=fee, late_fee=money(fee))
            rows.append(row)
        return rows

    @staticmethod
    def late_fee(lease: dict, rent: int) -> int | None:
        if lease["late_fee_amount"]:
            return lease["late_fee_amount"]
        if lease["late_fee_bp"]:
            return int((Decimal(rent) * lease["late_fee_bp"] / 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return None

    def sources(self) -> list[dict]:
        """Payments that could be rent: bank deposits and cash receipts with money not yet applied."""
        starts = [x["start"] for x in self.leases if x["start"]]
        if not starts:
            return []
        first = min(starts) - timedelta(days=45)
        found = bank_transactions(self.mem, first, self.today + timedelta(days=1)) + cash_receipts(self.mem)
        out = []
        for t in found:
            if t["tx"] in self.ignored:
                continue
            left = t["amount_cents"] - self.used.get(t["tx"], 0)
            if left > 0:
                out.append({**t, "left_cents": left})
        return sorted(out, key=lambda t: (t["date"], t["tx"]))

    def candidates(self, source: dict) -> list[dict]:
        if source.get("lease"):  # a cash receipt is recorded for its lease
            return [x for x in self.leases if x["key"] == source["lease"]]
        out = []
        for lease in self.leases:
            if not lease["rule"] or not lease["start"]:
                continue
            if source["date"] < lease["start"] - timedelta(days=45):
                continue
            if lease["end"] and source["date"] > lease["end"] + timedelta(days=90):
                continue
            if matches_payment(lease["rule"], source):
                out.append(lease)
        return out

    def allocate(self, lease: dict, source: dict, amount: int, period: str | None = None) -> tuple[list[dict], int]:
        """Split a payment over the oldest months with a balance (or the one month asked); returns the rest."""
        ledger = {r["month"]: r for r in self.ledger(lease)}
        sets = self.sets.get(lease["key"], [])
        for m in months(month_of(lease["start"]), self.last_month(lease)):
            if m not in ledger:
                expected = rent_on(sets, first_of(m)) or 0
                ledger[m] = {"month": m, "balance_cents": expected}
        if period:
            if period not in ledger:
                raise ToolError(f"{period} is outside the lease ({month_of(lease['start'])} to {self.last_month(lease)}).")
            order = [period]
        else:
            order = sorted(ledger)
        parts, left = [], amount
        for m in order:
            balance = ledger[m]["balance_cents"]
            if balance <= 0 and not period:
                continue
            take = left if period else min(balance, left)
            if take <= 0:
                continue
            parts.append({"period": m, "amount_cents": take})
            left -= take
            if left == 0:
                break
        return parts, left

    def application_events(self, lease: dict, source: dict, parts: list[dict], tz: str,
                           existing: set[str]) -> list[dict]:
        out = []
        for p in parts:
            base = f"RENT_{source['tx']}_{p['period'].replace('-', '')}"
            key, n = base, 1
            while key in existing:  # applied before and undone: a new key keeps the history
                n += 1
                key = f"{base}_{n}"
            existing.add(key)
            out.append({"key": key, "type": "rent_applied", "occurred_at": noon(source["date"], tz),
                        "summary": f"{money(p['amount_cents'])} of rent for {p['period']} ({lease['name']})",
                        "attributes": {"rent_period": p["period"], "applied_amount": p["amount_cents"]},
                        "links": [{"predicate": "paid_with", "event": source["tx"]},
                                  {"predicate": "under_lease", "entity": lease["key"]}]})
        return out


def all_keys(mem: Memory, event_type: str) -> set[str]:
    return {r["key"] for r in events(mem, event_type, voided=True)}


# -- recurring items, work orders, providers ---------------------------------------------------
def load_recurring(mem: Memory) -> list[dict]:
    cols = ["--column", "key", "--column", "name", "--column", "fact:lease_property/key"]
    for f in ("recurring_kind", "payer", "every_months", "next_due", "notice_days", "charge_match", "note_text"):
        cols += ["--column", f"fact:{f}"]
    return [{"key": r["key"], "name": r["name"], "property": r["fact:lease_property/key"],
             "kind": r["fact:recurring_kind"], "payer": r["fact:payer"], "every": r["fact:every_months"],
             "next_due": day_of(r["fact:next_due"]), "notice_days": r["fact:notice_days"] or 0,
             "rule_text": r["fact:charge_match"], "rule": parse_rule(r["fact:charge_match"]), "note": r["fact:note_text"]}
            for r in mem.rows("--entity-type", "recurring_item", *cols)]


def recurring_done(mem: Memory) -> list[dict]:
    return [{"key": r["key"], "date": day_of(r["occurred_at"]), "amount": r["attr:charge_amount"],
             "due": day_of(r["attr:due_date"]), "item": r["link:for_item/key"], "tx": r["link:paid_with/key"]}
            for r in events(mem, "recurring_done", "attr:charge_amount", "attr:due_date", "link:for_item/key",
                            "link:paid_with/key")]


def load_works(mem: Memory) -> list[dict]:
    cols = ["--column", "key", "--column", "name", "--column", "fact:lease_property/key",
            "--column", "fact:work_provider/key", "--column", "fact:work_provider"]
    for f in ("payer", "reason_text", "work_status", "work_opened", "work_closed", "work_quote", "work_cost",
              "warranty_until", "note_text"):
        cols += ["--column", f"fact:{f}"]
    return [{"key": r["key"], "title": r["name"], "property": r["fact:lease_property/key"], "payer": r["fact:payer"],
             "payer_reason": r["fact:reason_text"], "status": r["fact:work_status"],
             "opened": day_of(r["fact:work_opened"]), "closed": day_of(r["fact:work_closed"]),
             "quote_cents": r["fact:work_quote"], "cost_cents": r["fact:work_cost"],
             "provider": r["fact:work_provider/key"], "provider_name": r["fact:work_provider"],
             "warranty_until": day_of(r["fact:warranty_until"]), "note": r["fact:note_text"]}
            for r in mem.rows("--entity-type", "work_order", *cols)]


def work_view(w: dict, today: date) -> dict:
    out = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in w.items()}
    out["quote"], out["cost"] = money(w["quote_cents"]), money(w["cost_cents"])
    if w["status"] in OPEN_WORK and w["opened"]:
        out["days_open"] = (today - w["opened"]).days
    if w["warranty_until"]:
        out["warranty_days_left"] = (w["warranty_until"] - today).days
    return out


def find_entity(rows: list[dict], prefix: str, ref: str, what: str) -> dict:
    key = entity_key(prefix, ref)
    found = [r for r in rows if r["key"] == key]
    if not found:
        raise ToolError(f"No {what} {ref!r}.")
    return found[0]


def one_source(mem: Memory, key: str) -> dict:
    key = key_part(key)
    if mem.count("transaction"):
        rows = mem.rows("--event-type", "transaction", "--where", f"key = {key}", *TX_COLUMNS)
        if rows:
            r = rows[0]
            return {"tx": r["key"], "date": day_of(r["occurred_at"]), "amount_cents": r["attr:amount"],
                    "tx_type": r["attr:tx_type"], "account": r["link:on_account/key"],
                    "bank_description": r["attr:bank_description"]}
    for c in cash_receipts(mem):
        if c["tx"] == key:
            return c
    raise ToolError(f"No bank transaction or cash receipt {key}. Import the statement first (TOOL import).")


# -- commands -------------------------------------------------------------------------------
def cmd_setup(mem: Memory, args, today: date) -> dict:
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    result = mem.write(args.by, f"arrendamiento seed v{seed['seed_version']}", "helper_command",
                       predicates=[{**p, "distinct_from_similar": True}
                                   for p in [*mxbank_records.PREDICATES, *seed["predicates"]]])
    mem.run("define-event-type", "--type", "transaction", "--high-volume", "--by", args.by,
            "--reason", "Imported bank transactions: hundreds per month")
    deposits = mem.count("transaction")
    return {"ok": True, "seed_version": seed["seed_version"], "transactions_in_memory": deposits,
            "warnings": result.get("warnings", []) + ([] if deposits else [
                "No bank transactions in this memory yet: import statements (TOOL import)."])}


def read_statements(paths: list[str]) -> list[dict]:
    out = []
    for path in paths:
        try:
            text = (sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")).strip()
        except OSError as error:
            raise ToolError(f"Cannot read {path}: {error.strerror or error}") from error
        try:
            docs = [json.loads(text)] if text.startswith("{") and "\n{" not in text else \
                [json.loads(line) for line in text.splitlines() if line.strip()]
        except json.JSONDecodeError as error:
            raise ToolError(f"{path} is not mxbank JSON or NDJSON (line {error.lineno}).") from error
        for doc in docs:
            out += doc if isinstance(doc, list) else [doc]
    return out


def current_temporal_facts(mem: Memory, document: dict) -> dict:
    """When each balance or plan fact in force began, so an older statement does not replace a newer value."""
    current = {}
    for subject in mxbank_records.temporal_subjects(document):
        kind = "account" if subject.startswith("account:") else "installment_plan"
        columns = [x for pred in sorted(mxbank_records.TEMPORAL) for x in ("--column", f"fact:{pred}/since")]
        rows = mem.rows("--entity-type", kind, "--where", f"key = {subject}", "--as-of", "2100-01-01", *columns)
        for pred in mxbank_records.TEMPORAL:
            if rows and rows[0].get(f"fact:{pred}/since"):
                current[(subject, pred)] = rows[0][f"fact:{pred}/since"]
    return current


def transaction_keys(items: list) -> int:
    return sum(1 for i in items if str(i.get("key") if isinstance(i, dict) else i).startswith("TX_"))


def cmd_import(mem: Memory, args, today: date) -> dict:
    documents = []
    for st in read_statements(args.files):
        try:
            documents.append(mxbank_records.memory_document(st, args.by, args.tz))
        except mxbank_records.RecordsError as error:
            raise ToolError(str(error)) from error
    report = []
    for document, info in sorted(documents, key=lambda d: d[1]["period"][0] or ""):
        older = mxbank_records.keep_newer(document, current_temporal_facts(mem, document))
        result = mem.run("write", stdin=document).get("events", {})
        report.append({"statement_id": info["statement_id"], "account": info["account_name"], "period": info["period"],
                       "reconciled": info["reconciled"], "transactions_new": transaction_keys(result.get("created", [])),
                       "transactions_existing": transaction_keys(result.get("existing", [])),
                       "warnings": info["warnings"], **({"older_than_current": older} if older else {})})
    return {"ok": True, "statements": report}


def cmd_property(mem: Memory, args, today: date) -> dict:
    key = entity_key("property", args.key)
    known = load_properties(mem)
    entity = {"key": key, "type": "property", "name": args.name}
    if key in known and known[key] != args.name:
        entity["rename"] = True
    result = mem.write(args.by, args.source or f"Property {args.name}", entities=[entity])
    return {"ok": True, "property": key, "name": args.name, "warnings": result.get("warnings", [])}


def increase_text(value: str) -> str:
    if value in ("none", "inpc"):
        return value
    m = re.fullmatch(r"percent:(\d{1,2}(\.\d{1,2})?)", value or "")
    if not m:
        raise ToolError(f"--increase is none, inpc or percent:<p> (e.g. percent:5), not {value!r}")
    return value


def cmd_lease(mem: Memory, args, today: date) -> dict:
    key = entity_key("lease", args.key)
    leases = {x["key"]: x for x in load_leases(mem)}
    current = leases.get(key)
    facts, events_ = [], []
    if not current:
        missing = [o for o in ("property", "start", "rent", "due_day") if getattr(args, o) in (None, "")]
        if missing:
            raise ToolError("A new lease needs " + ", ".join("--" + m.replace("_", "-") for m in missing) + ".")
    if args.rent is not None and current:
        raise ToolError("The rent of an existing lease changes with an increase (TOOL increase), so its history is kept.")
    if args.property:
        prop = entity_key("property", args.property)
        if prop not in load_properties(mem):
            raise ToolError(f"No property {args.property!r}: add it first (TOOL property).")
        facts.append({"subject": key, "predicate": "lease_property", "value": prop})
    start = parse_day(args.start, "--start") if args.start else (current or {}).get("start")
    if args.start:
        facts.append({"subject": key, "predicate": "lease_start", "value": noon(start, args.tz)})
    if args.end:
        end = parse_day(args.end, "--end")
        if start and end < start:
            raise ToolError("--end is before the start of the lease.")
        facts.append({"subject": key, "predicate": "lease_end", "value": noon(end, args.tz)})
    if args.tenant:
        facts.append({"subject": key, "predicate": "tenant_label", "value": args.tenant})
    if args.due_day is not None:
        if not 1 <= args.due_day <= 28:
            raise ToolError("--due-day is the last day to pay each month, 1 to 28.")
        facts.append({"subject": key, "predicate": "due_day", "value": args.due_day})
    if args.deposit is not None:
        facts.append({"subject": key, "predicate": "deposit_amount", "value": cents(args.deposit, "deposit")})
    if args.increase:
        facts.append({"subject": key, "predicate": "increase_rule", "value": increase_text(args.increase)})
    if args.late_fee_amount is not None and args.late_fee_percent is not None:
        raise ToolError("A late fee is either an amount or a percent, not both.")
    if args.late_fee_amount is not None:
        facts.append({"subject": key, "predicate": "late_fee_amount", "value": cents(args.late_fee_amount)})
    if args.late_fee_percent is not None:
        bp = int((Decimal(args.late_fee_percent) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        facts.append({"subject": key, "predicate": "late_fee_basis_points", "value": bp})
    if args.match_types:
        amount = cents(args.match_amount) if args.match_amount else None
        facts.append({"subject": key, "predicate": "payment_match",
                      "value": rule_text(args.match_types, args.match_account, amount)})
    if args.rent is not None:
        rent = cents(args.rent, "amount of rent")
        if rent <= 0:
            raise ToolError("--rent must be positive.")
        events_.append({"key": f"RENTSET_{key.split(':', 1)[1]}_{start.isoformat()}", "type": "rent_set",
                        "occurred_at": noon(start, args.tz), "summary": f"Rent {money(rent)} from {start}",
                        "attributes": {"monthly_rent": rent, "effective_from": noon(start, args.tz)},
                        "links": [{"predicate": "under_lease", "entity": key}]})
    if not facts and not events_ and not args.name and not args.paid_through:
        raise ToolError("Nothing to change: give the terms to set.")
    name = args.name or (current or {}).get("name") or key.split(":", 1)[1]
    entity = {"key": key, "type": "lease", "name": name}
    if current and args.name and args.name != current["name"]:
        entity["rename"] = True
    result = mem.write(args.by, args.source or f"Lease {name}", entities=[entity],
                       facts=[{**f, "valid_from": "now"} for f in facts], events=events_)
    lease = find_lease(load_leases(mem), key)
    opening = paid_through(mem, lease, args, today) if args.paid_through else None
    return {"ok": True, "lease": lease_view(lease, rent_sets(mem).get(key, []), today),
            "created": current is None, **({"paid_before_records": opening} if opening else {}),
            "warnings": result.get("warnings", [])}


def paid_through(mem: Memory, lease: dict, args, today: date) -> dict:
    """Months before the imported statements, settled as the owner says: an opening balance, not bank payments.

    They show as paid_before_records, count in no report and are never invoiced (they pay with no transaction).
    """
    last = parse_month(args.paid_through)
    if not lease["start"] or last < month_of(lease["start"]):
        raise ToolError(f"--paid-through {last} is before the start of the lease.")
    if last > month_of(today):
        raise ToolError("--paid-through can't be a future month: future rent is paid by deposits.")
    book = Book(mem, today)
    sets = book.sets.get(lease["key"], [])
    paid = {}
    for a in book.applied:
        if a["lease"] == lease["key"]:
            paid[a["period"]] = paid.get(a["period"], 0) + a["amount"]
    source_key = f"OPEN_{lease['key'].split(':', 1)[1]}"
    start = noon(lease["start"], args.tz)
    events_ = [{"key": source_key, "type": "rent_opening", "occurred_at": start,
                "summary": f"Rent settled before the records ({lease['name']})",
                "attributes": {"reason_text": args.source or "Paid before the imported statements"},
                "links": [{"predicate": "under_lease", "entity": lease["key"]}]}]
    settled = []
    for m in months(month_of(lease["start"]), last):
        balance = (rent_on(sets, first_of(m)) or 0) - paid.get(m, 0)
        if balance > 0:
            settled.append(m)
            events_.append({"key": f"RENT_{source_key}_{m.replace('-', '')}", "type": "rent_applied",
                            "occurred_at": start, "summary": f"Rent for {m} settled before the records",
                            "attributes": {"rent_period": m, "applied_amount": balance},
                            "links": [{"predicate": "paid_with", "event": source_key},
                                      {"predicate": "under_lease", "entity": lease["key"]}]})
    if settled:
        mem.write(args.by, args.source or f"Rent paid through {last}, before the imported statements", events=events_)
    return {"through": last, "months": settled}


def next_anniversary(lease: dict, today: date) -> date | None:
    if not lease["start"]:
        return None
    years = max(1, today.year - lease["start"].year)
    d = add_months(lease["start"], 12 * years)
    while d < today:
        years += 1
        d = add_months(lease["start"], 12 * years)
    return d


def lease_view(lease: dict, sets: list[tuple[date, int]], today: date) -> dict:
    rent = rent_on(sets, today) or (sets[0][1] if sets else None)
    anniversary = next_anniversary(lease, today)
    out = {"key": lease["key"], "name": lease["name"], "property": lease["property"], "tenant": lease["tenant"],
           "start": lease["start"].isoformat() if lease["start"] else None,
           "end": lease["end"].isoformat() if lease["end"] else None, "due_day": lease["due_day"],
           "rent_cents": rent, "rent": money(rent), "deposit": money(lease["deposit"]), "increase": lease["increase"],
           "late_fee": money(lease["late_fee_amount"]) if lease["late_fee_amount"] else
           (f"{lease['late_fee_bp'] / 100:g} %" if lease["late_fee_bp"] else None),
           "payment_rule": lease["rule_text"],
           "rent_history": [{"from": d.isoformat(), "rent": money(a)} for d, a in sets],
           "active": bool(lease["start"] and lease["start"] <= today and (not lease["end"] or lease["end"] >= today))}
    if anniversary and out["active"]:
        out["next_anniversary"] = anniversary.isoformat()
    return out


def cmd_leases(mem: Memory, args, today: date) -> dict:
    sets = rent_sets(mem)
    return {"ok": True, "leases": [lease_view(x, sets.get(x["key"], []), today) for x in load_leases(mem)]}


def cmd_sync(mem: Memory, args, today: date) -> dict:
    book = Book(mem, today)
    existing = all_keys(mem, "rent_applied")
    applied, ambiguous, leftovers, events_ = [], [], [], []
    for source in book.sources():
        found = book.candidates(source)
        if len(found) > 1:
            ambiguous.append({"tx": source["tx"], "date": source["date"].isoformat(), "amount": money(source["left_cents"]),
                              "leases": [x["key"] for x in found]})
            continue
        if not found:
            continue
        lease = found[0]
        parts, left = book.allocate(lease, source, source["left_cents"])
        new = book.application_events(lease, source, parts, args.tz, existing)
        events_ += new
        for p in parts:  # later sources see these months as paid
            book.applied.append({"key": "", "date": source["date"], "period": p["period"], "amount": p["amount_cents"],
                                 "source": source["tx"], "lease": lease["key"]})
        applied.append({"tx": source["tx"], "date": source["date"].isoformat(), "amount": money(source["left_cents"]),
                        "lease": lease["key"],
                        "months": [{"month": p["period"], "amount": money(p["amount_cents"])} for p in parts]})
        if left:
            leftovers.append({"tx": source["tx"], "lease": lease["key"], "left": money(left),
                              "why": "more than the rent pending through the end of the lease"})
    if events_ and not args.dry_run:
        mem.write(args.by, "Rent deposits applied by the owner's payment rules", "helper_command", events=events_)
    return {"ok": True, "dry_run": bool(args.dry_run), "applied": applied, "ambiguous": ambiguous,
            "not_applied": leftovers}


def cmd_apply(mem: Memory, args, today: date) -> dict:
    book = Book(mem, today)
    lease = find_lease(book.leases, args.lease)
    source = one_source(mem, args.tx)
    if source["amount_cents"] <= 0:
        raise ToolError("Only money received (positive amounts) pays rent.")
    if source["tx"] in book.ignored:
        raise ToolError("That deposit was marked as not rent.")
    left = source["amount_cents"] - book.used.get(source["tx"], 0)
    amount = cents(args.amount) if args.amount else left
    if amount <= 0 or amount > left:
        raise ToolError(f"Only {money(left)} of this payment is left to apply.")
    period = parse_month(args.period) if args.period else None
    parts, rest = book.allocate(lease, source, amount, period)
    if rest and not period:
        raise ToolError(f"{money(rest)} would be left over after every month pending through the end of the lease; "
                        "apply a smaller --amount or name the --period.")
    events_ = book.application_events(lease, source, parts, args.tz, all_keys(mem, "rent_applied"))
    mem.write(args.by, args.source or f"Payment {source['tx']} applied to {lease['name']}", events=events_)
    return {"ok": True, "tx": source["tx"], "lease": lease["key"],
            "months": [{"month": p["period"], "amount": money(p["amount_cents"])} for p in parts]}


def cmd_cash(mem: Memory, args, today: date) -> dict:
    book = Book(mem, today)
    lease = find_lease(book.leases, args.lease)
    day = parse_day(args.date, "--date")
    amount = cents(args.amount)
    if amount <= 0:
        raise ToolError("--amount must be positive.")
    key = stable_key("CASH", lease["key"], day.isoformat(), str(amount), args.nonce or "")
    receipt = {"key": key, "type": "rent_received", "occurred_at": noon(day, args.tz),
               "summary": f"Rent received outside the bank: {money(amount)} ({lease['name']})",
               "attributes": {"amount": amount}, "links": [{"predicate": "under_lease", "entity": lease["key"]}]}
    result = mem.write(args.by, args.source or f"Received {money(amount)} for {lease['name']}", events=[receipt])
    if not result.get("events", {}).get("created"):
        return {"ok": True, "unchanged": True, "receipt": key}
    source = {"tx": key, "date": day, "amount_cents": amount}
    parts, left = book.allocate(lease, source, amount, parse_month(args.period) if args.period else None)
    events_ = book.application_events(lease, source, parts, args.tz, all_keys(mem, "rent_applied"))
    if events_:
        mem.write(args.by, f"Cash receipt {key} applied", "helper_command", events=events_)
    return {"ok": True, "receipt": key, "lease": lease["key"],
            "months": [{"month": p["period"], "amount": money(p["amount_cents"])} for p in parts],
            **({"not_applied": money(left)} if left else {})}


def cmd_ignore(mem: Memory, args, today: date) -> dict:
    source = one_source(mem, args.tx)
    book = Book(mem, today)
    if book.used.get(source["tx"]):
        raise ToolError("That payment is applied to rent or the deposit: undo it first (TOOL unapply).")
    mem.write(args.by, args.reason, events=[{
        "key": f"NOTRENT_{source['tx']}", "type": "not_rent", "occurred_at": noon(source["date"], args.tz),
        "summary": f"Not rent: {args.reason[:120]}", "attributes": {"reason_text": args.reason},
        "links": [{"predicate": "paid_with", "event": source["tx"]}]}])
    return {"ok": True, "tx": source["tx"], "ignored": True}


def cmd_unapply(mem: Memory, args, today: date) -> dict:
    tx = key_part(args.tx)
    found = [a for a in applications(mem) if a["source"] == tx]
    if not found:
        raise ToolError(f"{tx} is not applied to any month of rent.")
    for a in found:
        mem.run("void", "--event", a["key"], "--reason", args.reason, "--by", args.by)
    return {"ok": True, "tx": tx, "undone": [{"month": a["period"], "amount": money(a["amount"])} for a in found]}


def cmd_status(mem: Memory, args, today: date) -> dict:
    book = Book(mem, today)
    leases = [find_lease(book.leases, args.lease)] if args.lease else book.leases
    out = []
    for lease in leases:
        rows = book.ledger(lease)
        owed = sum(r["balance_cents"] for r in rows if r["month"] <= month_of(today) and r["balance_cents"] > 0)
        ahead = [r["month"] for r in rows if r["month"] > month_of(today) and r["paid_cents"]]
        fees = sum(r.get("late_fee_cents", 0) for r in rows)
        out.append({"lease": lease["key"], "name": lease["name"], "tenant": lease["tenant"],
                    "owed_cents": owed, "owed": money(owed), "paid_ahead_through": max(ahead) if ahead else None,
                    **({"late_fees": money(fees), "late_fees_cents": fees} if fees else {}),
                    "months": rows[-args.months:] if args.months else rows})
    return {"ok": True, "today": today.isoformat(), "leases": out}


def cmd_increase(mem: Memory, args, today: date) -> dict:
    lease = find_lease(load_leases(mem), args.lease)
    sets = rent_sets(mem).get(lease["key"], [])
    day = parse_day(args.date, "--date") if args.date else next_anniversary(lease, today)
    current = rent_on(sets, day - timedelta(days=1)) or rent_on(sets, day)
    if current is None:
        raise ToolError("The lease has no rent yet.")
    if (args.percent is None) == (args.inpc_old is None and args.inpc_new is None):
        raise ToolError("Give either --percent, or --inpc-old and --inpc-new (the two index values).")
    if args.percent is not None:
        factor, basis = Decimal(1) + Decimal(str(args.percent)) / 100, f"{args.percent} %"
    else:
        if args.inpc_old is None or args.inpc_new is None:
            raise ToolError("An INPC increase needs both --inpc-old and --inpc-new.")
        old, new = Decimal(str(args.inpc_old)), Decimal(str(args.inpc_new))
        if old <= 0 or new <= 0:
            raise ToolError("INPC values are positive.")
        factor, basis = new / old, f"INPC {args.inpc_new} / {args.inpc_old}"
    step = args.round_to or 1
    rent = int((Decimal(current) * factor / step).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * step
    out = {"ok": True, "lease": lease["key"], "from": day.isoformat(), "basis": basis, "current_cents": current,
           "current": money(current), "new_cents": rent, "new": money(rent), "difference": money(rent - current),
           "applied": False}
    if args.apply:
        if not args.by:
            raise ToolError("--apply needs --by (the owner).")
        mem.write(args.by, args.source or f"Rent {money(rent)} from {day} ({basis})", events=[{
            "key": f"RENTSET_{lease['key'].split(':', 1)[1]}_{day.isoformat()}", "type": "rent_set",
            "occurred_at": noon(day, args.tz), "summary": f"Rent {money(rent)} from {day} ({basis})",
            "attributes": {"monthly_rent": rent, "effective_from": noon(day, args.tz)},
            "links": [{"predicate": "under_lease", "entity": lease["key"]}]}])
        out["applied"] = True
    return out


def cmd_deposit(mem: Memory, args, today: date) -> dict:
    book = Book(mem, today)
    lease = find_lease(book.leases, args.lease)
    links = [{"predicate": "under_lease", "entity": lease["key"]}]
    if args.tx:
        source = one_source(mem, args.tx)
        left = source["amount_cents"] - book.used.get(source["tx"], 0)
        amount = cents(args.amount) if args.amount else left
        if amount <= 0 or amount > left:
            raise ToolError(f"Only {money(left)} of this payment is left to apply.")
        day, key = source["date"], f"DEP_{source['tx']}"
        links.append({"predicate": "paid_with", "event": source["tx"]})
    else:
        if not (args.date and args.amount):
            raise ToolError("Give --tx (the bank deposit), or --date and --amount if it was received otherwise.")
        day, amount = parse_day(args.date, "--date"), cents(args.amount)
        key = stable_key("DEP", lease["key"], day.isoformat(), str(amount))
    result = mem.write(args.by, args.source or f"Security deposit {money(amount)} for {lease['name']}", events=[{
        "key": key, "type": "deposit_received", "occurred_at": noon(day, args.tz),
        "summary": f"Security deposit {money(amount)} ({lease['name']})", "attributes": {"applied_amount": amount},
        "links": links}])
    held = sum(d["amount"] for d in book.deposits if d["lease"] == lease["key"])
    created = bool(result.get("events", {}).get("created"))
    held += amount if created else 0
    agreed = lease["deposit"]
    return {"ok": True, "lease": lease["key"], "received": money(amount), "created": created, "held": money(held),
            "agreed": money(agreed), **({"short_by": money(agreed - held)} if agreed and held < agreed else {})}


def parse_deductions(items: list[str]) -> list[dict]:
    out = []
    for item in items or []:
        amount, _, reason = item.partition("=")
        if not reason.strip():
            raise ToolError(f"Each --deduct is AMOUNT=reason, e.g. 1200=pintura de la recámara; not {item!r}")
        value = cents(amount)
        if value <= 0:
            raise ToolError("Deductions are positive amounts.")
        out.append({"amount_cents": value, "amount": money(value), "reason": reason.strip()})
    return out


def cmd_settle(mem: Memory, args, today: date) -> dict:
    book = Book(mem, today)
    lease = find_lease(book.leases, args.lease)
    held = sum(d["amount"] for d in book.deposits if d["lease"] == lease["key"])
    deductions = parse_deductions(args.deduct)
    total = sum(d["amount_cents"] for d in deductions)
    owed = sum(r["balance_cents"] for r in book.ledger(lease) if r["month"] <= month_of(today) and r["balance_cents"] > 0)
    refund = held - total
    out = {"ok": True, "lease": lease["key"], "held": money(held), "deductions": deductions,
           "deductions_total": money(total), "refund_cents": refund, "refund": money(refund),
           "rent_owed": money(owed), "applied": False}
    if refund < 0:
        out["tenant_owes"] = money(-refund)
    if args.apply:
        if not args.by:
            raise ToolError("--apply needs --by (the owner).")
        day = parse_day(args.date, "--date") if args.date else today
        text = "; ".join(f"{d['amount']} {d['reason']}" for d in deductions) or "no deductions"
        mem.write(args.by, args.source or f"Deposit settled: {text}", events=[{
            "key": f"SETTLE_{lease['key'].split(':', 1)[1]}", "type": "deposit_settled", "occurred_at": noon(day, args.tz),
            "summary": f"Deposit settled: refund {money(refund)}",
            "attributes": {"refund_amount": refund, "deductions_amount": total, "deductions_text": text},
            "links": [{"predicate": "under_lease", "entity": lease["key"]}]}])
        out["applied"] = True
    return out


def cmd_recurring(mem: Memory, args, today: date) -> dict:
    key = entity_key("item", args.key)
    items = {r["key"]: r for r in load_recurring(mem)}
    current = items.get(key)
    if not current:
        missing = [o for o in ("property", "name", "kind", "payer", "every", "next_due") if getattr(args, o) in (None, "")]
        if missing:
            raise ToolError("A new recurring item needs " + ", ".join("--" + m.replace("_", "-") for m in missing) + ".")
    facts = []
    if args.property:
        prop = entity_key("property", args.property)
        if prop not in load_properties(mem):
            raise ToolError(f"No property {args.property!r}: add it first (TOOL property).")
        facts.append({"subject": key, "predicate": "lease_property", "value": prop})
    if args.kind:
        facts.append({"subject": key, "predicate": "recurring_kind", "value": choice(args.kind, RECURRING_KINDS, "--kind")})
    if args.payer:
        facts.append({"subject": key, "predicate": "payer", "value": choice(args.payer, PAYERS, "--payer")})
    if args.every is not None:
        if not 1 <= args.every <= 120:
            raise ToolError("--every is a number of months, 1 to 120.")
        facts.append({"subject": key, "predicate": "every_months", "value": args.every})
    if args.next_due:
        facts.append({"subject": key, "predicate": "next_due", "value": noon(parse_day(args.next_due, "--next-due"), args.tz)})
    if args.notice_days is not None:
        if not 0 <= args.notice_days <= 180:
            raise ToolError("--notice-days is 0 to 180.")
        facts.append({"subject": key, "predicate": "notice_days", "value": args.notice_days})
    if args.match_text:
        facts.append({"subject": key, "predicate": "charge_match", "value": charge_rule_text(args.match_text, args.match_account)})
    if args.note:
        facts.append({"subject": key, "predicate": "note_text", "value": args.note})
    if not facts and not args.name:
        raise ToolError("Nothing to change.")
    name = args.name or current["name"]
    entity = {"key": key, "type": "recurring_item", "name": name}
    if current and args.name and args.name != current["name"]:
        entity["rename"] = True
    mem.write(args.by, args.source or f"Recurring item {name}", entities=[entity],
              facts=[{**f, "valid_from": "now"} for f in facts])
    item = find_entity(load_recurring(mem), "item", key, "recurring item")
    return {"ok": True, "item": item_view(item, today), "created": current is None}


def item_view(item: dict, today: date) -> dict:
    out = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in item.items() if k not in ("rule",)}
    if item["next_due"]:
        out["due_in_days"] = (item["next_due"] - today).days
    return out


def cmd_done(mem: Memory, args, today: date) -> dict:
    item = find_entity(load_recurring(mem), "item", args.item, "recurring item")
    due = parse_day(args.due, "--due") if args.due else item["next_due"]
    if not due:
        raise ToolError("The item has no due date: give --due.")
    day = parse_day(args.date, "--date") if args.date else today
    attrs: dict[str, Any] = {"due_date": noon(due, args.tz)}
    links = [{"predicate": "for_item", "entity": item["key"]}]
    if args.tx:
        tx = one_source(mem, args.tx)
        if tx["amount_cents"] >= 0:
            raise ToolError("A payment is a charge (a negative amount in the statement).")
        if any(d["tx"] == tx["tx"] for d in recurring_done(mem)):
            raise ToolError("That charge already paid another item.")
        attrs["charge_amount"], day = -tx["amount_cents"], tx["date"]
        links.append({"predicate": "paid_with", "event": tx["tx"]})
    elif args.amount:
        attrs["charge_amount"] = cents(args.amount)
    event = {"key": f"DONE_{item['key'].split(':', 1)[1]}_{due.isoformat()}", "type": "recurring_done",
             "occurred_at": noon(day, args.tz), "attributes": attrs, "links": links,
             "summary": f"{item['name']}: {'verified' if item['payer'] == 'tenant' else 'done'} for {due}"
                        + (f" ({money(attrs['charge_amount'])})" if attrs.get("charge_amount") else "")}
    result = mem.write(args.by, args.source or event["summary"], events=[event])
    if not result.get("events", {}).get("created"):
        return {"ok": True, "unchanged": True, "item": item["key"], "due": due.isoformat()}
    following = parse_day(args.next_due, "--next-due") if args.next_due else add_months(due, item["every"] or 1)
    if not item["next_due"] or following > item["next_due"]:
        mem.write(args.by, f"{item['name']}: next due {following}", "helper_command",
                  facts=[{"subject": item["key"], "predicate": "next_due", "value": noon(following, args.tz),
                          "valid_from": "now"}])
    return {"ok": True, "item": item["key"], "due": due.isoformat(), "amount": money(attrs.get("charge_amount")),
            "next_due": following.isoformat()}


def cmd_work(mem: Memory, args, today: date) -> dict:
    key = entity_key("work", args.key)
    if any(w["key"] == key for w in load_works(mem)):
        raise ToolError(f"Work order {key} exists: move it with TOOL work-update.")
    prop = entity_key("property", args.property)
    if prop not in load_properties(mem):
        raise ToolError(f"No property {args.property!r}: add it first (TOOL property).")
    day = parse_day(args.date, "--date") if args.date else today
    facts = [{"subject": key, "predicate": "lease_property", "value": prop},
             {"subject": key, "predicate": "payer", "value": choice(args.payer, PAYERS, "--payer")},
             {"subject": key, "predicate": "work_status", "value": "reported"},
             {"subject": key, "predicate": "work_opened", "value": noon(day, args.tz)}]
    if args.reason:
        facts.append({"subject": key, "predicate": "reason_text", "value": args.reason})
    mem.write(args.by, args.source or f"Work order: {args.title}", entities=[{"key": key, "type": "work_order",
                                                                             "name": args.title}],
              facts=[{**f, "valid_from": "now"} for f in facts],
              events=[{"key": f"WORK_{key.split(':', 1)[1]}_reported", "type": "work_update",
                       "occurred_at": noon(day, args.tz), "summary": f"Reported: {args.title}",
                       "attributes": {"work_status": "reported"}, "links": [{"predicate": "for_item", "entity": key}]}])
    return {"ok": True, "work": work_view(find_entity(load_works(mem), "work", key, "work order"), today)}


def cmd_work_update(mem: Memory, args, today: date) -> dict:
    work = find_entity(load_works(mem), "work", args.key, "work order")
    status = choice(args.status, tuple(WORK_FLOW), "--status")
    if status != work["status"] and status not in WORK_FLOW.get(work["status"], ()):
        raise ToolError(f"A work order {work['status']} cannot move to {status} "
                        f"(it can move to: {', '.join(WORK_FLOW.get(work['status'], ())) or 'nothing'}).")
    day = parse_day(args.date, "--date") if args.date else today
    facts, attrs, links = [], {"work_status": status}, [{"predicate": "for_item", "entity": work["key"]}]
    if status != work["status"]:
        facts.append({"subject": work["key"], "predicate": "work_status", "value": status})
    if args.quote:
        facts.append({"subject": work["key"], "predicate": "work_quote", "value": cents(args.quote, "amount (quote)")})
    cost = cents(args.cost, "amount (cost)") if args.cost else None
    if args.tx:
        tx = one_source(mem, args.tx)
        if tx["amount_cents"] >= 0:
            raise ToolError("A payment is a charge (a negative amount in the statement).")
        cost = (work["cost_cents"] or 0) + -tx["amount_cents"] if args.add_cost else -tx["amount_cents"]
        links.append({"predicate": "paid_with", "event": tx["tx"]})
    if cost is not None:
        facts.append({"subject": work["key"], "predicate": "work_cost", "value": cost})
    if args.provider:
        provider = entity_key("provider", args.provider)
        if not any(p["key"] == provider for p in load_providers(mem)):
            raise ToolError(f"No provider {args.provider!r}: add it first (TOOL provider).")
        facts.append({"subject": work["key"], "predicate": "work_provider", "value": provider})
    if args.warranty_until and args.warranty_months:
        raise ToolError("Give --warranty-until or --warranty-months, not both.")
    if args.warranty_until or args.warranty_months:
        until = parse_day(args.warranty_until, "--warranty-until") if args.warranty_until else \
            add_months(day, args.warranty_months)
        facts.append({"subject": work["key"], "predicate": "warranty_until", "value": noon(until, args.tz)})
    if args.note:
        facts.append({"subject": work["key"], "predicate": "note_text", "value": args.note})
    if status in ("done", "cancelled") and status != work["status"]:
        facts.append({"subject": work["key"], "predicate": "work_closed", "value": noon(day, args.tz)})
    if not facts and not links[1:]:
        return {"ok": True, "unchanged": True, "work": work_view(work, today)}
    key = stable_key(f"WORK_{work['key'].split(':', 1)[1]}", status, day.isoformat(),
                     json.dumps(facts, sort_keys=True))
    mem.write(args.by, args.source or f"{work['title']}: {status}", facts=[{**f, "valid_from": "now"} for f in facts],
              events=[{"key": key, "type": "work_update", "occurred_at": noon(day, args.tz),
                       "summary": f"{status}: {work['title']}", "attributes": attrs, "links": links}])
    return {"ok": True, "work": work_view(find_entity(load_works(mem), "work", work["key"], "work order"), today)}


def cmd_works(mem: Memory, args, today: date) -> dict:
    works = load_works(mem)
    if args.open:
        works = [w for w in works if w["status"] in OPEN_WORK]
    if args.property:
        works = [w for w in works if w["property"] == entity_key("property", args.property)]
    works.sort(key=lambda w: (w["status"] not in OPEN_WORK, w["opened"] or date.min))
    return {"ok": True, "works": [work_view(w, today) for w in works]}


def load_providers(mem: Memory) -> list[dict]:
    cols = ["--column", "key", "--column", "name"]
    for f in ("provider_trade", "provider_contact", "provider_rating", "note_text"):
        cols += ["--column", f"fact:{f}"]
    return [{"key": r["key"], "name": r["name"], "trade": r["fact:provider_trade"], "contact": r["fact:provider_contact"],
             "rating": r["fact:provider_rating"], "note": r["fact:note_text"]}
            for r in mem.rows("--entity-type", "provider", *cols)]


def cmd_provider(mem: Memory, args, today: date) -> dict:
    key = entity_key("provider", args.key)
    current = next((p for p in load_providers(mem) if p["key"] == key), None)
    if not current and not (args.name and args.trade):
        raise ToolError("A new provider needs --name and --trade.")
    facts = []
    if args.trade:
        facts.append({"subject": key, "predicate": "provider_trade", "value": args.trade.strip().lower()})
    if args.contact:
        facts.append({"subject": key, "predicate": "provider_contact", "value": args.contact})
    if args.rating is not None:
        if not 1 <= args.rating <= 5:
            raise ToolError("--rating is 1 to 5.")
        facts.append({"subject": key, "predicate": "provider_rating", "value": args.rating})
    if args.note:
        facts.append({"subject": key, "predicate": "note_text", "value": args.note})
    name = args.name or current["name"]
    entity = {"key": key, "type": "provider", "name": name}
    if current and args.name and args.name != current["name"]:
        entity["rename"] = True
    mem.write(args.by, args.source or f"Provider {name}", entities=[entity],
              facts=[{**f, "valid_from": "now"} for f in facts])
    return {"ok": True, "provider": next(p for p in load_providers(mem) if p["key"] == key), "created": current is None}


def cmd_providers(mem: Memory, args, today: date) -> dict:
    providers = load_providers(mem)
    if args.trade:
        providers = [p for p in providers if args.trade.strip().lower() in (p["trade"] or "")]
    works = load_works(mem) if providers else []
    out = []
    for p in providers:
        jobs = [w for w in works if w["provider"] == p["key"]]
        spent = sum(w["cost_cents"] or 0 for w in jobs)
        out.append({**p, "jobs": len(jobs), "spent": money(spent),
                    "last_job": max((w["opened"] for w in jobs if w["opened"]), default=None)})
    for p in out:
        p["last_job"] = p["last_job"].isoformat() if p["last_job"] else None
    out.sort(key=lambda p: (-(p["rating"] or 0), p["name"]))
    return {"ok": True, "providers": out}


def charge_candidates(item: dict, done: list[dict], charges: list[dict]) -> list[dict]:
    if not item["rule"].get("text"):
        return []
    used = {d["tx"] for d in done if d["tx"]}
    window_start = add_months(item["next_due"], -(item["every"] or 1)) - timedelta(days=15)
    return [{"tx": t["tx"], "date": t["date"].isoformat(), "amount": money(-t["amount_cents"])}
            for t in charges if t["tx"] not in used and t["date"] >= window_start and matches_charge(item["rule"], t)]


def cmd_pending(mem: Memory, args, today: date) -> dict:
    book = Book(mem, today)
    sets, items_out = book.sets, []

    def add(kind: str, when: date | None, text: str, **extra) -> None:
        items_out.append({"kind": kind, "when": when.isoformat() if when else None,
                          "in_days": (when - today).days if when else None, "text": text, **extra})

    # rent
    for lease in book.leases:
        if not lease["start"]:
            continue
        for row in book.ledger(lease):
            if row["state"] in ("late", "partial_late"):
                add("rent_late", date.fromisoformat(row["due"]),
                    f"{lease['name']}: rent for {row['month']} is {row['days_late']} days late, {row['balance']} pending",
                    lease=lease["key"], month=row["month"], balance=row["balance"],
                    **({"late_fee": row["late_fee"]} if row.get("late_fee") else {}))
            elif row["state"] in ("due", "partial"):
                add("rent_due", date.fromisoformat(row["due"]),
                    f"{lease['name']}: rent for {row['month']} ({row['balance']}) is due by {row['due']}",
                    lease=lease["key"], month=row["month"], balance=row["balance"])
        anniversary = next_anniversary(lease, today)
        active = lease["start"] <= today and (not lease["end"] or lease["end"] >= today)
        if active and lease["increase"] != "none" and anniversary and (anniversary - today).days <= SOON_DAYS["increase"] \
                and not any(d == anniversary for d, _ in sets.get(lease["key"], [])):
            add("increase", anniversary, f"{lease['name']}: the rent increase ({lease['increase']}) applies from "
                f"{anniversary}; tell the tenant ahead", lease=lease["key"])
        if lease["end"] and 0 <= (lease["end"] - today).days <= SOON_DAYS["lease_end"]:
            add("lease_end", lease["end"], f"{lease['name']}: the lease ends on {lease['end']}; renew or plan the move-out",
                lease=lease["key"])
        held = sum(d["amount"] for d in book.deposits if d["lease"] == lease["key"])
        if lease["end"] and lease["end"] < today and held and not any(
                r["link:under_lease/key"] == lease["key"] for r in events(mem, "deposit_settled", "link:under_lease/key")):
            add("deposit_return", lease["end"], f"{lease['name']}: settle the security deposit ({money(held)})",
                lease=lease["key"])
    # deposits that a rule matches but are not applied yet, or that match several leases
    for source in book.sources():
        found = book.candidates(source)
        if len(found) == 1:
            add("payment_to_apply", source["date"], f"Deposit of {money(source['left_cents'])} on {source['date']} "
                f"matches {found[0]['name']}: apply it (TOOL sync)", tx=source["tx"], lease=found[0]["key"])
        elif len(found) > 1:
            add("payment_ambiguous", source["date"], f"Deposit of {money(source['left_cents'])} on {source['date']} "
                f"matches several leases: ask which", tx=source["tx"], leases=[x["key"] for x in found])
    # recurring items
    items = load_recurring(mem)
    done = recurring_done(mem) if items else []
    charges = bank_transactions(mem, today - timedelta(days=400), today, "< 0") if any(
        i["rule"].get("text") for i in items) else []
    for item in items:
        if not item["next_due"] or (item["next_due"] - today).days > item["notice_days"]:
            continue
        verb = "check the tenant paid" if item["payer"] == "tenant" else (
            "do" if item["kind"] == "preventive" else "pay")
        late = " (overdue)" if item["next_due"] < today else ""
        extra = {"candidates": charge_candidates(item, done, charges)} if item["payer"] == "owner" else {}
        add("recurring", item["next_due"], f"{item['name']}: {verb} by {item['next_due']}{late}", item=item["key"],
            payer=item["payer"], item_kind=item["kind"], **{k: v for k, v in extra.items() if v})
    # maintenance
    for w in load_works(mem):
        if w["status"] in OPEN_WORK:
            add("work_open", w["opened"], f"{w['title']}: {w['status'].replace('_', ' ')}, open "
                f"{(today - w['opened']).days if w['opened'] else '?'} days", work=w["key"], status=w["status"])
        elif w["status"] == "done" and w["warranty_until"] and 0 <= (w["warranty_until"] - today).days <= SOON_DAYS["warranty"]:
            add("warranty_ending", w["warranty_until"], f"{w['title']}: the warranty ends on {w['warranty_until']}; "
                "check it still works", work=w["key"])
    horizon = today + timedelta(days=args.days)
    # items with their own notice window (increase, lease end, recurring, warranty) keep it
    items_out = [i for i in items_out if not i["when"] or date.fromisoformat(i["when"]) <= horizon
                 or i["kind"] not in ("rent_due", "payment_to_apply", "payment_ambiguous")]
    order = {"rent_late": 0, "payment_ambiguous": 1, "payment_to_apply": 2, "deposit_return": 3, "recurring": 4,
             "rent_due": 5, "increase": 6, "lease_end": 7, "work_open": 8, "warranty_ending": 9}
    items_out.sort(key=lambda i: (i["when"] or "9999", order.get(i["kind"], 99)))
    counts: dict[str, int] = {}
    for i in items_out:
        counts[i["kind"]] = counts.get(i["kind"], 0) + 1
    return {"ok": True, "today": today.isoformat(), "counts": counts, "pending": items_out}


def cmd_report(mem: Memory, args, today: date) -> dict:
    year = int(args.year)
    first, last = date(year, 1, 1), date(year, 12, 31)
    book = Book(mem, today)
    props = load_properties(mem)
    if args.property:
        wanted = entity_key("property", args.property)
        if wanted not in props:
            raise ToolError(f"No property {args.property!r}.")
        props = {wanted: props[wanted]}
    lease_property = {x["key"]: x["property"] for x in book.leases}
    items = {i["key"]: i for i in load_recurring(mem)}
    works = load_works(mem)
    out = []
    for prop, name in props.items():
        recorded = [a for a in book.applied if lease_property.get(a["lease"]) == prop
                    and not a["source"].startswith("OPEN_")]  # an opening balance is not money that arrived
        collected = sum(a["amount"] for a in recorded if first <= a["date"] <= last)
        for_year = sum(a["amount"] for a in recorded if a["period"].startswith(f"{year}-"))
        bills = [d for d in recurring_done(mem) if items.get(d["item"], {}).get("property") == prop
                 and items[d["item"]]["payer"] == "owner" and d["amount"] and first <= d["date"] <= last]
        jobs = [w for w in works if w["property"] == prop and w["payer"] == "owner" and w["cost_cents"]
                and w["closed"] and first <= w["closed"] <= last]
        by_item: dict[str, int] = {}
        for d in bills:
            by_item[items[d["item"]]["name"]] = by_item.get(items[d["item"]]["name"], 0) + d["amount"]
        expenses = sum(by_item.values()) + sum(w["cost_cents"] for w in jobs)
        last_month = min(last, today)
        covered = set()
        for lease in book.leases:
            if lease["property"] == prop and lease["start"]:
                end = lease["end"] or last
                covered |= set(months(month_of(max(lease["start"], first)), month_of(min(end, last))))
        vacant = [m for m in months(month_of(first), month_of(last_month)) if m not in covered] if last_month >= first else []
        out.append({"property": prop, "name": name, "rent_collected": money(collected), "rent_collected_cents": collected,
                    "rent_for_months_of_year": money(for_year),
                    "expenses": money(expenses), "expenses_cents": expenses,
                    "expenses_by_item": [{"item": k, "amount": money(v)} for k, v in sorted(by_item.items())],
                    "maintenance": [{"work": w["title"], "cost": money(w["cost_cents"]), "closed": w["closed"].isoformat()}
                                    for w in jobs],
                    "net": money(collected - expenses), "net_cents": collected - expenses, "months_vacant": vacant})
    return {"ok": True, "year": year, "properties": out,
            "note": "Rent collected counts payments by the day they arrived; expenses count only what the owner pays."}


# -- main -------------------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(prog="arrendamiento.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"arrendamiento.py {__version__}")
    p.add_argument("--mem", help="Path to project-memory's memory.py")
    p.add_argument("--db", help="Path to the memory (default: the current project's)")
    p.add_argument("--tz", default=os.environ.get("HOWWARE_TZ") or local_offset(), help="UTC offset, e.g. --tz=-07:00")
    p.add_argument("--today", default=os.environ.get("ARR_TODAY"), help=argparse.SUPPRESS)  # fixed clock for tests
    sub = p.add_subparsers(dest="command", required=True)

    def cmd(name: str, by: bool = True, source: bool = True):
        s = sub.add_parser(name)
        if by:
            s.add_argument("--by", required=True, help="person:<id> of the owner")
        if source:
            s.add_argument("--source", help="The owner's literal words")
        return s

    cmd("setup", source=False)
    s = cmd("import", source=False)
    s.add_argument("files", nargs="+", help="mxbank JSON or NDJSON (extracted with --pseudonym-key-env), or -")
    s = cmd("property")
    s.add_argument("--key", required=True)
    s.add_argument("--name", required=True, help="the owner's label, e.g. Casa Tijuana (no full address needed)")
    s = cmd("lease")
    s.add_argument("--key", required=True)
    s.add_argument("--name")
    s.add_argument("--property")
    s.add_argument("--tenant", help="the owner's label for the tenant, not their legal name")
    s.add_argument("--start", help="YYYY-MM-DD")
    s.add_argument("--end", help="YYYY-MM-DD (none while open-ended)")
    s.add_argument("--rent", help="monthly rent at the start (later changes: increase)")
    s.add_argument("--due-day", type=int, help="last day of the month to pay, e.g. 7")
    s.add_argument("--deposit", help="security deposit agreed")
    s.add_argument("--increase", help="none | percent:<p> | inpc")
    s.add_argument("--late-fee-amount")
    s.add_argument("--late-fee-percent")
    s.add_argument("--match-types", help="transaction types of its payments, e.g. cash_deposit,spei_in")
    s.add_argument("--match-account", help="only payments to this account (ACC_…)")
    s.add_argument("--match-amount", help="only payments of exactly this amount")
    s.add_argument("--paid-through", help="YYYY-MM: every month until this one was paid before the imported statements")
    cmd("leases", by=False, source=False)
    s = cmd("sync", source=False)
    s.add_argument("--dry-run", action="store_true")
    s = cmd("apply")
    s.add_argument("--tx", required=True)
    s.add_argument("--lease", required=True)
    s.add_argument("--period", help="YYYY-MM: all of it to this month")
    s.add_argument("--amount", help="only part of the payment")
    s = cmd("cash")
    s.add_argument("--lease", required=True)
    s.add_argument("--amount", required=True)
    s.add_argument("--date", required=True)
    s.add_argument("--period")
    s.add_argument("--nonce", help="tells apart two equal receipts on the same day")
    s = cmd("ignore", source=False)
    s.add_argument("--tx", required=True)
    s.add_argument("--reason", required=True, help="the owner's words")
    s = cmd("unapply", source=False)
    s.add_argument("--tx", required=True)
    s.add_argument("--reason", required=True)
    s = cmd("status", by=False, source=False)
    s.add_argument("--lease")
    s.add_argument("--months", type=int, help="only the last N months")
    s = cmd("increase", by=False)
    s.add_argument("--by", help="person:<id> of the owner (needed with --apply)")
    s.add_argument("--lease", required=True)
    s.add_argument("--date", help="from YYYY-MM-DD (default: the next anniversary)")
    s.add_argument("--percent", type=Decimal)
    s.add_argument("--inpc-old", type=Decimal, help="INPC of the month the last rent was set")
    s.add_argument("--inpc-new", type=Decimal, help="latest INPC published")
    s.add_argument("--round-to", type=int, help="round to this many cents, e.g. 100 for whole pesos")
    s.add_argument("--apply", action="store_true")
    s = cmd("deposit")
    s.add_argument("--lease", required=True)
    s.add_argument("--tx")
    s.add_argument("--amount")
    s.add_argument("--date")
    s = cmd("settle", by=False)
    s.add_argument("--by", help="person:<id> of the owner (needed with --apply)")
    s.add_argument("--lease", required=True)
    s.add_argument("--deduct", action="append", help="AMOUNT=reason (repeatable)")
    s.add_argument("--date")
    s.add_argument("--apply", action="store_true")
    s = cmd("recurring")
    s.add_argument("--key", required=True)
    s.add_argument("--name")
    s.add_argument("--property")
    s.add_argument("--kind", help=" | ".join(RECURRING_KINDS))
    s.add_argument("--payer", help="owner | tenant")
    s.add_argument("--every", type=int, help="months")
    s.add_argument("--next-due", help="YYYY-MM-DD")
    s.add_argument("--notice-days", type=int)
    s.add_argument("--match-text", help="piece of the bank description of its charges, e.g. CFE")
    s.add_argument("--match-account")
    s.add_argument("--note")
    s = cmd("done")
    s.add_argument("--item", required=True)
    s.add_argument("--tx", help="the charge that paid it")
    s.add_argument("--amount")
    s.add_argument("--date")
    s.add_argument("--due", help="the due date it covers (default: its next due date)")
    s.add_argument("--next-due", help="override the next due date (e.g. property tax: next year's discount window)")
    s = cmd("work")
    s.add_argument("--key", required=True)
    s.add_argument("--property", required=True)
    s.add_argument("--title", required=True)
    s.add_argument("--payer", required=True, help="owner | tenant")
    s.add_argument("--reason", help="why that payer, in the owner's words (their rule)")
    s.add_argument("--date")
    s = cmd("work-update")
    s.add_argument("--key", required=True)
    s.add_argument("--status", required=True, help=" | ".join(WORK_FLOW))
    s.add_argument("--quote")
    s.add_argument("--cost")
    s.add_argument("--tx", help="the charge that paid it (its amount becomes the cost)")
    s.add_argument("--add-cost", action="store_true", help="with --tx: add to the cost so far (several payments)")
    s.add_argument("--provider")
    s.add_argument("--warranty-until")
    s.add_argument("--warranty-months", type=int)
    s.add_argument("--note")
    s.add_argument("--date")
    s = cmd("works", by=False, source=False)
    s.add_argument("--open", action="store_true")
    s.add_argument("--property")
    s = cmd("provider")
    s.add_argument("--key", required=True)
    s.add_argument("--name")
    s.add_argument("--trade")
    s.add_argument("--contact", help="as the owner gave it")
    s.add_argument("--rating", type=int)
    s.add_argument("--note")
    s = cmd("providers", by=False, source=False)
    s.add_argument("--trade")
    s = cmd("pending", by=False, source=False)
    s.add_argument("--days", type=int, default=30, help="how far ahead to look")
    s = cmd("report", by=False, source=False)
    s.add_argument("--year", required=True)
    s.add_argument("--property")
    args = p.parse_args()

    commands = {"setup": cmd_setup, "import": cmd_import, "property": cmd_property, "lease": cmd_lease,
                "leases": cmd_leases, "sync": cmd_sync, "apply": cmd_apply, "cash": cmd_cash, "ignore": cmd_ignore,
                "unapply": cmd_unapply, "status": cmd_status, "increase": cmd_increase, "deposit": cmd_deposit,
                "settle": cmd_settle, "recurring": cmd_recurring, "done": cmd_done, "work": cmd_work,
                "work-update": cmd_work_update, "works": cmd_works, "provider": cmd_provider,
                "providers": cmd_providers, "pending": cmd_pending, "report": cmd_report}
    try:
        tz = parse_offset(args.tz)
        today = parse_day(args.today, "--today") if args.today else datetime.now(tz).date()
        mem = Memory(find_helper(args.mem), args.db)
        mem.check_version()
        result, code = commands[args.command](mem, args, today), OK
    except ToolError as error:
        result, code = {"ok": False, "error": {"code": error.code, "message": str(error)}}, error.code
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
