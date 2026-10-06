"""
Interpretación del contenido de los QR de las motos.

El QR puede traer varios datos juntos, en cualquier orden y con cualquier separador.
Ejemplos válidos:
    7700149546881|SN-1-1                    (formato de las etiquetas del sistema)
    ART:7700149546881;SERIE:0001
    {"articulo": "7700149546881", "serie": "0001"}
    7700149546881                            (solo el artículo)
Cada dato se compara con el ARTÍCULO de las motos de la carga.
"""
import json
import re

_SEPARADORES = re.compile(r"[|;,\t\r\n]+")


def candidatos(contenido):
    """Posibles códigos de artículo dentro del texto del QR, en mayúsculas."""
    texto = (contenido or "").strip()
    partes = []
    try:
        datos = json.loads(texto)
        if isinstance(datos, dict):
            partes = [str(v) for v in datos.values()]
        elif isinstance(datos, list):
            partes = [str(v) for v in datos]
    except (ValueError, TypeError):
        pass

    if not partes:
        for parte in _SEPARADORES.split(texto):
            # "ART: XXXX" o "SERIE=YYYY" -> se toma el valor
            if ":" in parte or "=" in parte:
                parte = re.split(r"[:=]", parte, maxsplit=1)[1]
            partes.append(parte)

    resultado = {p.strip().upper().replace(" ", "") for p in partes}
    resultado.add(texto.upper().replace(" ", ""))  # QR con solo el artículo
    return sorted(t for t in resultado if len(t) >= 5)
