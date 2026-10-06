"""
Reglas del negocio de una carga: iniciar, registrar cada QR leído y finalizar.
La parte transaccional vive en funciones de Supabase (ver BASE_FINAL.sql).

Resultados posibles de una lectura (todas las hace la cámara, no hay registro manual):
  VALIDA        la moto pertenece a esta carga y queda marcada como CARGADA
  DUPLICADA     QR ya usado: esa moto ya está cargada en el camión
  SOBRANTE      ya se cargaron todas las unidades de esa referencia
  OTRA_CARGA    la moto pertenece a OTRA carga abierta -> ¡no debe subir a este camión!
  NO_PERTENECE  el QR no coincide con ninguna moto
"""
from . import db, evidencias, notificaciones
from .qr import candidatos


class ErrorCarga(Exception):
    pass


def _rpc(funcion, parametros):
    try:
        return db.rpc(funcion, parametros)
    except db.ErrorBD as err:
        raise ErrorCarga(str(err)) from err


def registrar_lectura(carga_id, contenido, camara_id=None, foto_jpeg=None, track_id=None):
    """QR leído por la cámara. track_id: moto de YOLO que llevaba el QR."""
    contenido = (contenido or "").strip()[:1000]
    if not contenido:
        raise ErrorCarga("La lectura está vacía.")

    ruta = evidencias.ruta_nueva(carga_id) if foto_jpeg else None
    r = _rpc("app_registrar_lectura", {
        "p_carga_id": carga_id,
        "p_contenido": contenido,
        "p_candidatos": candidatos(contenido),
        "p_camara_id": camara_id,
        "p_evidencia": ruta,
        "p_track_id": track_id,
    })
    if ruta and r["resultado"] != "DUPLICADA":  # un QR ya usado no necesita foto
        evidencias.subir(ruta, foto_jpeg)
    return r


def registrar_deteccion(carga_id, camara_id, moto, foto_jpeg=None):
    """Guarda una moto que YOLO siguió hasta que salió de la imagen (ver camaras.py)."""
    ruta = evidencias.ruta_nueva(carga_id) if foto_jpeg else None
    r = _rpc("app_registrar_deteccion", {
        "p_carga_id": carga_id,
        "p_camara_id": camara_id,
        "p_track_id": moto["id"],
        "p_confianza": moto["confianza"],
        "p_fotogramas": moto["fotogramas"],
        "p_primera": moto["primera"].isoformat(),
        "p_ultima": moto["ultima"].isoformat(),
        "p_qr": moto["qr"],
        "p_evidencia": ruta,
    })
    if ruta and r.get("estado") == "SIN_IDENTIFICAR":  # solo se guarda la foto de las motos sin identificar
        evidencias.subir(ruta, foto_jpeg)
    return r


def iniciar_carga(carga_id, camara_id):
    """Pone la carga EN_CARGA con la cámara que va a detectar las motos. Devuelve esa cámara."""
    return _rpc("app_iniciar_carga", {"p_carga_id": carga_id, "p_camara_id": camara_id})


def finalizar_carga(carga_id, usuario_id):
    """
    Cierra la carga comparando contra la base del contrato.
    Si faltan motos queda INCOMPLETA y se alerta al administrador.
    """
    r = _rpc("app_finalizar_carga", {"p_carga_id": carga_id, "p_usuario_id": usuario_id})
    if r.get("alerta_id"):
        notificaciones.enviar_correo_alerta(r["alerta_id"])
    return r


def cambiar_estado(carga_id, nuevo, permitidos):
    return _rpc("app_cambiar_estado", {"p_carga_id": carga_id, "p_nuevo": nuevo, "p_permitidos": list(permitidos)})
