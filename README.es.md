<h1 align="center">arrendamiento · Rentas para caseros, sin app</h1>

<p align="center">
  <b>Tu agente de IA revisa la renta contra tus estados de cuenta, aplica cada pago al mes que corresponde y lleva
  una sola lista de todo lo pendiente de la casa: servicios, predial, reparaciones, garantías, el incremento y el
  depósito.</b>
</p>

<p align="center">
  <a href="https://github.com/howware/arrendamiento/actions/workflows/ci.yml"><img src="https://github.com/howware/arrendamiento/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/versión-0.1.0-blue" alt="Versión 0.1.0">
  <a href="https://howware.org/es/"><img src="https://img.shields.io/badge/howware-0.2-5a45d6" alt="howware 0.2"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-blue" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/licencia-Apache%202.0-green" alt="Apache 2.0">
</p>

<p align="center"><a href="README.md">English</a> · <a href="docs/building.md">Cómo se construyó</a></p>

> **Un [howware](https://howware.org/es/):** tu saber hacer, puesto a trabajar con IA. Aquí el saber hacer es el de
> un casero: cuándo vence la renta, quién paga cada servicio y cada reparación, cómo sube la renta, qué se descuenta
> del depósito. Combina dos adaptadores compartidos: estados de cuenta
> ([mxbank](https://github.com/howware/mx-bank-statement-reader)) y la
> [memoria](https://github.com/howware/long-term-memory-for-AI). Funciona solo, o sobre la misma memoria que
> [finanzas-personales](https://github.com/howware/finanzas-personales) y
> [facturacion](https://github.com/howware/facturacion).

```text
› ¿Qué tengo pendiente de la casa?
  1. Renta de marzo: faltan $3,000.00, 3 días de atraso (depositó $2,000.00 el día 9).
  2. Predial: pagar antes del 31 de marzo. Hay un cargo de $3,200.00 del 15 de enero que parece ser. ¿Fue ese?
  3. Luz (CFE): la paga el inquilino; vence el 15 de marzo. ¿Ya te enseñó el recibo?
  4. Fuga del boiler: aprobada, Juan (plomero) cotizó $1,800.00.

› Sí, ese fue el predial. Y la luz ya me la enseñó.
  ✓ Predial $3,200.00 pagado; el siguiente vence el 31 de marzo de 2027.
  ✓ Luz revisada; el siguiente recibo, el 15 de mayo.
```

## Qué hace

| Dices | Hace |
|---|---|
| «¿Ya pagó el inquilino?» | Importa el estado de cuenta, reconoce los depósitos de la renta con **tu regla** («los depósitos en efectivo a mi cuenta de débito son la renta») y aplica cada uno al **mes más antiguo pendiente**. Si paga adelantado, va al mes siguiente; si paga una parte, el mes muestra lo que falta |
| «¿Qué tengo pendiente?» | Una sola lista, lo más próximo primero: renta atrasada, depósitos por revisar, servicios y predial por pagar o por revisar con el inquilino, reparaciones en curso, garantías por vencer, el incremento que viene, un contrato por terminar, un depósito por devolver |
| «Hay una fuga» | Una orden de trabajo: quién paga según tu regla (desgaste natural o daño), cotización, proveedor de tu directorio, costo tomado del cargo que la pagó, garantía |
| «Ya toca el incremento» | La nueva renta con un porcentaje o con dos valores del INPC, redondeada como prefieras, vigente desde el aniversario. Prepara el aviso; tú lo envías |
| «El inquilino se va» | Lo que se devuelve del depósito después de cada descuento y su motivo |
| «¿Cuánto me dejó la casa este año?» | Renta cobrada, gastos que pagaste, neto, meses sin inquilino |

**No decide por ti.** Quién paga una reparación, si se cobra recargo, cómo sube la renta: son tus reglas,
guardadas con tus palabras. **No contacta a nadie ni paga nada**: prepara, tú envías.

**Con [facturacion](https://github.com/howware/facturacion) en la misma memoria**, una renta pagada por adelantado se
factura por el mes que paga, no con una regla fija: dos facturas en un mes, o ninguna, salen bien.

## Cómo funciona

| Parte | Aquí |
|---|---|
| Protocolo | [`skill/arrendamiento/SKILL.md`](skill/arrendamiento/SKILL.md): el ciclo del casero, las reglas, qué preguntar, en palabras claras |
| Herramienta | [`arrendamiento.py`](skill/arrendamiento/scripts/arrendamiento.py): aplicar pagos a meses, saldos y días de atraso, vencimientos, órdenes de trabajo, incrementos, el depósito, el reporte del año. Nunca abre un estado de cuenta ni un contrato |
| Adaptadores | [mxbank](https://github.com/howware/mx-bank-statement-reader) lee los estados de cuenta; la [memoria](https://github.com/howware/long-term-memory-for-AI) guarda todo con historia. Los estados se guardan como los registros comunes de mxbank, así que otros howwares en la misma memoria los comparten |

## Instalación

```bash
uv tool install git+https://github.com/howware/mx-bank-statement-reader   # si aún no tienes mxbank
git clone https://github.com/howware/long-term-memory-for-AI && python long-term-memory-for-AI/tools/install_skill.py
git clone https://github.com/howware/arrendamiento && python arrendamiento/tools/install_skill.py
```

Requiere Python 3.9+ (mxbank necesita 3.12+), project-memory 0.4.0+ y mxbank 0.2.0+, con tu llave de seudónimos
`MXBANK_KEY` definida una vez (ver el [README de mxbank](https://github.com/howware/mx-bank-statement-reader)). En el
`.claude/settings.json` de la carpeta, deja los documentos fuera del alcance del agente:

```json
{ "permissions": { "deny": ["Read(**/*.pdf)"] } }
```

Luego abre tu agente en esa carpeta y di: *«Quiero llevar aquí la renta de mi casa.»*

## Privacidad y límites

| Diseñado para quedarse en tu computadora | Lo que ve el agente de IA |
|---|---|
| Estados de cuenta, contratos, recibos | Depósitos y cargos: fecha, monto, tipo, descripción anonimizada, seudónimo de la cuenta |
| Nombres, números de cuenta y de tarjeta de los estados | Tus etiquetas de inmuebles e inquilinos («Casa Tijuana», «Inquilino A»), las condiciones del contrato, reparaciones y costos |
| El archivo de la memoria | Los contactos de proveedores, solo como tú los des; lo que escribes |

**Lo que no puede hacer ni garantizar:**
- La anonimización automática no es infalible; mxbank retiene su salida cuando detecta una fuga, y su código está
  abierto para revisarlo.
- No abrir documentos es una instrucción al agente; el permiso de negar de arriba reduce el riesgo, pero no es una
  barrera absoluta.
- Lo que ve el agente sale de tu computadora hacia tu proveedor de IA, bajo sus términos. La memoria no está cifrada.
- **No es asesoría legal ni fiscal.** Consulta a un abogado sobre el contrato y a tu contador sobre impuestos.
- **El INPC no se consulta en línea:** tú das sus valores (los publica el INEGI).
- **No prorratea** un primer o último mes incompleto en esta versión: la renta es por mes completo.
- **Sin notificaciones:** los pendientes aparecen cuando abres una conversación.
- **Aún no se ha probado en una conversación real** en ningún anfitrión; `howware.json` lista anfitriones solo
  cuando se prueban.

## Desarrollo

```bash
git clone https://github.com/howware/long-term-memory-for-AI ../long-term-memory-for-AI
git clone https://github.com/howware/mx-bank-statement-reader ../mx-bank-statement-reader   # para comparar mxbank_records.py
python -m unittest discover -s tests -v
git ls-files -z | xargs -0 python tools/check_private_data.py
```

Las pruebas corren contra una memoria temporal con depósitos y cargos sintéticos. `mxbank_records.py` es una copia
tal cual de `src/mxbank/records.py` de mxbank: se actualiza desde ahí, nunca a mano. Ver [AGENTS.md](AGENTS.md), y
cómo se construyó con `howware-builder`: [docs/building.md](docs/building.md).

## Licencia

[Apache 2.0](LICENSE). No es asesoría legal ni fiscal.
