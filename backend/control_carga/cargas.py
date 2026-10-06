import csv
import io
from datetime import date

from flask import Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request, url_for

from . import db, evidencias, lecturas
from .auth import empleado_requerido
from .camaras import gestor
from .cifrado import cifrar, descifrar
from .importador import ErrorImportacion, leer_archivo
from .seguridad import a_fecha, hora_local, hoy

bp = Blueprint("cargas", __name__)

ESTADOS = ["PENDIENTE", "EN_CARGA", "PAUSADA", "COMPLETA", "INCOMPLETA", "CANCELADA"]


def _fecha_param(nombre, defecto):
    try:
        return date.fromisoformat(request.values.get(nombre, ""))
    except ValueError:
        return defecto


def _carga_o_404(carga_id):
    carga = db.uno(db.tabla("v_cargas").select("*").eq("id", carga_id))
    if not carga:
        abort(404)
    carga["conductor"] = descifrar(carga["conductor"])
    carga.pop("camara_fuente", None)  # puede llevar credenciales de la cámara: no va a las plantillas
    return carga


# ---------------------------------------------------------------------------
# Listado e importación
# ---------------------------------------------------------------------------
@bp.get("/cargas")
@empleado_requerido
def listado():
    fecha = _fecha_param("fecha", hoy())
    estado = request.args.get("estado", "")
    consulta = db.tabla("v_cargas").select("*").eq("fecha", fecha.isoformat())
    if estado in ESTADOS:
        consulta = consulta.eq("estado", estado)
    cargas = db.ejecutar(consulta.order("creada_en"))
    return render_template("cargas.html", cargas=cargas, fecha=fecha, estado=estado, estados=ESTADOS)


@bp.route("/cargas/importar", methods=["GET", "POST"])
@empleado_requerido
def importar():
    form = {k: request.form.get(k, "").strip() for k in ("codigo_contrato", "destino", "placa", "conductor")}
    fecha = _fecha_param("fecha", hoy())

    if request.method == "POST":
        archivo = request.files.get("archivo")
        try:
            if not archivo or not archivo.filename:
                raise ErrorImportacion("Seleccione el archivo REFRENCIAS MOTOS AKT.xlsx.")
            motos = leer_archivo(archivo.filename, archivo.read())
            carga = _crear_carga(motos, form, fecha, archivo.filename)
        except ErrorImportacion as err:
            for linea in str(err).split("\n"):
                flash(linea, "error")
            return render_template("importar.html", fecha=fecha, **form), 400

        flash(f"Carga {carga['codigo']} creada con {carga['motos']} motos.", "ok")
        return redirect(url_for("cargas.detalle", carga_id=carga["id"]))

    return render_template("importar.html", fecha=fecha, **form)


def _crear_carga(motos, form, fecha, nombre_archivo):
    """La carga y todas sus motos se crean juntas o nada (función app_importar_carga)."""
    carga = {
        "codigo": form["codigo_contrato"].upper() or _codigo_automatico(fecha),
        "fecha": fecha.isoformat(),
        "destino": form["destino"],
        "placa": form["placa"].upper(),
        "conductor": cifrar(form["conductor"]),
        "motos": motos,
    }
    r = db.rpc("app_importar_carga", {"p_carga": carga, "p_usuario_id": g.usuario["id"], "p_archivo": nombre_archivo})
    if not r["ok"]:
        raise ErrorImportacion(r["error"])
    return r


def _codigo_automatico(fecha):
    """El archivo no trae código de carga: CARGA-AAAAMMDD-01, -02... por día."""
    del_dia = db.contar(db.tabla("cargas").select("id", count="exact").eq("fecha", fecha.isoformat()))
    return f"CARGA-{fecha:%Y%m%d}-{del_dia + 1:02d}"


# ---------------------------------------------------------------------------
# Detalle y operación de una carga
# ---------------------------------------------------------------------------
@bp.get("/cargas/<int:carga_id>")
@empleado_requerido
def detalle(carga_id):
    carga = _carga_o_404(carga_id)
    motos = db.ejecutar(
        db.tabla("motos_carga").select("*").eq("carga_id", carga_id)
        .order("estado", desc=True).order("marca").order("descripcion").order("id")
    )
    lecturas_ = db.ejecutar(
        db.tabla("lecturas_qr").select("*").eq("carga_id", carga_id).order("leida_en", desc=True).limit(30)
    )
    camaras = db.ejecutar(db.tabla("camaras").select("id, nombre, ubicacion").eq("activa", True).order("nombre"))
    return render_template("carga.html", carga=carga, motos=motos, lecturas=lecturas_, camaras=camaras)


@bp.post("/cargas/<int:carga_id>/iniciar")
@empleado_requerido
def iniciar(carga_id):
    camara_id = request.form.get("camara_id", type=int)
    if not camara_id:
        # Todo se registra con la cámara: no hay modo manual
        flash("Seleccione la cámara que va a detectar las motos.", "error")
        return redirect(url_for("cargas.detalle", carga_id=carga_id))
    anterior = db.uno(db.tabla("cargas").select("estado").eq("id", carga_id))
    accion = "reanudada" if anterior and anterior["estado"] in ("PAUSADA", "INCOMPLETA") else "iniciada"
    try:
        camara = lecturas.iniciar_carga(carga_id, camara_id)
        gestor.iniciar(camara["id"], descifrar(camara["fuente"]), carga_id)
        flash(f"Carga {accion}. La cámara '{camara['nombre']}' está detectando motos y leyendo QR.", "ok")
    except lecturas.ErrorCarga as err:
        flash(str(err), "error")
    return redirect(url_for("cargas.detalle", carga_id=carga_id))


@bp.post("/cargas/<int:carga_id>/finalizar")
@empleado_requerido
def finalizar(carga_id):
    try:
        r = lecturas.finalizar_carga(carga_id, g.usuario["id"])
    except lecturas.ErrorCarga as err:
        flash(str(err), "error")
        return redirect(url_for("cargas.detalle", carga_id=carga_id))
    if r["camara_id"]:
        gestor.liberar(r["camara_id"])
    if r["faltantes"]:
        flash(f"CARGA INCOMPLETA: faltaron {r['faltantes']} de {r['total']} motos. "
              f"Se envió una alerta al administrador.", "error")
    else:
        flash(f"Carga COMPLETA: se verificaron las {r['total']} motos.", "ok")
    if r.get("yolo_sin_identificar"):
        flash(f"YOLO vio {r['yolo_detectadas']} motos y {r['yolo_sin_identificar']} subieron SIN identificar "
              f"(sin QR). Revise las alertas.", "error")
    elif r.get("yolo_detectadas"):
        flash(f"YOLO confirmó visualmente {r['yolo_detectadas']} motos, todas identificadas.", "ok")
    return redirect(url_for("cargas.detalle", carga_id=carga_id))


@bp.post("/cargas/<int:carga_id>/pausar")
@empleado_requerido
def pausar(carga_id):
    """Detiene la carga sin cerrarla: lo ya cargado se conserva y se puede reanudar después."""
    try:
        r = lecturas.cambiar_estado(carga_id, "PAUSADA", ["EN_CARGA"])
        if r["camara_id"]:
            gestor.liberar(r["camara_id"])
        flash("Carga pausada. Puede reanudarla cuando quiera; las motos ya cargadas se conservan.", "ok")
    except lecturas.ErrorCarga as err:
        flash(str(err), "error")
    return redirect(url_for("cargas.detalle", carga_id=carga_id))


@bp.post("/cargas/<int:carga_id>/cancelar")
@empleado_requerido
def cancelar(carga_id):
    try:
        r = lecturas.cambiar_estado(carga_id, "CANCELADA", ["PENDIENTE", "EN_CARGA", "PAUSADA"])
        if r["camara_id"]:
            gestor.liberar(r["camara_id"])
        flash("Carga cancelada.", "ok")
    except lecturas.ErrorCarga as err:
        flash(str(err), "error")
    return redirect(url_for("cargas.detalle", carga_id=carga_id))


@bp.get("/cargas/<int:carga_id>/reporte.csv")
@empleado_requerido
def reporte(carga_id):
    carga = _carga_o_404(carga_id)
    motos = db.ejecutar(db.tabla("motos_carga").select("*").eq("carga_id", carga_id).order("id"))
    fecha = a_fecha(carga["fecha"])
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    w.writerow(["carga", "fecha", "destino", "placa", "articulo", "marca", "descripcion", "cod_int",
                "estado", "hora_cargue", "qr_leido", "confirmada_yolo"])
    for m in motos:
        w.writerow([carga["codigo_contrato"], fecha.isoformat(), carga["destino"] or "", carga["placa_camion"] or "",
                    m["articulo"], m["marca"] or "", m["descripcion"] or "", m["referencia"] or "",
                    m["estado"], hora_local(m["cargada_en"]) or "", m["qr_leido"] or "", "SI" if m["track_id"] else ""])
    nombre = f"reporte_{carga['codigo_contrato']}_{fecha:%Y%m%d}.csv"
    return Response("\ufeff" + salida.getvalue(), mimetype="text/csv",  # BOM: Excel abre bien las tildes
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# ---------------------------------------------------------------------------
# API usada por la pantalla de la carga (se consulta cada 2 s).
# No hay registro manual: las motos solo se registran cuando las detecta la cámara.
# ---------------------------------------------------------------------------
@bp.get("/api/cargas/<int:carga_id>/estado")
@empleado_requerido
def api_estado(carga_id):
    e = db.rpc("app_estado_carga", {"p_carga_id": carga_id})
    if not e:
        return jsonify(error="no existe"), 404
    return jsonify(
        estado=e["estado"],
        total=e["total"],
        cargadas=e["cargadas"],
        faltantes=e["faltantes"],
        motos_cargadas={k: {**v, "hora": hora_local(v["hora"])} for k, v in e["motos_cargadas"].items()},
        yolo=e["yolo"],
        lecturas=[{**l, "leida_en": hora_local(l["leida_en"]),
                   "evidencia": url_for("cargas.evidencia", ruta=l["evidencia"]) if l["evidencia"] else None}
                  for l in e["lecturas"]],
        camara=gestor.estado(e["camara_id"]) if e["camara_id"] else None,
    )


@bp.get("/camaras/<int:camara_id>/vivo")
@empleado_requerido
def vivo(camara_id):
    t = gestor.trabajador(camara_id)
    if not t:
        return Response(status=404)
    return Response(t.fotogramas(), mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-store"})


@bp.get("/evidencias/<path:ruta>")
@empleado_requerido
def evidencia(ruta):
    """Foto de evidencia desde Supabase Storage (bucket privado), solo para usuarios con sesión."""
    if ".." in ruta or ruta.startswith("/"):
        abort(404)
    foto = evidencias.descargar(ruta)
    if foto is None:
        abort(404)
    return Response(foto, mimetype="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
