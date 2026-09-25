# Operación y control

## Preparar una propuesta

La entrada es un JSON con `contratista`, `beneficiario`, `objeto` y una lista `fianzas`. Cada fianza requiere `tipo`, `monto`, `vigencia_meses` y `fuente`. El campo `fuente` contiene la cláusula o evidencia contractual que sustenta esa fianza. El ejemplo en `examples/proposal.synthetic.json` muestra el formato.

El agente puede extraer y proponer esos datos, pero el cálculo se ejecuta con `gpi_handoff.cli`. El programa rechaza importes no positivos, vigencias fuera de rango, tipos duplicados y fianzas laborales sin cláusula expresa.

## Revisar el resultado

1. Verifique nombre de contratista, beneficiario y objeto contra el contrato recibido.
2. Compare cada fianza, monto, vigencia y cláusula fuente con el documento original.
3. Confirme que la política comercial local corresponde a la versión aprobada.
4. Ejecute el cálculo y revise el JSON de salida.
5. Someta la precotización al responsable humano antes de presentarla o emitir cualquier documento vinculante.

## Cambiar la política

Edite únicamente el archivo local de parámetros. Conserve una copia aprobada y registre fecha, responsable y versión en su sistema de control documental. Ejecute las pruebas del repositorio y compare casos conocidos antes de poner la nueva política en uso.

## Acceso al agente

Una instalación de TheAIGNC puede ofrecer acceso a actividad autorizada del agente cuando Grupo GPI la haya contratado y configurado. El administrador asigna el acceso al correo y agente correctos. La autenticación multifactor se aplica sólo si la política de esa instalación lo exige. El alcance de permisos se verifica con una consulta permitida al agente asignado y consultas denegadas a otros agentes y organizaciones.

Para cambiar instrucciones, modelo o canales de atención, use los controles autorizados de la instalación que opera el agente y conserve un registro del cambio. No coloque contraseñas, tokens, pólizas, documentos de clientes ni expedientes en este repositorio. El runtime local descrito en `RUNTIME_LOCAL_CLIENTE.md` no depende de TheAIGNC.
