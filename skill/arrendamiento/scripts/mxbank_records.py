"""Registros de memoria de un estado de cuenta: la forma común en que cualquier howware lo guarda.

Convierte la salida de ``mxbank extract`` en un documento para ``write`` de project-memory con lo que el estado
dice, sin interpretarlo: la cuenta, el evento del estado, los movimientos y los planes a meses. Las llaves son los
ids estables de mxbank, así que dos howwares que importan el mismo estado escriben los mismos registros y la
memoria no los duplica; cada howware agrega aparte su propia lectura (categorías, periodos de renta, facturas)
como vínculos o hechos.

Este archivo es solo biblioteca estándar y funciona desde Python 3.9 porque los howwares lo copian tal cual
(``mxbank_records.py``) junto a sus herramientas. La copia no se edita: se actualiza desde aquí.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

RECORDS_VERSION = "1"
MIN_SCHEMA = (1, 1)

# Predicados de los registros comunes. Un howware que los declare debe usar exactamente estas definiciones.
PREDICATES = [
    {"id": "amount", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one", "label": "Amount",
     "description": "Signed amount in cents: outflows negative, inflows positive"},
    {"id": "tx_type", "value_type": "text", "cardinality": "one", "label": "Transaction type",
     "description": "Technical type from mxbank (card_purchase, spei_out, fee...) or manual"},
    {"id": "bank_description", "value_type": "text", "cardinality": "one", "label": "Bank description",
     "description": "Anonymized description as printed by the bank"},
    {"id": "entry_source", "value_type": "text", "cardinality": "one", "label": "Entry source",
     "description": "statement (imported) or manual (told by the person)"},
    {"id": "original_currency", "value_type": "text", "cardinality": "one", "label": "Original currency",
     "description": "Currency of a foreign purchase"},
    {"id": "original_amount_text", "value_type": "text", "cardinality": "one", "label": "Original amount",
     "description": "Amount in the original currency, decimal text"},
    {"id": "exchange_rate_text", "value_type": "text", "cardinality": "one", "label": "Exchange rate",
     "description": "Exchange rate applied by the bank, decimal text"},
    {"id": "installment_number", "value_type": "integer", "cardinality": "one", "label": "Installment number",
     "description": "Installment N of M"},
    {"id": "installments_total", "value_type": "integer", "cardinality": "one", "label": "Installments total",
     "description": "M in installment N of M"},
    {"id": "on_account", "value_type": "entity", "label": "On account",
     "description": "Account a transaction, statement or plan belongs to", "cardinality": "one"},
    {"id": "imported_from", "value_type": "any", "label": "Imported from",
     "description": "Statement event a transaction came from", "cardinality": "one"},
    {"id": "account_product", "value_type": "text", "cardinality": "one", "label": "Account product",
     "description": "debit, credit or cash"},
    {"id": "bank_code", "value_type": "text", "cardinality": "one", "label": "Bank",
     "description": "Bank code from mxbank (bbva, bancoppel...)"},
    {"id": "balance", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one", "label": "Balance",
     "description": "Account balance at a date in cents; credit card debt is negative"},
    {"id": "credit_limit", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Credit limit", "description": "Credit card limit in cents"},
    {"id": "period_start", "value_type": "datetime", "cardinality": "one", "label": "Period start",
     "description": "First day of a statement period"},
    {"id": "period_end", "value_type": "datetime", "cardinality": "one", "label": "Period end",
     "description": "Last day (cut-off) of a statement period"},
    {"id": "opening_balance", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Opening balance", "description": "Statement opening balance in cents"},
    {"id": "closing_balance", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Closing balance", "description": "Statement closing balance in cents"},
    {"id": "total_balance", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Total card debt", "description": "Credit card total debt at cut-off in cents (positive)"},
    {"id": "no_interest_payment", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "No-interest payment", "description": "Payment that avoids interest, in cents"},
    {"id": "minimum_payment", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Minimum payment", "description": "Minimum payment in cents"},
    {"id": "payment_due_date", "value_type": "datetime", "cardinality": "one", "label": "Payment due date",
     "description": "Last day to pay a credit card statement"},
    {"id": "interest_charged", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Interest charged", "description": "Interest charged in the period, in cents"},
    {"id": "fees_charged", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Fees charged", "description": "Bank fees in the period, in cents"},
    {"id": "vat_on_interest_and_fees", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "VAT on interest and fees", "description": "VAT on interest and fees, in cents"},
    {"id": "reconciled", "value_type": "boolean", "cardinality": "one", "label": "Reconciled",
     "description": "mxbank reconciled the statement against its balances"},
    {"id": "plan_original_amount", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Plan original amount", "description": "Original amount of an installment plan, in cents"},
    {"id": "pending_balance", "value_type": "integer", "unit": "MXN_cent", "cardinality": "one",
     "label": "Pending balance", "description": "Pending balance of an installment plan at a statement, in cents"},
    {"id": "installments_paid", "value_type": "integer", "cardinality": "one", "label": "Installments paid",
     "description": "Installment number reached at a statement"},
]


# Hechos que cambian con el tiempo: un estado viejo importado después de uno nuevo no los reemplaza.
TEMPORAL = {"balance", "credit_limit", "pending_balance", "installments_paid"}


class RecordsError(ValueError):
    """El JSON no sirve para registros comunes (versión vieja, sin llave estable, error de mxbank)."""


def cents(value: Any) -> int | None:
    if value is None:
        return None
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def at(day: str | None, tz: str, clock: str = "12:00:00") -> str | None:
    """Fechas de calendario a mediodía local, para que ninguna zona horaria las mueva de día."""
    return f"{day}T{clock}{tz}" if day else None


def check_statement(st: dict) -> None:
    if not st.get("ok"):
        raise RecordsError(f"mxbank reportó un error: {st.get('error')}")
    version = tuple(int(x) for x in str(st.get("schema_version", "0.0")).split(".")[:2])
    if version < MIN_SCHEMA or not st.get("statement_id"):
        raise RecordsError("Se necesita mxbank con schema 1.1 o más reciente (ids estables). Actualiza mxbank.")
    if st["privacy"].get("pseudonym_scope") != "key":
        raise RecordsError("El JSON se generó sin --pseudonym-key-env: sus ids cambian en cada ejecución y "
                           "duplicarían movimientos. Vuelve a extraer con la misma llave de siempre.")
    if not st["account"].get("account_ref"):
        raise RecordsError("El estado no trae account_ref: no se puede saber a qué cuenta pertenece.")


def account_name(st: dict) -> str:
    doc_, acct = st["document"], st["account"]
    label = doc_.get("product_name") or f"{doc_['bank_name']} {doc_['product']}"
    return f"{label} ({acct['account_last4']})" if acct.get("account_last4") else label


def source_text(st: dict) -> str:
    """Texto de la evidencia: el mismo para todo howware, así la memoria la guarda una sola vez."""
    doc_, period = st["document"], st["period"]
    return (f"mxbank statement {st['statement_id']} ({doc_['bank']} {doc_['product']} "
            f"{period.get('start')}..{period.get('end')})")


def memory_document(st: dict, by: str, tz: str) -> tuple[dict, dict]:
    """Documento ``write`` con los registros comunes de un estado, y un resumen para quien importa.

    ``by`` es la entidad que importa (``person:...``) y ``tz`` el desfase local (``-07:00``).
    """
    check_statement(st)
    doc_, acct, period = st["document"], st["account"], st["period"]
    credit = st.get("credit") or {}
    account_key = f"account:{acct['account_ref']}"
    product = doc_["product"]
    name = account_name(st)
    end_instant = at(period.get("end"), tz)
    entities = [{"key": account_key, "type": "account", "name": name}]
    facts = [{"subject": account_key, "predicate": "account_product", "value": product},
             {"subject": account_key, "predicate": "bank_code", "value": doc_["bank"]}]
    if product == "credit":
        if credit.get("total_balance") is not None and end_instant:
            facts.append({"subject": account_key, "predicate": "balance", "value": -cents(credit["total_balance"]),
                          "valid_from": end_instant})
        if credit.get("credit_limit") is not None and end_instant:
            facts.append({"subject": account_key, "predicate": "credit_limit", "value": cents(credit["credit_limit"]),
                          "valid_from": end_instant})
    elif (st.get("summary") or {}).get("closing_balance") is not None and end_instant:
        facts.append({"subject": account_key, "predicate": "balance", "value": cents(st["summary"]["closing_balance"]),
                      "valid_from": end_instant})

    attrs: dict[str, Any] = {"period_start": at(period.get("start"), tz), "period_end": end_instant,
                             "reconciled": st["validation"].get("reconciled")}
    summary = st.get("summary") or {}
    for k in ("opening_balance", "closing_balance"):
        attrs[k] = cents(summary.get(k))
    for k in ("no_interest_payment", "minimum_payment", "interest_charged", "fees_charged",
              "vat_on_interest_and_fees", "total_balance"):
        attrs[k] = cents(credit.get(k))
    attrs["payment_due_date"] = at(credit.get("payment_due_date"), tz)
    attrs = {k: v for k, v in attrs.items() if v is not None}
    sid = st["statement_id"]
    events = [{"key": sid, "type": "statement_imported", "occurred_at": end_instant or "now",
               "summary": f"{name} statement {period.get('start')}..{period.get('end')}",
               "attributes": attrs, "links": [{"predicate": "on_account", "entity": account_key}]}]

    for tx in st["transactions"]:
        tattrs = {"amount": cents(tx["amount"]), "tx_type": tx["type"], "bank_description": tx.get("description"),
                  "entry_source": "statement", "original_currency": tx.get("original_currency"),
                  "original_amount_text": tx.get("original_amount"), "exchange_rate_text": tx.get("exchange_rate"),
                  "installment_number": tx.get("installment_number"), "installments_total": tx.get("installments_total")}
        events.append({"key": tx["id"], "type": "transaction", "occurred_at": at(tx["date"], tz),
                       "summary": (tx.get("description") or tx["type"])[:160],
                       "attributes": {k: v for k, v in tattrs.items() if v is not None},
                       "links": [{"predicate": "on_account", "entity": account_key},
                                 {"predicate": "imported_from", "event": sid}]})

    for plan in st.get("installment_plans") or []:
        pkey = f"plan:{plan['id']}"
        entities.append({"key": pkey, "type": "installment_plan", "name": plan["description"]})
        facts.append({"subject": pkey, "predicate": "on_account", "value": account_key})
        for pred, value in (("plan_original_amount", cents(plan.get("original_amount"))),
                            ("installments_total", plan.get("installments_total"))):
            if value is not None:
                facts.append({"subject": pkey, "predicate": pred, "value": value})
        for pred, value in (("pending_balance", cents(plan.get("pending_balance"))),
                            ("installments_paid", plan.get("installment_number"))):
            if value is not None and end_instant:
                facts.append({"subject": pkey, "predicate": pred, "value": value, "valid_from": end_instant})

    write = {"source": {"type": "import", "content": source_text(st), "provided_by": by, "captured_at": "now"},
             "performed_by": by,
             "predicates": [{**p, "distinct_from_similar": True} for p in PREDICATES],
             "entities": entities, "facts": facts, "events": events}
    info = {"statement_id": sid, "account": account_key, "account_name": name, "product": product,
            "period": [period.get("start"), period.get("end")], "reconciled": st["validation"].get("reconciled"),
            "warnings": st["validation"].get("warnings", []), "transactions": len(st["transactions"]),
            "records_version": RECORDS_VERSION}
    return write, info


def temporal_subjects(document: dict) -> list[str]:
    """Cuentas y planes cuyos hechos temporales hay que comparar con los vigentes antes de escribir."""
    return sorted({f["subject"] for f in document["facts"] if f["predicate"] in TEMPORAL})


def keep_newer(document: dict, current: dict) -> int:
    """Quita del documento los hechos temporales que no son más nuevos que los vigentes; devuelve cuántos quitó.

    ``current`` es ``{(sujeto, predicado): desde}`` con el inicio del valor vigente en la memoria (texto ISO). El
    estado sigue guardando esos valores en su evento; solo no reemplazan a uno posterior.
    """
    keep, skipped = [], 0
    for f in document["facts"]:
        since = current.get((f["subject"], f["predicate"])) if f["predicate"] in TEMPORAL else None
        if since and f.get("valid_from") and _instant(f["valid_from"]) <= _instant(str(since)):
            skipped += 1
            continue
        keep.append(f)
    document["facts"] = keep
    return skipped


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
