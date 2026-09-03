"""Monthly report, served from outside /dashboard.

/dashboard is a WSGI mount that swallows everything beneath it, so these routes
live at their own prefix.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from app.services import report as report_service

router = APIRouter(prefix="/informe")


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


@router.get("/{token}", response_class=HTMLResponse)
def report_html(token: str, mes: str | None = None):
    business = _business_or_404(token)
    year, month = _period_or_400(mes)
    return report_service.render_html(business, year, month)


@router.get("/{token}/pdf")
def report_pdf(token: str, mes: str | None = None):
    business = _business_or_404(token)
    year, month = _period_or_400(mes)

    try:
        pdf = report_service.render_pdf(business, year, month)
    except report_service.PDFEngineUnavailable:
        # Never a 500: the report itself is fine, only this rendering path is
        # unavailable on this machine.
        return PlainTextResponse(
            "El motor de PDF (WeasyPrint) no tiene sus librerías nativas disponibles en este "
            "equipo.\n\nAlternativas:\n"
            f"  · Abre /informe/{token} y usa Imprimir → Guardar como PDF (calidad idéntica).\n"
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
