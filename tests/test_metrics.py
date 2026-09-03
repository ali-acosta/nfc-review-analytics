"""La métrica es lo que el cliente paga. Estos tests existen para que no vuelva
a romperse en silencio."""

from datetime import datetime, timezone

from app.services import metrics
from tests.conftest import add_tap, add_visit


def _funnel(business_id):
    return metrics.funnel(metrics.load_taps(business_id))


class TestConversion:
    def test_conversion_llega_a_100_por_ciento(self, negocio):
        """Regresión del bug original: contar filas en vez de sesiones metía
        cada conversión en su propio denominador, topando la métrica en 50%.
        Si los 10 visitantes convierten, la respuesta correcta es 100%."""
        for _ in range(10):
            add_visit(negocio.id, negocio.mesa_id, converts=True)

        resultado = _funnel(negocio.id)

        assert resultado["visits"] == 10
        assert resultado["clicks"] == 10
        assert resultado["conversion"] == 100.0

    def test_convertir_no_infla_el_denominador(self, negocio):
        """10 llegan, 6 convierten → 60%, no 6/16."""
        for _ in range(6):
            add_visit(negocio.id, negocio.mesa_id, converts=True)
        for _ in range(4):
            add_visit(negocio.id, negocio.mesa_id, converts=False)

        resultado = _funnel(negocio.id)

        assert resultado["visits"] == 10
        assert resultado["conversion"] == 60.0

    def test_recargas_de_pagina_no_son_visitas_nuevas(self, negocio):
        """Aunque lleguen varias filas 'landed' con la misma sesión, es una
        sola persona."""
        sesion = "una-sola-persona"
        for _ in range(5):
            add_tap(negocio.id, negocio.mesa_id, "landed", session_id=sesion)

        assert _funnel(negocio.id)["visits"] == 1

    def test_sin_datos_no_divide_por_cero(self, negocio):
        resultado = _funnel(negocio.id)

        assert resultado == {"visits": 0, "clicks": 0, "conversion": 0.0}

    def test_los_bots_no_cuentan(self, negocio):
        add_visit(negocio.id, negocio.mesa_id, converts=True)
        for _ in range(9):
            add_visit(negocio.id, negocio.mesa_id, converts=False, is_bot=True)

        resultado = _funnel(negocio.id)

        assert resultado["visits"] == 1
        assert resultado["conversion"] == 100.0


class TestAislamientoEntreNegocios:
    def test_un_negocio_no_ve_los_datos_de_otro(self, negocio):
        from app.database import SessionLocal
        from app.models import Business, Placement

        with SessionLocal() as db:
            otro = Business(name="Otro", google_review_url="https://g.page/r/CY/review")
            db.add(otro)
            db.flush()
            placa = Placement(business_id=otro.id, label="Barra")
            db.add(placa)
            db.commit()
            otro_id, placa_id = otro.id, placa.id

        add_visit(negocio.id, negocio.mesa_id, converts=True)
        for _ in range(7):
            add_visit(otro_id, placa_id, converts=False)

        assert _funnel(negocio.id)["visits"] == 1
        assert _funnel(otro_id)["visits"] == 7


class TestPorSoporte:
    def test_compara_placas_y_ordena_por_rendimiento(self, negocio):
        # Mesa 1: 4 visitas, 3 clicks = 75%. Mesón: 4 visitas, 1 click = 25%.
        for i in range(4):
            add_visit(negocio.id, negocio.mesa_id, converts=i < 3)
        for i in range(4):
            add_visit(negocio.id, negocio.meson_id, converts=i < 1)

        tabla = metrics.by_placement(metrics.load_taps(negocio.id))
        filas = {f["label"]: f for f in tabla.to_dict("records")}

        assert filas["Mesa 1"]["conversion"] == 75.0
        assert filas["Mesón"]["conversion"] == 25.0
        # La mejor va primero: el informe usa la primera fila como "destacada".
        assert tabla.iloc[0]["label"] == "Mesa 1"

    def test_placa_sin_visitas_no_rompe(self, negocio):
        add_tap(negocio.id, negocio.mesa_id, "went_to_google", session_id="huerfano")

        tabla = metrics.by_placement(metrics.load_taps(negocio.id))

        assert list(tabla["conversion"]) == [0.0]


class TestPeriodos:
    def test_filtra_por_mes(self, negocio):
        agosto = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)
        julio = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
        for _ in range(3):
            add_visit(negocio.id, negocio.mesa_id, converts=True, when=agosto)
        add_visit(negocio.id, negocio.mesa_id, converts=False, when=julio)

        taps = metrics.load_taps(negocio.id)
        inicio, fin = metrics.month_bounds(2026, 8)

        assert metrics.funnel(metrics.in_period(taps, inicio, fin))["visits"] == 3
        assert metrics.funnel(taps)["visits"] == 4  # sin filtrar, están los dos meses

    def test_mes_anterior_cruza_el_año(self):
        assert metrics.previous_month(2026, 1) == (2025, 12)
        assert metrics.previous_month(2026, 9) == (2026, 8)

    def test_limites_de_diciembre(self):
        inicio, fin = metrics.month_bounds(2026, 12)

        assert inicio == datetime(2026, 12, 1)
        assert fin == datetime(2027, 1, 1)


class TestPorDia:
    def test_agrupa_visitantes_unicos_por_dia(self, negocio):
        dia = datetime(2026, 8, 10, 9, tzinfo=timezone.utc)
        sesion = "vuelve-varias-veces"
        for _ in range(3):
            add_tap(negocio.id, negocio.mesa_id, "landed", session_id=sesion, when=dia)
        add_visit(negocio.id, negocio.mesa_id, when=datetime(2026, 8, 11, 9, tzinfo=timezone.utc))

        tabla = metrics.by_day(metrics.load_taps(negocio.id))

        assert list(tabla["visitas"]) == [1, 1]
        assert len(tabla) == 2
