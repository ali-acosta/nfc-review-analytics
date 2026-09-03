# Pendientes tuyos — todo lo que requiere tus manos

Este es el único documento que tienes que revisar tú. Todo lo demás (código, tests, correcciones)
lo trabajo yo en paralelo. Actualizado el 2026-09-03.

Aquí está **todo** lo que no puedo hacer yo: probar con tus ojos y tu celular, decidir lo que es
tuyo decidir, crear cuentas a tu nombre, comprar cosas y ordenar lo que quedó suelto.

**Orden sugerido**: bloque A (probar) hoy, bloque E (seguridad, 5 minutos) hoy también, bloque C
(cuentas) esta semana porque una de ellas tarda semanas en aprobarse, bloque B (decisiones)
cuando tengas tiempo de leer, bloque D (compras) cuando decidas avanzar a producción.

---

## A · Probar lo que está construido

El detalle paso a paso está en [ruta-de-pruebas-manuales.md](ruta-de-pruebas-manuales.md). Acá
va la versión corta para que lleves la cuenta.

**El servidor ya está corriendo** en `http://10.207.55.203:8000`. Tu celular tiene que estar en
la misma WiFi. Si se cae o reinicias el computador:

```powershell
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### A.1 · El flujo del cliente, desde tu celular (lo más importante)

- [ ] Escanear el QR de "Mesa 5" (`qrcodes\ZTYFEMtc.png`) o abrir `http://10.207.55.203:8000/r/ZTYFEMtc`
- [ ] Confirmar que **no hay selector de estrellas** antes del botón de Google
- [ ] Tocar "Dejar reseña en Google" y confirmar que redirige
- [ ] Recargar y tocar varias veces seguidas, confirmar que no da errores
- [ ] Abrir el canal privado y enviar un comentario **con** calificación y contacto
- [ ] Enviar otro **sin** calificación y **sin** contacto
- [ ] Desde la página de gracias, tocar el botón de Google y anotar qué pasa
- [ ] Probar un código inventado: `http://10.207.55.203:8000/r/no-existe-esto` → debe dar 404 limpio

### A.2 · El panel del dueño

- [ ] Entrar en `/panel/login` con `demo@cafe.cl` / `demo1234`
- [ ] Antes, probar contraseña incorrecta: no debe revelar si el correo existe
- [ ] Revisar los cuatro números de arriba y los dos gráficos
- [ ] Marcar dos o tres quejas como atendidas, y reabrir una
- [ ] Exportar el buzón a CSV y abrirlo en Excel (revisar que los acentos estén bien)
- [ ] Probar "Cambiar contraseña", incluida la actual mal escrita
- [ ] Cerrar sesión y confirmar que `/dashboard/` ya no abre

### A.3 · El informe mensual

- [ ] Abrir `http://10.207.55.203:8000/informe/4VB6_OoK`
- [ ] Probar un mes concreto: `?mes=2026-08`
- [ ] Probar un mes vacío: `?mes=2026-01` → debe cargar con ceros, no romperse
- [ ] Imprimir a PDF desde el navegador y revisar cómo queda
- [ ] Abrir `/informe/4VB6_OoK/pdf` → debe dar un mensaje claro, nunca un error de servidor

### A.4 · Dar de alta un cliente de prueba

- [ ] Correr `python -m scripts.new_client` en modo interactivo y crear uno inventado
- [ ] Anotar la contraseña que imprime (no se vuelve a mostrar)
- [ ] Entrar al panel de ese cliente nuevo y confirmar que está vacío
- [ ] Correr `python -m scripts.new_client --listar`

### A.5 · Casos límite (opcional)

- [ ] Recargar la landing más de 60 veces rápido: la página nunca debe fallar
- [ ] Fallar el login 9 veces seguidas: debe bloquear por unos minutos
- [ ] Ver la landing en pantalla de computador, no solo celular

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

## B · Decisiones que solo tú puedes tomar

Para cada una dejo mi recomendación, así puedes responder con un "sí" o "no" sin tener que
investigar. Ninguna bloquea mi trabajo de esta semana.

| # | Decisión | Mi recomendación |
|---|---|---|
| B1 | **¿Enlace del informe con vencimiento?** Hoy el enlace del informe nunca caduca, no pide clave y da acceso a todos los meses, con teléfonos y quejas de clientes finales adentro. Se puede firmar por mes con vencimiento a 90 días, sin agregar ni un click de fricción para el dueño. | **Sí.** Mantiene la fricción cero que pediste y limita el daño de un correo reenviado. |
| B2 | **¿Ocultar el contacto del cliente en el informe** y mostrarlo solo en el panel? | **No por ahora.** El contacto en el informe sirve para llamar al cliente enojado, que es el valor del producto. Revisar si algún cliente lo objeta. |
| B3 | **¿Cambiar el texto "¿Tuviste un problema?"** en la landing por algo neutro como "¿Prefieres contárnoslo en privado?" | **Sí.** Google endureció la detección de solicitud selectiva en abril de 2026. No cambia el flujo y quita ambigüedad. |
| B4 | **¿Borrar automáticamente los contactos** de las quejas atendidas después de 6 meses? La Ley 21.719 pide finalidad y plazo. | **Sí**, con un comando que corra mensual. Te dejo el borrador cuando digas. |
| B5 | **¿Quién es el responsable del tratamiento** de datos, el comercio o tu plataforma? Es lo primero que pregunta un abogado. | **El comercio**, con tu plataforma como encargada. Es lo habitual y lo más defendible. Conviene confirmarlo con alguien que sepa antes del primer cliente que pague. |
| B6 | **¿Sesión del panel que expire a los 7 días?** Hoy dura 14. | **Sí.** Un panel abierto en el mostrador del local dos semanas es mucho. |
| B7 | **¿Logout por POST en vez de GET?** Hoy cualquier enlace puede cerrarle la sesión al dueño. | **Sí.** Es molesto, no peligroso, y son diez minutos. |

Estas siete son lo único de la revisión técnica que sigue esperando por ti en la parte de código.
Todo lo demás que no dependía de una decisión tuya ya está corregido: 27 hallazgos cerrados, la
suite pasó de 149 a 176 tests.

**Cómo responder**: basta con "B1 sí, B2 no, B3 sí…" o "todas las recomendadas". Yo las
implemento.

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

### C4 · Neon (base de datos) — gratis · **no uses Supabase**

- [ ] Crear cuenta en neon.tech y una base
- [ ] Copiar la cadena de conexión

**Por qué Neon y no Supabase**: Supabase pausa los proyectos gratuitos a los 7 días sin actividad
y hay que reanudarlos a mano; si eso pasa, un cliente toca la placa y no carga nada. Neon
suspende el cómputo pero despierta solo en aproximadamente un segundo.

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

## Resumen: lo tres cosas más importantes

1. **Probar el flujo con tu celular** (bloque A.1). Es lo único que valida que el producto
   funciona de verdad, y nadie lo ha hecho todavía.
2. **Comprar el dominio** (D1). Diez dólares que evitan el único error irreversible.
3. **Solicitar el acceso a la API de Google** (C1). Tarda semanas y no cuesta nada empezar.

Todo lo demás puede esperar a que termines de probar.
