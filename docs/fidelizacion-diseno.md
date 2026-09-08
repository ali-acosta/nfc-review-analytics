# Fidelización digital sin app — diseño

Estado: **Fase 1 construida y funcionando** (2026-09-04). Las fases 2 a 4 siguen sin empezar.
Escrito a partir de la idea del usuario, antes de escribir código, para que las decisiones de
costo y de confianza quedaran tomadas primero: dos de ellas son caras de revertir.

Decidido por el usuario el 2026-09-04: **el sello lo da un código rotativo en la caja** (no el
modelo laxo de un sello diario sin control), y **la Fase 1 se construye ahora**.

## Qué es

Reemplazar la tarjeta de sellos de papel por una digital, en la misma placa NFC que ya capta
reseñas. El cliente final acumula sellos y canjea un premio; el comercio obtiene, además de la
reseña, una base de clientes recurrentes y un canal para traerlos de vuelta.

El argumento de venta es real: ataca la **frecuencia de compra**, que es un número que el dueño
siente en la caja, y justifica una suscripción más alta que la de solo reseñas.

## Los tres supuestos falsos del pitch original

Verificados el 2026-09-04. **Confirmar contra la tarifa oficial de Meta antes de fijar precio**:
lo de abajo viene de revendedores, no de la página de Meta.

### 1. WhatsApp ya no tiene 1.000 conversaciones gratis

Ese modelo terminó el **1 de julio de 2025**. Hoy Meta cobra **por mensaje entregado**, por
categoría y por país. Chile es de los mercados más caros de LATAM: **~$0.0592 USD por mensaje de
marketing**. Los mensajes de marketing además **no** tienen descuento por volumen.

Lo que eso hace con el modelo de negocio:

| Clientes fidelizados | Mensajes/mes c/u | Costo mensual solo Meta |
|---|---|---|
| 100 | 1 | ~$6 |
| 200 | 1 | ~$12 |
| 300 | 2 | ~$35 |

La suscripción que el pitch propone es de $35-60 USD/mes. **A 300 clientes y dos mensajes al mes,
Meta se lleva el piso completo de la suscripción.** Y empeora con el éxito del cliente: mientras
mejor le funcione el programa, más caro sale servirlo. Un producto cuyo costo variable crece
con el uso necesita, o mensajes racionados, o un precio con componente por mensaje, o un canal que
no cobre por mensaje.

Además, desde el **1 de octubre de 2026** (en menos de un mes) se empezarían a cobrar también los
mensajes de servicio salientes dentro de la ventana de 24 horas, con lo que desaparece el último
camino gratis. Verificar.

Y hay fricción de alta, no solo costo: mandar desde el número *del comercio* exige verificación de
negocio en Meta para cada cliente. Mandar desde un número de la plataforma es rápido, pero
entonces el mensaje llega de "NFC Reviews" y no de "Café Demo" — que es justo lo que el dueño
cree estar comprando.

### 2. Apple Wallet no es gratis; Google Wallet sí

Las librerías para generar `.pkpass` son libres, pero el archivo tiene que ir **firmado con un Pass
Type ID certificate**, y ese solo sale de una cuenta del **Apple Developer Program: $99 USD/año**,
con renovación anual del certificado. Sin firma válida, el iPhone rechaza el pase.

Lo importante: el certificado es **del emisor, o sea de la plataforma, no de cada cliente**. Un
solo pago de $99 al año cubre a todos los comercios. A diez clientes son ~$0.83 por cliente al mes.

**Google Wallet no cobra por la API.** Pide crear una cuenta de emisor en la Google Pay & Wallet
Console; las cuentas nuevas arrancan en *demo mode* (solo emiten a cuentas de prueba) y hay que
pedir acceso de publicación. Trámite, no costo. Como la mayoría del parque de teléfonos en Chile
es Android, Google Wallet solo ya cubre a la mayor parte de los clientes finales.

### 3. El re-enganche por Wallet cuesta $0 por mensaje

Es el punto que el pitch no ve. Un pase de Wallet **se actualiza y notifica solo**: cambia el
contador de sellos y aparece en la pantalla bloqueada, y en el caso de Apple puede mostrarse
cuando el cliente está cerca del local. Eso es exactamente el mecanismo de re-enganche que el
pitch quiere comprarle a WhatsApp a $0.059 el mensaje.

Es menos llamativo que un WhatsApp, sí. Pero cuesta cero por envío, no necesita verificación de
Meta, no necesita consentimiento de marketing con la misma carga, y no se cae si el cliente
cambia de opinión sobre pagarle a Meta.

## El problema que el pitch no menciona: un sello vale dinero

Toda la arquitectura actual se apoya en que **el token de una placa es público a propósito** —
está pegado en una mesa, cualquiera lo lee, y lo peor que puede pasar es que alguien ensucie una
métrica (por eso hay límite por IP, deduplicación por sesión y filtro de bots).

**Con fidelización eso deja de ser cierto**: el sello se canjea por un café. Si tocar la placa da
un sello, cualquiera se regala el quinto café tocándola cinco veces, o directamente desde su casa
con una foto del QR. Es la primera pregunta que va a hacer un dueño en la demo, y si la respuesta
es mala, no hay venta.

### La solución: el sello lo da la caja, no la mesa

Es lo que ya hace el mundo físico. El timbre de la tarjeta de papel lo tiene el cajero, no el
cliente. Traducido:

- **La placa de la mesa** sigue haciendo lo de hoy (reseña) y suma "ver mi tarjeta" / "inscribirme".
  No otorga sellos. Sigue siendo pública sin consecuencias.
- **El sello sale de la caja**: el panel del comercio tiene una pantalla para el cajero que muestra
  un **código que rota cada minuto** (derivado de un secreto del negocio + la hora, tipo TOTP). El
  cliente lo escanea con la cámara y el sello queda registrado.

Por qué rota: sin rotación, el código se fotografía una vez y se usa desde la casa para siempre.
Rotando, hay que estar mirando la pantalla del cajero, que es justo la condición física que se
quiere exigir. La ventana corta también acota cuánto sirve una foto compartida por WhatsApp.

No necesita hardware, ni lector, ni cámara del lado del cajero: es una página que muestra un QR.

**Defensa en profundidad, además del código rotativo**: máximo un sello por cliente por día (nadie
toma cinco cafés en una hora) y el ledger de sellos es de solo agregar, para que un canje mal hecho
se pueda auditar.

Alternativa descartada: no controlar nada y limitar a un sello diario. Es más simple y hay dueños
que lo aceptarían, pero desacopla el sello de la compra — alguien que pasa por la puerta cinco días
seguidos se gana un café sin consumir nunca. No es defendible en una demo.

## Diseño de datos

Se apoya en lo que ya existe (`Business`, `Placement`) y agrega cuatro tablas. Todo va por Alembic.

- **`LoyaltyProgram`** — uno por negocio: cuántos sellos, cuál es el premio, texto de las reglas,
  si está activo. El premio es texto libre porque es del comercio ("el 5° café gratis").
- **`LoyaltyCard`** — la tarjeta de un cliente final *en un comercio*. Se identifica por un token
  capacidad, igual que las demás URLs del proyecto. **Está alcanzada por negocio**: el mismo
  teléfono en dos locales son dos tarjetas, porque la base de clientes es del comercio y
  cruzarlas sería repartir entre comercios un dato que no es nuestro.
- **`Stamp`** — el libro de sellos, **solo se agrega, nunca se borra ni se edita**. Es lo que
  respalda un premio, así que tiene que ser auditable: cuándo, con qué código, en qué local.
- **`Reward`** — premio emitido y su canje. El canje tiene que ser **irrepetible**: es el mismo
  problema que una tarjeta de regalo, y un premio cobrado dos veces es plata del comercio.

## Fases, por costo y por dependencia externa

El orden es al revés del pitch: **primero lo gratis y sin trámite**, y WhatsApp al final, cuando
haya un cliente cuya economía lo justifique.

### Fase 1 — Tarjeta digital propia · $0, sin trámites, sin datos personales

Ledger de sellos, pantalla del cajero con código rotativo, tarjeta web para el cliente final
(una URL que guarda en la pantalla de inicio), y en el panel del dueño: configurar el programa,
ver clientes y sellos, canjear un premio.

**Sin recolectar ningún dato personal.** La tarjeta es una URL secreta guardada en el teléfono.
Sin nombre, sin teléfono, sin correo: no hay consentimiento que pedir, ni plazo de borrado que
cumplir, ni base de datos que filtrar. Es demoable de punta a punta y prueba el mecanismo completo.

El costo de eso es que una tarjeta se pierde si el cliente borra el navegador o cambia de teléfono
— que es exactamente lo que pasa hoy con la de papel, así que no es un retroceso. Y se resuelve
ofreciendo el contacto **como recuperación opcional**, que es un fin distinto del marketing y va
en su propia casilla.

### Fase 2 — Google Wallet · $0, requiere cuenta de emisor

El pase de verdad, con actualización automática del contador y notificación en pantalla bloqueada.
Cubre la mayoría del parque en Chile. Trámite: cuenta de emisor y salir de demo mode.

### Fase 3 — Apple Wallet · $99 USD/año, una sola vez para toda la plataforma

Mismo pase para iPhone. Se hace cuando haya iPhones entre los clientes finales que lo pidan; no
antes, porque son $99 al año que hoy no compran nada.

### Fase 4 — Mensajería · costo variable, al final

Por orden de costo: **notificación del pase** (incluida en fases 2-3, $0), **correo** ($0, el SMTP
ya está en la lista de pendientes por otras tres razones) y **WhatsApp** (~$0.059 por mensaje en
Chile) solo para el cliente que lo pida y con el costo trasladado a su precio.

Nada de librerías no oficiales de WhatsApp: arriesgan el baneo del número del comercio. Ya está
decidido en `CLAUDE.md` y sigue en pie.

## Lo legal cambia de tamaño

Hoy la plataforma guarda contactos de quejas, se borran a los 6 meses y el responsable es el
comercio. Un programa de fidelización agrega cosas que no están cubiertas por eso:

- El teléfono se recolectaría para **marketing**, que bajo la Ley 21.719 necesita consentimiento
  **explícito y separado** del de recuperación de la tarjeta. Dos casillas, dos fines.
- Todo mensaje comercial necesita una forma de **darse de baja**, y tiene que funcionar.
- **La regla de borrado a los 6 meses no aplica**: una tarjeta activa tiene que persistir. Necesita
  su propia regla, por inactividad (por ejemplo, borrar la tarjeta y su contacto tras N meses sin
  un sello), y no puede colgarse del script de anonimización actual.
- El responsable sigue siendo el comercio y la plataforma la encargada, igual que hoy.

La Fase 1 esquiva todo esto por diseño, porque no recolecta nada. La carga aparece recién cuando se
pide un contacto, y ahí conviene que ya esté escrita.

## Lo que no se toca

**El paso de reseña no cambia.** El texto del pitch original dice que después del sello "se activa
la lógica de Review Gating: 4-5 estrellas van a Google, 1-3 abren formulario de queja". Eso es lo
mismo que prohíbe la restricción 1 de `CLAUDE.md` y no se va a construir. El sello se suma **antes**
del paso que ya existe, sin condicionar quién llega al botón de Google: un camino para todos, canal
privado siempre disponible como agregado.

Vale la pena notar que el combo funciona igual de bien sin el filtro: el cliente deja la reseña con
gusto porque acaba de recibir algo, que es todo el argumento del pitch. El filtro no aportaba a esa
mecánica, solo riesgo.

## Cómo quedó la Fase 1

| Pieza | Dónde |
|---|---|
| Reglas (código rotativo, un sello por día, premios, canje) | [app/services/fidelizacion.py](../app/services/fidelizacion.py) |
| Lo que ve el cliente final | [app/routers/fidelizacion.py](../app/routers/fidelizacion.py) |
| Configuración y pantalla de la caja | [app/routers/panel_sellos.py](../app/routers/panel_sellos.py) |
| Tests | [tests/test_fidelizacion.py](../tests/test_fidelizacion.py) — 44 |

El dueño activa el programa en `/panel/fidelizacion` (cuántos sellos y cuál es el premio) y deja
abierta `/panel/caja` en el computador del mostrador. El cliente escanea el QR de esa pantalla,
que cambia cada minuto: se le crea la tarjeta sola, se le suma el sello y ve cuánto le falta. Al
completar, el premio se emite solo; para cobrarlo tiene que volver a escanear el código de la
caja. Después del sello se le ofrece dejar la reseña, con el mismo botón de siempre.

Activar el programa crea una placa propia ("Caja (fidelización)") para que las reseñas que salgan
de este flujo no se le sumen a una mesa: así el dueño puede ver si el camino de sellos convierte
mejor, en su comparación por soporte de siempre.

Los sellos y los premios entran al **respaldo semanal**. Perderlos no es perder historial: es un
cliente que ya juntó los suyos parado en el mostrador mientras el sistema le dice que no tiene
nada.

## Lo que queda por decidir

1. **Precio**: si se cobra un plan combo fijo o si WhatsApp va aparte, dado su costo variable. No
   corre prisa hasta que haya un cliente que lo pida.
2. **Cuándo hacer la Fase 2** (Google Wallet). Es gratis, pero es un trámite de cuenta de emisor
   que no vale la pena empezar sin un local real usando la Fase 1.
