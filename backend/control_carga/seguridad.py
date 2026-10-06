"""Protección CSRF y utilidades de formato para las plantillas."""
import hmac
import secrets
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import abort, request, session

ZONA = ZoneInfo("America/Bogota")

# Cómo se muestra en pantalla cada resultado de lectura
NOMBRES_RESULTADO = {
    "VALIDA": "VÁLIDA",
    "DUPLICADA": "QR YA USADO",
    "SOBRANTE": "SOBRANTE",
    "OTRA_CARGA": "OTRA CARGA",
    "NO_PERTENECE": "NO PERTENECE",
}


def token_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def es_api():
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def _a_local(valor):
    """Fecha y hora en hora de Colombia. Acepta datetime o el texto ISO que devuelve Supabase."""
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor)
        except ValueError:
            return None
    if isinstance(valor, datetime):
        return valor.astimezone(ZONA) if valor.tzinfo else valor
    return None


def a_fecha(valor):
    """date desde un date o un texto 'AAAA-MM-DD'."""
    if isinstance(valor, str):
        try:
            return date.fromisoformat(valor[:10])
        except ValueError:
            return None
    return valor


def registrar(app):
    @app.before_request
    def verificar_csrf():
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        enviado = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        esperado = session.get("csrf", "")
        if not esperado or not hmac.compare_digest(enviado, esperado):
            abort(400, "Token de seguridad inválido. Recargue la página.")

    app.jinja_env.globals["csrf_token"] = token_csrf
    app.jinja_env.globals["nombres_resultado"] = NOMBRES_RESULTADO

    @app.template_filter("hora")
    def filtro_hora(valor):
        valor = _a_local(valor)
        return valor.strftime("%I:%M:%S %p").lower() if valor else "—"

    @app.template_filter("fechahora")
    def filtro_fechahora(valor):
        valor = _a_local(valor)
        return valor.strftime("%d/%m/%Y %I:%M %p").lower() if valor else "—"

    @app.template_filter("fecha")
    def filtro_fecha(valor):
        valor = a_fecha(valor)
        return valor.strftime("%d/%m/%Y") if valor else "—"


def hoy():
    return datetime.now(ZONA).date()


def hora_local(valor):
    valor = _a_local(valor)
    return valor.strftime("%I:%M:%S %p").lower() if valor else None
