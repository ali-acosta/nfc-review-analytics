"""Monthly report, served from outside /dashboard.

/dashboard is a WSGI mount that swallows everything beneath it, so these routes
live at their own prefix.

El enlace sigue sin pedir login —va por correo al propio dueño, como el enlace
de una factura, y una contraseña en cada correo mensual pondría fricción justo
en la pieza que sostiene la retención— pero ya no es eterno: lleva una firma que
cubre el token *y* el mes, válida 90 días. Un correo reenviado deja de exponer
la historia completa del negocio, que incluye teléfonos y quejas de sus clientes
finales. Ver `app/services/enlaces.py`.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from app.services import admin_auth, enlaces
from app.services import report as report_service
from app.services.auth import SESSION_KEY

router = APIRouter(prefix="/informe")
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _business_or_404(token: str):
    business = report_service.get_business(token)
    if business is None:
        raise HTTPException(status_code=404, detail="Informe no encontrado")
    return business


def _period_or_400(mes: str | None):
    try:
        return report_service.resolve_period(mes)
    except ValueError:
        raise HTTPException(status_code=400, detail="El parámetro 'mes' debe tener formato AAAA-MM")


def _autorizado(request: Request, token: str, year: int, month: int, firma: str | None) -> bool:
    """¿Puede quien pide ver este informe?

    Tres vías, en orden de frecuencia real: la firma del correo mensual, la
    sesión del propio dueño (el panel enlaza su informe y sería absurdo que su
    propio enlace caducara mientras está dentro) y la sesión del operador.
    """
    if enlaces.informe_valido(firma, token, year, month):
        return True

    sesion = request.session
    if admin_auth.sesion_valida(sesion):
        return True

    business_id = sesion.get(SESSION_KEY)
    if not business_id:
        return False
    business = report_service.get_business(token)
    return business is not None and business.id == business_id


def _vencido(request: Request) -> HTMLResponse:
    """Página de enlace no válido.

    Es 403 y no 404 a propósito, y es la *misma* respuesta exista o no el
    negocio: si un token inexistente diera 404 y uno real diera 403, la página
    serviría para averiguar qué tokens son de clientes.
    """
    return templates.TemplateResponse(request, "informe_vencido.html", {}, status_code=403)


@router.get("/{token}", response_class=HTMLResponse)
def report_html(token: str, request: Request, mes: str | None = None, firma: str | None = None):
    year, month = _period_or_400(mes)
    if not _autorizado(request, token, year, month, firma):
        return _vencido(request)
    business = _business_or_404(token)
    return report_service.render_html(business, year, month)


@router.get("/{token}/pdf")
def report_pdf(token: str, request: Request, mes: str | None = None, firma: str | None = None):
    year, month = _period_or_400(mes)
    if not _autorizado(request, token, year, month, firma):
        return _vencido(request)
    business = _business_or_404(token)

    try:
        pdf = report_service.render_pdf(business, year, month)
    except report_service.PDFEngineUnavailable:
        # Never a 500: the report itself is fine, only this rendering path is
        # unavailable on this machine.
        return PlainTextResponse(
            "El motor de PDF (WeasyPrint) no tiene sus librerías nativas disponibles en este "
            "equipo.\n\nAlternativas:\n"
            "  · Abre el informe en el navegador y usa Imprimir → Guardar como PDF "
            "(calidad idéntica).\n"
            "  · En Windows, instala el runtime de GTK3 para habilitar WeasyPrint.\n"
            "  · En el servidor de producción (Linux) esto funciona sin configuración extra.",
            status_code=501,
        )

    filename = f"informe-{year}-{month:02d}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
