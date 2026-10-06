"""
Protección de datos sensibles en la base de datos (librería cryptography).

  cifrar / descifrar   datos que hay que poder leer (correo, IP, navegador, conductor,
                       fuente de la cámara con su usuario y clave RTSP) -> Fernet (AES + HMAC)
  huella               índice ciego para buscar/validar duplicados sin guardar el dato en claro
                       (p. ej. el correo) -> HMAC-SHA256
  hash_token           tokens de sesión: en la base solo queda su SHA-256

Las contraseñas se guardan con scrypt (werkzeug) y nunca se pueden descifrar.
La clave ENCRYPTION_KEY vive solo en backend/.env: si se pierde, lo cifrado no se recupera.
"""
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

_PREFIJO_FERNET = "gAAAAA"  # todo texto cifrado con Fernet empieza así
_fernet = None
_clave_huella = None


class ErrorCifrado(Exception):
    pass


def iniciar(clave):
    global _fernet, _clave_huella
    try:
        _fernet = Fernet(clave.encode() if isinstance(clave, str) else clave)
    except (ValueError, TypeError) as err:
        raise ErrorCifrado(
            "ENCRYPTION_KEY no es válida. Genere una con:\n"
            '  py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        ) from err
    _clave_huella = hashlib.sha256(b"huella:" + clave.encode()).digest()


def esta_cifrado(valor):
    return isinstance(valor, str) and valor.startswith(_PREFIJO_FERNET)


def cifrar(texto):
    if texto is None or texto == "":
        return None
    return _fernet.encrypt(str(texto).encode()).decode()


def descifrar(valor):
    """Devuelve el texto original. Un valor antiguo sin cifrar se devuelve tal cual."""
    if not esta_cifrado(valor):
        return valor
    try:
        return _fernet.decrypt(valor.encode()).decode()
    except InvalidToken:
        return "[no se pudo descifrar]"


def huella(texto):
    if not texto:
        return None
    normalizado = str(texto).strip().lower().encode()
    return hmac.new(_clave_huella, normalizado, hashlib.sha256).hexdigest()


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()
