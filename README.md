# Herramientas del agente de Grupo GPI

Este repositorio contiene el cálculo determinista de precotizaciones de fianzas y una interfaz de línea de comandos para ejecutarlo. Las cifras comerciales se leen de un archivo local administrado por Grupo GPI. El modelo propone los datos del contrato; el programa valida cada fianza y calcula los importes.

## Requisitos

- Python 3.11 o posterior.
- Parámetros comerciales vigentes, aprobados por Grupo GPI.
- Una propuesta estructurada con tipo, monto, vigencia y cláusula fuente por fianza.

## Primera ejecución

Desde la carpeta del repositorio:

```sh
python3 -m unittest discover -s tests
python3 -m gpi_handoff.cli examples/policy.synthetic.json examples/proposal.synthetic.json
```

Los dos archivos de `examples/` contienen cifras y nombres inventados para probar la instalación. Para operar con las condiciones de Grupo GPI, coloque su política comercial en `policy.local.json`. Git ignora ese archivo.

```sh
python3 -m gpi_handoff.cli policy.local.json propuesta.json
```

La salida es JSON. Cada fianza incluye prima calculada, prima aplicable, derechos, gastos, impuesto y total. El campo `estado` indica que se trata de una estimación sujeta a revisión.

Si el agente entrega un bloque `<gpi_quote_snapshot>` dentro de su respuesta, puede procesarlo así:

```sh
python3 -m gpi_handoff.cli policy.local.json respuesta.txt agent-reply
```

El programa separa la respuesta visible del bloque estructurado y calcula la cotización. Una propuesta sin datos del contrato, cláusula fuente o parámetros comerciales válidos se rechaza.

## Contenido

| Ruta | Uso |
| --- | --- |
| `gpi_handoff/quote.py` | Validación y cálculo determinista |
| `gpi_handoff/cli.py` | Ejecución local con archivos JSON |
| `tests/test_quote.py` | Pruebas con información ficticia |
| `examples/` | Formatos de entrada y política de prueba |
| `agent/AGENTS.md` | Instrucciones de extracción y revisión para el agente |
| `docs/OPERACION.md` | Flujo de control y revisión |
| `docs/CONFIGURACION.md` | Campos de la política comercial |

## Control de la operación

Grupo GPI conserva su política comercial fuera del repositorio público. El equipo autorizado puede actualizarla sin cambiar las instrucciones del modelo. Cada cambio debe pasar las pruebas y una revisión con casos representativos antes de usarse en atención a clientes. Ninguna precotización emite una fianza por sí sola.
