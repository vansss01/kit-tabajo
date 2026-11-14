"""Servidor HTTP local de la interfaz: biblioteca estándar, solo 127.0.0.1, un token aleatorio por sesión.

Comprobaciones de cada petición (con pruebas en tests/test_interfaz.py):
- Cabecera Host: solo `127.0.0.1:PUERTO` o `localhost:PUERTO` (el puerto propio).
- Token: la página se abre con `/?token=...`; las llamadas a `/api/...` lo envían en la cabecera
  `X-Kit-Token` (o en la consulta). Sin token o con otro token: 403.
- Sin cabeceras CORS: ninguna otra página del navegador puede leer las respuestas.
- Lo que cambia algo (subir, ejecutar, abrir) solo por POST con cuerpo JSON (`Content-Type: application/json`).
- Cuerpo acotado (límite de subida más el envoltorio base64).
El servidor se cierra con Ctrl+C; no queda como servicio ni se inicia solo.
"""
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from kitlib.interfaz.puente import LIMITE_SUBIDA, Ocupado, PeticionInvalida, Puente

ESTATICOS = Path(__file__).resolve().parent / "estaticos"
TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}
LIMITE_CUERPO = LIMITE_SUBIDA * 4 // 3 + 4096
RUTAS_POST = ("/api/subir", "/api/ejecutar", "/api/abrir")
POLITICA_CONTENIDO = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                      "img-src 'self' data:; base-uri 'none'; form-action 'none'")


class Servidor:
    def __init__(self, puente=None, puerto=0, token=None):
        self.puente = puente or Puente()
        self.token = token or secrets.token_urlsafe(24)
        servidor = self

        class Manejador(_Manejador):
            servidor_kit = servidor

        self.httpd = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
        self.httpd.daemon_threads = True
        self.puerto = self.httpd.server_address[1]
        self._hilo: threading.Thread | None = None
        self._sirviendo = False

    @property
    def url(self):
        return f"http://127.0.0.1:{self.puerto}/?token={self.token}"

    def hosts_permitidos(self):
        return {f"127.0.0.1:{self.puerto}", f"localhost:{self.puerto}"}

    def servir(self):
        """Bloquea hasta Ctrl+C."""
        self._sirviendo = True
        try:
            self.httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            self.cerrar()

    def servir_en_hilo(self):
        self._sirviendo = True
        self._hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True, name="kit-interfaz")
        self._hilo.start()
        return self

    def cerrar(self):
        if self._sirviendo:  # shutdown() espera a serve_forever: sin él se bloquearía
            self._sirviendo = False
            self.httpd.shutdown()
        self.httpd.server_close()


class _Manejador(BaseHTTPRequestHandler):
    servidor_kit: Servidor
    server_version = "KitTabajo"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - firma de la clase base
        return  # sin registro por terminal: la URL lleva el token

    # ------------------------------------------------------------------ respuestas

    def _enviar(self, status, cuerpo, tipo="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", POLITICA_CONTENIDO)
        # Una petición por conexión: si se rechaza sin leer el cuerpo, sus bytes no se leen como otra petición.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self.wfile.write(cuerpo)

    def _json(self, status, valor):
        self._enviar(status, json.dumps(valor, ensure_ascii=False).encode("utf-8"))

    def _error(self, status, mensaje, codigo=None):
        self._json(status, {"error": mensaje, "codigo": codigo or {400: "peticion_invalida", 403: "token_invalido",
                                                                   404: "no_encontrado", 405: "metodo_no_admitido",
                                                                   409: "ocupado", 413: "demasiado_grande"}.get(
            status, "error")})

    # ------------------------------------------------------------------ comprobaciones

    def _host_valido(self):
        return (self.headers.get("Host") or "") in self.servidor_kit.hosts_permitidos()

    def _token_valido(self, query):
        sent = self.headers.get("X-Kit-Token") or (query.get("token") or [""])[0]
        return bool(sent) and secrets.compare_digest(sent, self.servidor_kit.token)

    def _preparar(self):
        parts = urlsplit(self.path)
        query = parse_qs(parts.query, keep_blank_values=False)
        if not self._host_valido():
            self._error(400, "Cabecera Host no permitida: la interfaz solo atiende a 127.0.0.1", "host_no_permitido")
            return None, None
        if not self._token_valido(query):
            self._error(403, "Falta el token de sesión o no coincide. Abre la URL que mostró ./kit interfaz")
            return None, None
        return parts.path, query

    def _cuerpo_json(self):
        if not (self.headers.get("Content-Type") or "").split(";")[0].strip() == "application/json":
            raise PeticionInvalida("El cuerpo debe ser JSON (Content-Type: application/json)")
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            raise PeticionInvalida("Content-Length inválido") from None
        if length <= 0:
            raise PeticionInvalida("Cuerpo vacío")
        if length > LIMITE_CUERPO:
            raise PeticionInvalida("Cuerpo demasiado grande", 413)
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            raise PeticionInvalida("Cuerpo JSON inválido") from None
        if not isinstance(value, dict):
            raise PeticionInvalida("El cuerpo JSON debe ser un objeto")
        return value

    # ------------------------------------------------------------------ rutas

    def do_GET(self):
        path, query = self._preparar()
        if path is None:
            return
        puente = self.servidor_kit.puente
        try:
            if path == "/":
                return self._pagina()
            if path.startswith("/estaticos/"):
                return self._estatico(path[len("/estaticos/"):])
            if path == "/api/estado":
                return self._json(200, puente.estado())
            if path == "/api/archivos":
                return self._json(200, {"archivos": puente.archivos()})
            if path == "/api/inspeccionar":
                return self._json(200, puente.inspeccionar(_uno(query, "ruta")))
            if path == "/api/recetas":
                return self._json(200, {"recetas": puente.recetas()})
            if path == "/api/vista_previa":
                return self._json(200, puente.vista_previa(_uno(query, "archivo"), _uno(query, "receta")))
            if path == "/api/resultado":
                return self._json(200, puente.resultado(_uno(query, "ejecucion") or None))
            if path in RUTAS_POST:
                return self._error(405, "Esta acción solo se admite por POST con cuerpo JSON")
            if path.startswith("/api/"):
                return self._error(404, "Ruta de la API desconocida")
            return self._error(404, "No encontrado")
        except PeticionInvalida as exc:
            return self._error(exc.http, str(exc))

    def do_POST(self):
        path, _ = self._preparar()
        if path is None:
            return
        puente = self.servidor_kit.puente
        try:
            body = self._cuerpo_json()
            if path == "/api/subir":
                return self._json(201, puente.subir(body.get("nombre"), body.get("contenido_base64")))
            if path == "/api/ejecutar":
                return self._json(202, puente.iniciar_ejecucion(body.get("archivo"), body.get("receta")))
            if path == "/api/abrir":
                return self._json(200, puente.abrir(body.get("ejecucion"), body.get("archivo")))
            if path in ("/api/estado", "/api/archivos", "/api/inspeccionar", "/api/recetas", "/api/vista_previa",
                        "/api/resultado"):
                return self._error(405, "Esta ruta solo admite GET")
            return self._error(404, "Ruta de la API desconocida")
        except Ocupado as exc:
            return self._error(409, str(exc))
        except PeticionInvalida as exc:
            return self._error(exc.http, str(exc))

    def do_PUT(self):
        self._error(405, "Método no admitido")

    do_DELETE = do_PATCH = do_PUT

    def _pagina(self):
        html = (ESTATICOS / "interfaz.html").read_text(encoding="utf-8")
        html = html.replace("{{TOKEN}}", self.servidor_kit.token)
        self._enviar(200, html.encode("utf-8"), TIPOS[".html"])

    def _estatico(self, nombre):
        if "/" in nombre or nombre.startswith(".") or Path(nombre).suffix not in TIPOS:
            return self._error(404, "No encontrado")
        path = ESTATICOS / nombre
        if not path.is_file():
            return self._error(404, "No encontrado")
        self._enviar(200, path.read_bytes(), TIPOS[path.suffix])


def _uno(query, nombre):
    values = query.get(nombre) or [""]
    return values[0]


def run(args):
    if not 0 <= args.puerto <= 65535:
        raise ValueError("--puerto debe estar entre 0 y 65535")
    servidor = Servidor(Puente(), puerto=args.puerto)
    print("Interfaz del kit en: " + servidor.url)
    print("Solo este equipo (127.0.0.1). Cierra con Ctrl+C. Manual: docs/tools/interfaz.md")
    if not args.sin_abrir:
        webbrowser.open(servidor.url)
    servidor.servir()
    print("Interfaz cerrada.")
    return 0
