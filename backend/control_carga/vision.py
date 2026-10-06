"""
Detección de motos con YOLO + seguimiento (tracking ByteTrack) usando Ultralytics.

Es opcional: si la librería no está instalada o YOLO_ACTIVO=false, el sistema sigue
funcionando solo con QR. Usa la GPU NVIDIA si está disponible; si no, la CPU.
"""
import logging

import numpy as np

from .config import BACKEND, Config

log = logging.getLogger("control_carga.vision")

CLASE_MOTO = 3  # "motorcycle" en el modelo YOLO entrenado con COCO
RUTA_MODELO = BACKEND / "modelos" / Config.YOLO_MODELO

_disponible = None


def disponible():
    """(True, None) si YOLO puede usarse, o (False, motivo)."""
    global _disponible
    if _disponible is None:
        if not Config.YOLO_ACTIVO:
            _disponible = (False, "Desactivado en .env (YOLO_ACTIVO=false)")
        elif not RUTA_MODELO.exists():
            _disponible = (False, f"No se encontró el modelo {RUTA_MODELO.name} en backend/modelos/")
        else:
            try:
                import ultralytics  # noqa: F401
                _disponible = (True, None)
            except ImportError:
                _disponible = (False, "Falta instalar ultralytics (pip install -r requirements.txt)")
    return _disponible


def _elegir_dispositivo(modelo):
    """GPU si está disponible y responde; si falla (drivers, arquitectura), CPU."""
    pedido = Config.YOLO_DISPOSITIVO.strip().lower()
    if pedido == "cpu":
        return "cpu"
    try:
        import torch

        if not torch.cuda.is_available():
            return "cpu"
        dispositivo = 0 if pedido in ("auto", "") else int(pedido)
        modelo.predict(np.zeros((320, 320, 3), np.uint8), device=dispositivo, verbose=False)  # prueba real
        return dispositivo
    except Exception as err:  # noqa: BLE001 — cualquier fallo de CUDA -> CPU
        log.warning("YOLO no pudo usar la GPU (%s); se usa la CPU.", err)
        return "cpu"


class DetectorMotos:
    """Un detector por cámara: el tracker guarda el estado entre fotogramas."""

    def __init__(self):
        from ultralytics import YOLO

        self.modelo = YOLO(str(RUTA_MODELO))
        self.dispositivo = _elegir_dispositivo(self.modelo)
        self.nombre_dispositivo = "GPU" if self.dispositivo != "cpu" else "CPU"

    def seguir(self, frame):
        """Motos del fotograma: [{"track": int | None, "caja": (x1, y1, x2, y2), "confianza": float}]."""
        r = self.modelo.track(
            frame,
            persist=True,
            classes=[CLASE_MOTO],
            conf=Config.YOLO_CONFIANZA,
            imgsz=Config.YOLO_IMGSZ,
            tracker="bytetrack.yaml",
            device=self.dispositivo,
            verbose=False,
        )[0]
        cajas = r.boxes
        if cajas is None or len(cajas) == 0:
            return []
        xyxy = cajas.xyxy.cpu().numpy().astype(int)
        confianzas = cajas.conf.cpu().tolist()
        ids = cajas.id.int().cpu().tolist() if cajas.id is not None else [None] * len(confianzas)
        return [
            {"track": t, "caja": tuple(int(v) for v in c), "confianza": round(float(p), 3)}
            for t, c, p in zip(ids, xyxy, confianzas)
        ]
