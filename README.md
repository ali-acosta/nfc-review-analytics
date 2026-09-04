# NFC Review & Analytics — MVP ($0)

Captación de reseñas de Google en punto de venta vía NFC/QR, con analítica de conversión para
el comercio. Construido con herramientas open source y capas gratuitas.

- `Proyecto_NFC_Review_Analytics.pdf` — visión de producto y modelo de negocio.
- [ROADMAP.md](ROADMAP.md) — **plan de ejecución vigente** (reemplaza el orden de módulos del PDF).

## Qué hace hoy

- **Landing de un click** (`/r/{token}`): botón directo a Google para todos, sin pasos previos.
  Como opción secundaria siempre disponible, un canal privado para quien tuvo un problema.
  Sin filtrar por calificación — eso viola las políticas de Google y agrega fricción.
- **Un código por soporte físico**: cada placa, tarjeta o sticker tiene su propia URL, así se
  puede comparar cuál convierte mejor.
- **Embudo real**: cookie de sesión, deduplicación de recargas y filtro de bots, para que la
  tasa de conversión sea defendible frente a un cliente.
- **Panel del comercio** (`/panel/login`): entra con correo y contraseña. Visitas únicas, clicks
  a Google, conversión, conversión comparada por soporte, y buzón de quejas con estado
  (pendiente/atendida) exportable a CSV. El dueño puede cambiar su contraseña él mismo.
- **Informe mensual** (`/informe/{token}`): KPIs con comparación contra el mes anterior,
  rendimiento por soporte, visitas por día y el detalle de las quejas recibidas. Listo para
  imprimir o enviar. Es la pieza que sostiene la suscripción.
- **Alertas por correo y/o Telegram** (opcional): cada comentario privado dispara una
  notificación por los canales que el negocio tenga configurados. El correo suele importar
  más: un dueño de pyme lo revisa a diario y puede no tener Telegram. Si no hay ninguno
  configurado, la app funciona igual.
- **Personalización por cliente**: la landing lleva el logo del local y un mensaje propio, para
  que el cliente del negocio vea la página de ese negocio y no una genérica. El logo va también en
  la hoja de placas, así que la placa física sale con la marca del local.
- **QR de demo**: mismo link que iría en el chip, para probar el flujo real con un celular.

## Cómo correrlo

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Crea el negocio demo con 3 soportes e imprime sus URLs, sus QR y el link del panel.
# Los tokens son aleatorios: revisa la salida, cambian cada vez que se recrea la BD.
python -m scripts.seed_demo_business

# Llena la base con ~2,5 meses de tráfico realista, para que el panel y el informe
# se vean como se verían en un local de verdad.
python -m scripts.seed_demo_data --limpiar

uvicorn app.main:app --reload
```

Para entrar al panel de demo: **`demo@cafe.cl` / `demo1234`** en `/panel/login`.

El script de alta imprime algo así:

```
Soportes físicos (cada uno con su propio código, el que va grabado en el chip):
  · Mesa 5          http://localhost:8000/r/ZTYFEMtc   (QR: qrcodes/ZTYFEMtc.png)
  · Mesón de pago   http://localhost:8000/r/H1IwNJrX   (QR: qrcodes/H1IwNJrX.png)
  · Boleta          http://localhost:8000/r/Ygb-AOFn   (QR: qrcodes/Ygb-AOFn.png)

CREDENCIALES DEL PANEL  (entrégaselas al dueño)
    Entrar en: http://localhost:8000/panel/login
    Correo:    dueno@cafe.cl
    Clave:     k3m9xq2wb7dp
```

Antes de mostrarlo a alguien, reemplaza el `google_review_url` del negocio demo por el link real
de "Escribir una reseña" del comercio (desde Google Business Profile → "Solicitar reseñas", o
armándolo con el Place ID real).

## Dar de alta un cliente real

```powershell
# Modo interactivo: te pregunta nombre, link de Google y las placas
python -m scripts.new_client

# O de una sola línea
python -m scripts.new_client --nombre "Café Central" `
  --google-url "https://g.page/r/CXXXX/review" --placas "Mesa 1,Mesa 2,Mesón"

# Ver todos los clientes, con qué correo entran y su enlace de informe
python -m scripts.new_client --listar

# Agregar placas a un cliente que ya existe
python -m scripts.new_client --agregar TOKEN --placas "Mesa 7,Mesa 8"

# Generar una contraseña nueva (si el dueño la perdió)
python -m scripts.new_client --reset-password TOKEN
```

Entrega los QR listos en `qrcodes/` y las **credenciales del panel** para el dueño. La
contraseña se guarda con hash: se muestra una sola vez, anótala en ese momento. Si se pierde,
se genera otra con `--reset-password`.

El script avisa si `BASE_URL` todavía apunta a `localhost`, porque esos QR solo funcionarían en
tu equipo y no sirven para imprimir.

## El informe mensual

```powershell
# Lo guarda en informes/ (por defecto el último mes completo)
python -m scripts.generate_report --mes 2026-08
```

También está en vivo en `/informe/{token}`, con link desde el panel.

Para obtener el PDF hay dos caminos. El inmediato: abrir el informe en el navegador y usar
**Imprimir → Guardar como PDF**, que da calidad idéntica porque la plantilla está hecha con CSS
de impresión. El automático (`/informe/{token}/pdf`) usa WeasyPrint, que en Linux funciona sin
configuración pero en Windows necesita instalar aparte el runtime de GTK3; mientras no esté, ese
endpoint responde con instrucciones en vez de fallar.

## ⚠️ Antes de grabar el primer chip

La URL queda grabada para siempre en la placa instalada. Antes de imprimir nada:

1. Compra el dominio propio y ponlo en `BASE_URL` (`.env`). Si imprimes un subdominio de hosting
   gratuito y luego migras, mueren todas las placas ya instaladas.
2. Regenera los QR (`python -m scripts.seed_demo_business`) para que apunten al dominio final.
3. Bloquea los chips con contraseña después de grabarlos.

Detalle completo en [ROADMAP.md](ROADMAP.md).

## Alertas al dueño (opcional, gratis)

Cada negocio puede recibir las quejas por **correo**, por **Telegram**, por ambos o por ninguno.
Se elige al dar de alta el cliente. El correo suele funcionar mejor: un dueño de pyme lo revisa
a diario y puede no tener Telegram instalado.

Copia `.env.example` a `.env` y configura el canal que uses:

- **Correo**: cualquier SMTP en `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM`.
  El free tier de Brevo (300 correos al día) sobra.
- **Telegram**: crea un bot con `@BotFather` → `TELEGRAM_BOT_TOKEN`; el chat id lo da
  `@userinfobot`.

Si no configuras nada, la app funciona igual: solo no se envían avisos.

## Cambios de esquema

```powershell
alembic revision --autogenerate -m "qué cambia"   # revisa siempre lo generado
alembic upgrade head
```

Nunca borres la base para aplicar un cambio: con un cliente instalado, su historial de taps es
irrecuperable. En el despliegue las migraciones se aplican solas antes de arrancar.

## Mostrarlo fuera de tu red, sin desplegar

```powershell
cloudflared tunnel --url http://localhost:8000   # gratis, sin cuenta
ngrok http 8000                                   # gratis, con cuenta
```

Actualiza `BASE_URL` con la URL pública y regenera los QR antes de mostrarlos.

## Envío automático mensual

```powershell
python -m scripts.send_reports --dry-run    # ver qué se enviaría
python -m scripts.send_reports              # enviar de verdad
```

Manda por Telegram un resumen con los titulares del mes y el enlace al informe completo, y
adjunta el PDF donde WeasyPrint esté disponible. Ya viene agendado el día 1 de cada mes en
`.github/workflows/informe-mensual.yml`; para activarlo hay que cargar en los secrets del repo
`DATABASE_URL`, `BASE_URL` y `TELEGRAM_BOT_TOKEN`.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest -q
```

269 tests. Cuidan sobre todo tres cosas: que la tasa de conversión siga siendo correcta, que las
fechas se agrupen en hora local del negocio, y que nadie reintroduzca el filtrado de reseñas
que viola las políticas de Google. Corren solos en cada push.

## Exportar o respaldar

```powershell
python -m scripts.export_data --listar
python -m scripts.export_data --todos --destino respaldos/
```

Saca las visitas y las quejas de cada cliente a CSV, con las fechas en hora local. Útil para
respaldar antes de un cambio grande y para entregarle sus datos a un cliente que los pida.

## Despliegue

El proyecto ya viene listo: `render.yaml` tiene el blueprint (health check, puerto y host
correctos) y `psycopg` está en `requirements.txt`, así que pasar a Postgres es solo cambiar
`DATABASE_URL`.

Pasos: crear el Postgres gratuito en Supabase o Neon, conectar el repo en Render.com, y cargar
en el panel de Render las variables `DATABASE_URL`, `BASE_URL`, `TELEGRAM_BOT_TOKEN` y
`TELEGRAM_CHAT_ID`.

Ojo con dos cosas. El plan gratuito de Render duerme tras ~15 min de inactividad (~50s de
arranque en frío): sirve para demos pero **no** para producción — con el primer cliente pagando
hay que pasar a una instancia siempre encendida (~$7/mes, que un cliente cubre tres veces).
Y `BASE_URL` define la URL que va en los QR: si se imprimen placas con el subdominio de
onrender.com y luego se migra, esas placas mueren. Ver [ROADMAP.md](ROADMAP.md).

## Panel de administración

Para gestionar los clientes desde el navegador en vez de la línea de comandos:

```powershell
python -m scripts.admin_password      # genera ADMIN_PASSWORD_HASH y lo explica
```

Pega la línea que imprime en tu `.env`, reinicia y entra en `/admin`. Mientras esa variable esté
vacía el panel responde 404, que es el valor por defecto: un panel que ve a todos los clientes no
puede quedar accesible por olvidar configurarlo.

## Documentación

- [docs/revision-tecnica-2026-09-03.md](docs/revision-tecnica-2026-09-03.md) — revisión técnica
  completa: hallazgos con su corrección y su test, lo que está bien y no hay que "arreglar",
  el plan de trabajo y los próximos desarrollos.
- [docs/pendientes-del-usuario.md](docs/pendientes-del-usuario.md) — todo lo que requiere
  intervención manual: pruebas, decisiones, cuentas y compras.
- [docs/ruta-de-pruebas-manuales.md](docs/ruta-de-pruebas-manuales.md) — cómo probar el producto
  a mano, paso a paso.
