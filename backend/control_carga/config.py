import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
RAIZ = BACKEND.parent
FRONTEND = RAIZ / "frontend"
ENV = BACKEND / ".env"

load_dotenv(ENV)


def _int(nombre, defecto):
    try:
        return int(os.getenv(nombre, defecto))
    except ValueError:
        return defecto


def _float(nombre, defecto):
    try:
        return float(os.getenv(nombre, defecto))
    except ValueError:
        return defecto


def _bool(nombre, defecto):
    return os.getenv(nombre, str(defecto)).strip().lower() in ("1", "true", "si", "sí", "yes")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    # Clave SECRETA de Supabase: solo vive en el backend, nunca se envía al navegador
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
    SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    # Clave Fernet para cifrar datos sensibles en la base de datos
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "").strip()
    APP_NOMBRE = os.getenv("APP_NOMBRE", "Control de Carga de Motos")
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = _int("PORT", 5173)
    DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Cookie de sesión sin fecha de expiración: el navegador la borra al cerrarse
    SESSION_PERMANENT = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESION_TIMEOUT_SEG = _int("SESION_TIMEOUT_SEG", 120)

    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # archivos de contrato de hasta 10 MB

    # Cámara: resolución pedida a la cámara USB y análisis por segundo
    CAMARA_ANCHO = _int("CAMARA_ANCHO", 1280)
    CAMARA_ALTO = _int("CAMARA_ALTO", 720)
    CAMARA_FPS_ANALISIS = _int("CAMARA_FPS_ANALISIS", 8)
    # Segundos que el QR debe desaparecer de la imagen para que, al volver, cuente como otra lectura
    QR_NUEVA_LECTURA_SEG = _float("QR_NUEVA_LECTURA_SEG", 3.0)

    # YOLO + tracking (detección de motos). Si no está instalado, el sistema trabaja solo con QR.
    YOLO_ACTIVO = _bool("YOLO_ACTIVO", True)
    YOLO_MODELO = os.getenv("YOLO_MODELO", "yolov8n.pt")        # archivo dentro de backend/modelos/
    YOLO_CONFIANZA = _float("YOLO_CONFIANZA", 0.40)
    YOLO_IMGSZ = _int("YOLO_IMGSZ", 640)
    YOLO_DISPOSITIVO = os.getenv("YOLO_DISPOSITIVO", "auto")     # auto | cpu | 0 (primera GPU)
    YOLO_MIN_FOTOGRAMAS = _int("YOLO_MIN_FOTOGRAMAS", 5)         # para confirmar que es una moto real
    YOLO_TRACK_PERDIDO_SEG = _float("YOLO_TRACK_PERDIDO_SEG", 2.5)  # sin verla este tiempo = salió de la imagen

    # Monitoreo sin carga: la cámara se apaga si nadie la está viendo
    MONITOREO_INACTIVO_SEG = _int("MONITOREO_INACTIVO_SEG", 60)
