# Estándares para agentes (OpenCode) en los proyectos de Alfonso

Claude actúa como arquitecto y revisor; OpenCode ejecuta tareas acotadas.

## SIEMPRE
- Código completo y funcional, sin "TODO" ni fragmentos con "...".
- Tests para toda lógica nueva; ejecutarlos y dejar el resultado en la respuesta.
- Respetar la estructura y convenciones ya existentes del proyecto.
- Comentarios y textos de interfaz en español; identificadores en inglés.
- Responder al final con: archivos tocados, comandos ejecutados y resultado de los tests.

## NUNCA
- Hacer git push, borrar archivos fuera del alcance de la tarea ni reescribir historial.
- Añadir dependencias no pedidas sin justificarlo.
- Introducir secretos, claves o datos personales en el código.
- Tocar datos de clientes, expedientes ni el Gestor Legal (prohibido para modelos gratuitos).
