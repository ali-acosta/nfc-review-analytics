# Pendientes tuyos — todo lo que requiere tus manos

Este es el único documento que tienes que revisar tú. Todo lo demás (código, tests, correcciones)
lo trabajo yo en paralelo. Actualizado el 2026-09-03, tras tu ronda de pruebas.

> **Bloque A completado.** Recorriste los 27 puntos de prueba y todo funcionó. La única falla que
> encontraste fue el informe sin estilos ni gráficos, que resultó ser un bug real de política de
> seguridad y ya está corregido. Ningún test lo podía detectar, porque esa política la aplica el
> navegador: es el mejor argumento de por qué valía la pena que probaras a mano.

> **Bloque B completado.** Respondiste "todas las recomendadas" y las siete están implementadas,
> con tests. Lo que cambió para ti está resumido abajo, en el bloque B.

**Lo que queda es todo tuyo**: cinco cuentas por crear, cuatro compras y cinco tareas de orden.
Nada de eso lo puedo hacer yo.

Aquí está **todo** lo que no puedo hacer yo: probar con tus ojos y tu celular, decidir lo que es
tuyo decidir, crear cuentas a tu nombre, comprar cosas y ordenar lo que quedó suelto.

**Orden sugerido**: bloque E (seguridad, 5 minutos) hoy, bloque C (cuentas) esta semana porque
una de ellas tarda semanas en aprobarse, y bloque D (compras) cuando decidas avanzar a
producción.

---

## A · Probar lo que está construido · ✅ TERMINADO

Los 27 puntos quedaron probados y funcionando. Se dejan marcados abajo como registro de qué se
verificó y cuándo; el detalle paso a paso sigue en
[ruta-de-pruebas-manuales.md](ruta-de-pruebas-manuales.md), que sirve para repetir la ronda
después de cambios grandes o antes de desplegar.

**Qué quedó sin probar y hay que hacer antes de vender**: la experiencia real en un teléfono. La
red no dejó que el celular alcanzara al computador, así que todo se probó en el navegador con la
vista de móvil. No es lo mismo que un cliente parado en un local con mala señal. Queda pendiente
para cuando el proyecto viva en un equipo personal (punto E3) o esté desplegado.

**El servidor ya está corriendo** en `http://localhost:8000`. Las pruebas se hacen desde el
navegador de este computador: se intentó desde el celular, pero la red no deja que el teléfono
alcance al equipo. Para ver la landing como se verá en un teléfono, usa F12 y la vista de
dispositivo móvil.

Si el servidor se cae o reinicias el computador:

```powershell
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

### A.1 · El flujo del cliente (lo más importante)

- [x] Abrir la landing de "Mesa 5": http://localhost:8000/r/ZTYFEMtc (con F12 en vista de móvil)
- [x] Confirmar que **no hay selector de estrellas** antes del botón de Google
- [x] Tocar "Dejar reseña en Google" y confirmar que redirige
- [x] Recargar y tocar varias veces seguidas, confirmar que no da errores
- [x] Abrir el canal privado y enviar un comentario **con** calificación y contacto
- [x] Enviar otro **sin** calificación y **sin** contacto
- [x] Desde la página de gracias, tocar el botón de Google y anotar qué pasa
- [x] Probar un código inventado: `http://localhost:8000/r/no-existe-esto` → debe dar 404 limpio

### A.2 · El panel del dueño

- [x] Entrar en `/panel/login` con `demo@cafe.cl` / `demo1234`
- [x] Antes, probar contraseña incorrecta: no debe revelar si el correo existe
- [x] Revisar los cuatro números de arriba y los dos gráficos
- [x] Marcar dos o tres quejas como atendidas, y reabrir una
- [x] Exportar el buzón a CSV y abrirlo en Excel (revisar que los acentos estén bien)
- [x] Probar "Cambiar contraseña", incluida la actual mal escrita
- [x] Cerrar sesión y confirmar que `/dashboard/` ya no abre

### A.3 · El informe mensual

- [x] Abrir `http://localhost:8000/informe/4VB6_OoK`
- [x] Probar un mes concreto: `?mes=2026-08`
- [x] Probar un mes vacío: `?mes=2026-01` → debe cargar con ceros, no romperse
- [x] Imprimir a PDF desde el navegador y revisar cómo queda
- [x] Abrir `/informe/4VB6_OoK/pdf` → debe dar un mensaje claro, nunca un error de servidor

### A.4 · Dar de alta un cliente de prueba

- [x] Correr `python -m scripts.new_client` en modo interactivo y crear uno inventado
- [x] Anotar la contraseña que imprime (no se vuelve a mostrar)
- [x] Entrar al panel de ese cliente nuevo y confirmar que está vacío
- [x] Correr `python -m scripts.new_client --listar`

### A.5 · Casos límite (opcional)

- [x] Recargar la landing más de 60 veces rápido: la página nunca debe fallar
- [x] Fallar el login 9 veces seguidas: debe bloquear por unos minutos
- [x] Ver la landing en pantalla de computador, no solo celular

### La prueba en celular queda pendiente

El QR y el servidor están correctos: lo verifiqué decodificando el archivo del QR y comprobando
que el servidor respondía en la dirección de red, no solo en localhost. Lo que falla es que el
teléfono no logra alcanzar a este computador estando en la misma WiFi, y el firewall de Windows
no es la causa porque está desactivado en el perfil activo. Queda como sospechoso el aislamiento
de clientes del router o alguna protección del equipo corporativo.

No vale la pena resolverlo ahora. La prueba de la experiencia real en un teléfono importa y hay
que hacerla antes de vender, pero puede esperar a que el proyecto viva en un equipo personal
(punto E3 de esta lista). Mientras tanto, todo lo demás se prueba igual desde el navegador.

### Lo que cambió mientras preparabas la ronda

Corregí las fases A y B completas de la revisión y **reinicié el servidor dos veces**, así que
estás probando el código nuevo. Lo que verás distinto a lo que dice la ruta de pruebas:

- **El panel ahora tiene un selector de período** arriba (Este mes / Mes pasado / Todo) y un botón
  "Actualizar". Por defecto muestra este mes, igual que el informe, así que ya no vas a ver dos
  cifras distintas sin explicación. El título del panel dice qué período estás mirando.
- **El botón de Google de la página de gracias ahora sí cuenta la conversión.**
- **El buzón de quejas no se filtra por período**, a propósito: una queja pendiente de hace dos
  meses sigue pendiente hoy.
- **Si tenías sesión abierta, se cerró.** Vuelve a entrar.

**Sigue pendiente y no hace falta que lo reportes**: el PDF no genera en Windows (es esperado) y
los QR apuntan a tu red local (es solo para esta prueba).

**Si encuentras algo que no está en esa lista, eso es lo que vale oro.** Anota el paso exacto.

---

## B · Decisiones que solo tú puedes tomar · ✅ TERMINADO

Respondiste "todas las recomendadas" el 2026-09-03. Las siete están implementadas y con tests.
Esto es lo que cambió, en lo que tú vas a notar:

| # | Qué pediste | Qué cambió para ti |
|---|---|---|
| B1 | Enlace del informe con vencimiento | El enlace del informe ahora **caduca a los 90 días y abre un solo mes**. Sigue sin pedir contraseña: el dueño lo abre desde el correo igual que antes, cero clicks extra. Si intenta abrir uno viejo, ve una página que le explica que venció y lo manda a su panel. Ojo con una cosa: **el enlace “a secas” (`/informe/TOKEN`) ya no abre nada** salvo que tengas sesión iniciada. Los que salen del panel de administración y del envío mensual ya vienen firmados. |
| B2 | No ocultar el contacto | Sin cambios: el teléfono del cliente enojado sigue en el informe, que es lo que te permite llamarlo. |
| B3 | Texto neutro del canal privado | La landing ya no dice "¿Tuviste un problema?" sino **"¿Prefieres contárnoslo en privado?"**, y el campo dice "Cuéntanos cómo te fue". Hay un test que falla si alguna vez vuelve a presuponer que al cliente le fue mal. |
| B4 | Borrar contactos antiguos | Los contactos de las quejas se borran **a los 6 meses**, automáticamente, el día 1 de cada mes. Se borra solo el contacto: el comentario queda, y las métricas no se mueven. La landing ahora se lo avisa al cliente final. **Cambié un detalle de la propuesta**: el plazo se cuenta desde que llegó la queja y no desde que la marcaste atendida, porque si no, una queja que nadie marca guarda el teléfono para siempre. |
| B5 | Responsable del tratamiento | Queda escrito: **el comercio es el responsable, tu plataforma es la encargada**. La landing lo refleja ("Café Demo usará lo que nos escribas…"). Sigue conviniendo que lo confirme alguien que sepa antes del primer cliente que pague. |
| B6 | Sesión de 7 días | El panel del dueño **cierra sesión a los 7 días** en vez de 14. |
| B7 | Logout por POST | Cerrar sesión ahora es un botón de verdad. Antes, cualquier página ajena podía sacar al dueño de su panel con un enlace escondido. |

**Una cosa nueva que necesito de ti por culpa de B1** (está también en el bloque C): cuando
configures el envío mensual en GitHub, tiene que llevar el secret `SESSION_SECRET`, **el mismo
valor** que pongas en el servidor. Es la clave con la que se firman los enlaces del informe: si
fueran distintas, el correo del día 1 saldría con un enlace que tu propio servidor rechaza. Hay
un test que falla si el workflow se queda sin ese secret, pero que las dos claves sean iguales
solo lo puedes garantizar tú.

---

## C · Cuentas y trámites (empezar esta semana)

### C1 · Acceso a la API de Google Business Profile — **empieza ya, tarda semanas**

- [ ] Crear un proyecto en Google Cloud Console
- [ ] Solicitar acceso a las Business Profile APIs mediante el formulario de Google
- [ ] Anotar el número de solicitud y la fecha

**Por qué ahora**: la aprobación puede tardar semanas y es lo que permite mostrar *reseñas
publicadas* en vez de solo *clicks hacia Google*. Es el número que realmente vendes. No hay nada
que construir hasta que aprueben, pero la espera corre desde que solicitas.

### C2 · Sentry (monitoreo de errores) — gratis

- [ ] Crear cuenta en sentry.io, plan gratuito
- [ ] Crear un proyecto Python y copiar el DSN
- [ ] Pegármelo o ponerlo en `.env` como `SENTRY_DSN=`

**Por qué**: hoy, si un cliente ve un error en producción, no te enteras nunca. Un cliente parado
en un mostrador no reclama, se va. Yo dejo la integración lista y apagada; se enciende sola
cuando pegas la clave.

### C3 · Brevo (envío de correos) — gratis, 300 correos/día

- [ ] Crear cuenta en brevo.com
- [ ] Obtener las credenciales SMTP (servidor, puerto, usuario, clave)
- [ ] Guardarlas para cuando despleguemos

**Por qué**: es el canal de la alerta de queja, que es la razón principal por la que un cliente
sigue pagando. Un dueño de pyme chileno revisa su correo a diario.

**Y desde hoy también**, dos cosas más que ya están construidas y que sin SMTP no sirven:

- **El correo de bienvenida**: al dar de alta un cliente le llega un enlace para que elija su
  propia contraseña, y tú no tienes que dictarle nada. Sin SMTP, el alta te imprime una clave
  generada y vuelves a leérsela por teléfono.
- **La recuperación de contraseña**: el dueño entra a "¿Olvidaste tu contraseña?" en el login y
  le llega un enlace de una hora. Sin SMTP la página se lo dice honestamente, y vuelve a
  depender de que se la regeneres tú.

Es la diferencia entre una función que existe y una que funciona.

### C4 · Neon (base de datos) — gratis · **no uses Supabase**

- [ ] Crear cuenta en neon.tech y una base
- [ ] Copiar la cadena de conexión

**Por qué Neon y no Supabase**: Supabase pausa los proyectos gratuitos a los 7 días sin actividad
y hay que reanudarlos a mano; si eso pasa, un cliente toca la placa y no carga nada. Neon
suspende el cómputo pero despierta solo en aproximadamente un segundo.

### C6 · Los secrets de GitHub para el envío mensual

- [ ] En Settings → Secrets del repositorio, cargar: `DATABASE_URL`, `BASE_URL`,
      `SESSION_SECRET`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
- [ ] Verificar que `SESSION_SECRET` sea **exactamente el mismo valor** que el del servidor

**Por qué el mismo valor**: con esa clave se firman los enlaces del informe. Si el servidor firma
con una y el correo mensual con otra, el día 1 de cada mes cada cliente recibe un enlace que tu
propio servidor rechaza, y te enteras por el reclamo. Es la misma clase de error que ya pasó con
el correo: el código perfecto y la variable que nunca llega.

### C5 · Telegram (opcional)

- [ ] Hablar con `@BotFather` para crear un bot y copiar el token
- [ ] Hablar con `@userinfobot` para obtener tu chat id

**Por qué opcional**: el correo es el canal principal. Telegram es un extra para ti como
operador, para enterarte al instante.

---

## D · Compras y hardware (cuando decidas avanzar)

### D1 · El dominio — **lo único que bloquea todo lo físico**

- [ ] Comprar el dominio (~$10 al año)
- [ ] Decirme cuál es, para ponerlo en `BASE_URL`

**Por qué es lo más urgente de esta lista**: la URL queda grabada en el chip y pegada en la mesa.
Si imprimes con una URL temporal y algún día cambias de hosting, **mueren todas las placas
instaladas**. Es el único error verdaderamente irreversible del proyecto y cuesta diez dólares
evitarlo.

Sugerencia de nombres cortos, porque la URL va impresa: algo de 8 a 12 caracteres, fácil de
dictar por teléfono, sin guiones ni tildes.

### D2 · Link real de reseña de Google

- [ ] Conseguir el link de reseñas de cualquier negocio conocido (un amigo, un familiar, tu
      cafetería de siempre)

**Por qué**: hoy el negocio demo tiene un placeholder. Sin un link real no puedes hacerle una
demo creíble a nadie. Se obtiene desde el perfil de Google Business del negocio, en "Solicitar
reseñas", y toma dos minutos si el dueño te lo comparte.

### D3 · Hardware NFC

- [ ] Comprar chips NTAG213 (alcanzan de sobra para una URL corta, más baratos que el 215)
- [ ] Al grabarlos, **bloquearlos con contraseña**

**Por qué el bloqueo**: si el chip queda sin proteger, cualquiera con un celular puede
reescribirle la URL a la placa de tu cliente y redirigir a donde quiera. Es parte del proceso de
fabricación, no del software.

### D4 · Hosting cuando llegue el primer cliente

- [ ] Pasar de la instancia gratuita a una siempre encendida (~$7 al mes)

**Por qué**: el plan gratuito duerme, y despertar tarda alrededor de 50 segundos. Un cliente
parado en la caja no espera 50 segundos. Un cliente que te paga $20 al mes cubre ese costo tres
veces.

---

## E · Seguridad y orden (5 minutos, hoy)

### E1 · Revocar los tokens de GitHub que pegaste en el chat

- [ ] Entrar a `github.com/settings/tokens`
- [ ] Borrar el token clásico `ghp_YpMEn...` y el fine-grained `github_pat_11AQ...`

**Por qué**: los dos quedaron escritos en la conversación. Ya cumplieron su función (el código
está subido) y mientras existan son llaves válidas de tu cuenta.

### E2 · Confirmar que el repositorio es privado

- [ ] Abrir `github.com/ali-acosta/nfc-review-analytics/settings` y verificar que dice "Private"

**Por qué**: el repositorio incluye el PDF con tu modelo de negocio y precios, y los documentos
de estrategia. No hay claves ni secretos en el código, pero eso no es para publicar.

### E3 · Sacar el proyecto de OneDrive

- [ ] Clonar en una ruta fuera de OneDrive, por ejemplo `C:\Users\aliacost\Proyectos\`
- [ ] Crear ahí el entorno virtual nuevo
- [ ] Verificar que todo corre, y recién ahí borrar la copia de OneDrive

**Por qué**: OneDrive sincronizando los archivos internos de git mientras git los escribe es una
causa conocida de repositorios corruptos. Además el entorno virtual son miles de archivos
subiéndose a la nube de la empresa sin ningún motivo. Ahora que el código está en GitHub, mover
es seguro.

### E4 · Instalar Python 3.12

- [ ] Instalar Python 3.12 y crear el entorno virtual nuevo con esa versión

**Por qué**: tu computador usa 3.10 y el servidor usará 3.12. Este proyecto ya se quemó dos veces
con diferencias entre desarrollo y producción. Conviene hacerlo junto con E3, en un solo
movimiento.

### E5 · Decidir sobre el equipo corporativo

- [ ] Pensar si te conviene seguir desarrollando esto en un equipo de Cencosud

**Por qué**: el proyecto vive en un equipo de la empresa, dentro de su OneDrive, y el git del
equipo tenía configurado tu correo corporativo. Muchas políticas laborales reclaman la propiedad
de lo desarrollado con recursos de la empresa. No es una alarma, es algo que conviene tener
claro antes de que el proyecto valga dinero. Los commits ya salen con tu correo personal.

---

## Resumen: las tres cosas más importantes

1. **Probar el flujo con tu celular** (bloque A.1). Es lo único que valida que el producto
   funciona de verdad, y nadie lo ha hecho todavía.
2. **Comprar el dominio** (D1). Diez dólares que evitan el único error irreversible.
3. **Solicitar el acceso a la API de Google** (C1). Tarda semanas y no cuesta nada empezar.

Todo lo demás puede esperar a que termines de probar.

---

## Qué volver a probar a mano después de estos cambios

Son cinco minutos y cubren lo que la suite no ve. El detalle está en
[ruta-de-pruebas-manuales.md](ruta-de-pruebas-manuales.md).

- [ ] Abrir la landing y confirmar que el botón privado dice "¿Prefieres contárnoslo en privado?"
      y que abajo aparece el aviso de que el contacto se borra a los 6 meses.
- [ ] Abrir `/informe/4VB6_OoK` **sin** sesión: debe salir la página de "este enlace ya no sirve",
      no un error.
- [ ] Correr `python -m scripts.new_client --listar`, copiar el enlace del informe que imprime y
      abrirlo en una ventana privada: ese sí debe abrir, con sus gráficos.
- [ ] En el panel del dueño, cerrar sesión con el botón nuevo.
- [ ] Da de alta un cliente de prueba desde `/admin`: sin SMTP debe seguir mostrándote la
      contraseña generada. Con Brevo configurado, esa pantalla tiene que cambiar a "ya le
      avisamos al dueño" y no mostrarte ninguna clave.
- [ ] En el login, entrar a "¿Olvidaste tu contraseña?": sin SMTP configurado debe decirlo
      claramente, no fingir que mandó un correo.

---

## F · Probar el programa de sellos (nuevo, 2026-09-04)

Está construido y probado de punta a punta por código, pero **nadie lo ha visto con dos teléfonos
de verdad**, que es donde se nota si sirve. Ya está activo en Café Demo: 3 sellos, "El 4° café
gratis". Si no tienes a mano la clave del panel, reemítela con
`python -m scripts.new_client --reset-password 4VB6_OoK`: la imprime una sola vez.

La idea: tú haces de cajero en el computador, y usas tu celular como si fueras el cliente.

- [ ] Entra a `/panel/fidelizacion` y mira los números del programa.
- [ ] Abre `/panel/caja` y déjala abierta. **Confirma que el código cambia solo cada minuto** y que
      el contador baja. Esta es la pantalla que va a estar todo el día en el mostrador.
- [ ] Con el celular, escanea el QR de esa pantalla. Debe crearte una tarjeta y sumarte un sello.
- [ ] **Escanea otra vez de inmediato**: tiene que decirte que ya tienes tu sello de hoy y no
      sumarte otro. Es lo que impide que alguien se regale el premio en cinco minutos.
- [ ] Espera a que el código cambie y **escanea una foto del código viejo**: tiene que rechazarlo.
- [ ] Guarda la página de la tarjeta en la pantalla de inicio del celular y ábrela después: tus
      sellos tienen que seguir ahí.
- [ ] Desde la landing de la mesa (`/r/ZTYFEMtc`), busca "Ver mi tarjeta de sellos" abajo del todo.
      **Confirma que el botón de Google sigue siendo lo primero de la página.**

**Lo que quiero que mires con ojo crítico**, porque es una decisión de producto y es tuya:

1. ¿La fricción de escanear el código de la caja es aceptable para un cajero con fila? Si te
   parece demasiado, la alternativa es más débil pero existe (ver el documento de diseño).
2. ¿El premio y la cantidad de sellos se configuran fácil, o le pedirías algo más al dueño?
3. ¿Se entiende la tarjeta sin que nadie te la explique?

**Y una advertencia**: cuando lo muestres como argumento de venta, el precio del combo que
proponía el pitch ($35-60/mes) da por hecho un WhatsApp que **ya no es gratis** y que a volumen
se come la suscripción entera. Los números están en
[fidelizacion-diseno.md](fidelizacion-diseno.md). Lo que sí puedes vender hoy sin costo variable
es la tarjeta de sellos y, más adelante, el pase de Google Wallet.
