// Muestra u oculta el canal privado. Vive en un archivo aparte —y no en línea
// dentro del HTML— para poder aplicar una CSP que prohíba scripts embebidos,
// que es lo que bloquea la inyección de código en una página pública.
(function () {
  var toggle = document.getElementById("private-toggle");
  var panel = document.getElementById("private-panel");
  if (!toggle || !panel) return;

  toggle.addEventListener("click", function () {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  });
})();
