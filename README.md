<h1 align="center">arrendamiento · Rentals for landlords, without an app</h1>

<p align="center">
  <b>Your AI agent checks the rent against your bank statements, applies each payment to the right month, and keeps
  one list of everything pending around the house: services, property tax, repairs, warranties, the increase and
  the deposit.</b>
</p>

<p align="center">
  <a href="https://github.com/howware/arrendamiento/actions/workflows/ci.yml"><img src="https://github.com/howware/arrendamiento/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/version-0.1.0-blue" alt="Version 0.1.0">
  <a href="https://howware.org"><img src="https://img.shields.io/badge/howware-0.2-5a45d6" alt="howware 0.2"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="Apache 2.0">
</p>

<p align="center"><a href="README.es.md">Español</a> · <a href="docs/building.md">How it was built</a></p>

> **A [howware](https://howware.org):** your know-how, put to work by AI. Here the know-how is a landlord's: when
> the rent is due, who pays each service and each repair, how the rent increases, what comes off the deposit. It
> composes two shared adapters, bank statements ([mxbank](https://github.com/howware/mx-bank-statement-reader)) and
> the [memory](https://github.com/howware/long-term-memory-for-AI). It works on its own, or on the same memory as
> [finanzas-personales](https://github.com/howware/finanzas-personales) and
> [facturacion](https://github.com/howware/facturacion).

```text
› ¿Qué tengo pendiente de la casa?
  1. March rent: $3,000.00 missing, 3 days late (they deposited $2,000.00 on the 9th).
  2. Property tax: pay by March 31. Found a charge of $3,200.00 on Jan 15 that looks like it. Was that it?
  3. Electricity (CFE): the tenant pays it; due March 15. Did they show you the receipt?
  4. Water heater leak: approved, Juan (plumber) quoted $1,800.00.

› Sí, ese fue el predial. Y la luz ya me la enseñó.
  ✓ Property tax $3,200.00 paid; next one due March 31, 2027.
  ✓ Electricity checked; next bill May 15.
```

## What it does

| You say | It does |
|---|---|
| "Did the tenant pay?" | Imports the statement, recognizes the rent deposits by **your rule** ("cash deposits to my debit account are the rent") and applies each one to the **oldest month pending**. Paid early, it goes to the next month; partial, the month shows what is missing |
| "What do I have pending?" | One list, soonest first: late rent, deposits to check, services and property tax to pay or to check with the tenant, repairs in progress, warranties ending, the increase coming, a lease ending, a deposit to return |
| "There's a leak" | A work order: who pays by your rule (natural wear or damage), quote, provider from your directory, cost from the charge that paid it, warranty |
| "It's time for the increase" | The new rent from a percent or two INPC values, rounded as you like, in force from the anniversary. Drafts the notice; you send it |
| "The tenant is leaving" | The deposit refund after each deduction and its reason |
| "How did the house do this year?" | Rent collected, expenses you paid, net, months without a tenant |

**It doesn't decide for you.** Who pays a repair, whether a late fee is charged, how the rent increases: your
rules, stored with your words. **It doesn't contact anyone or pay anything**: it drafts, you send.

**With [facturacion](https://github.com/howware/facturacion) on the same memory**, a rent paid early is invoiced for
the month it pays, not by a fixed rule: two invoices in one month, or none, come out right.

## How it works

| Part | Here |
|---|---|
| Protocol | [`skill/arrendamiento/SKILL.md`](skill/arrendamiento/SKILL.md): the landlord's cycle, the rules, what to ask, in plain words |
| Tool | [`arrendamiento.py`](skill/arrendamiento/scripts/arrendamiento.py): applying payments to months, balances and days late, due dates, work orders, increases, the deposit, the year's report. It never opens a statement or a lease |
| Adapters | [mxbank](https://github.com/howware/mx-bank-statement-reader) reads statements; the [memory](https://github.com/howware/long-term-memory-for-AI) keeps everything with history. Statements are stored as mxbank's common records, so other howwares on the same memory share them |

## Install

```bash
uv tool install git+https://github.com/howware/mx-bank-statement-reader   # if you don't have mxbank yet
git clone https://github.com/howware/long-term-memory-for-AI && python long-term-memory-for-AI/tools/install_skill.py
git clone https://github.com/howware/arrendamiento && python arrendamiento/tools/install_skill.py
```

Requires Python 3.9+ (mxbank needs 3.12+), project-memory 0.4.0+ and mxbank 0.2.0+, with your pseudonym key
`MXBANK_KEY` set once (see the [mxbank README](https://github.com/howware/mx-bank-statement-reader)). In the folder's
`.claude/settings.json`, keep documents out of the agent's reach:

```json
{ "permissions": { "deny": ["Read(**/*.pdf)"] } }
```

Then open your agent in that folder and say: *"Quiero llevar aquí la renta de mi casa."*

## Privacy and limits

| Designed to stay on your computer | What the AI agent sees |
|---|---|
| Bank statements, leases, receipts and bills | Deposits and charges: date, amount, type, anonymized description, account pseudonym |
| Names, account and card numbers in the statements | Your labels for properties and tenants ("Casa Tijuana", "Inquilino A"), lease terms, repairs and costs |
| The memory file | Providers' contacts, only as you give them; what you type |

**What it cannot do or guarantee:**
- Automatic anonymization is not infallible; mxbank withholds its output when it detects a leak, and its code is
  open for review.
- Not opening documents is an instruction to the agent; the deny permission above reduces the risk but is not an
  absolute barrier.
- What the agent sees leaves your computer for your AI provider, under its terms. The memory is not encrypted.
- **No legal or tax advice.** Ask a lawyer about the lease and your accountant about taxes.
- **The INPC is not looked up online:** you give its values (INEGI publishes them).
- **No proration** of a first or last partial month in this version: rent is per whole month.
- **No push notifications:** pending items appear when you open a conversation.
- **Not yet tested in a real conversation** on any host; `howware.json` lists hosts only once tested.

## Development

```bash
git clone https://github.com/howware/long-term-memory-for-AI ../long-term-memory-for-AI
git clone https://github.com/howware/mx-bank-statement-reader ../mx-bank-statement-reader   # to compare mxbank_records.py
python -m unittest discover -s tests -v
git ls-files -z | xargs -0 python tools/check_private_data.py
```

Tests run against a temporary memory with synthetic deposits and charges. `mxbank_records.py` is a verbatim copy of
mxbank's `src/mxbank/records.py`: update it from there, never by hand. See [AGENTS.md](AGENTS.md), and how it was
built with `howware-builder`: [docs/building.md](docs/building.md).

## License

[Apache 2.0](LICENSE). Not legal or tax advice.
