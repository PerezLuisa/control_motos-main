import secrets
import sys

import httpx
from flask import Flask, render_template

from . import cifrado, db
from .config import ENV, FRONTEND, RAIZ, Config


def create_app():
    app = Flask(__name__, template_folder=str(FRONTEND / "templates"), static_folder=str(FRONTEND / "static"))
    app.config.from_object(Config)

    if not ENV.exists():
        if (RAIZ / ".env").exists():
            sys.exit("✖ El archivo .env está en la raíz del proyecto. Muévalo a la carpeta backend/.")
        sys.exit("✖ Falta backend/.env. Copie backend/.env.example como backend/.env y complételo.")
    if not app.config["SUPABASE_URL"] or not app.config["SUPABASE_SECRET_KEY"]:
        sys.exit("✖ Falta la conexión a Supabase: complete SUPABASE_URL y SUPABASE_SECRET_KEY en backend/.env.")
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        print("⚠ SECRET_KEY vacía en .env: se usa una temporal (las sesiones se cierran al reiniciar).")

    if not app.config["ENCRYPTION_KEY"]:
        sys.exit(
            "✖ Falta ENCRYPTION_KEY en backend/.env (cifra los datos sensibles). Genérela con:\n"
            '  py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        cifrado.iniciar(app.config["ENCRYPTION_KEY"])
        db.iniciar(app.config["SUPABASE_URL"], app.config["SUPABASE_SECRET_KEY"])
    except (cifrado.ErrorCifrado, db.ErrorConexion) as err:
        sys.exit(f"✖ {err}")

    from . import admin, alertas, auth, cargas, etiquetas, evidencias, migracion, monitoreo, principal, seguridad

    migracion.cifrar_datos_existentes()
    evidencias.asegurar_bucket()  # fotos de evidencia en Supabase Storage (bucket privado)

    seguridad.registrar(app)
    auth.registrar(app)
    for bp in (auth.bp, principal.bp, cargas.bp, monitoreo.bp, etiquetas.bp, alertas.bp, admin.bp):
        app.register_blueprint(bp)
    app.jinja_env.globals["app_nombre"] = app.config["APP_NOMBRE"]

    @app.errorhandler(403)
    def prohibido(_):
        return render_template("error.html", codigo=403, mensaje="No tiene permiso para ver esta página."), 403

    @app.errorhandler(404)
    def no_encontrado(_):
        return render_template("error.html", codigo=404, mensaje="La página no existe."), 404

    @app.errorhandler(413)
    def muy_grande(_):
        return render_template("error.html", codigo=413, mensaje="El archivo supera los 10 MB."), 413

    @app.errorhandler(db.ErrorBD)
    @app.errorhandler(httpx.HTTPError)
    def sin_base_de_datos(err):
        app.logger.error("Error con Supabase: %s", err)
        return render_template("error.html", codigo=503,
                               mensaje="No se pudo comunicar con la base de datos. Intente de nuevo en unos segundos."), 503

    # Si el servidor se reinició con cargas en proceso, las cámaras vuelven a leer
    from .camaras import gestor

    gestor.reanudar_cargas_en_proceso()
    return app
