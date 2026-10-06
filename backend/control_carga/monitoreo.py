"""
Monitoreo en vivo de las cámaras (empleados y administradores).

Muestra lo que ve la cámara con la detección YOLO + tracking y la lectura de QR en
tiempo real. Si la cámara no está asignada a una carga, se abre en modo monitoreo
(no registra nada) y se apaga sola cuando nadie la está viendo.
"""
from flask import Blueprint, jsonify, render_template, request

from . import db, vision
from .auth import empleado_requerido
from .camaras import gestor
from .cifrado import descifrar

bp = Blueprint("monitoreo", __name__)


def _camaras():
    camaras = db.ejecutar(db.tabla("v_camaras").select("id, nombre, ubicacion, activa, carga_id, codigo_contrato")
                          .eq("activa", True).order("nombre"))
    for k in camaras:
        k["vivo"] = gestor.estado(k["id"])["estado"]
    return camaras


@bp.get("/monitoreo")
@empleado_requerido
def pantalla():
    camaras = _camaras()
    elegida = request.args.get("camara", type=int)
    if not any(k["id"] == elegida for k in camaras):
        elegida = camaras[0]["id"] if camaras else None
    yolo_ok, yolo_motivo = vision.disponible()
    return render_template("monitoreo.html", camaras=camaras, elegida=elegida,
                           yolo_ok=yolo_ok, yolo_motivo=yolo_motivo)


@bp.post("/api/camaras/<int:camara_id>/monitoreo")
@empleado_requerido
def encender(camara_id):
    """Abre la cámara para verla. Si ya está leyendo una carga, se muestra esa misma sesión."""
    if gestor.trabajador(camara_id):
        return jsonify(ok=True)
    cam = db.uno(db.tabla("camaras").select("fuente").eq("id", camara_id).eq("activa", True))
    if not cam:
        return jsonify(ok=False, mensaje="La cámara no existe o está desactivada."), 404
    gestor.iniciar(camara_id, descifrar(cam["fuente"]), None)
    return jsonify(ok=True)


@bp.get("/api/camaras/<int:camara_id>/monitoreo")
@empleado_requerido
def estado(camara_id):
    r = gestor.resumen(camara_id)
    if r.get("carga_id"):
        carga = db.uno(db.tabla("v_cargas").select("id, codigo_contrato, total_motos, motos_cargadas, motos_faltantes")
                       .eq("id", r["carga_id"]))
        r["carga"] = carga
    return jsonify(r)
