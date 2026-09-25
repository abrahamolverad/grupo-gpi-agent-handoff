# Puesta en marcha

## Preparar el cálculo

1. Clone este repositorio en un equipo administrado por Grupo GPI.
2. Ejecute `python3 -m unittest discover -s tests`.
3. Copie `examples/policy.synthetic.json` a `policy.local.json` y sustituya todos los valores por los parámetros comerciales aprobados. El archivo local queda excluido de Git.
4. Verifique una propuesta de prueba con `python3 -m gpi_handoff.cli policy.local.json examples/proposal.synthetic.json`.
5. Compare el resultado con casos aprobados por el responsable comercial antes de usarlo en atención real.

## Conectar una respuesta del agente

Las instrucciones de `agent/AGENTS.md` indican al agente cómo extraer una propuesta estructurada del contrato. El programa toma el bloque de la respuesta, valida los datos y calcula los importes:

```sh
python3 -m gpi_handoff.cli policy.local.json examples/respuesta.synthetic.txt agent-reply
```

El operador debe mostrar al cliente únicamente la respuesta visible y los importes validados, después de revisar la fuente contractual. No debe mostrar el bloque `gpi_quote_snapshot` como parte del mensaje final.

## Control de cambios

El responsable designado por Grupo GPI conserva la política comercial y autoriza sus cambios. Antes de activar una versión nueva, registra la versión de la política, ejecuta las pruebas, compara casos conocidos y confirma la aprobación humana. Los expedientes de clientes, las credenciales y los parámetros comerciales reales permanecen en sus sistemas autorizados.

## Activar el acceso de consulta

El acceso al portal existente de TheAIGNC se gestiona mediante invitaciones y fuera de este repositorio. Los roles, la autenticación y el alcance se confirman en el portal; este repositorio no crea acceso ni asigna permisos.

El repositorio ejecuta el cálculo y valida la propuesta. Los canales de comunicación, la recepción de documentos y el servicio que atiende mensajes requieren una instalación elegida y operada por Grupo GPI. La ruta local independiente se documenta en `RUNTIME_LOCAL_CLIENTE.md` y no ofrece esos canales.
