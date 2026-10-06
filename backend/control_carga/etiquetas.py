"""
Generador de códigos QR para pruebas y para etiquetar las motos.

  /qr                     generador libre: escriba un texto y obtenga su QR
  /qr.png?texto=...       imagen PNG del QR (para imprimir o mostrar en el celular)
  /cargas/<id>/etiquetas  hoja imprimible con un QR por cada moto del contrato

Formato del QR de cada moto: ARTICULO|SN-<carga>-<moto>
(el artículo identifica la referencia y el número de serie distingue cada unidad).
"""
import cv2
from flask import Blueprint, Response, abort, render_template, request

from . import db
from .auth import empleado_requerido
from .seguridad import hoy

bp = Blueprint("etiquetas", __name__)

MAX_TEXTO = 500


def texto_qr_moto(moto):
    return f"{moto['articulo']}|SN-{moto['carga_id']}-{moto['id']}"


def png_qr(texto, lado=360):
    qr = cv2.QRCodeEncoder.create().encode(texto)
    qr = cv2.copyMakeBorder(qr, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)  # zona blanca alrededor
    qr = cv2.resize(qr, (lado, lado), interpolation=cv2.INTER_NEAREST)
    return cv2.imencode(".png", qr)[1].tobytes()


@bp.get("/qr.png")
@empleado_requerido
def imagen():
    texto = (request.args.get("texto") or "").strip()
    if not texto or len(texto) > MAX_TEXTO:
        abort(400)
    lado = min(max(request.args.get("lado", 360, type=int), 120), 1000)
    return Response(png_qr(texto, lado), mimetype="image/png", headers={"Cache-Control": "private, max-age=3600"})


@bp.get("/qr")
@empleado_requerido
def generador():
    cargas = db.ejecutar(
        db.tabla("v_cargas").select("id, codigo_contrato, fecha, estado, total_motos")
        .in_("estado", ["PENDIENTE", "EN_CARGA"]).order("fecha", desc=True).order("creada_en", desc=True).limit(30)
    )
    texto = (request.args.get("texto") or "").strip()[:MAX_TEXTO]
    return render_template("qr.html", cargas=cargas, texto=texto, hoy=hoy())


@bp.get("/cargas/<int:carga_id>/etiquetas")
@empleado_requerido
def hoja(carga_id):
    carga = db.uno(db.tabla("v_cargas").select("id, codigo_contrato, fecha, destino").eq("id", carga_id))
    if not carga:
        abort(404)
    motos = db.ejecutar(db.tabla("motos_carga").select("id, carga_id, articulo, marca, descripcion, referencia")
                        .eq("carga_id", carga_id).order("id"))
    for m in motos:
        m["qr"] = texto_qr_moto(m)
    return render_template("etiquetas.html", carga=carga, motos=motos)
