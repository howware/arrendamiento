# Changelog

## 0.1.2

- `howware.json` lists `claude-code` in `hosts`: used in a real conversation, with the owner's statements, on Claude
  Code. Codex will be added once tested.

## 0.1.1

- `lease --paid-through YYYY-MM`: a lease older than the imported statements settles the months before them as an
  opening balance. They show as `paid_before_records`, count in no report and are never invoiced; without it they
  showed as rent late. The protocol asks for it when registering a lease (found in the first real conversation).

## 0.1.0 — first version

- Protocol for a landlord without an app: register a property and its lease, check the rent against the bank
  statements, late rent, services and property tax, preventive maintenance, repairs with providers and warranties,
  the yearly increase, the deposit when a tenant leaves, and the year per property.
- `arrendamiento.py`: `setup`, `import`, `property`, `lease`, `leases`, `sync`, `apply`, `cash`, `ignore`,
  `unapply`, `status`, `increase`, `deposit`, `settle`, `recurring`, `done`, `work`, `work-update`, `works`,
  `provider`, `providers`, `pending`, `report`. Payments are applied to the oldest month pending; rent changes only
  through increases, so past months keep their rent; late fees only if the lease has one. Errors as JSON with exit
  codes 2 and 3.
- Shares the memory with other howwares (howware specification 0.2 §8): statements are stored as mxbank's common
  records (`mxbank_records.py`, a verbatim copy of mxbank 0.3.0's `src/mxbank/records.py`), and the month of rent
  each deposit pays is a `rent_applied` event that `facturacion` 0.2.0 reads to invoice the right month.
- Requires project-memory 0.4.0. Built with `howware-builder`; the process is recorded in `docs/building.md`.
