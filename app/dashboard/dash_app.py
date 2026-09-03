"""Owner-facing panel, mounted inside FastAPI at /dashboard.

Requires a logged-in session: DashboardAuthMiddleware redirects anonymous
requests to /panel/login and injects the authenticated business id, since this
is a WSGI app and can't reach Starlette's session itself. The identity is never
taken from the URL — that is what made the old capability-token version
unsuitable for paying clients.
"""

import flask
import pandas as pd
import plotly.express as px
from dash import Dash, Input, Output, State, dash_table, dcc, html, no_update

from app.database import SessionLocal
from app.middleware import BUSINESS_HEADER
from app.models import Business
from app.services import inbox, metrics

REFRESH_MS = 5000

CARD_STYLE = {
    "flex": "1 1 160px",
    "background": "#ffffff",
    "borderRadius": "12px",
    "padding": "16px 20px",
    "boxShadow": "0 1px 4px rgba(0,0,0,0.08)",
}
TITLE_STYLE = {"fontSize": "0.8rem", "color": "#5b6270", "marginBottom": "6px"}
VALUE_STYLE = {"fontSize": "1.8rem", "fontWeight": "600", "color": "#1a1d23"}
PENDING_STYLE = {**VALUE_STYLE, "color": "#9a3b2c"}
LINK_STYLE = {"color": "#16607d", "fontSize": "0.9rem"}
BUTTON_STYLE = {
    "background": "#16607d",
    "color": "#fff",
    "border": "none",
    "borderRadius": "6px",
    "padding": "8px 14px",
    "cursor": "pointer",
    "fontSize": "0.85rem",
}
INBOX_COLUMNS = ["estado", "fecha", "soporte", "estrellas", "contacto", "mensaje"]


def _current_business() -> Business | None:
    """El negocio de la sesión iniciada.

    La identidad la resuelve DashboardAuthMiddleware y la inyecta en una
    cabecera interna, porque esta app es WSGI y no alcanza la sesión de
    Starlette. Nunca se lee de la URL: eso permitiría ver el panel ajeno
    cambiando un parámetro.
    """
    business_id = flask.request.headers.get(BUSINESS_HEADER.decode())
    if not business_id:
        return None
    with SessionLocal() as db:
        return db.get(Business, int(business_id))


def _kpi(title: str, value: str, style: dict = VALUE_STYLE) -> html.Div:
    return html.Div([html.Div(title, style=TITLE_STYLE), html.Div(value, style=style)], style=CARD_STYLE)


def _inbox_rows(business_id: int) -> list[dict]:
    """Filas de la bandeja, pendientes primero: son las que hay que atender."""
    feedback = metrics.load_feedback(business_id)
    if feedback.empty:
        return []

    tabla = feedback.copy()
    pendiente = tabla["resolved_at"].isna()
    tabla["estado"] = pendiente.map({True: "Pendiente", False: "Atendida"})
    tabla["fecha"] = pd.to_datetime(tabla["created_at"]).dt.strftime("%d-%m-%Y %H:%M")
    tabla["estrellas"] = tabla["rating"].fillna("—")
    tabla = tabla.rename(columns={"contact": "contacto", "message": "mensaje", "label": "soporte"})
    tabla = tabla.sort_values(["resolved_at", "created_at"], ascending=[True, False], na_position="first")

    return tabla[["id", *INBOX_COLUMNS]].to_dict("records")


def create_dash_app() -> Dash:
    dash_app = Dash(__name__, requests_pathname_prefix="/dashboard/", title="Panel — NFC Review Analytics")

    dash_app.layout = html.Div(
        [
            dcc.Location(id="url"),
            html.H1(id="header", style={"fontSize": "1.4rem", "marginBottom": "4px"}),
            html.Div(
                [
                    html.A("Ver informe mensual →", id="report-link", href="", target="_blank", style=LINK_STYLE),
                    html.Span(
                        [
                            html.A("Cambiar contraseña", href="/panel/password", style={**LINK_STYLE, "color": "#6b7a76"}),
                            html.A(
                                "Cerrar sesión",
                                href="/panel/logout",
                                style={**LINK_STYLE, "color": "#6b7a76", "marginLeft": "16px"},
                            ),
                        ]
                    ),
                ],
                style={"display": "flex", "justifyContent": "space-between", "marginBottom": "18px"},
            ),
            html.Div(id="kpi-row", style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}),
            dcc.Graph(id="placement-chart"),
            dcc.Graph(id="visits-chart"),
            html.H2("Buzón privado", style={"fontSize": "1.1rem"}),
            html.P(
                "Marca las quejas que ya atendiste para no perderles el rastro.",
                style={"color": "#5b6270", "fontSize": "0.9rem", "marginTop": "0"},
            ),
            html.Div(
                [
                    html.Button("Marcar como atendidas", id="resolver-btn", n_clicks=0, style=BUTTON_STYLE),
                    html.Button(
                        "Reabrir",
                        id="reabrir-btn",
                        n_clicks=0,
                        style={**BUTTON_STYLE, "background": "#e9eeed", "color": "#1a1d23", "marginLeft": "8px"},
                    ),
                    html.Span(id="resolver-aviso", style={"marginLeft": "12px", "color": "#5b6270", "fontSize": "0.85rem"}),
                ],
                style={"marginBottom": "10px"},
            ),
            # La bandeja vive en el layout y no se regenera en cada refresco: si
            # se recreara cada 5 segundos, borraría la selección justo mientras
            # el dueño está marcando filas.
            dash_table.DataTable(
                id="inbox-table",
                columns=[{"name": c, "id": c} for c in INBOX_COLUMNS],
                data=[],
                row_selectable="multi",
                selected_rows=[],
                page_size=10,
                sort_action="native",
                # El dueño puede bajarse sus quejas sin pedírselas a nadie.
                export_format="csv",
                export_headers="display",
                style_cell={"textAlign": "left", "fontFamily": "inherit", "whiteSpace": "normal", "height": "auto"},
                style_header={"fontWeight": "600"},
                style_data_conditional=[
                    {
                        "if": {"filter_query": '{estado} = "Atendida"'},
                        "color": "#8a938f",
                    },
                    {
                        "if": {"filter_query": '{estado} = "Pendiente"', "column_id": "estado"},
                        "color": "#9a3b2c",
                        "fontWeight": "600",
                    },
                ],
            ),
            dcc.Interval(id="refresh", interval=REFRESH_MS, n_intervals=0),
        ],
        style={
            "fontFamily": "-apple-system, Segoe UI, Roboto, sans-serif",
            "maxWidth": "960px",
            "margin": "0 auto",
            "padding": "24px",
            "background": "#f5f6f8",
        },
    )

    @dash_app.callback(
        Output("header", "children"),
        Output("report-link", "href"),
        Output("kpi-row", "children"),
        Output("placement-chart", "figure"),
        Output("visits-chart", "figure"),
        Input("refresh", "n_intervals"),
    )
    def refresh(_n_intervals: int):
        business = _current_business()
        if business is None:
            vacio = px.bar(title="")
            return (
                "Sesión no válida",
                "",
                [html.Div("Vuelve a entrar en /panel/login.", style=CARD_STYLE)],
                vacio,
                vacio,
            )

        # Every number here comes from app.services.metrics so that the panel
        # and the monthly PDF can never disagree about the same month.
        taps = metrics.load_taps(business.id)
        feedback = metrics.load_feedback(business.id)
        summary = metrics.funnel(taps)
        visits = summary["visits"]
        pendientes = int(feedback["resolved_at"].isna().sum()) if not feedback.empty else 0

        kpis = [
            _kpi("Visitas únicas", str(visits)),
            _kpi("Fueron a Google", str(summary["clicks"])),
            _kpi("Tasa de conversión", f"{summary['conversion']:.0f}%"),
            _kpi("Quejas por atender", str(pendientes), PENDING_STYLE if pendientes else VALUE_STYLE),
        ]

        if visits:
            per = metrics.by_placement(taps).rename(columns={"label": "soporte", "conversion": "conversión %"})
            per["conversión %"] = per["conversión %"].round(0)
            placement_fig = px.bar(
                per,
                x="soporte",
                y="conversión %",
                title="¿Qué soporte convierte mejor?",
                hover_data=["visitas", "clicks"],
            )
        else:
            placement_fig = px.bar(title="¿Qué soporte convierte mejor? (sin datos aún)")

        daily = metrics.by_day(taps)
        if not daily.empty:
            visits_fig = px.line(daily, x="fecha", y="visitas", title="Visitas por día", markers=True)
        else:
            visits_fig = px.line(title="Visitas por día (sin datos aún)")

        return (
            f"{business.name} — Panel de reseñas",
            f"/informe/{business.dashboard_token}",
            kpis,
            placement_fig,
            visits_fig,
        )

    @dash_app.callback(
        Output("inbox-table", "data"),
        Output("inbox-table", "selected_rows"),
        Output("resolver-aviso", "children"),
        Input("url", "pathname"),
        Input("resolver-btn", "n_clicks"),
        Input("reabrir-btn", "n_clicks"),
        State("inbox-table", "selected_rows"),
        State("inbox-table", "data"),
    )
    def gestionar_bandeja(_pathname, resolver_clicks, reabrir_clicks, seleccionadas, filas):
        """Carga la bandeja y aplica las acciones sobre las filas marcadas.

        Deliberadamente fuera del Interval: la bandeja no cambia cada cinco
        segundos, y regenerarla borraría la selección del dueño a mitad de uso.
        """
        business = _current_business()
        if business is None:
            return [], [], ""

        from dash import ctx

        disparador = ctx.triggered_id
        aviso = ""

        if disparador in ("resolver-btn", "reabrir-btn") and seleccionadas:
            ids = [filas[i]["id"] for i in seleccionadas if i < len(filas)]
            if disparador == "resolver-btn":
                cambiadas = inbox.mark_resolved(business.id, ids)
                aviso = f"{cambiadas} marcada(s) como atendida(s)." if cambiadas else "Ya estaban atendidas."
            else:
                cambiadas = inbox.reopen(business.id, ids)
                aviso = f"{cambiadas} reabierta(s)." if cambiadas else ""
        elif disparador in ("resolver-btn", "reabrir-btn"):
            aviso = "Selecciona al menos una fila."

        return _inbox_rows(business.id), [], aviso

    return dash_app
