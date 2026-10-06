"""
Cámaras en el servidor (USB, IP/RTSP o video de prueba) con YOLO + tracking + QR.

Cada cámara en uso tiene un Trabajador con tres hilos:
  captura   lee fotogramas y publica la vista en vivo (MJPEG) con los recuadros dibujados
  análisis  CAMARA_FPS_ANALISIS veces por segundo:
              - YOLO detecta las motos y el tracker les da un número de seguimiento (track)
              - se leen los QR y cada QR se asocia a la moto (track) que lo lleva
              - cuando una moto sale de la imagen se registra; si nunca se identificó
                (sin QR) queda como SIN IDENTIFICAR y se genera una alerta
  registro  guarda en Supabase las lecturas y detecciones (sin frenar el video)

Modos:
  carga      (carga_id = número) registra todo en esa carga
  monitoreo  (carga_id = None) solo muestra lo que ve la cámara; no registra nada
"""
import logging
import os
import queue
import threading
import time
from collections import deque
from datetime import datetime, timezone

import cv2
import numpy as np

from . import db, lecturas, vision
from .cifrado import descifrar
from .config import RAIZ, Config

log = logging.getLogger("control_carga.camaras")

COLORES = {  # BGR
    "VALIDA": (80, 175, 76),
    "DUPLICADA": (0, 165, 255),     # naranja: QR ya usado
    "SOBRANTE": (40, 40, 230),
    "OTRA_CARGA": (40, 40, 230),
    "NO_PERTENECE": (40, 40, 230),
    "ERROR": (0, 165, 255),
    "MONITOREO": (230, 180, 40),
}
COLOR_MOTO = (0, 200, 255)          # moto seguida, aún sin identificar
COLOR_MOTO_OK = (80, 200, 80)       # moto identificada por su QR


def _es_archivo(fuente):
    return not fuente.strip().isdigit() and "://" not in fuente


def _abrir(fuente):
    fuente = fuente.strip()
    if fuente.isdigit():
        indice = int(fuente)
        cap = cv2.VideoCapture(indice, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(indice)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.CAMARA_ANCHO)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.CAMARA_ALTO)
        return cap
    if _es_archivo(fuente) and not os.path.isabs(fuente):
        fuente = str(RAIZ / fuente)  # ruta de un video relativa a la raíz del proyecto
    return cv2.VideoCapture(fuente)


def _detector_qr():
    return cv2.QRCodeDetectorAruco() if hasattr(cv2, "QRCodeDetectorAruco") else cv2.QRCodeDetector()


def imagen_mensaje(texto, ancho=960, alto=540):
    img = np.full((alto, ancho, 3), 32, np.uint8)
    for i, linea in enumerate(texto.split("\n")):
        cv2.putText(img, linea, (40, alto // 2 - 20 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (220, 220, 220), 2)
    return cv2.imencode(".jpg", img)[1].tobytes()


def _ahora_utc():
    return datetime.now(timezone.utc)


def _hora():
    return time.strftime("%I:%M:%S %p").lower()


def _dentro(punto, caja, margen=0.25):
    x, y = punto
    x1, y1, x2, y2 = caja
    mx, my = (x2 - x1) * margen, (y2 - y1) * margen
    return x1 - mx <= x <= x2 + mx and y1 - my <= y <= y2 + my


class Trabajador(threading.Thread):
    def __init__(self, camara_id, fuente, carga_id):
        super().__init__(daemon=True, name=f"camara-{camara_id}")
        self.camara_id = camara_id
        self.fuente = fuente
        self.carga_id = carga_id
        self.estado = "CONECTANDO"
        self.error = None
        self.jpeg = imagen_mensaje("Conectando con la camara...")
        self.ultimo_uso = time.monotonic()
        self.inicio = datetime.now()

        self.eventos = deque(maxlen=60)       # bitácora para la pantalla de monitoreo
        self.ultimas = deque(maxlen=8)        # últimas lecturas QR registradas
        self.contadores = {"motos_vistas": 0, "identificadas": 0, "sin_identificar": 0, "qr_leidos": 0}
        self.yolo = {"estado": "CARGANDO", "detalle": None, "dispositivo": None, "fps": 0.0, "ms": 0}

        self._parar = threading.Event()
        self._nuevo = threading.Condition()
        self._lock = threading.Lock()
        self._frame = None
        self._frame_n = 0
        self._vistos = {}            # contenido QR -> momento en que se leyó
        self._resultado_qr = {}      # contenido QR -> resultado (color del recuadro)
        self._qr_marcas = ([], 0.0)  # [(puntos, texto)], momento
        self._motos = {}             # track de YOLO -> estado de la moto
        self._cola = queue.Queue()

        threading.Thread(target=self._analizar, daemon=True, name=f"analisis-{camara_id}").start()
        threading.Thread(target=self._procesar_cola, daemon=True, name=f"registro-{camara_id}").start()

    # -- control -----------------------------------------------------------
    def detener(self):
        self._parar.set()
        self._cola.put(None)
        with self._nuevo:
            self._nuevo.notify_all()

    @property
    def detenido(self):
        return self._parar.is_set()

    def asignar_carga(self, carga_id):
        """Pasa de monitoreo a carga (o al revés) sin cortar el video."""
        if carga_id == self.carga_id:
            return
        with self._lock:
            self.carga_id = carga_id
            self._vistos.clear()
            self._resultado_qr.clear()
        self._evento("info", f"Cámara asignada a la carga #{carga_id}" if carga_id else "Cámara en modo monitoreo")

    def _evento(self, tipo, texto):
        self.eventos.appendleft({"hora": _hora(), "tipo": tipo, "texto": texto})

    def _publicar(self, jpeg):
        with self._nuevo:
            self.jpeg = jpeg
            self._nuevo.notify_all()

    # -- hilo de captura -----------------------------------------------------
    def run(self):
        es_archivo = _es_archivo(self.fuente)
        ultima_publicacion = 0.0
        pausa_video = 0.0
        cap = None
        while not self._parar.is_set():
            if cap is None:
                cap = _abrir(self.fuente)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    self._fallo("No se pudo abrir la camara\nRevise que este conectada o la fuente")
                    self._parar.wait(3)
                    continue
                self.estado, self.error = "CONECTADA", None
                self._evento("info", "Cámara conectada")
                pausa_video = 1.0 / (cap.get(cv2.CAP_PROP_FPS) or 25) if es_archivo else 0.0

            ok, frame = cap.read()
            if not ok:
                if es_archivo:  # video de prueba: vuelve a empezar
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                cap.release()
                cap = None
                self._fallo("Se perdio la senal de la camara\nReintentando...")
                self._evento("error", "Se perdió la señal de la cámara")
                self._parar.wait(2)
                continue

            with self._lock:
                self._frame = frame
                self._frame_n += 1

            ahora = time.monotonic()
            if ahora - ultima_publicacion >= 1 / 12:  # vista en vivo a ~12 fps
                ultima_publicacion = ahora
                self._publicar(self._jpeg_vista(frame, ahora))
            if pausa_video:
                time.sleep(pausa_video)

        if cap is not None:
            cap.release()

    def _fallo(self, mensaje):
        self.estado, self.error = "ERROR", mensaje.replace("\n", " ")
        self._publicar(imagen_mensaje(mensaje))

    # -- hilo de análisis (YOLO + tracking + QR) ----------------------------------
    def _cargar_yolo(self):
        ok, motivo = vision.disponible()
        if not ok:
            self.yolo.update(estado="NO_DISPONIBLE", detalle=motivo)
            self._evento("aviso", f"YOLO no disponible: {motivo}. Se trabaja solo con QR.")
            return None
        try:
            detector = vision.DetectorMotos()
            self.yolo.update(estado="ACTIVO", dispositivo=detector.nombre_dispositivo)
            self._evento("info", f"YOLO + tracking activo ({detector.nombre_dispositivo})")
            return detector
        except Exception as err:  # noqa: BLE001
            log.exception("No se pudo cargar YOLO")
            self.yolo.update(estado="ERROR", detalle=str(err))
            self._evento("error", f"No se pudo cargar YOLO: {err}")
            return None

    def _analizar(self):
        detector_qr = _detector_qr()
        yolo = self._cargar_yolo()
        intervalo = 1.0 / max(1, Config.CAMARA_FPS_ANALISIS)
        visto_n = 0
        inicios = deque(maxlen=20)  # para medir los análisis reales por segundo

        while not self._parar.is_set():
            inicio = time.monotonic()
            with self._lock:
                frame, n = self._frame, self._frame_n
            if frame is None or n == visto_n:
                self._parar.wait(0.02)
                continue
            visto_n = n

            detecciones = []
            if yolo is not None:
                try:
                    detecciones = yolo.seguir(frame)
                except Exception as err:  # noqa: BLE001 — un fallo de YOLO no debe tumbar la cámara
                    log.exception("Error de YOLO")
                    self.yolo.update(estado="ERROR", detalle=str(err))
                    self._evento("error", f"YOLO se detuvo por un error: {err}")
                    yolo = None
            self._actualizar_motos(detecciones, frame, inicio)
            self._leer_qr(detector_qr, frame, inicio)
            self._cerrar_motos_perdidas(inicio)

            inicios.append(inicio)
            if len(inicios) > 1 and inicios[-1] > inicios[0]:
                self.yolo["fps"] = round((len(inicios) - 1) / (inicios[-1] - inicios[0]), 1)
            self.yolo["ms"] = round((time.monotonic() - inicio) * 1000)
            espera = intervalo - (time.monotonic() - inicio)
            if espera > 0:
                self._parar.wait(espera)

    def _actualizar_motos(self, detecciones, frame, ahora):
        for d in detecciones:
            if d["track"] is None:
                continue
            moto = self._motos.get(d["track"])
            if moto is None:
                moto = self._motos[d["track"]] = {
                    "id": f"C{self.camara_id}-{self.inicio:%H%M%S}-T{d['track']}",
                    "numero": d["track"],
                    "primera": _ahora_utc(), "fotogramas": 0, "confianza": 0.0,
                    "qr": None, "foto": None, "anunciada": False,
                }
            moto.update(caja=d["caja"], ultima=_ahora_utc(), ultima_mono=ahora)
            moto["fotogramas"] += 1
            if d["confianza"] > moto["confianza"]:
                moto["confianza"] = d["confianza"]
                moto["foto"] = frame  # la mejor imagen, para la evidencia
            if not moto["anunciada"] and moto["fotogramas"] >= Config.YOLO_MIN_FOTOGRAMAS:
                moto["anunciada"] = True
                self.contadores["motos_vistas"] += 1
                self._evento("moto", f"Moto #{moto['numero']} detectada (confianza {moto['confianza']:.0%})")

    def _moto_de_punto(self, punto):
        """La moto seguida cuyo recuadro contiene el punto (la más pequeña si hay varias)."""
        candidatas = [m for m in self._motos.values() if _dentro(punto, m["caja"])]
        if not candidatas:
            return None
        return min(candidatas, key=lambda m: (m["caja"][2] - m["caja"][0]) * (m["caja"][3] - m["caja"][1]))

    def _leer_qr(self, detector, frame, ahora):
        try:
            ok, textos, puntos, _ = detector.detectAndDecodeMulti(frame)
        except cv2.error:
            return
        if not ok or puntos is None:
            return
        marcas = []
        for texto, pts in zip(textos, puntos):
            if not texto:
                continue
            pts = pts.astype(int)
            marcas.append((pts, texto))
            moto = self._moto_de_punto(tuple(pts.mean(axis=0)))
            if moto is not None and moto["qr"] is None:
                moto["qr"] = texto
                self._evento("qr", f"QR asociado a la moto #{moto['numero']}: {texto}")

            # Una "lectura" es cada vez que el QR aparece frente a la cámara. Mientras siga a la
            # vista no se repite; si desaparece y vuelve a aparecer, se lee de nuevo (así un QR
            # ya usado muestra "QR ya usado y moto ya cargada en el camión").
            visto = self._vistos.get(texto)
            self._vistos[texto] = ahora
            if visto is not None and ahora - visto < Config.QR_NUEVA_LECTURA_SEG:
                continue
            self.contadores["qr_leidos"] += 1
            if self.carga_id is None:
                self._resultado_qr[texto] = "MONITOREO"
                self._evento("qr", f"QR leído (monitoreo, no se registra): {texto}")
            else:
                self._cola.put(("qr", self.carga_id, texto, frame.copy(), pts, moto["id"] if moto else None))
        if marcas:
            self._qr_marcas = (marcas, ahora)

    def _cerrar_motos_perdidas(self, ahora):
        for numero, moto in list(self._motos.items()):
            if ahora - moto["ultima_mono"] < Config.YOLO_TRACK_PERDIDO_SEG:
                continue
            del self._motos[numero]
            if not moto["anunciada"]:
                continue  # muy pocos fotogramas: probablemente una detección falsa
            if moto["qr"]:
                self.contadores["identificadas"] += 1
                self._evento("ok", f"Moto #{numero} salió de la imagen · identificada")
            else:
                self._evento("alerta", f"Moto #{numero} salió de la imagen SIN QR")
            if self.carga_id is not None:
                self._cola.put(("moto", self.carga_id, moto))

    # -- vista en vivo -------------------------------------------------------
    def _jpeg_vista(self, frame, ahora):
        frame = frame.copy()
        for moto in list(self._motos.values()):
            if ahora - moto["ultima_mono"] > 0.8:
                continue
            x1, y1, x2, y2 = moto["caja"]
            color = COLOR_MOTO_OK if moto["qr"] else COLOR_MOTO
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            etiqueta = f"MOTO #{moto['numero']} {moto['confianza']:.0%}" + (" QR OK" if moto["qr"] else "")
            (tw, th), _ = cv2.getTextSize(etiqueta, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x1, max(0, y1 - th - 10)), (x1 + tw + 10, y1), color, -1)
            cv2.putText(frame, etiqueta, (x1 + 5, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        marcas, momento = self._qr_marcas
        if marcas and ahora - momento < 0.8:
            for pts, texto in marcas:
                color = COLORES.get(self._resultado_qr.get(texto), (0, 220, 255))
                cv2.polylines(frame, [pts], True, color, 4)

        yolo = self.yolo
        if yolo["estado"] == "ACTIVO":
            hud = f"YOLO {yolo['dispositivo']} {yolo['fps']} fps"
        else:
            hud = "YOLO no disponible"
        hud += f" | motos: {self.contadores['motos_vistas']} | QR: {self.contadores['qr_leidos']}"
        hud += " | CARGA" if self.carga_id else " | MONITOREO"
        cv2.rectangle(frame, (0, 0), (frame.shape[1], 34), (0, 0, 0), -1)
        cv2.putText(frame, hud, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

        alto, ancho = frame.shape[:2]
        if ancho > 960:
            frame = cv2.resize(frame, (960, int(alto * 960 / ancho)))
        return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()

    def fotogramas(self):
        ultimo = None
        while not self._parar.is_set():
            self.ultimo_uso = time.monotonic()
            with self._nuevo:
                if self.jpeg is ultimo:
                    self._nuevo.wait(timeout=2)
                jpeg = self.jpeg
            if jpeg is ultimo:
                continue
            ultimo = jpeg
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

    # -- hilo de registro en la base -------------------------------------------
    def _procesar_cola(self):
        while True:
            item = self._cola.get()
            if item is None:
                return
            try:
                if item[0] == "qr":
                    self._registrar_qr(*item[1:])
                else:
                    self._registrar_moto(*item[1:])
            except Exception:  # noqa: BLE001 — p. ej. se cayó la conexión a internet
                log.exception("Error guardando en la base (cámara %s)", self.camara_id)
                self._evento("error", "No se pudo guardar en la base de datos; se reintentará con la próxima lectura")
                if item[0] == "qr":
                    self._vistos.pop(item[2], None)

    def _registrar_qr(self, carga_id, texto, frame, pts, track_id):
        self._resultado_qr[texto] = "PROCESANDO"
        cv2.polylines(frame, [pts], True, (0, 220, 255), 4)
        foto = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        try:
            r = lecturas.registrar_lectura(carga_id, texto, self.camara_id, foto_jpeg=foto, track_id=track_id)
        except lecturas.ErrorCarga as err:
            r = {"resultado": "ERROR", "mensaje": str(err)}
        self._resultado_qr[texto] = r["resultado"]
        self.ultimas.appendleft({"hora": _hora(), **r})
        tipo = {"VALIDA": "ok", "DUPLICADA": "aviso"}.get(r["resultado"], "alerta")
        self._evento(tipo, r["mensaje"] if r["resultado"] == "DUPLICADA" else f"{r['resultado'].replace('_', ' ')}: {r['mensaje']}")

    def _registrar_moto(self, carga_id, moto):
        foto = None
        if moto["foto"] is not None:
            imagen = moto["foto"].copy()
            x1, y1, x2, y2 = moto["caja"]
            cv2.rectangle(imagen, (x1, y1), (x2, y2), COLOR_MOTO_OK if moto["qr"] else (40, 40, 230), 4)
            foto = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        r = lecturas.registrar_deteccion(carga_id, self.camara_id, moto, foto)
        if r.get("estado") == "SIN_IDENTIFICAR":
            self.contadores["sin_identificar"] += 1
            self._evento("alerta", f"⚠ Alerta enviada: la moto #{moto['numero']} subió sin identificar")

    # -- estado para las pantallas ---------------------------------------------
    def resumen(self):
        self.ultimo_uso = time.monotonic()
        ahora = time.monotonic()
        motos = [
            {"numero": m["numero"], "confianza": m["confianza"], "identificada": bool(m["qr"]),
             "qr": m["qr"], "segundos": round(ahora - m["ultima_mono"], 1)}
            for m in list(self._motos.values()) if m["anunciada"]
        ]
        return {
            "estado": self.estado, "error": self.error, "carga_id": self.carga_id,
            "yolo": dict(self.yolo), "contadores": dict(self.contadores),
            "motos_en_imagen": sorted(motos, key=lambda m: m["numero"]),
            "eventos": list(self.eventos)[:40], "ultimas": list(self.ultimas),
        }


class Gestor:
    def __init__(self):
        self._trabajadores = {}
        self._lock = threading.Lock()
        threading.Thread(target=self._apagar_inactivas, daemon=True, name="camaras-inactivas").start()

    def iniciar(self, camara_id, fuente, carga_id=None):
        """Arranca la cámara (o reutiliza la que ya está abierta) en modo carga o monitoreo."""
        with self._lock:
            actual = self._trabajadores.get(camara_id)
            if actual and not actual.detenido:
                if actual.fuente == fuente:
                    actual.asignar_carga(carga_id)
                    actual.ultimo_uso = time.monotonic()
                    return actual
                actual.detener()
            t = Trabajador(camara_id, fuente, carga_id)
            self._trabajadores[camara_id] = t
            t.start()
            return t

    def liberar(self, camara_id):
        """La carga terminó: la cámara sigue en modo monitoreo (se apaga sola si nadie la ve)."""
        t = self.trabajador(camara_id)
        if t:
            t.asignar_carga(None)
            t.ultimo_uso = time.monotonic()

    def detener(self, camara_id):
        with self._lock:
            t = self._trabajadores.pop(camara_id, None)
        if t:
            t.detener()

    def trabajador(self, camara_id):
        t = self._trabajadores.get(camara_id)
        return t if t and not t.detenido else None

    def estado(self, camara_id):
        t = self.trabajador(camara_id)
        if not t:
            return {"estado": "APAGADA", "error": None, "ultimas": [], "yolo": None, "contadores": None}
        return {"estado": t.estado, "error": t.error, "ultimas": list(t.ultimas),
                "yolo": dict(t.yolo), "contadores": dict(t.contadores)}

    def resumen(self, camara_id):
        t = self.trabajador(camara_id)
        return t.resumen() if t else {"estado": "APAGADA"}

    def captura(self, fuente, camara_id=None):
        """Una foto para probar la cámara desde el panel de administración."""
        t = self.trabajador(camara_id) if camara_id else None
        if t:
            return t.jpeg
        cap = _abrir(fuente)
        try:
            if not cap.isOpened():
                return None
            ok, frame = False, None
            for _ in range(5):  # las primeras imágenes de algunas cámaras salen negras
                ok, frame = cap.read()
            return cv2.imencode(".jpg", frame)[1].tobytes() if ok else None
        finally:
            cap.release()

    def _apagar_inactivas(self):
        while True:
            time.sleep(10)
            for camara_id, t in list(self._trabajadores.items()):
                if t.carga_id is None and time.monotonic() - t.ultimo_uso > Config.MONITOREO_INACTIVO_SEG:
                    log.info("Apagando la cámara %s: nadie la está viendo", camara_id)
                    self.detener(camara_id)

    def reanudar_cargas_en_proceso(self):
        filas = db.ejecutar(
            db.tabla("v_cargas").select("id, camara_id, camara_fuente")
            .eq("estado", "EN_CARGA").eq("camara_activa", True)
        )
        for f in filas:
            log.info("Reanudando cámara %s para la carga %s", f["camara_id"], f["id"])
            self.iniciar(f["camara_id"], descifrar(f["camara_fuente"]), f["id"])


gestor = Gestor()
