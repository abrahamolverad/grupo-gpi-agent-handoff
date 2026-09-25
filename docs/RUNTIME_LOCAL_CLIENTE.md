# Runtime local independiente de Grupo GPI

Esta carpeta ofrece una ruta que Grupo GPI puede ejecutar y operar en su propio equipo. Es una adición independiente al cálculo determinista del repositorio; no representa ni reproduce el runtime actualmente desplegado de TheAIGNC ni requiere código, URL, credenciales, base de datos o infraestructura de TheAIGNC.

## Qué hace

- Se inicia en `127.0.0.1` por defecto y expone una pantalla local para pegar texto contractual o cargar un PDF.
- Guarda conversaciones, propuestas y el historial de cálculo en `customer_data/gpi-local.sqlite3`. Los PDF se guardan sólo dentro de `customer_data/documents/` con permisos de propietario.
- Calcula únicamente con `gpi_handoff.quote` y la política comercial local indicada por Grupo GPI.
- Marca cada resultado como `revision_humana_obligatoria`. No existe una acción para enviar correo, presentar una oferta final, emitir una fianza o cambiar el resultado calculado.
- El botón **Ver historial local** muestra el registro de la conversación actual desde SQLite en el mismo equipo.

## Arranque sin red

1. Use Python 3.11 o posterior y copie una política comercial aprobada a `policy.local.json`. No use los valores sintéticos como tarifas reales.
2. Verifique el paquete: `python3 -m unittest discover -s tests`.
3. Inicie el servicio: `python3 -m gpi_handoff.local_app --policy policy.local.json`.
4. Abra `http://127.0.0.1:8787` en el mismo equipo. Pegue el texto contractual y calcule una propuesta JSON, o configure el adaptador opcional descrito abajo.

El servidor rechaza enlaces que no sean `127.0.0.1`, `::1` o `localhost`. La carpeta `customer_data/`, las políticas locales, PDFs, SQLite y `.env` están ignorados por Git.

## PDF

La pantalla acepta PDF de hasta 10 MB. Para extraer texto localmente necesita el comando `pdftotext` instalado en el equipo. Un PDF escaneado o un sistema sin ese comando se conserva localmente, pero no puede crear una propuesta hasta que el operador pegue texto verificable o use una herramienta de OCR aprobada por Grupo GPI. El runtime nunca sube un PDF por su cuenta.

## Modelo BYOK opcional

Por defecto no se llama a ningún modelo ni servicio externo. El operador puede configurar explícitamente un endpoint compatible con OpenAI mediante variables de entorno propias:

```sh
export GPI_MODEL_PROVIDER=openai_responses
export GPI_MODEL_BASE_URL=https://api.openai.com
export GPI_MODEL_NAME=nombre-del-modelo
export GPI_MODEL_API_KEY='clave-propia'
python3 -m gpi_handoff.local_app --policy policy.local.json
```

El adaptador envía una solicitud `POST /v1/responses` con `model` e `input`, usando la clave BYOK mediante `Authorization: Bearer`. Sólo permite HTTPS, excepto un endpoint que escuche en `localhost` para pruebas. Al pulsar **Proponer con modelo configurado**, el texto contractual se transmite a la cuenta del proveedor elegida por Grupo GPI; esa llamada puede generar cargos de API. En el modo offline predeterminado no se transmite texto ni PDF fuera del equipo. La clave se usa en memoria para la solicitud, no se guarda en SQLite ni se escribe en los logs. Grupo GPI debe evaluar por separado el contrato, residencia de datos, retención y coste de OpenAI. El nombre del modelo lo elige Grupo GPI en `GPI_MODEL_NAME`; el runtime no impone uno ni hace solicitudes durante la instalación o las pruebas.

## Límite operativo

Este proyecto es una herramienta local de borrador. No es un servicio hospedado 24/7, no ofrece redundancia, monitoreo, colas, gestión de usuarios, respaldo administrado, SLA ni integración con correo o emisión. Grupo GPI conserva la responsabilidad de revisar el contrato, la política y la precotización antes de cualquier comunicación o emisión.
