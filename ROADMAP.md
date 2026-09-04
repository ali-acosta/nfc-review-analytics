# Roadmap

Reemplaza el orden de módulos del PDF original. El PDF sigue siendo válido como visión de
producto y modelo de negocio; esto es el plan de ejecución corregido tras la revisión técnica
del 2026-09-01.

## Decisiones irreversibles — resolver ANTES de imprimir la primera placa

Una vez que un chip está grabado y la placa pegada en la mesa de un cliente, su URL no se puede
cambiar. Todo lo de esta sección es más barato de decidir hoy que de corregir después.

| Decisión | Estado |
|---|---|
| **Dominio propio** (~$10/año). Único gasto que vale la pena romper la regla de $0: si se imprime `algo.onrender.com` y algún día se cambia de hosting, mueren todas las placas instaladas. | ⏳ **Pendiente — acción del usuario** |
| **Tokens aleatorios no enumerables** en la URL en vez de slugs legibles, para que nadie pueda recorrer la cartera de clientes ni envenenar métricas ajenas. | ✅ Hecho |
| **Un código por soporte físico**, no por negocio — es lo que permite responder "qué placa convierte mejor". Imposible de retrofitear en placas ya instaladas. | ✅ Hecho |
| **Bloquear los chips con contraseña** después de grabarlos, o cualquiera con un celular puede reescribir la placa de un cliente. | ⏳ Pendiente (al comprar hardware) |
| NTAG213 alcanza de sobra para una URL corta y es más barato que el 215. | ✅ Decidido |

## Estado por módulo

### Módulo 1 — Redirector y captación · ✅ Funcionando
Landing de un solo click a Google (sin selector de estrellas: cada paso intermedio pierde
reseñas, y segmentar por calificación antes de Google va contra sus políticas). Canal privado
siempre disponible como opción secundaria, nunca como reemplazo del botón de Google.
Embudo real con `session_id`, deduplicación de recargas y filtro de bots.

### Módulo 5 — Panel · ✅ Con login real
Conversión honesta sobre visitantes únicos, comparación por soporte físico y buzón privado.
Entrada con correo y contraseña (`/panel/login`), sin dependencias externas: `scrypt` de la
biblioteca estándar y las cookies firmadas que ya trae Starlette. Se descartó Supabase Auth
para no sumar un servicio de terceros donde la biblioteca estándar alcanza.
El enlace del informe sigue siendo directo a propósito: se le manda por correo al propio dueño
y exigir login en cada correo mensual haría fricción justo en la pieza de retención.
El dueño cambia su contraseña él mismo en `/panel/password` (se le pide la actual: si deja el
panel abierto en el mostrador, nadie debería poder quedarse con la cuenta). El operador puede
regenerarla con `--reset-password` si la pierde.

### Módulo 4 — Alertas y reportes · ✅ Informe funcionando
Es lo que sostiene la suscripción mes a mes: la alerta de queja tiene valor operativo diario y
el informe mensual es el recordatorio recurrente de que el servicio existe. Un panel, por sí
solo, no genera retención.
- Alertas: ✅ Telegram funcionando (opcional, no rompe si no está configurado).
- Informe mensual: ✅ en `/informe/{token}`, con KPIs, comparación contra el mes anterior,
  rendimiento por soporte, visitas por día y el detalle de quejas privadas. Por defecto muestra
  el último mes completo, que es la semántica de un informe mensual.
- Canal de alertas: ✅ resuelto. Ya no depende solo de Telegram: cada negocio puede tener
  correo, Telegram, ambos o ninguno, y `app/services/notify.py` reparte a los que estén
  configurados. El correo se agregó porque el canal importa tanto como el mensaje — un dueño de
  pyme en Chile revisa su correo a diario y puede no tener Telegram instalado.
  Falta configurar el SMTP (Brevo free tier: 300 correos/día).
- ⏳ WhatsApp queda pendiente: es el canal que realmente usan, pero su API es de pago.
- Envío automático mensual: ✅ `python -m scripts.send_reports` manda el resumen con los
  titulares y el enlace al informe, y adjunta el PDF donde el motor esté disponible. Agendado
  con GitHub Actions (`.github/workflows/informe-mensual.yml`) el día 1 de cada mes.
  Falta configurar los secrets, que requiere tener el Postgres y el bot creados.
- ⏳ PDF nativo en Windows: WeasyPrint necesita el runtime de GTK3. Mientras tanto el informe se
  imprime desde el navegador con calidad idéntica, y el workflow de GitHub sí lo genera porque
  ahí se pueden instalar las librerías nativas.

### Operación — Alta de clientes · ✅ Resuelto
`python -m scripts.new_client` crea el negocio, sus placas y sus QR, y entrega los enlaces del
panel y del informe. `--listar` recupera tokens perdidos (son aleatorios y se imprimen una sola
vez), `--agregar` suma placas después, `--editar` corrige los datos de un cliente ya creado
(incluido su `google_review_url`, que era lo único frecuente que obligaba a escribir Python contra
la base) y `--rotar-token` invalida el enlace del informe. `python -m scripts.qr_sheet` genera la
hoja de placas para mandarle a quien las fabrique, con un aviso de NO IMPRIMIR mientras la URL no
sea definitiva. Pendiente: un panel web de administración.

### Módulo 2 — Sincronización con Google Business Profile · ⏳ Importa más de lo que parece
Hoy se pueden contar clicks hacia Google, pero **no** reseñas efectivamente publicadas. El
número que se vende ("toques vs reseñas") no se puede probar sin esta API. Sube de prioridad
por encima del Módulo 3.

### Módulo 3 — Motor de IA / sentimiento · ⏳ Último
Con 20 reseñas al mes, un dueño no necesita NLP. Es una función de demo, no de retención.

### Infraestructura — Migraciones · ✅ Resuelto
Antes, cualquier cambio de esquema obligaba a borrar la base: con un cliente instalado, eso es
perder su historial. Ahora hay Alembic (`alembic upgrade head`, aplicado solo en cada despliegue
desde `render.yaml`) y un test que falla si los modelos y las migraciones se desincronizan.
Ya se estrenó agregando la columna del correo de alertas, con los 1915 taps de demo intactos.

### Calidad — Tests · ✅ 292 tests
`pip install -r requirements-dev.txt && pytest -q`. Corren solos en cada push, sobre SQLite y Postgres
(`.github/workflows/tests.yml`). Protegen sobre todo la métrica de conversión —que ya se rompió
una vez en silencio— y la regla de no reintroducir el filtrado de reseñas.
Encontraron un bug real: `send_alert` solo capturaba errores de red, así que cualquier otra
excepción llegaba al cliente como un error 500 después de haber guardado su comentario.

Y la **prueba manual encontró uno que los tests no podían ver**: la CSP pública bloqueaba los
estilos del informe, que van dentro del HTML porque el documento tiene que funcionar solo. El dueño
lo habría recibido como texto plano, sin un gráfico. La CSP la aplica el navegador, así que para la
suite el HTML llegaba perfecto. Es el argumento de por qué probar a mano sigue haciendo falta.

### Correctitud — Zona horaria · ✅ Bug corregido
Los eventos se guardan en UTC pero los informes y gráficos se agrupan en hora local del negocio.
Antes, un toque a las 21:30 del 31 de agosto en Chile aparecía en el informe de **septiembre**, y
toda la cena de un restaurante se contabilizaba al día siguiente. Además se blindó el
almacenamiento (`UtcDateTime`): SQLite descartaba en silencio la zona horaria y Postgres no, así
que el mismo código daba resultados distintos en desarrollo y en producción.

### Seguridad — Abuso y endurecimiento · ✅ Resuelto
El token de una placa es público por diseño (está pegado en una mesa), así que un script podía
inflar las visitas de un cliente y hundirle la conversión. Ahora hay límite por IP, con un
criterio: en las páginas públicas se degrada la métrica pero **nunca** la experiencia —los
clientes de un local comparten el WiFi y por tanto la IP—, mientras que en el login sí se bloquea
de verdad contra fuerza bruta. Se sumaron cabeceras de endurecimiento y una CSP estricta en las
páginas públicas; `Referrer-Policy` evita filtrarle a Google la URL con el token de la placa.

### Producto — Personalización por cliente · ✅ Hecho
La landing lleva el logo del local y un mensaje propio, configurables desde el panel al dar de
alta o después. Deja de verse como una plataforma genérica y pasa a ser la página del negocio,
que es buena parte de lo que un cliente cree estar comprando. El logo se guarda en la base y no
como archivo porque el hosting no tiene disco persistente, y va también en la hoja de placas, así
que la placa física sale con la marca del local.

### Producto — Uso diario · ✅ Resuelto
La bandeja de quejas tiene estado (pendiente/atendida, con reapertura) y ordena las pendientes
primero: antes solo crecía y el dueño perdía el rastro de lo que ya había resuelto. El dueño
también puede cambiar su contraseña solo, y bajarse sus quejas en CSV.

### Operación · ✅ Resuelto
Logs con marca de tiempo y nivel, avisos al arrancar si falta `SESSION_SECRET` o si `BASE_URL` no
usa https, `/health/ready` que sí consulta la base, y `scripts/export_data.py` para respaldar o
entregarle sus datos a un cliente.

## Infraestructura

Antes de desplegar: `python -m scripts.check_deploy --clientes`. Revisa lo que rompe en
producción y no en desarrollo, y sale con error si encuentra algo bloqueante. Hay respaldo
semanal automático de los datos de todos los clientes.

$0/mes es correcto para validar, pero **el free tier que duerme es incompatible con el producto
en producción**: si el cliente toca la placa y espera ~50s a que el servidor despierte, se va.
El día que se firme el primer cliente hay que pasar a una instancia siempre encendida (~$7/mes);
un cliente a $20/mes lo cubre 3 veces. No deformar la arquitectura para defender el $0.
(Verificar las condiciones vigentes de los free tiers al momento de decidir: cambian seguido.)

## Legal / privacidad

El formulario privado recolecta datos personales (contacto + texto libre). Ya lleva un aviso
mínimo en la landing. Antes de vender a clientes reales conviene revisar la Ley 21.719 de
protección de datos (Chile) y definir quién es el responsable del tratamiento — el comercio o
la plataforma.

---

# Próximos pasos

*Estado al 2026-09-03, cierre de la jornada. Esta es la sección para leer primero al retomar.*

> Documentos que hay que leer antes de tocar código:
> [docs/revision-tecnica-2026-09-03.md](docs/revision-tecnica-2026-09-03.md) (hallazgos, qué está
> resuelto y qué no, y por qué las cosas son como son) y
> [docs/pendientes-del-usuario.md](docs/pendientes-del-usuario.md) (todo lo que depende del usuario).

## Cómo levantar todo

```powershell
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

| Qué | Dónde |
|---|---|
| Panel del comercio | `/panel/login` · `demo@cafe.cl` / `demo1234` |
| Panel del operador | `/admin` · clave **`admin-de-prueba-1234`** (provisional, ver abajo) |
| Landing de demo | `/r/ZTYFEMtc` (Café Demo, "Mesa 5") |
| Informe de demo | `/informe/4VB6_OoK` |

Hay dos negocios en la base local: **Café Demo** (token `4VB6_OoK`, con ~1900 toques de historia y
logo cargado) y **local3** (token `m0dyc-RA`), creado por el usuario probando el panel.

El `.env` local tiene `BASE_URL=http://localhost:8000` y un `ADMIN_PASSWORD_HASH` de prueba.
`python -m scripts.check_deploy --clientes` lista lo que falta para producción.

## Estado: el producto está terminado para validar

Funciona de punta a punta y **el usuario probó los 27 puntos de la ruta manual, todos correctos**.
La única falla que apareció fue el informe sin estilos, que resultó ser un bug real de CSP y ya está
corregido. Quedan 292 tests en verde.

Lo construido en la última jornada, además de cerrar 27 hallazgos de la revisión técnica:

- **Panel de administración del operador** en `/admin`: alta, edición, placas, contraseñas, rotación
  del enlace del informe, hoja de placas, aviso de prueba, actividad por cliente y eliminación.
- **Personalización por cliente**: logo y mensaje propios en la landing, y el logo también impreso
  en la placa física.
- **Revisión previa al despliegue** y **respaldo semanal automático**.

## Lo único que bloquea seguir avanzando en código

**Siete decisiones del usuario**, todas con recomendación escrita, en el bloque B de
[docs/pendientes-del-usuario.md](docs/pendientes-del-usuario.md). Basta que responda
"todas las recomendadas". Son: caducidad del enlace del informe, ocultar el contacto en el informe,
texto del canal privado, borrado automático de contactos antiguos, responsable del tratamiento de
datos, expiración de la sesión y logout por POST.

## Lo que se puede construir sin esperar a nadie

1. **Recuperación de contraseña por el propio dueño** (9.5 de la revisión). Hoy, si la olvida, el
   operador se la regenera y se la dicta. Requiere SMTP para llegar, pero se puede construir ya.
2. **Correo de bienvenida al dar de alta** (9.6), con enlace para que el dueño cree su propia clave,
   así la contraseña nunca viaja en texto plano ni hay que dictarla.
3. **Módulo 3, sentimiento** (9.10). Sigue siendo la prioridad más baja.

## Bloqueado esperando al usuario, por orden de importancia

1. **Comprar el dominio** (~$10/año). Bloquea imprimir cualquier placa. Es el único error
   irreversible del proyecto y cuesta diez dólares evitarlo.
2. **Conseguir un enlace real de reseñas de Google**. Hoy los dos negocios tienen uno provisional,
   así que un visitante que toque la placa no llega a dejar reseña. `check_deploy` lo marca como
   bloqueante.
3. **Solicitar acceso a la API de Google Business Profile**. Tarda semanas en aprobarse y no cuesta
   nada empezar; es lo que permitiría mostrar reseñas publicadas y no solo clics.
4. Crear las cuentas de Neon, Brevo y Sentry, y desplegar.
5. **Cambiar la clave del panel de administración**, que hoy es una de prueba escrita en una
   conversación: `python -m scripts.admin_password`.
6. **Revocar los tokens de GitHub** pegados en el chat, y subir los 8 commits pendientes.

## Decisiones ya tomadas (no volver a abrirlas)

| Decisión | Resuelto |
|---|---|
| `TIMEZONE` es global (`America/Santiago`); pasa a columna por negocio solo cuando haya un cliente fuera de Chile. | Confirmado por el usuario, 2026-09-03 |
| El enlace del informe **no pide login**: va por correo al propio dueño, como el enlace de una factura. | Confirmado por el usuario, 2026-09-03 |
| Login del panel con `scrypt` de la biblioteca estándar; se descartó Supabase Auth. | Decidido |
| WeasyPrint queda fuera de `requirements.txt`: un build que falla es peor que un PDF que falta. | Decidido |
| Base de datos: **Neon, no Supabase**, porque Supabase pausa los proyectos gratuitos y un cliente frente a una placa que no carga es inaceptable. | Decidido, 2026-09-03 |
| El logo se guarda en la base y no como archivo: el hosting no tiene disco persistente. | Decidido, 2026-09-03 |
| El panel de administración no existe sin `ADMIN_PASSWORD_HASH`: responde 404, nunca queda abierto por olvido. | Decidido, 2026-09-03 |

## WhatsApp como canal de alertas — explicado, sin decidir

Las alertas son dos: la **queja privada** (inmediata, es la que sostiene la suscripción, permite
llamar al cliente antes de que escriba una estrella pública) y el **resumen mensual**.

Hoy salen por correo y/o Telegram, ambos gratis. WhatsApp sería mejor canal porque es donde
realmente está un dueño de pyme chileno, pero la API oficial de Meta cobra los mensajes que inicia
el negocio (verificar tarifas al decidir). Las librerías no oficiales son gratis pero arriesgan el
baneo del número del negocio: **no usarlas**.

**Recomendación dada**: no pagar todavía. Arrancar con correo y, con dos o tres clientes reales,
medir si el dueño efectivamente reacciona. Agregar un canal es tocar solo `notify.py`.
