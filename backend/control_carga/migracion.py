"""
Cifra los datos sensibles que quedaron en texto plano de versiones anteriores.
Se ejecuta al arrancar y es idempotente: lo que ya está cifrado no se toca.
"""
import logging

from . import db
from .cifrado import cifrar, esta_cifrado, huella

log = logging.getLogger("control_carga.migracion")


def _cifrar_columnas(tabla, columnas):
    # Solo las filas con algún valor aún sin cifrar (todo texto Fernet empieza por "gAAAAA")
    pendientes = ",".join(f"{c}.not.like.gAAAAA*" for c in columnas)
    filas = db.ejecutar(db.tabla(tabla).select(",".join(["id", *columnas])).or_(pendientes))
    cambiadas = 0
    for fila in filas:
        cambios = {c: cifrar(fila[c]) for c in columnas if fila[c] and not esta_cifrado(fila[c])}
        if tabla == "usuarios" and "email" in cambios:
            cambios["email_hash"] = huella(fila["email"])
        if cambios:
            db.ejecutar(db.tabla(tabla).update(cambios).eq("id", fila["id"]))
            cambiadas += 1
    return cambiadas


def cifrar_datos_existentes():
    total = 0
    total += _cifrar_columnas("usuarios", ["email"])
    total += _cifrar_columnas("sesiones", ["ip", "user_agent"])
    total += _cifrar_columnas("camaras", ["fuente"])
    total += _cifrar_columnas("cargas", ["conductor"])
    if total:
        print(f"🔒 Se cifraron datos sensibles antiguos en {total} registro(s).")
