"""
Fotos de evidencia en Supabase Storage (bucket privado "evidencias").

Cada foto queda enlazada a su registro en la base (lecturas_qr.evidencia,
detecciones_yolo.evidencia y el detalle de las alertas) por su ruta:
    <carga_id>/<fecha_hora>.jpg
El bucket es privado: solo el backend (clave secreta) sube y descarga, y la
pantalla las muestra a través de /evidencias/<ruta> a usuarios con sesión.
"""
import logging
from datetime import datetime

from storage3.exceptions import StorageApiError

from . import db

log = logging.getLogger("control_carga.evidencias")

BUCKET = "evidencias"
TAMANO_MAXIMO = 5 * 1024 * 1024  # 5 MB por foto


def _bucket():
    return db.cliente().storage.from_(BUCKET)


def asegurar_bucket():
    """Crea el bucket privado la primera vez (se llama al arrancar la app)."""
    storage = db.cliente().storage
    try:
        storage.get_bucket(BUCKET)
    except StorageApiError:
        storage.create_bucket(BUCKET, options={
            "public": False, "file_size_limit": TAMANO_MAXIMO, "allowed_mime_types": ["image/jpeg"],
        })
        print(f"🗂 Bucket privado «{BUCKET}» creado en Supabase Storage.")


def ruta_nueva(carga_id):
    return f"{carga_id}/{datetime.now():%Y%m%d_%H%M%S_%f}.jpg"


def subir(ruta, foto_jpeg):
    try:
        _bucket().upload(ruta, foto_jpeg, {"content-type": "image/jpeg", "upsert": "true"})
        return True
    except StorageApiError:
        log.exception("No se pudo subir la evidencia %s", ruta)
        return False


def descargar(ruta):
    try:
        return _bucket().download(ruta)
    except StorageApiError:
        return None
