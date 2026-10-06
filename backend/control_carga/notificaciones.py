"""
Correo al administrador cuando se crea una alerta crítica (opcional).
Las alertas se crean dentro de las funciones de Supabase; aquí solo se envían por correo.
"""
import logging
import os
import smtplib
import threading
from email.message import EmailMessage

from . import db
from .cifrado import descifrar
from .seguridad import a_fecha

log = logging.getLogger("control_carga.notificaciones")


def correo_configurado():
    return bool(os.getenv("SMTP_HOST"))


def _destinatarios():
    configurados = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
    if configurados:
        return configurados
    filas = db.ejecutar(db.tabla("usuarios").select("email").eq("rol", "admin").eq("activo", True))
    return [descifrar(f["email"]) for f in filas if f["email"]]


def enviar_correo_alerta(alerta_id):
    """Envía la alerta por correo en segundo plano (no bloquea la respuesta)."""
    if correo_configurado():
        threading.Thread(target=_enviar, args=(alerta_id,), daemon=True).start()


def _enviar(alerta_id):
    try:
        a = db.uno(db.tabla("v_alertas").select("*").eq("id", alerta_id))
        para = _destinatarios()
        if not a or not para:
            return

        cuerpo = [a["mensaje"], ""]
        if a["codigo_contrato"]:
            fecha = a_fecha(a["fecha"])
            cuerpo += [
                f"Contrato: {a['codigo_contrato']}",
                f"Fecha: {fecha:%d/%m/%Y}" if fecha else "Fecha: —",
                f"Destino: {a['destino'] or '—'}",
                f"Placa camión: {a['placa_camion'] or '—'}",
                "",
            ]
        for m in (a["detalle"] or {}).get("faltantes", []):
            partes = [m.get("articulo"), m.get("marca"), m.get("descripcion") or m.get("referencia")]
            cuerpo.append("  - " + " · ".join(p for p in partes if p))

        msg = EmailMessage()
        msg["Subject"] = f"[{os.getenv('APP_NOMBRE', 'Control de Carga de Motos')}] {a['titulo']}"
        msg["From"] = os.getenv("SMTP_REMITENTE") or os.getenv("SMTP_USUARIO")
        msg["To"] = ", ".join(para)
        msg.set_content("\n".join(cuerpo))

        puerto = int(os.getenv("SMTP_PORT", "587"))
        clase = smtplib.SMTP_SSL if puerto == 465 else smtplib.SMTP
        with clase(os.getenv("SMTP_HOST"), puerto, timeout=20) as smtp:
            if puerto != 465:
                smtp.starttls()
            if os.getenv("SMTP_USUARIO"):
                smtp.login(os.getenv("SMTP_USUARIO"), os.getenv("SMTP_PASSWORD", ""))
            smtp.send_message(msg)

        db.ejecutar(db.tabla("alertas").update({"email_enviado": True}).eq("id", alerta_id))
    except Exception:  # noqa: BLE001 — un fallo de correo no debe tumbar el sistema
        log.exception("No se pudo enviar el correo de la alerta %s", alerta_id)
