# Revisión técnica completa — 2026-09-03

Revisión de todo el proyecto hecha con Claude Fable 5.1 sobre el commit `4b702b5`
("MVP de captación de reseñas NFC/QR con panel e informe mensual"), el primero subido a
`github.com/ali-acosta/nfc-review-analytics`.

**Este documento es de lectura obligatoria al retomar el trabajo**, junto con
[ROADMAP.md](../ROADMAP.md) y [CLAUDE.md](../CLAUDE.md). Contiene el veredicto, cada hallazgo
con su corrección y su test, lo que está bien y no hay que "arreglar", el orden de trabajo
recomendado y los próximos desarrollos.

---

## 0. Cómo usar este documento

- Cada hallazgo tiene un identificador (`C1`, `I3`, `M7`, `N2`) y una casilla. Al resolverlo,
  marcar `[x]` y anotar el commit al lado. Así la próxima sesión sabe qué queda.
- Las referencias `archivo:línea` corresponden al estado del 2026-09-03. Las líneas se mueven;
  el archivo y la función no.
- La sección 3 ("Lo que está bien") existe para que ningún modelo ni persona "simplifique" algo
  que está así por una razón. Leerla antes de refactorizar.
- La sección 8 es el plan. La 9 son ideas de producto para después del plan.

---

## 1. Alcance y método

**Se leyó el 100 % del código**: `app/` completo (config, database, models, main, middleware,
logging, los tres routers, los diez servicios, el panel Dash, las cinco plantillas, el CSS y el
JS), las cuatro migraciones y `env.py`, los seis scripts, los quince archivos de tests, los dos
workflows de GitHub Actions, `render.yaml`, `requirements*.txt`, `.env.example`, `alembic.ini`,
`README.md`, `ROADMAP.md` y `CLAUDE.md`.

**Se ejecutó la suite completa**: 149 tests, todos pasan, 34 segundos. Un único warning de
deprecación de Starlette sobre `httpx` en el `TestClient`, sin efecto.

**Se verificaron contra fuentes externas** los tres hechos de los que dependen hallazgos y que
no se pueden comprobar leyendo código: cómo maneja Render la cabecera `X-Forwarded-For`, la
política de pausa del plan gratuito de Supabase y el estado de la política de reseñas de Google
tras los cambios de abril de 2026. Las fuentes están en la sección 10.

**Se inspeccionó la base de datos local** (`nfc_analytics.db`): un negocio, 1919 taps, versión
de Alembic `53f661c21212` (la última). Las credenciales de demo existen solo ahí (ver `I4`).

### Versiones al momento de la revisión

| Componente | Local | CI / Render |
|---|---|---|
| Python | 3.10.0 | 3.12 |
| FastAPI / Starlette | 0.141.1 / 1.6.0 | igual (sin pin exacto) |
| Dash / Plotly | 2.18.2 / 7.0.0 | igual |
| SQLAlchemy / Alembic | 2.0.52 / 1.19.1 | igual |
| pandas | 2.3.3 | igual |
| a2wsgi / httpx / uvicorn | 1.10.10 / 0.28.1 / 0.52.4 | igual |

---

## 2. Veredicto

**El proyecto va bien encausado.** La arquitectura y las decisiones de fondo son correctas y
no se cambiarían: un token por soporte físico, la métrica en un único módulo, UTC en disco y
hora local al agrupar, migraciones desde el primer cliente, un middleware que descarta la
cabecera de identidad antes de inyectar la propia, dos niveles de manejo de errores en las
alertas. Los tests protegen exactamente los invariantes que sostienen el negocio.

**El problema no es la dirección sino un punto ciego**: hay cuatro fallas que solo aparecen en
producción y que la suite actual no puede ver, porque los tests corren únicamente sobre SQLite,
sin proxy delante y sin GitHub Actions. Tres de ellas son la misma clase de bug que ya mordió
una vez con `UtcDateTime`: SQLite es permisivo, Postgres no, y el código se prueba solo en el
permisivo.

En una frase: **el código está listo para un cliente de demo; le faltan cuatro correcciones
acotadas y una base de datos real en CI para estar listo para un cliente que paga.**

---

## 3. Lo que está bien y NO hay que "arreglar"

Cada punto tiene una razón que no es visible en el código. Si alguien propone cambiar uno de
estos, la respuesta correcta es "por qué está así" antes que "cómo lo cambio".

- **Sin filtro por estrellas antes del botón de Google.** Google prohíbe la solicitud selectiva
  y en abril de 2026 endureció la detección con herramientas automáticas. El test
  `tests/test_flow.py::TestPoliticaDeGoogle` falla si reaparece un selector. No reintroducirlo
  "para mejorar la conversión": el riesgo es la suspensión del perfil del cliente.
- **Un token por soporte físico, aleatorio y no enumerable.** Es lo que permite responder "qué
  placa convierte mejor", y es imposible de retrofitear una vez pegada la placa.
- **`app/services/metrics.py` es la única fuente de números.** Panel, informe y resumen mensual
  leen de ahí. La conversión se calcula sobre sesiones únicas con `nunique()`, nunca contando
  filas. Un intento anterior de contar filas topó la métrica en 50 %.
- **La carrera en `_already_logged` es inofensiva y no hay que "cerrarla" contando filas.** Dos
  peticiones simultáneas de la misma sesión pueden insertar dos filas iguales. La métrica no se
  entera porque cuenta sesiones. Si algún día se quiere una restricción única en
  `(session_id, placement_id, outcome)`, ver `M13`; si se hace, usar `on_conflict_do_nothing`
  y no un `try/except` alrededor del commit.
- **`UtcDateTime` y el agrupamiento en hora local.** SQLite descarta la zona horaria en
  silencio y Postgres la convierte: el mismo código daba números distintos en desarrollo y
  producción. Los tests de `tests/test_horario.py` cubren la cena que cruza medianoche UTC y el
  último día del mes.
- **`DashboardAuthMiddleware` es ASGI puro y descarta la cabecera `x-business-id` del cliente
  antes de poner la suya.** Sin eso cualquiera vería el panel de otro comercio.
  `tests/test_auth.py::TestAislamientoEntreClientes` prueba el ataque. El orden de
  `add_middleware` en `app/main.py` es deliberado: `SessionMiddleware` se agrega último para
  quedar más afuera y que `scope["session"]` exista cuando corre el de autenticación.
- **El límite público degrada la métrica y nunca la experiencia.** Los clientes de un local
  comparten la IP del WiFi; un 429 ahí rompe un almuerzo. El login sí bloquea de verdad. Esto
  sigue siendo correcto; lo que está mal es cómo se obtiene la IP (`C1`).
- **Dos niveles de errores en las alertas.** `send_alert` traga todo y no devuelve nada, porque
  corre dentro del flujo de un cliente. `send_message`, `send_document` y `send_email`
  devuelven `bool`, porque su llamador es el envío mensual y tiene que reportar fallos. No
  unificarlos.
- **WeasyPrint importado de forma perezosa y fuera de `requirements.txt`.** Sus librerías
  nativas no cargan en Windows y no están garantizadas en el hosting. Un build que falla es
  peor que un PDF que falta. El workflow mensual las instala él mismo.
- **`render_item` en `migrations/env.py`.** Sin él, autogenerate escribe
  `app.models.UtcDateTime()` en la migración y el upgrade revienta con `NameError`.
- **`server_default` en columnas `NOT NULL` nuevas.** Autogenerate no lo pone y la migración
  falla en cualquier tabla con filas. Ya pasó una vez (`cdd115ca0d87`).
- **CSP estricta solo en páginas públicas, `landing.js` en archivo aparte,
  `Referrer-Policy` en todas las respuestas.** Dash genera scripts en línea y una CSP estricta
  lo rompe; el panel está detrás de login. Sin `Referrer-Policy`, al ir a Google el navegador
  enviaría la URL completa con el token de la placa.
- **`/health` no toca la base.** Un parpadeo de la base no debe hacer que el hosting reinicie
  un proceso sano. `/health/ready` sí la toca, para revisar a mano.
- **El enlace del informe no exige login.** Decisión del usuario del 2026-09-03 ("la menor
  fricción posible"). No reabrir; `I7` propone mitigaciones que respetan esa decisión.
- **`TIMEZONE` global.** Decisión del usuario del 2026-09-03; pasa a columna por negocio solo
  cuando exista un cliente fuera de Chile. Cómo hacerlo está en la sección 9.
- **`scrypt` de la biblioteca estándar en vez de Supabase Auth.** Sin dependencias ni terceros
  donde la biblioteca estándar alcanza. Comparación en tiempo constante con `hmac.compare_digest`.
- **`conftest.py` fija `DATABASE_URL` antes de importar `app`.** `app.config` y `app.database`
  construyen settings y engine en tiempo de import; sin eso la suite escribiría en la base real.
- **Todo script que imprime en consola de Windows reconfigura stdout a UTF-8.** El traceback de
  cp1252 llegaba después del commit y hacía parecer que la alta de cliente falló, invitando a
  crearlo dos veces.

---

## 4. Hallazgos críticos — rompen con el primer cliente real

### C1 · El límite por IP se salta con una cabecera `X-Forwarded-For`

- [x] **RESUELTO 2026-09-03.** `client_ip` lee la cadena de derecha a izquierda saltando IPs
  privadas. Tres tests nuevos en `TestIpDelCliente` más `TestNoSeEsquivaElLimiteFalsificandoLaCabecera`,
  que reproduce el ataque real contra el login.

**Dónde**: [app/services/ratelimit.py:69](../app/services/ratelimit.py#L69), función `client_ip`.

**Qué pasa**: se toma la *primera* IP de la lista de `X-Forwarded-For`. Render confirmó en su
foro público que **no borra ni reinicia esa cabecera, solo agrega al final** (ver sección 10).
Entonces, si el cliente manda `X-Forwarded-For: 1.2.3.4`, la app recibe `1.2.3.4, <ip real>` y
se queda con `1.2.3.4`. Un script que ponga una IP inventada distinta en cada petición nunca
comparte clave con la anterior y el limitador no lo ve jamás.

**Por qué importa**: anula las tres protecciones a la vez. La del panel es la grave: el límite
de 8 intentos por 15 minutos del login queda en nada y la contraseña de un cliente se puede
probar a ciegas sin freno. Las otras dos, visitas y comentarios, vuelven a ser inflables, que
es lo que el limitador existía para evitar.

**Además**: el test `tests/test_ratelimit.py::TestIpDelCliente::test_usa_x_forwarded_for_detras_del_proxy`
codifica el comportamiento equivocado: con `"200.1.2.3, 10.0.0.1"` espera `200.1.2.3`. Ese
caso solo es correcto si `10.0.0.1` fuera un segundo proxy, y sigue pasando con la corrección
de abajo porque `10.0.0.1` es privada. Hay que agregar el caso que hoy falta.

**Corrección**: recorrer la lista de derecha a izquierda y quedarse con la primera IP
**pública**. Lo que agregó el proxy propio está al final; lo que hay antes lo pudo escribir el
cliente. Las IPs privadas se saltan para tolerar saltos internos del hosting.

```python
import ipaddress


def _es_publica(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def client_ip(request) -> str:
    reenviada = request.headers.get("x-forwarded-for", "")
    if reenviada:
        # De derecha a izquierda: lo que agregó el proxy propio está al final,
        # lo que venga antes lo pudo escribir el cliente y no se le cree.
        for ip in reversed([p.strip() for p in reenviada.split(",")]):
            if _es_publica(ip):
                return ip
    return request.client.host if request.client else "desconocida"
```

Si Render alguna vez agregara un salto interno con IP pública, todos los visitantes caerían en
una sola clave. Eso degrada la métrica pero no es falsificable, que es el comportamiento
anterior a tener `X-Forwarded-For`. Es el fallo seguro.

**Tests a agregar** en `tests/test_ratelimit.py`:

```python
def test_ignora_lo_que_el_cliente_escribio_a_la_izquierda(self):
    class Req:
        headers = {"x-forwarded-for": "6.6.6.6, 200.1.2.3"}
        client = type("C", (), {"host": "10.0.0.1"})()

    assert client_ip(Req()) == "200.1.2.3"


def test_salta_los_saltos_internos_privados(self):
    class Req:
        headers = {"x-forwarded-for": "6.6.6.6, 200.1.2.3, 10.0.0.1"}
        client = type("C", (), {"host": "10.0.0.1"})()

    assert client_ip(Req()) == "200.1.2.3"
```

Y uno de extremo a extremo: con `login_limiter.max_hits = 2`, tres intentos fallidos con
cabeceras `X-Forwarded-For` de primera IP distinta y misma IP final deben terminar en 429.

---

### C2 · Postgres devolverá error 500 al cliente con un texto largo

- [x] **Corrección puntual RESUELTA 2026-09-03.** Recorte al escribir con los largos leídos del
  propio modelo, `maxlength` en el formulario y validación de `rating`. Cuatro tests nuevos en
  `TestLimitesDeLaBaseDeDatos`.
- [x] **Postgres en CI RESUELTO 2026-09-03.** `tests.yml` corre una matriz sqlite/postgres;
  `conftest.py` respeta `TEST_DATABASE_URL`. **Pendiente de verificación real**: no hay Docker ni
  Postgres en el equipo del usuario, así que la primera corrida contra Postgres ocurre en el
  próximo push a GitHub. Si algo falla ahí, es en estos tests donde va a aparecer.

**Dónde**: [app/models.py:141](../app/models.py#L141) (`message`, 2000),
[app/models.py:140](../app/models.py#L140) (`contact`, 255),
[app/models.py:116](../app/models.py#L116) (`user_agent`, 512). Se escriben desde
`submit_feedback` y `_log` en [app/routers/redirect.py](../app/routers/redirect.py).

**Qué pasa**: SQLite ignora el largo declarado en `String(n)`. Postgres lo aplica y lanza
`StringDataRightTruncation`. Un cliente enojado que escriba más de 2000 caracteres, o que
pegue un contacto de más de 255, verá una pantalla de error parado en el mostrador, después de
haberse tomado el trabajo de escribir. La plantilla no tiene `maxlength`, así que nada lo
frena antes. Un `user-agent` de más de 512 caracteres, que existe en algunos navegadores
embebidos de apps, haría fallar **cada carga de la landing** desde ese teléfono.

**Por qué importa**: es la misma clase de bug que `UtcDateTime`: desarrollo permisivo,
producción estricta, y la suite no lo ve. Y aparece justo en el momento en que el producto
tiene que funcionar sin falta.

**Corrección puntual**: recortar al escribir, con el largo tomado del modelo para que no
diverjan, y poner `maxlength` en el formulario. Validar `rating` de paso (`M7`).

```python
# app/routers/redirect.py
from app.models import Feedback, Tap

MAX_CONTACTO = Feedback.__table__.c.contact.type.length   # 255
MAX_MENSAJE = Feedback.__table__.c.message.type.length    # 2000
MAX_UA = Tap.__table__.c.user_agent.type.length           # 512

# en submit_feedback, antes de crear el Feedback:
contact = contact.strip()[:MAX_CONTACTO]
message = message.strip()[:MAX_MENSAJE]
if rating is not None and not 1 <= rating <= 5:
    rating = None

# en _log:
user_agent=user_agent[:MAX_UA],
```

```html
<!-- app/templates/landing.html -->
<input type="text" name="contact" maxlength="255" ... />
<textarea name="message" rows="4" maxlength="2000" ...></textarea>
```

**Test de regresión** en `tests/test_flow.py`: enviar un mensaje de 3000 caracteres y un
contacto de 400; la respuesta debe ser 200 y lo guardado debe medir 2000 y 255. Enviar
`rating=9` y comprobar que se guarda `None`. Cargar la landing con un `user-agent` de 700
caracteres y comprobar 200.

**Corrección estructural: correr la suite también sobre Postgres en CI.** Es gratis en GitHub
Actions y es lo único que hace que esta clase de bugs no vuelva. Hasta hoy la base de datos de
producción nunca ha ejecutado una sola línea de este proyecto.

```yaml
# .github/workflows/tests.yml
jobs:
  pytest:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        motor: [sqlite, postgres]
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: nfc
          POSTGRES_PASSWORD: nfc
          POSTGRES_DB: nfc_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U nfc"
          --health-interval 5s --health-timeout 5s --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements-dev.txt
      - run: pytest -q
        env:
          TEST_DATABASE_URL: ${{ matrix.motor == 'postgres' && 'postgresql+psycopg://nfc:nfc@localhost:5432/nfc_test' || '' }}
```

```python
# tests/conftest.py — respetar una base de prueba externa, nunca DATABASE_URL a secas
# (si el desarrollador la tuviera exportada en su shell, la suite escribiría en su base real)
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
```

`tests/test_migraciones.py` seguirá usando su SQLite temporal con `tmp_path`, que es correcto:
prueba las migraciones, no el motor. Todo lo demás funciona sobre ambos motores sin cambios.
Con esto, el test de regresión de arriba **falla en Postgres antes de la corrección y pasa
después**, que es la prueba de que el problema existía.

---

### C3 · El correo mensual no puede salir del workflow de GitHub Actions

- [x] **RESUELTO 2026-09-03.** Las cuatro variables SMTP en el workflow mensual y en `render.yaml`,
  más `env_ignore_empty=True` para que un secret vacío no tumbe el arranque. Tres tests nuevos en
  `TestLosCanalesDeAvisoLleganAProduccion`.

**Dónde**: [.github/workflows/informe-mensual.yml:48-52](../.github/workflows/informe-mensual.yml#L48-L52)
y [render.yaml:33-38](../render.yaml#L33-L38).

**Qué pasa**: el paso "Enviar" pasa al proceso solo `DATABASE_URL`, `BASE_URL`,
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`. Ninguna de las cinco variables `SMTP_*` se
referencia, así que configurarlas como secrets en GitHub no tendría ningún efecto:
`send_email` registrará "SMTP no configurado" y devolverá `False`, y el job saldrá con código 1
para cada cliente que solo tenga correo. El ROADMAP dice "falta configurar los secrets", pero
el problema es anterior: el workflow no los pide. `render.yaml` tampoco declara las variables
`SMTP_*`, así que el servidor web tampoco enviará la alerta de queja por correo salvo que
alguien las agregue a mano en el panel de Render.

**Por qué importa**: el propio ROADMAP describe el correo como el canal principal para un dueño
de pyme chileno, y la alerta de queja como la principal razón por la que un cliente sigue
pagando. Hoy ese canal no existe en producción.

**Corrección**:

```yaml
# .github/workflows/informe-mensual.yml, en env: del paso Enviar
          SMTP_HOST: ${{ secrets.SMTP_HOST }}
          SMTP_USER: ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
          SMTP_FROM: ${{ secrets.SMTP_FROM }}
```

```yaml
# render.yaml, en envVars:
      - key: SMTP_HOST
        sync: false
      - key: SMTP_USER
        sync: false
      - key: SMTP_PASSWORD
        sync: false
      - key: SMTP_FROM
        sync: false
```

**Cuidado con `SMTP_PORT`**: si se pasa desde un secret que no existe, llega como cadena vacía
y `pydantic-settings` falla al convertirla a entero, tirando abajo el proceso entero al
arrancar. Dos opciones: no pasar `SMTP_PORT` salvo que sea distinto de 587, o mejor, agregar
`env_ignore_empty=True` a `SettingsConfigDict` en [app/config.py](../app/config.py) para que
cualquier variable vacía use su valor por defecto. La segunda protege también a `render.yaml`,
donde una variable `sync: false` puede quedar vacía por descuido.

**Test de consistencia** en `tests/test_envio_mensual.py` o `tests/test_deploy.py`, con la
misma técnica que ya usa `test_env_example_documenta_todas_las_variables`: cada campo `smtp_*`
de `Settings` debe aparecer, en mayúsculas, en el workflow mensual y en `render.yaml`.

---

### C4 · La página de gracias no cuenta la conversión

- [x] **RESUELTO 2026-09-03.** El botón pasa por `/r/{token}/go`. Dos tests nuevos, incluido el
  caso completo de quien se queja y aun así va a Google.

**Dónde**: [app/templates/feedback_thanks.html:16](../app/templates/feedback_thanks.html#L16).

**Qué pasa**: el botón "Dejar reseña en Google" de la página de gracias enlaza directo a
`business.google_review_url` en vez de pasar por `/r/{token}/go`. Quien deja un comentario
privado y después decide ir igual a Google no queda registrado como `went_to_google`.

**Por qué importa**: es el número por el que paga el cliente, y se pierde justo en el caso que
más vale contar: un cliente que tuvo un problema, lo dijo en privado, y aun así fue a Google.

**Corrección**: en `submit_feedback` pasar `placement` al contexto de la plantilla y enlazar a
`/r/{{ placement.token }}/go`. La sesión ya existe, así que `/go` registrará la conversión
sobre la misma sesión que dejó el comentario, que es lo correcto.

**Test** en `tests/test_flow.py::TestCanalPrivado`: tras enviar el comentario, el HTML de
respuesta contiene `href="/r/{token}/go"`; el mismo cliente sigue ese enlace y
`metrics.funnel(...)["clicks"]` pasa a 1.

---

## 5. Hallazgos importantes — no urgentes, sí antes de escalar

### I1 · El panel muestra todo el histórico y el informe muestra un mes

- [x] **RESUELTO 2026-09-03.** Selector de período (Este mes / Mes pasado / Todo), con
  "Este mes" por defecto, y el período en el título. El buzón NO se filtra: una queja pendiente
  de hace dos meses sigue pendiente.

**Dónde**: [app/dashboard/dash_app.py:186](../app/dashboard/dash_app.py#L186), callback `refresh`.

**Qué pasa**: el panel carga `metrics.load_taps(business.id)` sin filtrar por período. Sus
KPIs son desde el primer día. El informe es mensual. El dueño ve "visitas únicas: 1900" en el
panel y "visitas únicas: 480" en el correo, y no hay ningún rótulo que explique la diferencia.
Los números sí salen de la misma fuente, pero sobre períodos distintos sin decirlo.

**Corrección**: un `dcc.RadioItems` con tres opciones, "Este mes", "Mes pasado" y "Todo", que
alimente el callback y filtre con `metrics.in_period` usando `metrics.month_bounds`. El título
del panel muestra el período elegido. Valor por defecto: "Este mes", porque es la semántica del
informe. Los gráficos y los KPIs usan el mismo filtro; la bandeja de quejas no se filtra, porque
una queja pendiente de hace dos meses sigue pendiente.

**Test** en `tests/test_bandeja.py` o uno nuevo: no hay forma barata de probar callbacks de
Dash de extremo a extremo; basta con extraer la función que arma los KPIs a partir de un
período y probarla directamente contra `metrics`.

---

### I2 · Cada refresco del panel y cada informe cargan la historia completa a pandas

- [x] **RESUELTO 2026-09-03.** `load_taps` y `load_feedback` aceptan límites y filtran en
  SQL, traduciendo la hora local a UTC. El informe hace una sola consulta que cubre el mes y el
  anterior. Tres tests nuevos, incluido que SQL y pandas dan idéntico resultado en el borde del mes.

**Dónde**: [app/services/metrics.py:43](../app/services/metrics.py#L43) `load_taps` y
`load_feedback`; llamados desde el panel cada 5 segundos por pestaña abierta y desde
`build_context` en [app/services/report.py](../app/services/report.py).

**Qué pasa**: no hay filtro de fecha en SQL; se trae todo y se filtra en pandas. Con 1900
filas de demo no se nota. Un local con tráfico real acumula del orden de 100 000 filas al año;
a dos años, cada pestaña abierta del panel moverá cientos de miles de filas cada 5 segundos, en
una instancia gratuita.

**Corrección**: `load_taps(business_id, start=None, end=None)` con los límites en hora local
convertidos a UTC antes de la consulta. `UtcDateTime` ya se encarga de la diferencia
SQLite/Postgres al comparar.

```python
from datetime import timezone
from zoneinfo import ZoneInfo


def _a_utc(local_sin_zona: datetime) -> datetime:
    return local_sin_zona.replace(tzinfo=ZoneInfo(settings.timezone)).astimezone(timezone.utc)


def load_taps(business_id: int, start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
    query = (
        select(Tap.created_at, Tap.session_id, Tap.outcome, Placement.label)
        .join(Placement, Tap.placement_id == Placement.id)
        .where(Tap.business_id == business_id, Tap.is_bot.is_(False))
    )
    if start is not None:
        query = query.where(Tap.created_at >= _a_utc(start))
    if end is not None:
        query = query.where(Tap.created_at < _a_utc(end))
    ...
```

El informe carga una sola vez el rango `[inicio del mes anterior, fin del mes)` y separa los
dos meses en pandas como hoy. `in_period` se mantiene como red de seguridad. El panel, con
`I1`, pide solo el período elegido. Junto con esto, subir `REFRESH_MS` de 5 a 60 segundos y
poner un botón "Actualizar" (`M14`).

**Test**: en `tests/test_metrics.py`, `load_taps` con límites devuelve solo lo del rango, y un
caso que cruce medianoche UTC (21:30 hora Chile del 31) queda en el mes correcto también por
SQL, no solo por pandas.

---

### I3 · El login revela por tiempo de respuesta qué correos son clientes

- [x] **RESUELTO 2026-09-03.** Hash señuelo calculado al importar; se verifica siempre.
  El test cuenta llamadas a `verify_password` en vez de medir tiempo.

**Dónde**: [app/routers/auth.py:55](../app/routers/auth.py#L55).

**Qué pasa**: `business is None or not verify_password(...)` hace cortocircuito. Un correo que
no existe responde sin calcular scrypt; uno que existe tarda decenas de milisegundos más. Lo
mismo con un negocio sin contraseña (hash vacío devuelve `False` de inmediato). El mensaje único
"correo o contraseña incorrectos" que se puso para no revelar quién es cliente queda anulado
por el reloj.

**Corrección**: verificar siempre contra un hash, real o señuelo, y decidir después.

```python
# app/routers/auth.py
import secrets
from app.services.auth import hash_password

_HASH_SENUELO = hash_password(secrets.token_urlsafe(16))  # calculado una vez al importar

# en login():
hash_a_probar = business.password_hash if (business and business.password_hash) else _HASH_SENUELO
clave_ok = verify_password(password, hash_a_probar)
if business is None or not business.password_hash or not clave_ok:
    ...  # mismo mensaje, mismo 401
```

**Test** en `tests/test_auth.py`: con `monkeypatch` contar las llamadas a `verify_password`;
tiene que ser exactamente una tanto para un correo inexistente como para uno existente con
clave mala. Medir tiempos en un test es frágil; contar llamadas no.

---

### I4 · Las credenciales de demo existen solo en la base de datos local

- [x] **RESUELTO 2026-09-03.** El seed las crea y también se las asigna a una demo antigua
  que hubiera quedado sin hash.

**Dónde**: [scripts/seed_demo_business.py](../scripts/seed_demo_business.py). `demo@cafe.cl /
demo1234` aparece en `README.md`, `ROADMAP.md` y `CLAUDE.md`, pero en ningún script; se
verificó con `grep` y consultando `nfc_analytics.db`, donde sí están.

**Qué pasa**: quien clone el repositorio y siga el README no podrá entrar al panel de demo. Y
si la base local se pierde, las credenciales se pierden con ella.

**Corrección**: en `seed_demo_business.py`, al crear el negocio poner `login_email`,
`alert_email` y `password_hash=hash_password("demo1234")`; si el negocio ya existe y no tiene
hash, asignárselo. Imprimir las credenciales en la salida. Eliminar la línea que imprime
`/dashboard/?t=...`, que ya no funciona (`M6`).

**Test** en `tests/test_operacion.py`: ejecutar `seed()` sobre la base de prueba y comprobar
que el login con `demo@cafe.cl / demo1234` responde 302 a `/dashboard/`.

---

### I5 · Supabase gratis se pausa a los 7 días sin actividad y no despierta solo

- [ ] Resuelto en: ______

**Dónde**: [render.yaml:8](../render.yaml#L8) y [.env.example:26](../.env.example#L26)
presentan "Supabase o Neon" como equivalentes.

**Qué pasa**: la documentación de Supabase confirma que un proyecto del plan gratuito se pausa
tras una semana sin actividad de base de datos y hay que reanudarlo a mano; tras un período
largo pausado, se elimina. Durante la validación, con cero clientes, el proyecto se pausará.
Con un cliente, un feriado largo basta. Un cliente tocando la placa contra una base pausada es
exactamente la restricción 5 de `CLAUDE.md`, aplicada a la base de datos. Neon también suspende
el cómputo tras unos minutos sin uso, pero **despierta solo en el orden de un segundo** al
recibir la primera consulta, que es aceptable.

**Corrección**: elegir Neon para la validación y decirlo en `render.yaml` y `.env.example`.
Cuando se firme el primer cliente y se pase a la instancia web de pago, evaluar también una
base con cómputo siempre encendido. Verificar las condiciones vigentes de ambos al momento de
decidir: cambian seguido.

---

### I6 · Python 3.10 en local, 3.12 en CI y en Render

- [ ] Resuelto en: ______

**Dónde**: `.venv` local es 3.10.0; `tests.yml`, `informe-mensual.yml` y `render.yaml` fijan 3.12.

**Qué pasa**: hoy no rompe nada. Es una diferencia más entre desarrollo y producción que no
aporta nada, en un proyecto que ya se quemó dos veces con ese tipo de diferencia.

**Corrección**: instalar Python 3.12 en el equipo y recrear `.venv` desde cero (es la
preferencia del usuario: siempre un entorno nuevo, nunca reutilizar uno). Alternativa menos
buena: bajar CI y Render a 3.10. Lo importante es que coincidan.

---

### I7 · El enlace del informe es permanente, sin login, cubre todos los meses y contiene datos de terceros

- [x] **Punto 1 RESUELTO 2026-09-03**: `scripts/new_client.py --rotar-token TOKEN` genera un
  enlace nuevo e invalida el anterior, con test.
- [x] **Punto 2 RESUELTO 2026-09-03** (decisión B1 del usuario, "sí"). El enlace del informe
  lleva firma `itsdangerous` sobre `token:AAAA-MM`, válida 90 días, en
  `app/services/enlaces.py`. Fricción cero para el dueño: sigue abriendo desde el correo sin
  login. Un enlace filtrado expone **un mes**, no la historia, y caduca. Sin firma responde 403
  con una página que explica qué pasó, y responde **lo mismo exista o no el token**, para que la
  página no sirva de oráculo de clientes. Excepción deliberada: con sesión del dueño (o del
  operador) abre sin firma, porque sería absurdo que a alguien dentro de su panel se le caducara
  su propio informe. Tests en `tests/test_auth.py::TestElInformeSigueSiendoEnlaceDirecto`.
- [x] **Punto 3 DECIDIDO 2026-09-03** (decisión B2, "no"). El contacto se queda en el informe:
  llamar al cliente enojado es el valor del producto. Se revisa si algún cliente lo objeta.

**Riesgo que trajo el cambio, y su test**: la firma usa `SESSION_SECRET`, así que el envío
mensual y el servidor web tienen que compartirla. El workflow de GitHub no la pasaba, y con
claves distintas cada correo del día 1 habría salido con un enlace que el propio servidor
rechaza. Es el mismo error que ya se cometió con SMTP, con otra cara.
`tests/test_deploy.py::TestLaFirmaDeLosEnlacesLlegaAProduccion` lo cubre.

**Dónde**: [app/routers/reports.py](../app/routers/reports.py); `Business.dashboard_token` no
rota nunca; `?mes=` acepta cualquier período.

**Qué pasa**: el informe lleva teléfonos, correos y quejas de los clientes finales del comercio
(datos personales de terceros bajo la Ley 21.719). Un correo reenviado, una casilla filtrada o
un dueño que se va del negocio dejan ese enlace vivo para siempre, con acceso a todos los meses.

**Esto no reabre la decisión de cero fricción**, que está tomada. Son mitigaciones que la
respetan, en orden de menor a mayor cambio:

1. **Comando `--rotar-token TOKEN` en `scripts/new_client.py`**: regenera `dashboard_token`.
   Invalida los enlaces anteriores a propósito. Cero cambio para el dueño salvo que se pida.
   Es lo mínimo y no tiene contraindicación.
2. **Enlace firmado por mes con vencimiento** en el correo mensual: `itsdangerous` ya está
   instalado como dependencia de Starlette. `TimestampSigner` sobre `"{business_id}:{mes}"` con
   `max_age` de 90 días. El dueño abre el correo y entra sin login, igual que hoy; el enlace deja
   de servir a los tres meses y no da acceso a otros meses. El enlace sin firma seguiría
   funcionando solo desde dentro del panel, con sesión. Esto sí cambia el comportamiento actual
   de `/informe/{token}` y **es decisión del usuario**.
3. **Ocultar el contacto en el informe** y mostrarlo solo en el panel. Reduce lo que viaja por
   correo sin tocar la fricción. También decisión del usuario, porque el contacto en el informe
   tiene valor para llamar al cliente.

---

### I8 · El límite público puede descontar conversiones en el momento de más tráfico

- [x] **RESUELTO 2026-09-03.** Una sesión con visita previa convierte aunque la IP esté
  topada. Un script sin visita previa sigue topando: hay test de ambos casos.

**Dónde**: [app/routers/redirect.py](../app/routers/redirect.py), `go_to_google`.

**Qué pasa**: el límite es por IP y los clientes de un local comparten la IP. Si la petición
número 60 del minuto es una landing y la 61 es el `/go` de esa misma persona, la visita se
cuenta y el click no. La degradación de la métrica no es neutra: en un almuerzo lleno solo
puede bajar la conversión. Es raro con 60 por minuto, pero cuando pasa, pasa en el mejor
momento del cliente.

**Corrección**: en `/go`, si la sesión ya tiene un `landed` para esa placa, escribir el
`went_to_google` sin consultar el limitador. Una sesión con cookie y visita previa es un
navegador real siguiendo el flujo; un script que borra cookies nunca tiene un `landed` previo
para su sesión nueva, así que sigue topando con el límite.

```python
ya_visito = _already_logged(db, session_id, placement.id, "landed")
if ya_visito or _debe_contarse(request):
    _log(db, placement, session_id, user_agent, "landed")
    _log(db, placement, session_id, user_agent, "went_to_google")
```

**Test** en `tests/test_ratelimit.py`: con `public_limiter.max_hits = 1`, un mismo visitante
carga la landing y luego `/go`; la conversión debe contarse. Un visitante nuevo que va directo a
`/go` con el límite agotado no debe contarse.

---

## 6. Hallazgos menores

### M1 · Monitoreo de errores (la pregunta abierta del ROADMAP)

- [x] **RESUELTO 2026-09-03.** `sentry-sdk` instalado, `SENTRY_DSN` documentado en
  `.env.example` y declarado en `render.yaml`. Apagado mientras el DSN esté vacío, y un fallo al
  inicializarlo no tumba el arranque. **Falta que el usuario cree la cuenta y pegue el DSN.**

El ROADMAP dejó pendiente confirmar si el "ok hazlo" del usuario se refería a Sentry.
**Recomendación de esta revisión: sí, hacerlo.** Hoy un error 500 en producción solo se ve si
un cliente lo cuenta, y un cliente parado en un mostrador no lo cuenta, se va.

Cómo: `sentry-sdk>=2,<3` en `requirements.txt`; campo `sentry_dsn: str = ""` en `Settings`;
en `lifespan`, si hay DSN, `sentry_sdk.init(dsn=..., traces_sample_rate=0, send_default_pii=False)`;
`SENTRY_DSN=` en `.env.example` (el test lo exige) y en `render.yaml` con `sync: false`. Con
DSN vacío no hace nada, así que se puede dejar integrado y desactivado hasta que el usuario
cree la cuenta gratuita y pegue la clave. `send_default_pii=False` importa: los comentarios
privados no deben viajar a un tercero.

### M2 · La landing debería llevar `noindex`

- [x] **RESUELTO 2026-09-03.** Cabecera `X-Robots-Tag` en las rutas `/r/` y meta en las
  dos plantillas públicas.

Si un cliente comparte el enlace de una placa, Google lo indexa. Googlebot se filtra como bot,
pero los visitantes de escritorio que lleguen desde el buscador tienen navegadores reales y
inflan las visitas de esa placa. Agregar `<meta name="robots" content="noindex, nofollow">` en
`landing.html` y `feedback_thanks.html`, y la cabecera `X-Robots-Tag: noindex` para rutas
`/r/` en `SecurityHeadersMiddleware`. Test en `tests/test_seguridad.py`.

### M3 · El marcador `"bot"` descarta a los teléfonos marca Cubot

- [x] **RESUELTO 2026-09-03.** Lista `_NO_SON_BOTS` evaluada antes que los marcadores.

[app/services/tracking.py:15](../app/services/tracking.py#L15). Los Cubot son teléfonos
Android baratos que se venden en Chile; su `user-agent` contiene "CUBOT" y se marcan como bot.
No quitar el marcador genérico, que atrapa bots desconocidos; agregar una lista de excepciones
que se evalúa antes: `_NO_SON_BOTS = ("cubot",)`. Test con un user-agent real de Cubot.

### M4 · Un cliente sin canal de aviso cuenta como envío fallido

- [x] **RESUELTO 2026-09-03.** `omitidos` separado de `fallidos`; solo un fallo real
  termina con código de error.

[scripts/send_reports.py:80](../scripts/send_reports.py#L80). Un negocio sin correo ni
Telegram se agrega a `fallidos` y el script sale con código 1, así que el workflow mensual se
verá en rojo todos los meses por un caso que no es un fallo. Separar `omitidos` de `fallidos`,
imprimir ambos, salir con 1 solo si hubo fallidos.

### M5 · Texto del canal privado en la landing

- [x] **RESUELTO 2026-09-03** (decisión B3, "sí"). Ahora dice "¿Prefieres contárnoslo en
  privado?" y el campo de texto "Cuéntanos cómo te fue".
  `tests/test_flow.py::TestPoliticaDeGoogle::test_el_canal_privado_se_ofrece_en_terminos_neutros`
  falla si la etiqueta vuelve a presuponer descontento.

[app/templates/landing.html:22](../app/templates/landing.html#L22): "¿Tuviste un problema?
Cuéntanos en privado". No es filtrado, el botón de Google está antes y para todos. Pero la
frase dirige suavemente al descontento hacia el canal privado, y Google endureció en abril de
2026 la detección de solicitud selectiva con herramientas automáticas. Una frase neutra como
"¿Prefieres contárnoslo en privado?" reduce la ambigüedad sin cambiar el flujo ni los tests.
Es una decisión de producto, no un bug.

### M6 · Salidas y textos desactualizados

- [x] **RESUELTO 2026-09-03.** Los dos seeds imprimen `/panel/login`, el README describe
  los dos canales de alerta y enlaza a `docs/`, y `generate_report --help` dice "último mes
  completo".

- [scripts/seed_demo_business.py:45](../scripts/seed_demo_business.py#L45) y
  [scripts/seed_demo_data.py:139](../scripts/seed_demo_data.py#L139) imprimen un enlace
  `/dashboard/?t=TOKEN` que ya no existe: el panel exige login e ignora `?t=`.
- `README.md` dice "Alertas por Telegram (opcional)"; hoy hay correo y Telegram.
- `scripts/generate_report.py` dice en su `--help` "por defecto, el mes actual"; el valor por
  defecto es el último mes completo.
- `README.md` no menciona `docs/`. Agregar un enlace a este documento.

### M7 · `rating` no se valida entre 1 y 5

- [x] **RESUELTO 2026-09-03.** Incluido en C2.

Un `rating=9` enviado a mano se guarda. Incluido en la corrección de `C2`.

### M8 · Falta la cabecera HSTS cuando la base es https

- [x] **RESUELTO 2026-09-03.** Solo sobre https, con test de ambos casos.

En `SecurityHeadersMiddleware`, agregar
`strict-transport-security: max-age=31536000; includeSubDomains` solo cuando
`settings.base_url` empiece por `https://`. En desarrollo sobre http no debe emitirse. Test en
`tests/test_seguridad.py` con `monkeypatch` sobre `base_url`.

### M9 · `date.today()` usa la zona del servidor, no la del negocio

- [x] **RESUELTO 2026-09-03.** `_hoy_local()` en `report.py`.

`resolve_period` y `generated_on` en [app/services/report.py](../app/services/report.py) usan
`date.today()`, que en Render es UTC. Entre las 21:00 y las 24:00 hora Chile del último día del
mes, "el último mes completo" ya apunta al mes que en Chile no terminó. Es marginal, pero
contradice la restricción 4 de `CLAUDE.md`. Corrección de una línea:
`datetime.now(ZoneInfo(settings.timezone)).date()`.

### M10 · El QR se genera en disco en cada petición

- [x] **RESUELTO 2026-09-03.** `qr_png_bytes` sirve desde memoria; los scripts del
  operador siguen escribiendo el archivo, que es lo que necesitan para imprimir.

`/r/{token}/qr.png` escribe un archivo en `qrcodes/` cada vez. En Render el disco es efímero y
esto funciona, pero es innecesario: generar en memoria con `io.BytesIO` y responder con
`Response(content=..., media_type="image/png")`. Los scripts de alta pueden seguir escribiendo
a disco, que es lo que el operador necesita para imprimir.

### M11 · `/panel/logout` responde a GET

- [x] **RESUELTO 2026-09-03** (decisión B7, "sí"). Cerrar sesión es POST; el GET muestra un
  botón en vez de un 405, que a quien tecleó la dirección le parecería un error del sistema. El
  panel lo dispara con un `html.Form` de Dash. El test mira el **layout de Dash y no el HTML**:
  el panel se arma en el navegador desde un JSON, así que una aserción sobre la respuesta HTTP
  no vería nunca ese botón ni notaría que volvió a ser un enlace.

Un enlace en cualquier página cierra la sesión del dueño. Es molesto, no peligroso. Pasarlo a
`POST` con un formulario mínimo en el panel.

### M12 · `init_db()` puede dejar una base sin marca de Alembic

- [x] **RESUELTO 2026-09-03.** `create_all` solo en SQLite; en otro motor registra un
  aviso pidiendo migrar.

`create_all` corre al arrancar. Si alguien levanta la app contra un Postgres nuevo sin haber
corrido `alembic upgrade head` (por ejemplo, con `uvicorn` a mano en vez del `startCommand`),
las tablas se crean sin `alembic_version` y el siguiente `alembic upgrade head` falla porque
las tablas ya existen. Corrección: en `init_db`, ejecutar `create_all` solo cuando la URL sea
SQLite; en cualquier otro motor, registrar un aviso pidiendo correr las migraciones.

### M13 · Restricción única opcional sobre `(session_id, placement_id, outcome)`

- [ ] Decidido: ______

No es necesaria: la métrica cuenta sesiones únicas y las filas duplicadas no la afectan. Si se
quiere igual por prolijidad, hacerlo con una migración y cambiar `_log` a
`insert(...).on_conflict_do_nothing()`, que SQLAlchemy soporta en SQLite y Postgres. Nunca con
un `try/except IntegrityError` que deje la sesión en estado inválido.

### M14 · El panel se refresca cada 5 segundos

- [x] **RESUELTO 2026-09-03.** 60 segundos, más un botón "Actualizar".

`REFRESH_MS = 5000` en `dash_app.py`. Nadie mira un panel de reseñas cada cinco segundos y
cada refresco es una consulta completa (`I2`). Subir a 60 segundos y agregar un botón
"Actualizar".

### M15 · Retención de datos personales de las quejas

- [x] **RESUELTO 2026-09-03** (decisiones B4 y B5, "sí"). `scripts/anonimizar_contactos.py`,
  agendado en el workflow mensual, borra el contacto y **solo** el contacto: la queja es el
  registro operativo del comercio y las métricas no se mueven. La landing avisa el plazo.
  Responsable del tratamiento: **el comercio**, con la plataforma como encargada.

  **Se cambió el criterio de esta propuesta a propósito**: el plazo se cuenta desde que llegó la
  queja, no desde que se marcó atendida. Contarlo desde la atención deja una política que el
  dueño desactiva sin querer con solo no tocar el botón, y son justo las quejas abandonadas las
  que más tiempo acumulan un teléfono. `--solo-atendidas` recupera el criterio original.
  El script **simula por defecto**: es un borrado irreversible sobre datos de terceros.
  Tests en `tests/test_retencion.py`.

`Feedback.contact` guarda teléfonos y correos de clientes finales sin fecha de caducidad. La
Ley 21.719 exige finalidad y plazo. Propuesta: un comando `scripts/anonimizar_contactos.py
--meses 6` que borre `contact` de las quejas atendidas hace más de N meses, agendable en el
mismo workflow mensual; y una frase en el aviso legal de la landing que diga cuánto tiempo se
guarda. Definir con el usuario quién es el responsable del tratamiento: el comercio o la
plataforma.

### M16 · La sesión del panel no expira por inactividad

- [x] **RESUELTO 2026-09-03** (decisión B6, "sí"). `max_age` de 7 días en `SessionMiddleware`,
  con un test que mira la cookie del 302 del login y no solo la constante.

`SessionMiddleware` deja la cookie 14 días por defecto. Para un panel que se deja abierto en
un computador del local es mucho. Fijar `max_age` a 7 días es razonable; menos empieza a
molestar.

---

## 7. Riesgos que no son de código

### N1 · El repositorio vive dentro de OneDrive

- [ ] Resuelto en: ______

`.git` y `.venv` están en `OneDrive - Cencosud\Escritorio\...`. OneDrive sincronizando los
objetos de git mientras git los escribe es una causa conocida de repositorios corruptos, y el
`.venv` son miles de archivos que se suben a la nube de la empresa sin ningún motivo. Ahora que
el código está en GitHub, lo limpio es clonar en `C:\Users\aliacost\Proyectos\nfc-review-analytics`
(o cualquier ruta fuera de OneDrive), recrear el `.venv` ahí con Python 3.12 (`I6`) y borrar la
copia de OneDrive una vez verificado que todo corre.

### N2 · Equipo y cuentas corporativas

- [ ] Decidido: ______

El proyecto se desarrolla en un equipo de Cencosud, dentro de su OneDrive, y el `git config`
global del equipo lleva el correo corporativo. Los commits ya van con el correo personal porque
se fijó a nivel de repositorio, y el Credential Manager tenía guardada la cuenta corporativa de
GitHub. Todo esto deja abierta la pregunta de a quién pertenece el código; muchas políticas
laborales reclaman lo desarrollado en equipos de la empresa. Es una decisión del usuario, pero
un revisor serio la deja anotada. **Además: los dos tokens de GitHub que se pegaron en el chat
durante la subida deben revocarse** en `github.com/settings/tokens` si no se hizo ya.

### N3 · El repositorio es privado y debe seguir siéndolo

- [ ] Verificado: ______

Contiene `Proyecto_NFC_Review_Analytics.pdf` con el modelo de negocio y precios, y `ROADMAP.md`
y `CLAUDE.md` con la estrategia. No hay secretos en el código (se buscó con `grep`), pero el
contenido de negocio no es para publicar. Si algún día se quiere un repositorio público como
portafolio, hacerlo con una copia sin el PDF ni los documentos de estrategia.

---

## 8. Plan recomendado, en orden

Las fases A y B son trabajo de código que no depende de nadie. La D depende del usuario. La E
es producto.

### Fase A · Antes de cualquier cliente que pague · ✅ **COMPLETADA 2026-09-03**

La suite pasó de 149 a 162 tests. Falta solo confirmar la corrida contra Postgres, que ocurre
en el próximo push (no hay Postgres en el equipo del usuario para probarlo antes).

1. `C1` IP real detrás del proxy, con sus tests.
2. `C2` recortes al escribir, `maxlength`, validación de `rating` (`M7`), y **Postgres en CI**.
3. `C3` variables SMTP en el workflow y en `render.yaml`, `env_ignore_empty`, test de consistencia.
4. `C4` página de gracias por `/go`.
5. Actualizar el contador de tests en `README.md`, `ROADMAP.md` y `CLAUDE.md`.

### Fase B · Rápidos y sin discusión · ✅ **COMPLETADA 2026-09-03**

6. `I3` señuelo en el login.
7. `I4` credenciales de demo en el seed.
8. `I8` `/go` exento del límite cuando la sesión ya visitó.
9. `I2` filtro por fecha en SQL, y `M14` refresco a 60 segundos.
10. `M2` noindex, `M3` excepción Cubot, `M4` omitidos vs fallidos, `M6` textos, `M8` HSTS,
    `M9` fecha local, `M10` QR en memoria, `M12` guardia de `create_all`.
11. `I7` punto 1: comando `--rotar-token`.

### Fase C · Producto y operación · ◑ **PARCIAL 2026-09-03**

Hechos I1, M1 y **las siete decisiones B1–B7**, que el usuario respondió "todas las
recomendadas" el 2026-09-03: I7.2 (enlace firmado), I7.3 (contacto se queda), M5 (texto neutro),
M11 (logout por POST), M15 (retención de contactos), M16 (sesión de 7 días).
Pendientes solo I6 y N1, que requieren instalar Python 3.12 y mover el repositorio: es trabajo
del usuario.

12. `I1` selector de período en el panel.
13. `M1` Sentry integrado y desactivado, a la espera de la clave.
14. `I6` Python 3.12 local con `.venv` nuevo, y `N1` mover el repositorio fuera de OneDrive
    (conviene hacer ambos juntos: se clona en la ruta nueva y ahí se crea el entorno).
15. Decidir con el usuario `I7` puntos 2 y 3, `M5`, `M11`, `M15`, `M16`.

### Fase D · Bloqueado por el usuario (sin cambio desde el 2026-09-01)

16. Comprar el dominio. Sigue siendo lo único que bloquea imprimir una placa.
17. Conseguir un enlace real de reseña de Google de cualquier negocio conocido.
18. Crear la base en Neon (`I5`), el servicio en Render con `BASE_URL` definitivo, y cargar
    los secrets de SMTP (Brevo gratuito) y Telegram en Render y en GitHub.
19. Primer despliegue, primer cliente de prueba con placas reales, chips bloqueados por
    contraseña al grabarlos.

### Fase E · Próximos desarrollos (sección 9)

---

## 9. Próximos desarrollos, con detalle

En orden de valor para el negocio dividido por esfuerzo.

### 9.1 · Editar un cliente sin escribir Python · ✅ HECHO 2026-09-03

Hoy `scripts/new_client.py` crea, lista, agrega placas y reinicia contraseñas, pero cambiar el
`google_review_url` o el correo de un cliente existente exige un snippet contra
`SessionLocal`. Antes de un panel web de administración, que es mucho más trabajo, basta con
`--editar TOKEN --google-url ... --email ... --telegram ... --nombre ...` en el mismo script.
Una hora de trabajo, con test en `tests/test_operacion.py`. El panel web de administración se
justifica cuando haya más de diez clientes.

### 9.2 · Hoja de impresión de QR · ✅ HECHO 2026-09-03

Para producir las placas hace falta imprimir los QR con su etiqueta y su URL corta. Un script
`scripts/qr_sheet.py --token TOKEN` que genere un HTML A4 con CSS de impresión (la misma técnica
que el informe: `@page`, sin JS, sin imágenes externas, los QR embebidos como `data:` URI) con
una tarjeta por placa: nombre del negocio, etiqueta de la placa, QR y URL en texto. Imprime desde
el navegador o con WeasyPrint donde esté. Es lo que se le entrega al que fabrica las placas.

### 9.3 · Módulo 2: sincronización con Google Business Profile

Es el módulo que **prueba** el número que se vende. Hoy se cuentan clicks hacia Google, no
reseñas publicadas; el informe lo dice honestamente en su nota al pie. Con la API se puede
mostrar "reseñas nuevas este mes" y calificación promedio al lado de las visitas, y correlacionar
ambas curvas.

Lo que requiere, y por qué en la práctica depende del usuario:

1. Un proyecto en Google Cloud y **solicitar acceso a las Business Profile APIs** mediante el
   formulario de Google. La aprobación no es inmediata y puede tardar semanas. **Conviene
   iniciar la solicitud ya**, sin esperar a tener el módulo construido.
2. Consentimiento OAuth del dueño de cada negocio (es su perfil, no el nuestro). Guardar el
   `refresh_token` cifrado por `Business`. Es fricción de onboarding: hacerlo opcional por
   cliente, con el producto funcionando igual sin él.
3. Un job diario (el mismo workflow de GitHub Actions, o un cron aparte) que lea las reseñas y
   las guarde en una tabla `google_reviews` (`review_id`, `rating`, `created_at`, `comment`,
   `reply`), con migración.
4. `metrics.py` gana `reviews_in_period` y el informe una fila más de KPI. Nunca calcular esto
   fuera de `metrics.py`.

Hasta que exista, la nota al pie del informe es la posición correcta: decir lo que se mide y lo
que no.

### 9.4 · WhatsApp como canal de alertas

Explicado en el ROADMAP, sin decidir. Es el canal que un dueño de pyme chileno mira de verdad.
La API oficial de Meta cobra por mensaje iniciado por el negocio, del orden de centavos; las
librerías no oficiales arriesgan el baneo del número del cliente y **no se usan**. La
recomendación sigue siendo: arrancar con correo, medir con dos o tres clientes si el dueño
reacciona, y pagar WhatsApp cuando haya ingresos que lo cubran. Cuando llegue, es un archivo
nuevo `app/services/whatsapp.py` con la misma firma que `send_email`, y una línea en
`notify.py`. Nada más cambia.

### 9.5 · Recuperación de contraseña por el propio dueño · ✅ HECHO 2026-09-03

`/panel/recuperar` pide el correo y manda a `login_email` un enlace firmado válido una hora;
`/panel/nueva-clave` recibe la clave nueva y deja al dueño dentro del panel. El operador
conserva `--reset-password` para cuando no haya correo.

Cuatro decisiones que no son obvias:

1. **La respuesta es idéntica exista o no la cuenta.** Un "ese correo no está registrado"
   convertiría el formulario en un recorrido de la cartera de clientes, que es justo lo que el
   mensaje único del login evita. El envío va en `BackgroundTask`, así que tampoco delata por
   tiempo de respuesta.
2. **El enlace muere al usarse**, sin tabla ni migración: la firma incluye el hash actual de la
   contraseña, así que en cuanto cambia deja de validar.
3. **Limitador propio** (`recovery_limiter`, 5 cada 15 minutos) y no el del login: cada acierto
   dispara un correo, así que sin techo el formulario es un cañón gratis contra la casilla de un
   cliente y contra la cuota diaria del proveedor; y castigar el login de una cuenta por pedir su
   clave dejaría al dueño sin poder entrar justo cuando ya no puede entrar.
4. **Sin SMTP, lo dice** (503) en vez de mostrar "te mandamos un correo" y dejar al dueño
   esperando algo que no va a llegar nunca.

Tests en `tests/test_recuperacion.py`. **Depende de SMTP para servir en producción**, que sigue
siendo bloqueante en `check_deploy`.

**Hallazgo posterior, corregido el 2026-09-04**: la primera versión metía el **hash scrypt
completo** del dueño dentro del enlace. `itsdangerous` firma pero no cifra, así que ese contenido
se lee decodificando el token, sin conocer la clave del servidor: un correo reenviado o una
casilla filtrada entregaban el hash para atacarlo sin apuro ni límite de intentos. Ahora viaja
una huella irreversible (`enlaces.huella`), que cumple lo mismo —morir cuando la contraseña
cambia— sin llevar nada aprovechable, y de paso acorta el enlace de 114 a 78 caracteres.
`tests/test_recuperacion.py::TestLoQueViajaDentroDelEnlace` decodifica el token a propósito con
una clave equivocada, que es lo que puede hacer cualquiera con el enlace en la mano.

### 9.6 · Correo de bienvenida en el alta · ✅ HECHO 2026-09-04

Cuando `new_client.py` crea un cliente con correo, mandar automáticamente un correo con el
enlace del panel y las instrucciones. **No mandar la contraseña por correo**: mandar el enlace
de "crear tu contraseña" de 9.5. Así la clave nunca viaja en texto plano y el operador no tiene
que dictarla.

### 9.7 · Zona horaria por negocio

Cuando exista un cliente fuera de Chile: columna `Business.timezone` con
`server_default=settings.timezone` en la migración; `metrics._to_local` recibe la zona como
parámetro en vez de leerla de `settings`; `load_taps` y `load_feedback` la toman del negocio.
Los tests de `tests/test_horario.py` se parametrizan con dos zonas. Un día de trabajo. No
antes.

### 9.8 · Respaldos · ✅ HECHO 2026-09-03

Neon gratuito tiene recuperación en el tiempo limitada. Un cliente con placas instaladas tiene
un historial irreemplazable. Agregar al workflow mensual, o a uno semanal, un paso que corra
`python -m scripts.export_data --todos` y suba la carpeta como artifact de GitHub (se conservan
90 días) o a un bucket. Es gratis y es la diferencia entre perder un mes y perder todo.

### 9.9 · Monitoreo de disponibilidad

UptimeRobot gratuito contra `/health` cada 5 minutos, avisando al correo del operador. Ya está
en la lista de bots, así que no ensucia las métricas. No usarlo para "mantener despierta" la
instancia gratuita de Render: la respuesta correcta a ese problema es la instancia de pago
cuando haya un cliente, como dice el ROADMAP.

### 9.10 · Módulo 3: análisis de sentimiento

Sigue siendo lo último. Con 20 reseñas al mes un dueño no necesita NLP; lo lee. Si se hace,
local y gratis con `pysentimiento` (entrenado en español) o VADER, sobre `Feedback.message` y,
cuando exista 9.3, sobre las reseñas de Google. Una columna `sentiment` y un color en la
bandeja. No antes de tener clientes que lo pidan.

### 9.11 · Panel de administración web · ✅ HECHO 2026-09-03

Cuando 9.1 quede corto: una ruta `/admin` con su propia contraseña de operador (no la de los
clientes), para listar negocios, editar sus datos, agregar placas, ver el estado de las alertas
y descargar la hoja de QR. Con FastAPI y Jinja2, sin Dash, siguiendo `login.html`. Es un módulo
mediano; se justifica con más de diez clientes o con un segundo operador.

---

## 10. Fuentes consultadas

- Render, hilo público de soporte sobre `X-Forwarded-For`, con respuestas del equipo de Render
  ("Render does not clear or reset any passed-in X-Forwarded-For header, it only appends to
  it"): <https://feedback.render.com/features/p/send-the-correct-xforwardedfor>
- MDN, `X-Forwarded-For` y la recomendación de leer la cadena desde la derecha:
  <https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Forwarded-For>
- Supabase, documentación oficial de pausa de proyectos gratuitos:
  <https://supabase.com/docs/guides/platform/free-project-pausing>
- Política de reseñas de Google Business Profile y su actualización de abril de 2026, con la
  prohibición explícita de "discourage or prohibit negative reviews, or selectively solicit
  positive reviews from customers":
  <https://launchcodex.com/blog/seo-geo-ai/google-business-profile-review-policy-update/> y
  <https://www.sterlingsky.ca/review-gating-is-now-against-the-google-my-business-guidelines/>

---

## 11. Registro de cambios de este documento

| Fecha | Cambio |
|---|---|
| 2026-09-03 | Revisión inicial completa sobre el commit `4b702b5`. |
| 2026-09-03 | Fase A completada: C1, C2, C3 y C4 corregidos y Postgres agregado a CI. 162 tests. |
| 2026-09-03 | Fase B completada (I2, I3, I4, I8, M2, M3, M4, M6, M7, M8, M9, M10, M12, M14, I7.1) y fase C parcial (I1, M1). 176 tests. |
| 2026-09-03 | Fase E: 9.1 (`--editar`) y 9.2 (hoja de placas). 189 tests. Panel e informe verificados coincidiendo con datos reales de la ronda de pruebas del usuario. |
| 2026-09-03 | **La prueba manual encontró un bug que la suite no podía ver**: la CSP pública bloqueaba los estilos del informe y el dueño lo habría recibido como texto plano. Corregido con una CSP propia para `/informe` y cuatro tests de regresión. 193 tests. |
| 2026-09-03 | Panel de administración del operador en `/admin` (9.11), adelantado a pedido del usuario. 28 tests propios, la mitad sobre quién no puede entrar. 221 tests. |
| 2026-09-03 | Personalización por cliente (logo y mensaje), logo también en la placa impresa, y rediseño de la hoja de fabricación. 273 tests. |
| 2026-09-03 | Revisión previa al despliegue (`scripts/check_deploy.py`) y respaldo semanal automático (9.8). 292 tests. |
| 2026-09-03 | **El usuario completó la ronda de pruebas manuales entera**: 27 de 27 puntos. Única falla encontrada, el informe sin estilos, ya corregida. Queda sin probar la experiencia en un teléfono real, bloqueada por la red. |
| 2026-09-03 | **Bloque B cerrado** (B1–B7, "todas las recomendadas"): enlace del informe firmado y con vencimiento, texto neutro del canal privado, retención de contactos a 6 meses, sesión de 7 días, logout por POST. Cierra I7.2, I7.3, M5, M11, M15 y M16. 299 tests. |
| 2026-09-03 | Recuperación de contraseña por el propio dueño (9.5), con su limitador propio y enlace de un solo uso. 337 tests. |
| 2026-09-04 | Correo de bienvenida en el alta (9.6): el dueño elige su contraseña desde un enlace y el operador deja de dictarla. Sin SMTP el alta sigue imprimiendo la clave, para no dejar al cliente sin entrada. 349 tests. |
| 2026-09-04 | **Corregido un hallazgo de la jornada anterior**: los enlaces de cuenta llevaban dentro el hash scrypt del dueño, legible por cualquiera que tuviera el enlace, porque `itsdangerous` firma pero no cifra. Ahora viaja una huella irreversible. 352 tests. |
