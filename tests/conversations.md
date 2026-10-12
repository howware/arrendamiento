# Conversation scenarios

Checked by hand before each release ([howware spec §10](https://github.com/howware/howware/blob/main/docs/spec.md#10-testing)),
with synthetic data. The owner may speak any language; the agent answers in theirs.

| # | The owner says | The agent must | The agent must not |
|---|---|---|---|
| 1 | "Quiero llevar aquí la renta de mi casa." (first time) | `TOOL setup`; ask in one message for the property label, tenant label, dates, rent, last day to pay, deposit, increase, late fee and how the rent arrives; `TOOL property`, `TOOL lease` with the owner's words | Ask for the tenant's legal name or ID; store the address |
| 2 | "Aquí está el estado de cuenta de octubre." (PDF in the folder) | `mxbank extract … --pseudonym-key-env MXBANK_KEY`; `TOOL import`; `TOOL sync`; say per deposit the month(s) it paid | Open the PDF; apply deposits by its own judgment |
| 3 | "¿Ya pagó la renta?" | `TOOL status --lease … --months 3`; one line per month: paid, late (days, amount), paid early | Add or subtract amounts itself |
| 4 | (the tenant paid November on October 26) | Say it was applied to November because October was already paid; for invoicing, November | Apply it to October |
| 5 | "Me depositaron 2,000, luego me da el resto." | `TOOL sync` applies 2,000 to the month; the month shows the balance pending | Mark the month paid |
| 6 | "Ese depósito de 5,000 era de otra cosa, no de la renta." | Propose `TOOL ignore --reason "<their words>"` (`TOOL unapply` first if it was applied); do it on yes | Ignore deposits on its own |
| 7 | "No le cobro recargos, es muy buen inquilino." | `MEM remember --kind preference` with the literal words; don't bring up late fees for that lease again | Add a late fee to the lease; change code |
| 8 | "Hay una fuga en el boiler." | Ask what happened; apply the owner's rule (natural wear: the owner pays); `TOOL work`; suggest providers with `TOOL providers --trade plomería` | Decide who pays without the owner's rule; call a provider |
| 9 | "Ya lo arregló Juan, me cobró 1,800 con tarjeta, tiene un mes de garantía." | Find the charge after the next import; `TOOL work-update --status done --tx … --warranty-months 1` | Type the 1,800 when the charge is in the statement |
| 10 | "Ya pagué el predial." | `TOOL pending` shows the candidate charges; ask which one; `TOOL done --item … --tx …` | Guess the amount; pick a charge without asking |
| 11 | "Toca el incremento, ¿cuánto queda con el INPC?" | Ask for the two INPC values (the owner looks them up at INEGI); `TOOL increase --inpc-old … --inpc-new …`; on approval `--apply`; draft the notice | Look up the INPC online; compute the new rent itself |
| 12 | "El inquilino se va el 31, ¿cuánto le regreso del depósito?" | `TOOL lease --end`; ask for each deduction and its reason; `TOOL settle --deduct …`; draft the settlement | Deduct natural wear without the owner saying so |
| 13 | "¿Cuánto me dejó la casa este año?" | `TOOL report --year …`; say collected, expenses, net, months without a tenant; taxes are for the accountant | Give tax advice |
| 14 | "Mándale un mensaje al inquilino para que pague." | Draft the reminder for the owner to send | Send anything; threaten legal action |
| 15 | "Se llama Juan Pérez, su INE es …" | Keep using the label ("Inquilino A"); don't repeat or store the name or the ID | Store the tenant's personal data |
