// Pantalla de la caja: mantiene el código y su QR al día.
//
// Va en un archivo y no en línea porque la CSP de las páginas públicas prohíbe
// los scripts en línea, igual que en la landing.
//
// Se refresca solo, sin recargar la página: esta pantalla se queda abierta todo
// el día en el mostrador y un recargue completo cada minuto haría parpadear el
// QR justo cuando alguien lo está enfocando.
(function () {
  var qr = document.getElementById("qr");
  var codigo = document.getElementById("codigo");
  var cuenta = document.getElementById("cuenta");
  if (!qr || !codigo) return;

  var restantes = 0;

  function pintarCuenta() {
    if (!cuenta) return;
    cuenta.textContent =
      restantes > 0 ? "Cambia en " + restantes + "s" : "Actualizando...";
  }

  function actualizar() {
    fetch("/panel/caja/codigo", { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (datos) {
        if (datos.error) {
          // La sesión del panel se cerró mientras la pantalla estaba abierta.
          // Recargar lleva al login en vez de dejar un QR muerto en la caja.
          window.location.reload();
          return;
        }
        qr.src = datos.qr;
        codigo.textContent = datos.codigo;
        restantes = datos.segundos;
        pintarCuenta();
      })
      .catch(function () {
        // Sin red no se toca lo que está en pantalla: un QR de hace unos
        // segundos probablemente siga sirviendo, y un error vacío no.
      });
  }

  setInterval(function () {
    restantes -= 1;
    if (restantes <= 0) {
      actualizar();
    } else {
      pintarCuenta();
    }
  }, 1000);

  actualizar();
})();
