# Ruta de pruebas manuales

Servidor levantado el 2026-09-03 para que pruebes tú mismo, desde tu celular, lo que hasta ahora
solo se había probado con `pytest`. Marca cada casilla a medida que lo hagas. Si algo no se
comporta como dice "Qué deberías ver", anótalo (una foto de pantalla sirve) y lo revisamos.

## Antes de empezar

**Las pruebas se hacen desde el navegador de este computador.** Se intentó desde el celular, pero
la red no deja que el teléfono alcance al computador: el servidor responde bien y el QR es
correcto, pero algo entre medio (el router o el equipo corporativo) bloquea la conexión entrante.
No vale la pena pelear con eso ahora; la prueba en celular queda pendiente para cuando el
proyecto viva en un equipo personal.

El servidor ya está corriendo en `http://localhost:8000`. Si lo cerraste o reiniciaste el
computador, levántalo de nuevo con:

```powershell
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Todo apunta ahora a `localhost`, así que ya no importa a qué red te conectes.

**Para probar la experiencia de celular sin celular**: abre las herramientas de desarrollador del
navegador con F12 y activa la vista de dispositivo móvil (el ícono de teléfono, o Ctrl+Shift+M en
Chrome y Edge). La landing está diseñada para pantallas de teléfono y así la ves como se verá.

Datos de la demo: negocio "Café Demo", tres soportes (Mesa 5, Mesón de pago, Boleta), con ~1900
visitas y 33 quejas repartidas en los últimos meses, para que el panel y el informe se vean como
los de un local real.

### Enlaces directos, para ir haciendo clic

| Qué | Dirección |
|---|---|
| Landing "Mesa 5" | http://localhost:8000/r/ZTYFEMtc |
| Landing "Mesón de pago" | http://localhost:8000/r/H1IwNJrX |
| Landing "Boleta" | http://localhost:8000/r/Ygb-AOFn |
| Código inexistente (debe dar 404) | http://localhost:8000/r/no-existe-esto |
| Panel del dueño | http://localhost:8000/panel/login |
| Informe mensual | http://localhost:8000/informe/4VB6_OoK |
| Informe de un mes concreto | http://localhost:8000/informe/4VB6_OoK?mes=2026-08 |
| Informe de un mes vacío | http://localhost:8000/informe/4VB6_OoK?mes=2026-01 |
| PDF (debe dar un mensaje claro, no un error) | http://localhost:8000/informe/4VB6_OoK/pdf |

Credenciales del panel: **demo@cafe.cl** / **demo1234**

## Parte 1 — El flujo que vive un cliente

Esto es lo más importante de probar primero: es literalmente el producto.

1. **[ ] Abre la landing de una placa:** http://localhost:8000/r/ZTYFEMtc (es "Mesa 5").
   Activa antes la vista de móvil con F12, para verla como la vería un cliente.
   - Qué deberías ver: una página con el nombre "Café Demo", un botón grande "Dejar reseña en
     Google" y, más abajo, un enlace secundario "¿Tuviste un problema? Cuéntanos en privado".
   - Qué NO deberías ver: ningún selector de estrellas antes del botón de Google. Si lo ves, es
     el bug más grave que existe (viola las políticas de Google), avísame de inmediato.

2. **[ ] Toca "Dejar reseña en Google".**
   - Qué deberías ver: te redirige a una URL de Google (hoy es un placeholder porque todavía no
     tenemos el link real de un negocio — ver "Bloqueado esperando al usuario" en el ROADMAP).
     Lo que importa probar es que redirige, no a dónde.

3. **[ ] Vuelve atrás, recarga la misma landing y haz clic en "Dejar reseña" varias veces seguidas.**
   - Qué deberías ver: siempre te lleva a Google sin errores.
   - Lo que estás probando sin verlo: que recargar la página o tocar el botón dos veces no debe
     inflar las visitas ni las conversiones. Eso lo confirmamos después en el panel (paso 8).

4. **[ ] Abre otra placa distinta** (http://localhost:8000/r/H1IwNJrX) **y esta vez haz clic en
   "¿Tuviste un problema? Cuéntanos en privado".**
   - Qué deberías ver: se despliega un formulario con una calificación opcional (1 a 5, o "prefiero
     no decirlo"), un campo de contacto opcional, y un cuadro de texto.
   - **[ ] Envíalo con un mensaje cualquiera, con y sin calificación, con y sin contacto.**
   - Qué deberías ver: una página de gracias, con un botón para igual ir a dejar la reseña en
     Google si quieres.
   - **[ ] Toca ese botón de la página de gracias y anota qué pasa** — este es un caso que
     encontramos roto en la revisión (no cuenta como conversión); confirmar que efectivamente no
     queda registrado es la prueba de que el hallazgo era real.

5. **[ ] Prueba un código que no existe:** `http://localhost:8000/r/no-existe-esto`
   - Qué deberías ver: una página de error 404, no una pantalla en blanco ni un error feo de
     servidor.

## Parte 2 — El panel del dueño

6. **[ ] Entra a `http://localhost:8000/panel/login`** con `demo@cafe.cl` / `demo1234`.
   - Qué deberías ver: te lleva al panel con gráficos y números.

7. **[ ] Antes de eso, prueba con la contraseña mala un par de veces.**
   - Qué deberías ver: "Correo o contraseña incorrectos", sin decir si el correo existe o no.

8. **[ ] Ya adentro, revisa los números arriba:** visitas únicas, fueron a Google, conversión,
   quejas por atender.
   - **[ ] Prueba el selector de período** (Este mes / Mes pasado / Todo) y confirma que los
     números y los gráficos cambian, y que el título de arriba dice qué período estás viendo.
   - Con "Mes pasado" seleccionado, estos números **deben coincidir exactamente** con los del
     informe mensual del paso 14. Si no coinciden, eso sí es un hallazgo importante.
   - El contador de "Quejas por atender" no cambia con el período, a propósito: una queja
     pendiente lo sigue estando sin importar el mes en que llegó.

9. **[ ] Baja hasta el gráfico "¿Qué soporte convierte mejor?"**
   - Qué deberías ver: una barra por placa (Mesa 5, Mesón de pago, Boleta), con Mesa 5 más alta
     — así está armada la demo a propósito.

10. **[ ] Baja hasta "Buzón privado" y marca dos o tres quejas como "Marcar como atendidas".**
    - Qué deberías ver: cambian de estado, y el contador de "Quejas por atender" arriba baja.
    - **[ ] Pruébalas "Reabrir" también.**
    - **[ ] Prueba exportar la tabla a CSV** (el botón de exportar de la tabla) y ábrelo en Excel
      — es la prueba de que los acentos no se rompen (`utf-8-sig`).

11. **[ ] Cambia la contraseña** en el enlace "Cambiar contraseña" (arriba a la derecha).
    - Pídete la actual, y prueba una vez con la actual mal escrita — debe rechazarla.
    - Si la cambias de verdad, anota la nueva para poder volver a entrar. O puedes cancelar sin
      guardar, ya que es solo una prueba.

12. **[ ] Cierra sesión y confirma que ya no puedes ver `/dashboard/`** sin volver a entrar.

## Parte 3 — El informe mensual

13. **[ ] Visita `http://localhost:8000/informe/4VB6_OoK`** (ese es el "dashboard_token" del
    negocio demo — es un enlace distinto al del panel, a propósito: este no pide contraseña,
    porque es el que se manda por correo).
    - Qué deberías ver: un informe con visitas, conversión, comparación contra el mes anterior,
      rendimiento por soporte y el detalle de las quejas del mes.

14. **[ ] Prueba con un mes específico:**
    `http://localhost:8000/informe/4VB6_OoK?mes=2026-08`
    - Compara los números con lo que viste en el panel (paso 8). No van a coincidir porque miden
      períodos distintos — es esperado, no es un bug nuevo.

15. **[ ] Prueba un mes sin datos:** `?mes=2026-01`
    - Qué deberías ver: el informe igual carga, con "0%" de conversión y un aviso de que no hay
      visitas, no una pantalla en blanco ni un error.

15b. **[ ] El informe tiene que verse CON GRÁFICOS**: barras de colores en "Rendimiento por
    soporte" y columnas en "Visitas por día". Si lo ves como texto plano sin formato, avísame:
    es exactamente el bug que encontraste el 2026-09-03 y que ya está corregido, pero si
    reaparece significa que la política de seguridad volvió a bloquear los estilos.

16. **[ ] Desde ese informe, usa Imprimir del navegador → Guardar como PDF.**
    - **Activa "Gráficos de fondo"** en Más configuraciones, o las barras y los recuadros salen
      en blanco: el informe dibuja sus gráficos con fondos de color, no con imágenes.
    - Esta es la vía real de generar el PDF hoy (WeasyPrint no corre en Windows). Confirma que
      se ve bien impreso: la cabecera, las barras de conversión, el gráfico de columnas de
      visitas por día.

17. **[ ] Prueba también la ruta directa del PDF:**
    `http://localhost:8000/informe/4VB6_OoK/pdf`
    - Qué deberías ver: **no** un error de servidor. En tu Windows, un mensaje de texto claro
      explicando que WeasyPrint no está disponible ahí y las alternativas. Eso es correcto y
      esperado — confirmado que responde 501, no 500.

## Parte 4 — Dar de alta un cliente de prueba (línea de comandos)

Esto simula lo que harías con un cliente real. Es un buen momento para ver si el flujo de
`new_client.py` es cómodo o si algo se siente raro al usarlo de verdad.

18. **[ ] En una terminal nueva, con el entorno activado, corre:**
    ```powershell
    python -m scripts.new_client
    ```
    Sigue el modo interactivo: ponle un nombre inventado, cualquier link de Google (puede ser un
    placeholder, va a avisarte que no parece uno real — eso es intencional), un par de placas
    ("Mesa 1, Barra"), y tu propio correo para las alertas.
    - Qué deberías ver: te imprime las URLs de cada placa, un QR generado en `qrcodes/`, tu
      contraseña de panel generada (**anótala**, no se vuelve a mostrar), y el enlace del informe.

19. **[ ] Entra al panel con ese cliente nuevo** y confirma que ves un panel vacío (sin datos),
    no el de Café Demo.

20. **[ ] Corre `python -m scripts.new_client --listar`**
    - Qué deberías ver: la lista de los dos negocios (Café Demo y el que acabas de crear), con
      sus enlaces de informe.

## Parte 5 — Casos límite (opcional, si quieres ser exhaustivo)

21. **[ ] Recarga la landing de una placa (paso 1) más de 60 veces seguidas rápido** (F5 varias
    veces). Es el límite de visitas públicas. Después del intento 60 debería seguir cargando la
    página normal (nunca un error), pero las visitas de más no deberían sumarse en el panel.
22. **[ ] Intenta iniciar sesión con la contraseña mala 9 veces seguidas.**
    - Qué deberías ver: después de varios intentos, un mensaje de "demasiados intentos, espera
      unos minutos", incluso si la contraseña es correcta en el siguiente intento.
23. **[ ] Prueba la landing en pantalla ancha y en vista de móvil (F12)** — tiene que verse bien
    en las dos, aunque está pensada para celular.

---

## Ojo: el servidor ya trae las correcciones de la fase A

Mientras armabas la ronda de pruebas corregí los cuatro hallazgos críticos y **reinicié el
servidor**, así que estás probando el código ya corregido. Dos consecuencias:

- **El paso 4 cambió de sentido.** El botón de Google en la página de gracias **ahora sí** debe
  contar la conversión. Ya no es "anota qué pasa" sino "confirma que ahora sí queda registrado":
  después de tocarlo, entra al panel y verifica que la conversión subió.
- **Si tenías sesión abierta en el panel, se cerró.** Vuelve a entrar con `demo@cafe.cl` / `demo1234`.

## Lo que sigue sin estar bien y NO hace falta que reportes (ya está anotado)

Para que no dupliques trabajo, estos ya están documentados en
[revision-tecnica-2026-09-03.md](revision-tecnica-2026-09-03.md) y todavía no los corrijo:

- El panel (paso 8) y el informe (paso 14) muestran períodos distintos sin decirlo.
- El PDF no genera en Windows (paso 17) — es esperado, no un bug.
- Las URLs de los QR de hoy apuntan a tu red local, no sirven fuera de tu WiFi ni son las
  definitivas — normal, es solo para esta prueba.

Si encuentras algo que **no** está en esa lista, esa es la prueba que valió la pena hacer —
anótalo con el paso exacto donde pasó.

---

## Después de probar

Cuando termines la ronda, dime qué encontraste (o que todo se vio bien) y seguimos con la fase A
del plan de la revisión técnica: los cuatro hallazgos críticos primero.

Cuando quieras parar el servidor de pruebas, ve a la terminal donde quedó corriendo y presiona
`Ctrl+C`. Si no la tienes a mano, list a los procesos de Python con `tasklist` y cierra el que
corresponda con `taskkill /PID <número> /F`.
