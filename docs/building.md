# How this howware was built

A record of building `arrendamiento` with the
[`howware-builder`](https://github.com/howware/howware/blob/main/skills/howware-builder/SKILL.md) protocol. The
owner's words are kept verbatim, in Spanish. No real data appears here: amounts in examples are illustrative.

## 1. Choosing it

Two candidates came first and were set aside:

- **A security guards' logbook** (visits, rounds, incidents). It fits the idea (the value is in the post orders,
  not the screens), but guards capture from phones at the gate and several of them write at once, which needs
  something howware doesn't have yet.
- **A local network service** that would bring data and events from outside while the agent stays isolated. The
  owner saw it as necessary one day, and premature now:

  > «parece que me estoy metiendo en un problema para el cual es muy pronto entrar, o sea, si hay que implementar
  > algo como esto, pero me doy cuenta que es prematuro.»

Rentals won because the owner rents a house (so it is used with real data from day one), it **composes** what
already exists (bank statements, invoicing, the memory) and it needs no network. The owner asked for the complete
scope:

> «el de arrendamiento me parece bien, pero desde todo lo completo posible, pagos de renta, mantenimientos, pagos de
> luz, agua, predial, y lo que consideres»

## 2. Interview

| Topic | The owner's words |
|---|---|
| Properties | «ahorita 1 pero pueden ser multiples» |
| What is hard | «asegurarse que tanto el inquilino pague en tiempo y que no se nos olvide asi como siempre revisar los pagos que esten cubiertos» |
| When rent is paid | «casi siempre tiene los primeros 7 dias del mes para pagar la renta pero a veces paga desde una semana antes de que termine el mes el alquiler del mes siguiente, para facturacion significa que a veces en un mes hay dos facturas pero de diferentes meses y a veces no hay facturas en el mes» |
| Deposit | «si hay deposito en mi caso de 1 mes, pero es comun de 2 meses» |
| How rent arrives | «puede pagar tanto en efectivo o como transferencia a una cuenta de banco [...] En mi caso nunca recibo dinero en efectivo, siempre se tiene que hacer por medio de un deposito, es lo que me recomendo la contadora» |
| Late fees | «tengo un muy buen inquilino [...] no tengo problema con que pague tarde y no le cobro recargos, pero para la mayoria que quiera usar el skill es seguro que no sera el caso» |
| Services | «Yo corro con los gastos, pero en la mayoria de las veces es el inquilino» |
| Property tax | «se puede pagar a partir del 1 de enero y hay como 3 meses para pagar y si hay descuento si se paga en los primeros meses» |
| Repairs | «los daños por el desgaste natural, como plomeria, electricidad, instalaciones de gas las pago yo [...] lo demas el inquilino, no tengo proveedores pero si seria exelente tener un directorio de proveedores de servicios» |
| Preventive maintenance | «No lo hago pero debieria de hacerlo [...] es presisamente la clase de cosas que un howware provee» |
| The questions | «si ya pago, pero sobre todo que tareas tengo pendientes yo de hacer en pagos , mantenimientos, seguimiento a mantenimientos en progreso, garantias, y asi» |
| How the owner pays | «Si son cargos en mis tarjetas, no pago en efectivo» |
| Separate or together | «no todos los que quieren llevar sus finanazas tienen casas de alquiler por lo que hay que hacerlo separado [...] por eso es importante la fexibilidad de en una memoria integrar mas de un howware» |

## 3. What the interview changed outside this repository

Two answers changed the howware family, not only this howware.

**One payment covers the oldest month pending.** The answer about when rent is paid hid a rule. With it, every case
the owner described comes out right: paid on the 5th, it is this month; paid on the 24th with this month already
paid, it is next month; paid on the 24th with this month pending, it is this month, late. It also fixes invoicing,
which used a fixed rule ("the rent is invoiced for the next month"): now `facturacion` asks this howware which
month a deposit paid.

**Several howwares on one memory.** `facturacion` required `finanzas-personales`, because only finanzas imported
bank statements. Someone with only a house to rent should not have to install personal finance. So:

- The specification 0.2 gained a rule (§8): records that come from an adapter are written in the form the adapter
  documents, keyed by its stable ids and without interpretation; each howware adds its own reading beside them;
  no howware requires another only to get them.
- **project-memory 0.4.0**: a record sent again by a second importer gains the links it lacks (before, the whole
  record was skipped, and finanzas would have lost its categories if another howware imported first).
- **mxbank 0.3.0**: `mxbank records` and `src/mxbank/records.py`, the common form of a statement in the memory,
  extracted from what finanzas already wrote (identical on its test statements, so existing memories don't change).
  Howwares copy the module verbatim and test that the copy matches.
- **finanzas-personales 0.3.0** writes statements through that module; **facturacion 0.2.0** imports statements
  itself and no longer requires finanzas.

## 4. Design decisions

| Decision | Why |
|---|---|
| Labels, not names: "Casa Tijuana", "Inquilino A" | The job doesn't need the tenant's legal name or the address; what isn't stored can't leak |
| The payment rule is the owner's approval | Deposits matched by it are applied without asking each month; ambiguous ones are asked |
| Rent changes only through `increase` | Each rent has a start date, so past months keep the rent they had |
| Late fee only if the lease has one | The owner charges none; most landlords do. It is a term of the lease, not code |
| Who pays a repair is the owner's rule, stored with the work order | "Natural wear I pay; the rest, the tenant" is judgment: the agent applies it and asks when it doesn't settle |
| Recurring items: one model for services, property tax, insurance, condo fees and preventive tasks | All are "something due every N months, paid by someone, shown N days ahead" |
| Property tax as a due date at the end of the owner's window, with a long notice | The window and the discount change by municipality; the amount comes from the charge |
| The INPC is given by the owner | No network; INEGI publishes it once a month |
| No proration of partial months in 0.1 | The owner's lease started on the 1st; proration is a rule to add when a real case needs it |

## 5. Not included in 0.1

Sending anything to the tenant (drafts only), collecting payments, writing leases, looking up the INPC, reading
receipts or bills, photos of the move-in inventory, co-ownership, short stays (nightly rentals), taxes (for the
accountant and `facturacion`).
