"""
Inicio de sesión, registro (empleado / administrador) y control de sesión única.

Cómo funciona la sesión única:
  - Al entrar se crea una fila en `sesiones` (activa). El token va en la cookie y
    en la base solo se guarda su hash SHA-256 (si alguien lee la base, no puede
    suplantar la sesión). La IP y el navegador se guardan cifrados.
  - La cookie no tiene fecha de expiración: el navegador la borra al cerrarse.
  - Cada página abierta envía un "latido" cada 30 s que renueva `ultima_actividad`.
  - Si no llega latido en SESION_TIMEOUT_SEG (navegador cerrado), la sesión expira.
  - Mientras haya una sesión activa, el mismo usuario NO puede entrar desde otro
    dispositivo (índice único parcial + app_abrir_sesion en BASE_FINAL.sql).

Registro como administrador: exige la clave del super administrador (tabla
super_admin, guardada con hash). Hay un límite de intentos fallidos por IP.
"""
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .cifrado import cifrar, descifrar, hash_token, huella
from .seguridad import es_api, hora_local

bp = Blueprint("auth", __name__)

_HASH_FALSO = generate_password_hash("clave-inexistente")
_PATRON_USUARIO = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
ROLES = {"empleado": "Empleado", "admin": "Administrador"}

AVISOS_CIERRE = {
    "EXPIRADA": "Su sesión expiró por inactividad o porque se cerró el navegador. Inicie sesión de nuevo.",
    "CERRADA_POR_ADMIN": "Un administrador cerró su sesión.",
    "USUARIO_DESACTIVADO": "Su usuario fue desactivado. Contacte al administrador.",
    "LOGOUT": "Sesión cerrada.",
}

# Intentos fallidos de la clave del super admin, por IP (ventana de 10 minutos)
_MAX_INTENTOS = 5
_VENTANA_SEG = 600
_fallos = defaultdict(deque)
_fallos_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Carga del usuario en cada petición
# ---------------------------------------------------------------------------
def registrar(app):
    @app.before_request
    def cargar_usuario():
        g.usuario = None
        if request.endpoint == "static":
            return
        token = session.get("token")
        if not token:
            return

        # Valida, expira o renueva la sesión en una sola llamada a Supabase
        r = db.rpc("app_validar_sesion", {
            "p_token_hash": hash_token(token),
            "p_timeout": current_app.config["SESION_TIMEOUT_SEG"],
        })
        if r["estado"] != "ok":
            session.clear()
            # El aviso queda guardado y se muestra en la pantalla de inicio de sesión
            flash(AVISOS_CIERRE.get(r.get("motivo"), "Su sesión fue cerrada. Inicie sesión de nuevo."), "aviso")
            return
        g.usuario = r["usuario"]

    @app.context_processor
    def usuario_en_plantillas():
        return {"usuario_actual": g.get("usuario"), "nombres_rol": ROLES}


def login_requerido(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if g.usuario is None:
            if es_api():
                return jsonify(error="sesion", mensaje="Debe iniciar sesión"), 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?") if request.method == "GET" else None))
        return vista(*args, **kwargs)

    return envoltura


def admin_requerido(vista):
    @wraps(vista)
    @login_requerido
    def envoltura(*args, **kwargs):
        if g.usuario["rol"] != "admin":
            abort(403)
        return vista(*args, **kwargs)

    return envoltura


def empleado_requerido(vista):
    """La operación de las cargas es solo de los empleados; el administrador solo supervisa."""
    @wraps(vista)
    @login_requerido
    def envoltura(*args, **kwargs):
        if g.usuario["rol"] != "empleado":
            if es_api():
                return jsonify(resultado="ERROR", mensaje="Esta acción la realizan los empleados."), 403
            abort(403)
        return vista(*args, **kwargs)

    return envoltura


def cerrar_sesion(sesion_id, motivo):
    db.rpc("app_cerrar_sesion", {"p_sesion_id": sesion_id, "p_motivo": motivo})


def _abrir_sesion(usuario_id):
    """Devuelve (token, None) si pudo abrir sesión, o (None, sesion_activa) si ya hay otra."""
    token = secrets.token_urlsafe(32)
    r = db.rpc("app_abrir_sesion", {
        "p_usuario_id": usuario_id,
        "p_token_hash": hash_token(token),
        "p_ip": cifrar(request.remote_addr),
        "p_user_agent": cifrar((request.user_agent.string or "")[:300]),
        "p_timeout": current_app.config["SESION_TIMEOUT_SEG"],
    })
    return (token, None) if r["ok"] else (None, r)


# ---------------------------------------------------------------------------
# Clave del super administrador
# ---------------------------------------------------------------------------
def _intentos_recientes(ip):
    ahora = time.monotonic()
    cola = _fallos[ip]
    while cola and ahora - cola[0] > _VENTANA_SEG:
        cola.popleft()
    return cola


def verificar_superadmin(clave):
    """Devuelve (True, None) si la clave es correcta, o (False, mensaje de error)."""
    ip = request.remote_addr or "?"
    with _fallos_lock:
        if len(_intentos_recientes(ip)) >= _MAX_INTENTOS:
            return False, "Demasiados intentos fallidos. Espere 10 minutos e intente de nuevo."

    sa = db.uno(db.tabla("super_admin").select("password_hash").eq("usuario", "superadmin"))
    if sa and clave and check_password_hash(sa["password_hash"], clave):
        return True, None
    if not sa:
        check_password_hash(_HASH_FALSO, clave or "")

    with _fallos_lock:
        cola = _intentos_recientes(ip)
        cola.append(time.monotonic())
        restantes = _MAX_INTENTOS - len(cola)
    if restantes <= 0:
        return False, "Demasiados intentos fallidos. Espere 10 minutos e intente de nuevo."
    return False, f"Contraseña del super administrador incorrecta. Le quedan {restantes} intento(s)."


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario:
        return redirect(url_for("principal.inicio"))

    if request.method == "POST":
        nombre_usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "")
        u = db.uno(db.tabla("usuarios").select("id, password_hash, activo").eq("usuario", nombre_usuario.lower()))

        if not u:
            check_password_hash(_HASH_FALSO, clave)  # mismo tiempo de respuesta exista o no el usuario
            flash("Usuario o contraseña incorrectos.", "error")
        elif not check_password_hash(u["password_hash"], clave):
            flash("Usuario o contraseña incorrectos.", "error")
        elif not u["activo"]:
            flash("Su usuario está desactivado. Contacte al administrador.", "error")
        else:
            token, activa = _abrir_sesion(u["id"])
            if activa:
                minutos = max(1, current_app.config["SESION_TIMEOUT_SEG"] // 60)
                flash(
                    f"Este usuario ya tiene una sesión activa en otro dispositivo "
                    f"(IP {descifrar(activa['ip']) or 'desconocida'}, desde las {hora_local(activa['creada_en'])}). "
                    f"Cierre sesión en ese equipo, o espere {minutos} min después de cerrar su navegador.",
                    "error",
                )
            else:
                session.clear()
                session["token"] = token
                siguiente = request.args.get("next") or ""
                if not siguiente.startswith("/") or siguiente.startswith("//"):
                    siguiente = url_for("principal.inicio")
                rol = db.uno(db.tabla("usuarios").select("rol").eq("id", u["id"]))["rol"]
                if rol == "admin":
                    siguiente = url_for("admin.panel")
                return redirect(siguiente)

        return render_template("login.html", usuario=nombre_usuario), 401

    return render_template("login.html")


@bp.route("/registro", methods=["GET", "POST"])
def registro():
    if g.usuario:
        return redirect(url_for("principal.inicio"))

    datos = {k: request.form.get(k, "").strip() for k in ("nombre", "usuario", "email")}
    datos["rol"] = request.form.get("rol", "empleado")
    if request.method == "POST":
        clave = request.form.get("clave", "")
        errores = []
        if len(datos["nombre"]) < 3:
            errores.append("Escriba su nombre completo.")
        if not _PATRON_USUARIO.match(datos["usuario"]):
            errores.append("El usuario debe tener de 3 a 30 caracteres (letras, números, punto, guion).")
        if datos["email"] and "@" not in datos["email"]:
            errores.append("El correo no es válido.")
        if len(clave) < 8:
            errores.append("La contraseña debe tener al menos 8 caracteres.")
        if clave != request.form.get("clave2", ""):
            errores.append("Las contraseñas no coinciden.")
        if datos["rol"] not in ROLES:
            errores.append("Seleccione un tipo de usuario válido.")
        elif datos["rol"] == "admin" and not errores:
            ok, error = verificar_superadmin(request.form.get("clave_superadmin", ""))
            if not ok:
                errores.append(error)

        if not errores:
            r = db.rpc("app_registrar_usuario", {
                "p_nombre": datos["nombre"],
                "p_usuario": datos["usuario"],
                "p_email": cifrar(datos["email"]),
                "p_email_hash": huella(datos["email"]),
                "p_password_hash": generate_password_hash(clave),
                "p_rol": datos["rol"],
            })
            if r["ok"]:
                flash(f"Cuenta creada como {ROLES[r['rol']].upper()}. Ya puede iniciar sesión.", "ok")
                return redirect(url_for("auth.login"))
            errores.append("Ese usuario o correo ya está registrado.")

        for e in errores:
            flash(e, "error")
        return render_template("registro.html", **datos), 400

    return render_template("registro.html", **datos)


@bp.post("/api/registro/superadmin")
def api_verificar_superadmin():
    """Lo usa la ventana del formulario de registro antes de enviar como administrador."""
    ok, error = verificar_superadmin((request.get_json(silent=True) or {}).get("clave", ""))
    return jsonify(ok=ok, mensaje=error), (200 if ok else 403)


@bp.post("/logout")
def logout():
    if g.usuario:
        cerrar_sesion(g.usuario["sesion_id"], "LOGOUT")
    session.clear()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("auth.login"))


@bp.post("/api/latido")
@login_requerido
def latido():
    """El navegador lo llama cada 30 s para mantener viva la sesión."""
    pendientes = 0
    if g.usuario["rol"] == "empleado":
        pendientes = db.contar(db.tabla("alertas").select("id", count="exact").eq("leida", False))
    return jsonify(ok=True, alertas_pendientes=pendientes)
