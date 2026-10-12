---
name: arrendamiento
description: Rentals without an app, for landlords — whether the tenant paid, what the owner has to pay or check, maintenance and warranties, the deposit and the yearly increase. Use it when the person asks "¿ya pagó la renta?", "¿qué tengo pendiente de la casa?", wants to register a rental or a tenant, gives a bank statement to check the rent, records a payment in cash, a service bill (luz, agua, gas), the property tax (predial) or the condo fee, reports a repair or a maintenance job, asks for a plumber or another provider, wants to raise the rent, settle the deposit when a tenant leaves, or asks how much a property earned in the year.
---

# arrendamiento — rentals without an app

A [howware](https://howware.org): the owner's rentals, put to work by you. Around each lease:

```text
deposit reaches the bank → applied to the oldest month pending → late months show up first
services and property tax due → paid by the owner, or checked with the tenant → next due date
repair reported → who pays → quote → provider → done → warranty
anniversary → increase → new rent from that day        lease ends → deposit settled
```

It runs in the owner's folder, on its memory. It may share that memory with other howwares
([finanzas-personales](https://github.com/howware/finanzas-personales),
[facturacion](https://github.com/howware/facturacion)): a bank statement imported by any of them is stored once,
the same way, and each adds its own reading. Facturación uses this one's: the month of rent a deposit was applied
to is the month its invoice is for. Answer in the owner's language.

`TOOL` = `python "<this skill's folder>/scripts/arrendamiento.py"`; `MEM` = the project-memory helper. Run them
from the owner's folder. All output is JSON. Requires project-memory 0.4.0+ and, for statements, mxbank 0.2.0+.

## Rules (non-negotiable)

1. **Never open bank statements (`.pdf`), leases, receipts or bills.** Only the `mxbank` adapter reads statements;
   its output has names and account numbers replaced with pseudonyms. The rest the owner tells you. If the owner
   pastes a tenant's full name, an address or an account number, don't repeat it back and don't store it: the
   memory keeps labels ("Casa Tijuana", "Inquilino A").
2. **Amounts come from the bank or from the owner's words, never from you.** Never add, split, prorate or compute
   rent, balances, late fees, increases or refunds yourself: the tool does it, and you report what it returns.
3. **Payments are applied to the oldest month pending.** A deposit pays the earliest month with a balance; if that
   month is paid, it pays the next one (a rent paid early goes to the next month). Apply a payment to another month
   only when the owner says so (`TOOL apply --period`).
4. **The owner decides who pays, and what the lease says.** Whether a repair is natural wear (the owner pays) or
   damage (the tenant pays), whether a late fee is charged, the increase, the due day: all are the owner's rules,
   stored with their words. When the owner is not sure about a legal question (eviction, the lease's validity,
   taxes), say so and suggest a lawyer or their accountant.
5. **Nothing outward-facing.** You draft notices to the tenant (a reminder, the increase, the deposit settlement);
   the owner sends them. You never contact the tenant or a provider, and never pay anything.
6. You organize and check; you are not a lawyer, an accountant or a property manager.

## Exactness boundary

| The tool does | You do |
|---|---|
| Which deposits match a lease's payment rule; splitting them over the oldest months pending (`TOOL sync`) | Ask about deposits that match no lease or several; propose a payment rule |
| Month by month: rent, paid, balance, days late, late fee if the lease has one (`TOOL status`) | Say it plainly: "marzo: faltan $3,000.00, 3 días de atraso" |
| The new rent from a percent or two INPC values, rounded as the owner says (`TOOL increase`) | Ask for the INPC values (published by INEGI); draft the notice |
| Due dates of services, property tax, insurance, preventive tasks; the next one after each payment (`TOOL done`) | Ask whether the owner paid it, or whether the tenant showed the receipt |
| Charges in the card statements that look like a recurring item (`candidates` in `TOOL pending`) | Ask the owner to confirm which charge paid it |
| Valid steps of a work order, its cost from the charge that paid it, the end of the warranty (`TOOL work-update`) | Ask who pays, applying the owner's rule; suggest providers from the directory |
| The deposit refund after deductions (`TOOL settle`) | Ask for each deduction and its reason; draft the settlement for the tenant |
| A year per property: rent collected, expenses, net, months without a tenant (`TOOL report`) | Point out what stands out |
| Days to every due date (`TOOL pending`) | Say dates in absolute terms ("martes 7 de abril") |

Exit codes: 0 ok · 2 invalid input (explain `error.message`, ask or fix) · 3 memory problem (say what to install).
Errors arrive as `{"ok": false, "error": {"code", "message"}}`.

## Cold start

1. `MEM brief --format text` (or the one the session hook injected): the owner's rules appear as preferences.
2. The first time in a folder (or after an update): `TOOL setup --by person:<id>`. It is idempotent.
3. `TOOL pending`. Open with, only if non-empty, in this order:
   - **Rent late**, with the month, what is missing and the days late.
   - **Deposits to apply** (run `TOOL sync` and say what it did) and deposits that need the owner.
   - **What the owner has to pay or check soon**: services, property tax, the deposit to settle.
   - **Rent due this month**, the increase coming, a lease ending, open repairs and warranties ending.
4. Keep it short: one line each. If nothing is pending, say so in one line.

## Workflows

### 1. Register a property and its lease

1. Ask, in one message: a label for the property (no address needed); the tenant's label; start and end dates
   (or open-ended); the rent; the last day to pay (e.g. the 7th); the security deposit; how the rent increases
   (a percent, the INPC, or not at all) and from when; whether there is a late fee; and **how the rent arrives**
   (cash deposit at the branch, transfer; to which account). Never ask for the tenant's legal name or ID.
2. `TOOL property --key <k> --name "<label>" --by <owner>`.
3. `TOOL lease --key <k> --property <p> --tenant "<label>" --start … [--end …] --rent … --due-day … [--deposit …]
   [--increase percent:5 | inpc | none] [--late-fee-amount … | --late-fee-percent …] --match-types cash_deposit,spei_in
   [--match-account ACC_…] [--match-amount …] --by <owner> --source "<their words>"`. To find the account
   pseudonym, look at the deposits after importing a statement (`TOOL pending`, `MEM list`).
4. If the deposit was received, record it: `TOOL deposit --lease <k> --tx <deposit> [--amount <part>]` (a single
   deposit may carry the deposit and the first month: give the deposit part with `--amount`).
5. Ask about the recurring items of the property (workflow 4) and record them.

### 2. Did the tenant pay? (each statement)

1. Extract the statement with the same key as always: `mxbank extract <pdf> --pseudonym-key-env MXBANK_KEY --out
   <file>.json` (never open the PDF). `TOOL import <file>.json … --by <owner>`.
2. `TOOL sync --by <owner>`. It applies the deposits that match a lease's payment rule (the rule is the owner's
   approval). Say, per deposit: the date, the amount and the month(s) it paid.
3. Deposits that match **several leases** (`ambiguous`): ask which, then `TOOL apply --tx … --lease …`. A deposit
   that is rent but matches **no rule**: propose fixing the rule (`TOOL lease --match-…`), or apply it once with
   `TOOL apply`. A deposit that is not rent and keeps showing up: `TOOL ignore --tx … --reason "<their words>"`.
4. `TOOL status --lease <k> --months 6` when the owner asks how the tenant is doing.
5. Rent received outside the bank (only if the owner accepts cash): `TOOL cash --lease … --amount … --date …
   --source "<their words>"`. If the owner's rule is "only deposits", remind them of it instead.
6. A payment applied to the wrong month: `TOOL unapply --tx … --reason "<their words>"`, then `TOOL apply … --period`.

### 3. Late rent

1. Lead with the facts from `TOOL status`: month, missing amount, days late, and the late fee only if the lease has
   one. Apply the owner's stored tolerance ("no le cobro recargos, es buen inquilino") and say so.
2. If the owner wants, draft a friendly reminder for them to send. Never threaten, and never mention legal action
   unless the owner asks; for that, suggest a lawyer.

### 4. Services, property tax, insurance, condo fee, preventive maintenance

1. For each item: who pays (owner or tenant, from the lease), how often (months), the next due date, how many days
   ahead to show it, and for those the owner pays by card, a piece of the bank description of the charge (e.g.
   "CFE", "PREDIAL") so the tool can find it. `TOOL recurring --key … --name … --property … --kind
   service|property_tax|insurance|condo_fee|preventive|other --payer owner|tenant --every <months> --next-due …
   [--notice-days …] [--match-text …] --by <owner> --source "<their words>"`.
2. Property tax: the owner sets the due date at the end of the window they use (e.g. the discount month) and the
   notice from the day it can be paid (e.g. 90 days). The amount changes every year: it comes from the charge.
3. Preventive tasks: offer the usual ones and let the owner choose (water heater service once a year, gas
   installation check once a year, roof waterproofing every 3 to 5 years, fumigation, tinaco or cistern cleaning).
   Only the ones they approve are recorded, with the frequency they say.
4. When due: if the owner pays it, show the `candidates` (charges that match) and ask which one paid it, then
   `TOOL done --item … --tx …` (the amount comes from the charge). Paid otherwise: `TOOL done --item … --amount …`.
   If the tenant pays it, ask whether the tenant showed the receipt; on yes, `TOOL done --item … --source "<their
   words>"`. A preventive task done: `TOOL done --item …` (and a work order if there was a cost, workflow 5).

### 5. Repairs and maintenance (work orders)

1. When the owner reports something: what happened, and **who pays** by the owner's rule (e.g. "plumbing,
   electrical and gas installations from natural wear, I pay; the rest, the tenant"). If the rule doesn't settle
   it, ask. `TOOL work --key … --property … --title "<their words>" --payer owner|tenant --reason "<their rule>"`.
2. Suggest providers for the trade: `TOOL providers --trade <trade>`. A new one: `TOOL provider --key … --name …
   --trade … [--contact "<as the owner gives it>"] [--rating 1-5]`.
3. Move it forward as the owner tells you: `TOOL work-update --key … --status quoted --quote … --provider …`, then
   `approved`, `in_progress`, `done` (with `--tx <charge>` for the cost from the bank, `--add-cost` for several
   payments, and `--warranty-months` or `--warranty-until`). `cancelled` if it won't be done.
4. A problem again while under warranty: reopen it (`--status in_progress --note "<what happened>"`) and remind the
   owner to call the same provider.

### 6. The yearly increase and renewals

1. When `TOOL pending` shows the increase coming: `TOOL increase --lease …` with `--percent …`, or with the INPC
   values the owner gives (`--inpc-old` the month the rent was last set, `--inpc-new` the latest published).
   Show current and new rent and the difference. Rounding is the owner's choice (`--round-to 100` for whole pesos).
2. On approval: `TOOL increase … --apply --by <owner> --source "<their words>"`. Draft the notice for the tenant.
3. A lease ending: ask whether it renews. Renewal with new dates: `TOOL lease --key … --end …`. Move-out:
   workflow 7.

### 7. A tenant leaves: the deposit

1. `TOOL lease --key … --end <last day>`.
2. Ask for the move-out check: damages beyond natural wear, rent owed, services pending, each with its amount.
3. `TOOL settle --lease … --deduct "<amount>=<reason>" …` shows the refund (or what the tenant owes). On approval,
   `--apply --by <owner>`. Draft the settlement for the tenant with each deduction and its reason.

### 8. How did the property do?

`TOOL report --year YYYY [--property …]`: rent collected (by the day it arrived), rent for the months of the year,
expenses the owner paid (recurring items and repairs), net, and months without a tenant. Taxes on rental income are
for the owner's accountant (and the facturacion howware, if they use it).

## Rules the owner teaches

Store them with `MEM remember --kind preference` and the owner's literal words; they appear in every session brief.
Examples: "no le cobro recargos, es muy buen inquilino", "solo acepto depósitos, nunca efectivo", "el desgaste
natural (plomería, electricidad, gas) lo pago yo; lo demás, el inquilino", "redondeo la renta a pesos cerrados".
Apply them and say so. A rule about **how the rent arrives** is a lease's payment rule instead: `TOOL lease
--match-…` (same key). A rule about the lease's terms (due day, late fee, increase) also goes in `TOOL lease`.

## Approval

The owner approves, in one message per batch: a new lease or a change to its terms, a payment rule, applying a
payment by hand or to another month, ignoring a deposit, each recurring item, who pays a repair, the increase, and
the deposit settlement. Deposits matched by an approved rule are applied without asking again; say what was
applied. Store the owner's literal words with `--source`.

## Presenting results

- Lead with what needs the owner. Amounts with thousands separators and two decimals, as the tool returns them.
- Dates in absolute terms, with the weekday when it matters.
- Use the owner's labels, never pseudonyms (`ACC_…`, `TX_…`) unless they ask for them.
- "Rent collected" counts money by the day it arrived; "rent for the months" counts by the month it pays. Say which
  one you are showing.
