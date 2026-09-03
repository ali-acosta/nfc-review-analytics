"""Monthly executive report: the piece that sustains the subscription.

Renders to HTML first and to PDF second, on purpose. The HTML is always
available (and prints to a perfect PDF from any browser), while WeasyPrint
needs native GTK libraries that are trivial on Linux and an extra install on
Windows — so a missing PDF engine degrades to a clear message instead of
breaking the feature.
"""

from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Business
from app.services import metrics

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


class PDFEngineUnavailable(RuntimeError):
    """WeasyPrint is installed but its native libraries are not loadable."""


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _delta(current: float, previous: float) -> dict | None:
    """Change vs the previous month. None when there's no baseline to compare."""
    if previous == 0:
        return None
    change = (current - previous) / previous * 100
    return {"pct": abs(change), "up": change >= 0}


def build_context(business: Business, year: int, month: int) -> dict:
    start, end = metrics.month_bounds(year, month)
    prev_year, prev_month = metrics.previous_month(year, month)
    prev_start, prev_end = metrics.month_bounds(prev_year, prev_month)

    all_taps = metrics.load_taps(business.id)
    taps = metrics.in_period(all_taps, start, end)
    prev_taps = metrics.in_period(all_taps, prev_start, prev_end)

    feedback = metrics.in_period(metrics.load_feedback(business.id), start, end)

    now = metrics.funnel(taps)
    before = metrics.funnel(prev_taps)

    placements = metrics.by_placement(taps)
    daily = metrics.by_day(taps)
    max_daily = int(daily["visitas"].max()) if not daily.empty else 0

    return {
        "business": business,
        "period_label": f"{MONTHS_ES[month - 1].capitalize()} {year}",
        "generated_on": date.today().strftime("%d-%m-%Y"),
        "prev_label": f"{MONTHS_ES[prev_month - 1]} {prev_year}",
        "kpis": {
            "visits": now["visits"],
            "clicks": now["clicks"],
            "conversion": now["conversion"],
            "feedback": len(feedback),
        },
        "deltas": {
            "visits": _delta(now["visits"], before["visits"]),
            "clicks": _delta(now["clicks"], before["clicks"]),
            "conversion": _delta(now["conversion"], before["conversion"]),
        },
        "has_baseline": before["visits"] > 0,
        "placements": placements.to_dict("records"),
        "best_placement": placements.iloc[0].to_dict() if not placements.empty else None,
        "daily": daily.to_dict("records"),
        "max_daily": max_daily,
        "feedback": feedback.to_dict("records"),
    }


def render_html(business: Business, year: int, month: int) -> str:
    return _env().get_template("report.html").render(**build_context(business, year, month))


def build_summary_text(business: Business, year: int, month: int, base_url: str) -> str:
    """Resumen corto para el mensaje mensual. Lleva los titulares y el enlace al
    informe completo: es el recordatorio recurrente de que el servicio existe."""
    ctx = build_context(business, year, month)
    kpis, deltas = ctx["kpis"], ctx["deltas"]

    def variacion(clave: str) -> str:
        d = deltas.get(clave)
        if not d:
            return ""
        return f"  ({'+' if d['up'] else '-'}{d['pct']:.0f}% vs {ctx['prev_label']})"

    lineas = [
        f"📊 Informe de {ctx['period_label']} — {business.name}",
        "",
        f"Visitas únicas: {kpis['visits']}{variacion('visits')}",
        f"Fueron a Google: {kpis['clicks']}{variacion('clicks')}",
        f"Conversión: {kpis['conversion']:.0f}%{variacion('conversion')}",
        f"Comentarios privados: {kpis['feedback']}",
    ]

    mejor = ctx["best_placement"]
    if mejor:
        lineas += ["", f"Mejor soporte: {mejor['label']} ({mejor['conversion']:.0f}%)"]

    lineas += [
        "",
        f"Informe completo: {base_url.rstrip('/')}/informe/{business.dashboard_token}?mes={year}-{month:02d}",
    ]
    return "\n".join(lineas)


def render_pdf(business: Business, year: int, month: int) -> bytes:
    """HTML → PDF via WeasyPrint. Imported lazily so that a machine without the
    native libraries can still run the app and serve the HTML report."""
    try:
        from weasyprint import HTML
    except Exception as exc:  # ImportError, OSError from the cffi loader, …
        raise PDFEngineUnavailable(str(exc)) from exc

    return HTML(string=render_html(business, year, month)).write_pdf()


def get_business(token: str) -> Business | None:
    with SessionLocal() as db:
        return db.scalar(select(Business).where(Business.dashboard_token == token))


def resolve_period(mes: str | None) -> tuple[int, int]:
    """'2026-08' → (2026, 8).

    Defaults to the last *complete* month, which is what a monthly report means:
    August's report goes out in early September. Defaulting to the current month
    would show a half-empty period for most of the month.
    """
    if not mes:
        today = date.today()
        return metrics.previous_month(today.year, today.month)
    parsed = datetime.strptime(mes, "%Y-%m")
    return parsed.year, parsed.month
