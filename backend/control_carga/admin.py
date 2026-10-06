from flask import Blueprint, Response, flash, g, redirect, render_template, request, url_for
from werkzeug.security import generate_password_hash

from . import db
from .auth import admin_requerido
from .camaras import gestor, imagen_mensaje
from .cifrado import cifrar, descifrar

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/")
@admin_requerido
def panel():
    usuarios = db.ejecutar(db.tabla("v_usuarios_admin").select("*").order("creado_en"))
    for u in usuarios:
        u["email"] = descifrar(u["email"])
        u["ip"] = descifrar(u["ip"])
    camaras = db.ejecutar(db.tabla("v_camaras").select("*").order("nombre"))
    for k in camaras:
        k["fuente"] = descifrar(k["fuente"])
        k["vivo"] = gestor.estado(k["id"])
    return render_template("admin.html", usuarios=usuarios, camaras=camaras)


# -- usuarios -----------------------------------------------------------------
@bp.post("/usuarios/<int:usuario_id>")
@admin_requerido
def usuario(usuario_id):
    accion = request.form.get("accion")
    if usuario_id == g.usuario["id"]:
        flash("No puede cambiar su propio rol ni desactivarse.", "error")
        return redirect(url_for("admin.panel"))

    if accion in ("admin", "empleado"):
        db.ejecutar(db.tabla("usuarios").update({"rol": accion}).eq("id", usuario_id))
        flash("Rol actualizado.", "ok")
    elif accion in ("activar", "desactivar"):
        activo = accion == "activar"
        db.rpc("app_set_usuario_activo", {"p_usuario_id": usuario_id, "p_activo": activo})
        flash("Usuario activado." if activo else "Usuario desactivado y su sesión cerrada.", "ok")
    return redirect(url_for("admin.panel"))


@bp.post("/usuarios/<int:usuario_id>/clave")
@admin_requerido
def cambiar_clave(usuario_id):
    """El administrador asigna una contraseña nueva a un EMPLEADO (nunca a otro administrador)."""
    u = db.uno(db.tabla("usuarios").select("id, nombre, rol").eq("id", usuario_id))
    clave = request.form.get("clave", "")
    if not u or u["rol"] != "empleado":
        flash("Solo se puede cambiar la contraseña de los empleados.", "error")
    elif len(clave) < 8:
        flash("La contraseña nueva debe tener al menos 8 caracteres.", "error")
    elif clave != request.form.get("clave2", ""):
        flash("Las contraseñas no coinciden.", "error")
    else:
        db.ejecutar(db.tabla("usuarios").update({"password_hash": generate_password_hash(clave)}).eq("id", usuario_id))
        # Si tenía una sesión abierta, se cierra: debe entrar con la contraseña nueva
        activa = db.uno(db.tabla("sesiones").select("id").eq("usuario_id", usuario_id).eq("activa", True))
        if activa:
            db.rpc("app_cerrar_sesion", {"p_sesion_id": activa["id"], "p_motivo": "CERRADA_POR_ADMIN"})
        flash(f"Contraseña de {u['nombre']} actualizada. Debe iniciar sesión con la nueva.", "ok")
    return redirect(url_for("admin.panel"))


@bp.post("/sesiones/<int:sesion_id>/cerrar")
@admin_requerido
def cerrar_sesion(sesion_id):
    db.rpc("app_cerrar_sesion", {"p_sesion_id": sesion_id, "p_motivo": "CERRADA_POR_ADMIN"})
    flash("Sesión cerrada. El usuario ya puede entrar desde otro equipo.", "ok")
    return redirect(url_for("admin.panel"))


# -- cámaras ------------------------------------------------------------------
def _datos_camara():
    return {
        "nombre": request.form.get("nombre", "").strip(),
        "fuente": request.form.get("fuente", "").strip(),
        "ubicacion": request.form.get("ubicacion", "").strip() or None,
    }


@bp.post("/camaras")
@admin_requerido
def crear_camara():
    datos = _datos_camara()
    if not datos["nombre"] or not datos["fuente"]:
        flash("Escriba el nombre y la fuente de la cámara.", "error")
        return redirect(url_for("admin.panel"))
    try:
        db.ejecutar(db.tabla("camaras").insert({**datos, "fuente": cifrar(datos["fuente"])}))
        flash("Cámara agregada.", "ok")
    except db.ErrorBD as err:
        flash("Ya existe una cámara con ese nombre." if err.duplicado else str(err), "error")
    return redirect(url_for("admin.panel"))


@bp.post("/camaras/<int:camara_id>")
@admin_requerido
def editar_camara(camara_id):
    en_uso = db.uno(db.tabla("cargas").select("codigo_contrato").eq("camara_id", camara_id).eq("estado", "EN_CARGA"))
    if request.form.get("accion") == "eliminar":
        if en_uso:
            flash(f"La cámara está en uso por el contrato {en_uso['codigo_contrato']}.", "error")
        else:
            db.ejecutar(db.tabla("camaras").delete().eq("id", camara_id))
            flash("Cámara eliminada.", "ok")
        return redirect(url_for("admin.panel"))

    datos = {**_datos_camara(), "activa": request.form.get("activa") == "on"}
    if not datos["nombre"] or not datos["fuente"]:
        flash("El nombre y la fuente de la cámara no pueden quedar vacíos.", "error")
        return redirect(url_for("admin.panel"))
    try:
        db.ejecutar(db.tabla("camaras").update({**datos, "fuente": cifrar(datos["fuente"])}).eq("id", camara_id))
        flash("Cámara actualizada." + (" Se aplicará al iniciar la próxima carga." if en_uso else ""), "ok")
    except db.ErrorBD as err:
        flash("Ya existe una cámara con ese nombre." if err.duplicado else str(err), "error")
    return redirect(url_for("admin.panel"))


@bp.get("/camaras/<int:camara_id>/prueba.jpg")
@admin_requerido
def probar_camara(camara_id):
    cam = db.uno(db.tabla("camaras").select("fuente").eq("id", camara_id))
    jpeg = gestor.captura(descifrar(cam["fuente"]), camara_id) if cam else None
    if not jpeg:
        jpeg = imagen_mensaje("No se pudo obtener imagen\nRevise la fuente de la camara")
    return Response(jpeg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})
