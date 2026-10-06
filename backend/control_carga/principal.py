from flask import Blueprint, g, redirect, render_template, url_for

from . import db
from .auth import login_requerido
from .seguridad import hoy

bp = Blueprint("principal", __name__)


@bp.get("/")
@login_requerido
def inicio():
    if g.usuario["rol"] == "admin":
        return redirect(url_for("admin.panel"))  # el administrador solo administra
    fecha = hoy()
    cargas = db.ejecutar(
        db.tabla("v_cargas").select("*")
        .or_(f"fecha.eq.{fecha.isoformat()},estado.in.(EN_CARGA,PAUSADA)")
        .order("creada_en")
    )
    cargas.sort(key=lambda c: c["estado"] not in ("EN_CARGA", "PAUSADA"))  # las que están en proceso, primero
    del_dia = [c for c in cargas if c["fecha"] == fecha.isoformat()]
    kpis = {
        "cargas": len(del_dia),
        "en_proceso": sum(c["estado"] == "EN_CARGA" for c in cargas),
        "esperadas": sum(c["total_motos"] for c in del_dia),
        "cargadas": sum(c["motos_cargadas"] for c in del_dia),
        "incompletas": sum(c["estado"] == "INCOMPLETA" for c in del_dia),
    }
    alertas = db.ejecutar(
        db.tabla("v_alertas").select("*").eq("leida", False).order("creada_en", desc=True).limit(6)
    )
    return render_template("inicio.html", cargas=cargas, kpis=kpis, alertas=alertas, fecha=fecha)
