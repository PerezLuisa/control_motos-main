"""
Acceso a Supabase con la clave secreta (solo en el backend, nunca en el navegador).

- Consultas simples:        db.tabla("cargas").select("*").eq("id", 1).execute().data
- Operaciones atómicas:     db.rpc("app_finalizar_carga", {...})   (funciones de BASE_FINAL.sql)
"""
import threading
from datetime import datetime, timezone

import httpx
from postgrest.exceptions import APIError
from supabase import create_client

VERSION_ESQUEMA = 6

_local = threading.local()  # un cliente por hilo (servidor web y cámaras)
_url = None
_clave = None


class ErrorConexion(Exception):
    pass


class ErrorBD(Exception):
    """Error devuelto por Supabase (p. ej. un RAISE de una función o un valor duplicado)."""

    def __init__(self, mensaje, codigo=None):
        super().__init__(mensaje)
        self.codigo = codigo

    @property
    def duplicado(self):
        return self.codigo == "23505"


def cliente():
    """Cliente de Supabase del hilo actual (base de datos y Storage)."""
    c = getattr(_local, "cliente", None)
    if c is None:
        c = _local.cliente = create_client(_url, _clave)
    return c


def tabla(nombre):
    return cliente().table(nombre)


def ejecutar(consulta):
    """Ejecuta una consulta de tabla y devuelve sus filas, traduciendo los errores."""
    try:
        return consulta.execute().data
    except APIError as err:
        raise ErrorBD(err.message or str(err), err.code) from err


def uno(consulta):
    filas = ejecutar(consulta.limit(1))
    return filas[0] if filas else None


def contar(consulta):
    try:
        return consulta.limit(1).execute().count or 0
    except APIError as err:
        raise ErrorBD(err.message or str(err), err.code) from err


def rpc(funcion, parametros=None):
    try:
        return cliente().rpc(funcion, parametros or {}).execute().data
    except APIError as err:
        raise ErrorBD(err.message or str(err), err.code) from err


def ahora():
    return datetime.now(timezone.utc).isoformat()


def iniciar(url, clave):
    """Guarda la conexión y comprueba que Supabase responde y que BASE_FINAL.sql está instalado."""
    global _url, _clave
    if not url.startswith("https://") or not clave:
        raise ErrorConexion("SUPABASE_URL debe empezar por https:// y SUPABASE_SECRET_KEY no puede estar vacía.")
    _url, _clave = url.rstrip("/"), clave

    try:
        version = rpc("app_esquema")
    except ErrorBD as err:
        if err.codigo == "PGRST202":  # la función no existe
            raise ErrorConexion(
                "Faltan las funciones del sistema en Supabase. Abra Supabase > SQL Editor, "
                "pegue BASE_FINAL.sql completo y ejecútelo."
            ) from err
        raise ErrorConexion(f"Supabase rechazó la conexión: {err}. Revise SUPABASE_SECRET_KEY.") from err
    except httpx.HTTPError as err:
        raise ErrorConexion(f"No se pudo contactar a Supabase ({err}). Revise SUPABASE_URL y la conexión a internet.") from err

    if version != VERSION_ESQUEMA:
        raise ErrorConexion(
            f"La base de datos tiene la versión {version} y la app necesita la {VERSION_ESQUEMA}. "
            "Ejecute de nuevo BASE_FINAL.sql en Supabase."
        )
