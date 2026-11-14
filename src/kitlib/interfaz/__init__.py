"""Interfaz visual local del kit: un servidor HTTP en 127.0.0.1 (biblioteca estándar) que ejecuta
los comandos del kit y muestra en el navegador lo que el kit escribió.

El núcleo del kit no importa este paquete: `kitlib.cli` solo lo carga cuando se pide el comando
`interfaz`. Módulos:
- explicaciones: etiqueta y explicación en español simple por código de incidencia.
- puente: toda la lógica (carpetas permitidas, ejecución del kit, JSON listo para pintar).
- servidor: el servidor HTTP, el token de sesión y las comprobaciones de cada petición.
- estaticos/: la página (HTML, CSS y JS), que solo pinta el JSON del puente.
"""
