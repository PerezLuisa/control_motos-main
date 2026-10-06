"""
Sistema de Control de Carga de Motos — servidor.

    cd backend
    py app.py

Abre http://localhost:5173
"""
import socket

from control_carga import create_app

app = create_app()


def _ip_local():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


if __name__ == "__main__":
    host, port = app.config["HOST"], app.config["PORT"]
    print(f"\n=== {app.config['APP_NOMBRE']} ===")
    print(f"  En este PC:     http://localhost:{port}")
    ip = _ip_local()
    if host == "0.0.0.0" and ip:
        print(f"  Desde otro PC:  http://{ip}:{port}")
    print("  Ctrl+C para detener\n")
    app.run(host=host, port=port, threaded=True, debug=app.config["DEBUG"], use_reloader=False)
