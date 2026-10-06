from flask import Blueprint, g, redirect, render_template, request, url_for

from . import db
from .auth import empleado_requerido

bp = Blueprint("alertas", __name__)


@bp.get("/alertas")
@empleado_requerido
def listado():
    ver = request.args.get("ver", "pendientes")
    consulta = db.tabla("v_alertas").select("*")
    if ver != "todas":
        consulta = consulta.eq("leida", False)
    alertas = db.ejecutar(consulta.order("leida").order("creada_en", desc=True).limit(200))
    return render_template("alertas.html", alertas=alertas, ver=ver)


def _cambios_lectura():
    return {"leida": True, "leida_por": g.usuario["id"], "leida_en": db.ahora()}


@bp.post("/alertas/<int:alerta_id>/leer")
@empleado_requerido
def leer(alerta_id):
    db.ejecutar(db.tabla("alertas").update(_cambios_lectura()).eq("id", alerta_id).eq("leida", False))
    return redirect(request.referrer or url_for("alertas.listado"))


@bp.post("/alertas/leer-todas")
@empleado_requerido
def leer_todas():
    db.ejecutar(db.tabla("alertas").update(_cambios_lectura()).eq("leida", False))
    return redirect(url_for("alertas.listado"))
