# Control de Carga de Motos

## ¿Qué es?

Una aplicación web que **verifica con una cámara que todas las motos de un despacho se
suban al camión**. Una cámara ubicada encima del camión detecta cada moto con
inteligencia artificial (YOLO), la sigue mientras sube (*tracking*) y lee el código QR que
lleva pegado. Cada QR se compara con el archivo de la carga del día y la moto queda
registrada como **cargada**.

## ¿Para qué sirve?

Para evitar que se pierdan motos entre el almacén y el destino. Ejemplo: se deben
despachar 500 motos y en el destino solo llegan 480. Con el sistema:

- se sabe **en tiempo real** qué motos subieron al camión y cuáles faltan;
- si sube una moto **de otra carga**, **una de más** o **una sin identificar** (sin QR),
  se genera una alerta en el momento, con **foto de evidencia**;
- si un QR **ya se usó**, avisa: *«QR ya usado y moto ya cargada en el camión»*;
- al finalizar, si **faltaron motos**, la carga queda **INCOMPLETA** y se crea una alerta
  **crítica** con la lista exacta de las motos que no subieron;
- queda un **reporte** descargable de cada carga.

Sirve para cualquier marca de motos (el nombre se configura con `APP_NOMBRE`).

---

## Cambios nuevos

Esta versión reemplaza el prototipo inicial (Node.js + Vue con RFID y YOLO simulados) por
un sistema completo:

| Área | Qué cambió |
|---|---|
| **Backend** | Reescrito en **Python + Flask**. Se inicia con `py app.py`. |
| **Base de datos** | **Supabase** (PostgreSQL). Un solo script definitivo: `BASE_FINAL.sql`. La lógica crítica (lecturas, cierre de cargas, sesiones) corre en funciones SQL atómicas. |
| **Detección** | Cámara real (USB, IP/RTSP o video) con **YOLO + tracking (ByteTrack)** en GPU NVIDIA o CPU, y lectura de **QR** con OpenCV. |
| **Validación** | Resultados por QR: **válida**, **QR ya usado**, **sobrante** (una unidad de más), **otra carga** (¡no subir!) y **no pertenece**. Moto vista por YOLO sin QR → **sin identificar**. |
| **Solo cámara** | No existe registro manual: ninguna moto se puede digitar; todo lo detecta la cámara. |
| **Cargas** | Se importa el archivo **REFRENCIAS MOTOS AKT.xlsx** (Artículo, Marca, Descripción, COD INT). Una carga se puede **iniciar, pausar, reanudar, finalizar y cancelar**. |
| **Monitoreo en vivo** | Pantalla con la cámara, los recuadros de YOLO, las motos en la imagen, contadores y bitácora en tiempo real. |
| **Evidencias** | Las fotos se guardan en **Supabase Storage** (bucket privado `evidencias`), enlazadas a su lectura o alerta. |
| **Login y roles** | Registro e inicio de sesión en la base. **Empleado** (opera todo) y **Administrador** (solo administración). Registrar un administrador exige la clave del **super admin**. |
| **Sesión única** | Un usuario no puede tener sesión abierta en dos equipos. La sesión se cierra al cerrar el navegador. |
| **Seguridad** | Contraseñas con **scrypt**, token de sesión con **SHA-256**; correo, IP, navegador, conductor y fuente de la cámara **cifrados** (Fernet, librería `cryptography`); protección CSRF; la clave pública de Supabase no puede leer nada. |
| **Interfaz** | Diseño nuevo, marca neutral, login con ilustración propia, adaptable a celular. |
| **Generador de QR** | Etiquetas imprimibles con el QR de cada moto de una carga, y QR libre para pruebas. |

---

## Estructura

```
backend/
  app.py              arranque del servidor
  requirements.txt    dependencias de Python
  .env.example        plantilla de configuración (el .env real NO se sube a git)
  modelos/yolov8n.pt  modelo YOLO
  control_carga/      código del servidor
frontend/
  templates/          pantallas (Jinja)
  static/             estilos, JavaScript e imágenes
BASE_FINAL.sql        base de datos completa para Supabase
```

## Instalación

**1. Base de datos.** En Supabase → **SQL Editor** → pegue todo [`BASE_FINAL.sql`](BASE_FINAL.sql)
→ **Run**. Se puede ejecutar varias veces sin borrar datos. El bucket privado de
evidencias lo crea la app sola al arrancar.

**2. Backend** (Símbolo del sistema / cmd):

```bat
cd backend
py -m venv .venv
.venv\Scripts\activate.bat
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
copy .env.example .env
```

La línea de `torch` instala PyTorch con soporte para GPU NVIDIA; en un PC sin GPU NVIDIA
omítala. Luego complete `backend\.env`:

- `SUPABASE_URL` y `SUPABASE_SECRET_KEY`: Supabase → **Project Settings → API Keys**.
- `SECRET_KEY`: `py -c "import secrets; print(secrets.token_hex(32))"`
- `ENCRYPTION_KEY`: `py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
  **Guárdela en un lugar seguro**: si se pierde, los datos cifrados no se recuperan.

**3. Ejecutar** (cada vez):

```bat
cd backend
.venv\Scripts\activate.bat
py app.py
```

Abra **http://localhost:5173**. Por ahora corre solo en este PC (`HOST=127.0.0.1`); en el
servidor oficial se cambia a `HOST=0.0.0.0` para que entren otros equipos de la red.

## Usuarios y roles

Al registrarse se elige el tipo de usuario:

- **Empleado**: opera todo el sistema. Importa el archivo, inicia, pausa, reanuda,
  finaliza y cancela cargas, genera QR, ve el monitoreo en vivo y recibe las alertas.
- **Administrador** (el registro pide la **contraseña del super administrador**, con un
  máximo de 5 intentos fallidos cada 10 minutos). Solo puede:
  - cambiar la contraseña de los empleados;
  - dar o quitar el rol de administrador;
  - activar o desactivar usuarios;
  - cerrar la sesión de alguien (por ejemplo, si la dejó abierta en otro PC);
  - configurar las cámaras (USB, IP o video de prueba).

  Al iniciar sesión entra directo a *Administración*. Si hay SMTP configurado, las alertas
  críticas también le llegan por correo.

El super administrador está en la tabla `super_admin` (usuario `superadmin`); solo se
guarda el hash de su contraseña, que se entrega por aparte al responsable.

## Flujo de trabajo diario

1. **Importar**: subir el archivo **REFRENCIAS MOTOS AKT.xlsx** del camión. El código de
   la carga se genera solo (`CARGA-AAAAMMDD-01`) o se escribe en el formulario.
2. **Iniciar carga**: elegir la cámara del muelle.
3. Mientras las motos suben, la cámara las detecta y lee su QR:
   - **VÁLIDA** (verde): la moto es de esta carga → queda *CARGADA*.
   - **QR YA USADO** (naranja): esa moto ya estaba cargada en el camión.
   - **SOBRANTE** (rojo): ya se cargaron todas las unidades de esa referencia.
   - **OTRA CARGA** (rojo): la moto es de otra carga → ¡no debe subir a este camión!
   - **NO PERTENECE**: QR desconocido.
   - **SIN IDENTIFICAR**: YOLO vio pasar una moto y no se leyó su QR.
4. **Pausar / reanudar**: *Pausar carga* conserva lo cargado; *Reanudar carga* sigue con
   las motos que faltan (también sirve para una carga que se finalizó incompleta).
5. **Finalizar carga**: se compara con el archivo. Si faltan motos queda **INCOMPLETA** y se
   crea una alerta **crítica** con la lista de las que no subieron.

## El archivo de la carga

Se llama **REFRENCIAS MOTOS AKT.xlsx** (también se acepta en CSV) y siempre tiene estas
4 columnas. **Cada fila es una moto**; si un artículo se repite, son varias unidades.

| Artículo | Marca | Descripción | COD INT |
|---|---|---|---|
| 7700149546881 | AKT | Moto AK125TTR CBS G/N/V 26 PT | AK125TTR EIII |
| 7700149447294 | AKT-VOGE | Moto VOGE300Rally Ng/Mt 26 PT | 300RALLY |

## El QR de cada moto

Lleva el **artículo** y, recomendado, un número de serie para distinguir dos motos de la
misma referencia (así lo generan las etiquetas del sistema): `7700149546881|SN-1-1`.

La cámara cuenta una lectura nueva cada vez que el QR aparece; si desaparece de la imagen
al menos `QR_NUEVA_LECTURA_SEG` segundos y vuelve, se lee otra vez (así se detecta el
*QR ya usado*).

## Cámaras

Se configuran en *Administración → Cámaras*. La fuente puede ser `0`, `1`… (USB),
`rtsp://usuario:clave@ip:554/stream` (cámara IP) o la ruta a un video. Con **Probar** se
ve una foto de la cámara. Recomendado: buena luz, QR de al menos 8×8 cm y cámara 1080p.

## Generar QR para pruebas

Menú **Generar QR** (empleados):

- **Etiquetas de una carga**: hoja imprimible con el QR de cada moto.
- **QR libre**: escriba un texto (p. ej. `7700149546881|SN-PRUEBA-01`) y descargue su imagen
  para mostrarla desde el celular a la cámara.

## Seguridad de los datos

| Dato | Cómo se guarda |
|---|---|
| Contraseñas de usuarios y del super admin | hash **scrypt** (irreversible) |
| Token de la sesión | hash **SHA-256** (la cookie tiene el token; la base, solo su hash) |
| Correo, IP y navegador de la sesión, conductor, fuente de la cámara | cifrado **Fernet** con `ENCRYPTION_KEY` |
| Correo (para evitar duplicados) | huella **HMAC-SHA256** |
| Fotos de evidencia | **Supabase Storage**, bucket privado (solo el backend las lee) |

En Supabase todas las tablas tienen RLS activo y la clave pública no tiene permisos: solo
el backend, con la clave secreta, puede leer y escribir.

## Código del servidor

    backend/control_carga/
      __init__.py        crea la app y valida la configuración
      auth.py            login, registro con rol, super admin, sesión única, permisos
      admin.py           usuarios, contraseñas, sesiones y cámaras
      cargas.py          importar, iniciar, pausar, finalizar, pantalla de la carga
      lecturas.py        reglas de cada lectura QR y de cada detección YOLO
      camaras.py         cámara: YOLO + tracking + QR y vista en vivo (3 hilos por cámara)
      vision.py          detector YOLO de motos (GPU/CPU)
      monitoreo.py       pantalla de monitoreo en vivo
      evidencias.py      fotos en Supabase Storage
      etiquetas.py       generador de QR y etiquetas imprimibles
      alertas.py         alertas para los empleados
      notificaciones.py  correo de alertas críticas (opcional)
      importador.py      lectura del archivo REFRENCIAS MOTOS AKT
      cifrado.py         cifrado Fernet, huellas HMAC y hash de tokens
      migracion.py       cifra datos antiguos en texto plano al arrancar
      db.py              acceso a Supabase
      qr.py              interpretación del contenido del QR
      seguridad.py       CSRF y formatos de fecha
      config.py          configuración desde backend/.env
