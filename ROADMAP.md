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
y exigir login en cada correo mensual haría fricción justo en la pieza de retención. Lo que sí
tiene es **vencimiento**: va firmado sobre `token:AAAA-MM`, vale 90 días y abre un solo mes, así
que un correo reenviado deja de ser una llave permanente a los contactos y las quejas de los
clientes finales del comercio.
El dueño cambia su contraseña él mismo en `/panel/password` (se le pide la actual: si deja el
panel abierto en el mostrador, nadie debería poder quedarse con la cuenta) y **la recupera solo**
desde `/panel/recuperar`: un enlace firmado que le llega a su correo, vale una hora y muere al
usarse. El operador conserva `--reset-password` para cuando no haya correo saliente. La sesión
del panel dura 7 días y cerrarla es un POST, no un enlace que cualquiera pueda disparar.

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

### Calidad — Tests · ✅ 352 tests
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

## Legal / privacidad · ✅ Base cubierta

El formulario privado recolecta datos personales de terceros (contacto + texto libre): gente que
no es cliente nuestra y que no tiene forma de pedir que la borren. Lo que hay hoy:

- **Responsable del tratamiento: el comercio**; la plataforma es la encargada. Decidido por el
  usuario el 2026-09-03, y es lo habitual y lo más defendible. Conviene confirmarlo con alguien
  que sepa antes del primer cliente que pague.
- **Plazo y finalidad**, que es lo que exige la Ley 21.719: el contacto se borra a los 6 meses,
  automáticamente (`scripts/anonimizar_contactos.py`, agendado el día 1 de cada mes), y la
  landing se lo avisa al cliente final. Se borra el contacto y no la queja: sin contacto ya no
  identifica a nadie, y el comentario es el registro con el que el comercio trabaja.
- **Los enlaces que llevan esos datos caducan**: el informe mensual vale 90 días y abre un solo
  mes.

---

# Próximos pasos

*Estado al 2026-09-03, cierre de la segunda jornada. Esta es la sección para leer primero al
retomar.*

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
| Panel del comercio | `/panel/login` · `demo@cafe.cl` (el usuario cambió la clave probando) |
| Recuperar la clave | `/panel/recuperar` — necesita SMTP para llegar; sin él lo dice y no finge |
| Panel del operador | `/admin` · clave **`admin-de-prueba-1234`** (provisional, ver abajo) |
| Landing de demo | `/r/ZTYFEMtc` (Café Demo, "Mesa 5") |
| Informe de demo | **ya no basta `/informe/4VB6_OoK`**: el enlace va firmado. Sácalo de `python -m scripts.new_client --listar`, o ábrelo con la sesión del panel iniciada. |

Hay dos negocios en la base local: **Café Demo** (token `4VB6_OoK`, con ~1900 toques de historia y
logo cargado) y **local3** (token `m0dyc-RA`), creado por el usuario probando el panel.

El `.env` local tiene `BASE_URL=http://localhost:8000` y un `ADMIN_PASSWORD_HASH` de prueba.
`python -m scripts.check_deploy --clientes` lista lo que falta para producción.

## Estado: el producto está terminado para validar

Funciona de punta a punta, el usuario probó los 27 puntos de la ruta manual y **ya no queda
ninguna decisión suya pendiente en la parte de código**: respondió el bloque B entero ("todas las
recomendadas") y está implementado. 352 tests en verde.

Lo construido en esta jornada:

- **Bloque B completo**: enlace del informe firmado y con vencimiento a 90 días (abre un solo
  mes), texto neutro del canal privado, borrado automático de los contactos a los 6 meses,
  sesión del panel de 7 días y logout por POST.
- **Recuperación de contraseña por el propio dueño** (9.5), con enlace de un solo uso, limitador
  propio y una respuesta que no delata qué correos son de clientes.
- **Correo de bienvenida al dar de alta** (9.6): el dueño recibe un enlace y elige su propia
  contraseña. Ya no hay que dictarle una por teléfono. Si no hay SMTP, el alta vuelve al camino
  de antes e imprime la clave, para no dejar al cliente sin poder entrar.

## Lo que se puede construir sin esperar a nadie

Se acabó lo que tenía sentido hacer sin el usuario. Lo que queda en la lista de desarrollos son
cosas que no corresponde adelantar:

1. **Módulo 2, sincronización con Google Business Profile** (9.3). Es el módulo que *prueba* el
   número que se vende, pero no se puede empezar hasta que Google apruebe el acceso a la API, y
   esa solicitud la tiene que hacer el usuario.
2. **Zona horaria por negocio** (9.7). Un día de trabajo, y no antes de que exista un cliente
   fuera de Chile.
3. **Módulo 3, sentimiento** (9.10). Sigue siendo la prioridad más baja: con 20 reseñas al mes un
   dueño las lee.

Lo que de verdad falta ahora está en la lista de abajo, y es del usuario.

## Bloqueado esperando al usuario, por orden de importancia

1. **Comprar el dominio** (~$10/año). Bloquea imprimir cualquier placa. Es el único error
   irreversible del proyecto y cuesta diez dólares evitarlo.
2. **Conseguir un enlace real de reseñas de Google**. Hoy los dos negocios tienen uno provisional,
   así que un visitante que toque la placa no llega a dejar reseña. `check_deploy` lo marca como
   bloqueante.
3. **Configurar el SMTP** (Brevo gratuito). Ya no sostiene solo la alerta de queja: también es
   por donde el dueño recupera su contraseña. Sin él, esa función existe pero no sirve.
4. **Solicitar acceso a la API de Google Business Profile**. Tarda semanas en aprobarse y no cuesta
   nada empezar; es lo que permitiría mostrar reseñas publicadas y no solo clics.
5. Crear las cuentas de Neon y Sentry, y desplegar. **Al cargar los secrets de GitHub, incluir
   `SESSION_SECRET` con el mismo valor que el servidor**: con esa clave se firman los enlaces del
   informe, y si difieren, el correo del día 1 sale con enlaces que el servidor rechaza.
6. **Cambiar la clave del panel de administración**, que hoy es una de prueba escrita en una
   conversación: `python -m scripts.admin_password`.
7. **Revocar los tokens de GitHub** pegados en el chat, y subir los commits pendientes.

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
| El **responsable del tratamiento** de los datos de las quejas es **el comercio**; la plataforma es la encargada. | Confirmado por el usuario, 2026-09-03 |
| El enlace del informe **caduca a los 90 días y abre un solo mes**. Sigue sin pedir login: la fricción cero era la decisión, no la permanencia. | Confirmado por el usuario, 2026-09-03 |
| El contacto del cliente final **se queda en el informe**: llamar al cliente enojado es el valor del producto. | Confirmado por el usuario, 2026-09-03 |
| Los contactos de las quejas se borran a los **6 meses desde que llegan** (no desde que se atienden: si no, una queja que nadie marca los guarda para siempre). | Decidido, 2026-09-03 |

## WhatsApp como canal de alertas — explicado, sin decidir

Las alertas son dos: la **queja privada** (inmediata, es la que sostiene la suscripción, permite
llamar al cliente antes de que escriba una estrella pública) y el **resumen mensual**.

Hoy salen por correo y/o Telegram, ambos gratis. WhatsApp sería mejor canal porque es donde
realmente está un dueño de pyme chileno, pero la API oficial de Meta cobra los mensajes que inicia
el negocio (verificar tarifas al decidir). Las librerías no oficiales son gratis pero arriesgan el
baneo del número del negocio: **no usarlas**.

**Recomendación dada**: no pagar todavía. Arrancar con correo y, con dos o tres clientes reales,
medir si el dueño efectivamente reacciona. Agregar un canal es tocar solo `notify.py`.
