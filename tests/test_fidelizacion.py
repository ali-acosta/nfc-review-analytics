"""El programa de sellos.

Estos tests protegen algo distinto de los del embudo de reseñas: allá un evento
de más ensucia una métrica, acá un sello de más es un café regalado y un premio
cobrado dos veces es plata del comercio. Por eso lo que más se prueba no es que
funcione, sino que **no se pueda hacer trampa**: que la placa de la mesa no dé
sellos, que sin el código de la caja no pase nada, y que un premio se cobre una
sola vez.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models import Business, LoyaltyCard, LoyaltyProgram, Placement, Reward, Stamp
from app.services import fidelizacion
from app.services.auth import hash_password
from app.services.ratelimit import tarjeta_limiter

CLAVE = "clave-del-duenio"


@pytest.fixture(autouse=True)
def _sin_limite():
    """El límite de tarjetas nuevas es por IP y global al proceso: sin esto, los
    tests de más abajo empezarían a recibir 429 por culpa de los de más arriba,
    que salen todos de la misma IP."""
    tarjeta_limiter._hits.clear()
    yield
    tarjeta_limiter._hits.clear()


def _codigo(programa) -> str:
    return fidelizacion.codigo_actual(programa.secret)


def _sellar(client, programa, codigo=None):
    return client.get(f"/sello/{programa.token}/{codigo or _codigo(programa)}")


def _sellos(card_token=None) -> list[Stamp]:
    with SessionLocal() as db:
        query = select(Stamp)
        if card_token:
            card = db.scalar(select(LoyaltyCard).where(LoyaltyCard.token == card_token))
            query = query.where(Stamp.card_id == card.id)
        return list(db.scalars(query))


def _tarjetas() -> list[LoyaltyCard]:
    with SessionLocal() as db:
        return list(db.scalars(select(LoyaltyCard)))


def _premios() -> list[Reward]:
    with SessionLocal() as db:
        return list(db.scalars(select(Reward)))


def _atrasar_sellos(dias: int) -> None:
    """Mueve todos los sellos hacia atrás, para simular días distintos sin
    tener que esperar a mañana."""
    with SessionLocal() as db:
        for sello in db.scalars(select(Stamp)):
            sello.created_at = sello.created_at - timedelta(days=dias)
        db.commit()


def _token_de_tarjeta(respuesta) -> str:
    """El token sale de la URL a la que redirige el sellado."""
    return respuesta.url.path.split("/tarjeta/")[1]


def _entrar(negocio, correo="dueno@local.cl"):
    with SessionLocal() as db:
        business = db.get(Business, negocio.id)
        business.login_email = correo
        business.password_hash = hash_password(CLAVE)
        db.commit()
    client = TestClient(app, follow_redirects=False)
    client.post("/panel/login", data={"email": correo, "password": CLAVE})
    return client


# --------------------------------------------------------------------------- #


class TestElSelloLoDaLaCaja:
    """La regla que sostiene todo: un sello vale plata, así que no puede salir
    de un token que está pegado en una mesa a la vista de cualquiera."""

    def test_la_placa_de_la_mesa_no_da_sellos(self, programa, visitante):
        """Si algún día alguien cuelga el sellado de la landing, esto cae.

        El token de la placa es público por diseño: está impreso en la mesa. Si
        tocarla diera un sello, el premio se conseguiría tocándola N veces, o
        desde la casa con una foto del QR."""
        telefono = visitante()
        for _ in range(6):
            telefono.get(f"/r/{programa.negocio.mesa}")

        assert _sellos() == []
        assert _tarjetas() == []

    def test_un_codigo_valido_suma_un_sello(self, programa, visitante):
        respuesta = _sellar(visitante(), programa)

        assert respuesta.status_code == 200
        assert len(_sellos()) == 1

    def test_sin_codigo_valido_no_hay_sello(self, programa, visitante):
        respuesta = _sellar(visitante(), programa, codigo="XXXXXX")

        assert respuesta.status_code == 410
        assert _sellos() == []
        assert _tarjetas() == []

    def test_el_codigo_de_otro_negocio_no_sirve(self, programa, visitante):
        """Cada programa tiene su propio secreto: conocer el código de un local
        no permite sellar en el de al lado."""
        with SessionLocal() as db:
            otro = Business(name="Otro Local", google_review_url="https://g.page/r/otro/review")
            db.add(otro)
            db.flush()
            placa = Placement(business_id=otro.id, label="Caja")
            db.add(placa)
            db.flush()
            prog_otro = LoyaltyProgram(business_id=otro.id, placement_id=placa.id, reward="Algo")
            db.add(prog_otro)
            db.commit()
            token_otro, secreto_otro = prog_otro.token, prog_otro.secret

        ajeno = fidelizacion.codigo_actual(secreto_otro)
        respuesta = visitante().get(f"/sello/{programa.token}/{ajeno}")

        assert respuesta.status_code == 410
        assert _sellos() == []
        assert token_otro != programa.token

    def test_se_acepta_el_codigo_de_la_ventana_anterior(self, programa, visitante):
        """Entre que el cliente enfoca el QR y llega la petición pasan segundos.
        Sin tolerancia, el sello fallaría justo en el cambio de minuto, delante
        del cajero."""
        anterior = fidelizacion._codigo_de_ventana(programa.secret, fidelizacion._ventana() - 1)

        respuesta = _sellar(visitante(), programa, codigo=anterior)

        assert respuesta.status_code == 200
        assert len(_sellos()) == 1

    def test_un_codigo_viejo_ya_no_sirve(self, programa, visitante):
        viejo = fidelizacion._codigo_de_ventana(programa.secret, fidelizacion._ventana() - 3)

        respuesta = _sellar(visitante(), programa, codigo=viejo)

        assert respuesta.status_code == 410
        assert _sellos() == []

    def test_el_codigo_cambia_entre_ventanas(self, programa):
        ventana = fidelizacion._ventana()
        codigos = {
            fidelizacion._codigo_de_ventana(programa.secret, ventana - i) for i in range(5)
        }

        assert len(codigos) == 5

    def test_un_programa_apagado_no_sella(self, programa, visitante):
        with SessionLocal() as db:
            db.get(LoyaltyProgram, programa.id).active = False
            db.commit()

        respuesta = _sellar(visitante(), programa)

        assert respuesta.status_code == 404
        assert _sellos() == []


class TestUnSelloPorDia:
    """Nadie se toma cinco cafés en una hora. Es la defensa que queda en pie si
    alguien alcanza a compartir un código dentro de su ventana."""

    def test_escanear_dos_veces_el_mismo_dia_no_suma_dos(self, programa, visitante):
        telefono = visitante()
        _sellar(telefono, programa)
        respuesta = _sellar(telefono, programa)

        assert len(_sellos()) == 1
        assert "sello de hoy" in respuesta.text.lower()

    def test_al_dia_siguiente_si_suma(self, programa, visitante):
        telefono = visitante()
        _sellar(telefono, programa)
        _atrasar_sellos(1)

        _sellar(telefono, programa)

        assert len(_sellos()) == 2

    def test_dos_clientes_distintos_sellan_el_mismo_dia(self, programa, visitante):
        """El límite es por tarjeta, no por local ni por IP: en un café los
        clientes salen todos por el mismo WiFi."""
        _sellar(visitante(), programa)
        _sellar(visitante(), programa)

        assert len(_sellos()) == 2
        assert len(_tarjetas()) == 2


class TestElPremio:
    def _completar(self, programa, visitante):
        """Completa una tarjeta repartiendo los sellos en días distintos."""
        telefono = visitante()
        respuesta = None
        for _ in range(programa.requeridos):
            respuesta = _sellar(telefono, programa)
            _atrasar_sellos(1)
        return telefono, _token_de_tarjeta(respuesta)

    def test_al_completar_la_tarjeta_se_emite_el_premio(self, programa, visitante):
        self._completar(programa, visitante)

        premios = _premios()
        assert len(premios) == 1
        assert premios[0].redeemed_at is None

    def test_el_premio_consume_los_sellos(self, programa, visitante):
        _, card_token = self._completar(programa, visitante)

        with SessionLocal() as db:
            card = db.scalar(select(LoyaltyCard).where(LoyaltyCard.token == card_token))
            assert fidelizacion.sellos_disponibles(db, card) == 0
            assert fidelizacion.sellos_totales(db, card) == programa.requeridos

    def test_no_se_emite_un_premio_antes_de_tiempo(self, programa, visitante):
        telefono = visitante()
        _sellar(telefono, programa)

        assert _premios() == []

    def test_el_premio_guarda_su_texto_y_su_costo(self, programa, visitante):
        """Si el dueño cambia las condiciones, quien ya ganó tiene que poder
        cobrar lo que le prometieron."""
        self._completar(programa, visitante)

        with SessionLocal() as db:
            prog = db.get(LoyaltyProgram, programa.id)
            prog.reward = "Ahora regalamos otra cosa"
            prog.stamps_required = 10
            db.commit()

        premio = _premios()[0]
        assert premio.reward_text == programa.premio
        assert premio.stamps_consumed == programa.requeridos


class TestElCanje:
    def _con_premio(self, programa, visitante):
        telefono = visitante()
        respuesta = None
        for _ in range(programa.requeridos):
            respuesta = _sellar(telefono, programa)
            _atrasar_sellos(1)
        return telefono, _token_de_tarjeta(respuesta)

    def test_canjear_exige_el_codigo_de_la_caja(self, programa, visitante):
        """Sin esto, cualquiera cobra su café desde la casa abriendo su marcador
        y llega al local con la tarjeta ya limpia."""
        telefono, card_token = self._con_premio(programa, visitante)

        respuesta = telefono.post(
            f"/tarjeta/{card_token}/canjear", data={"codigo": "XXXXXX"}
        )

        assert respuesta.status_code == 410
        assert _premios()[0].redeemed_at is None

    def test_con_el_codigo_de_la_caja_se_cobra(self, programa, visitante):
        telefono, card_token = self._con_premio(programa, visitante)

        respuesta = telefono.post(
            f"/tarjeta/{card_token}/canjear", data={"codigo": _codigo(programa)}
        )

        assert respuesta.status_code == 200
        assert _premios()[0].redeemed_at is not None

    def test_un_premio_no_se_cobra_dos_veces(self, programa, visitante):
        """El segundo toque al botón no puede volver a cobrar el mismo premio."""
        telefono, card_token = self._con_premio(programa, visitante)
        datos = {"codigo": _codigo(programa)}

        primera = telefono.post(f"/tarjeta/{card_token}/canjear", data=datos)
        segunda = telefono.post(f"/tarjeta/{card_token}/canjear", data=datos)

        assert primera.status_code == 200
        assert "canjead" in primera.text.lower()
        assert "no tienes premios" in segunda.text.lower()
        assert len([p for p in _premios() if p.redeemed_at is not None]) == 1

    def test_canjear_sin_premio_no_rompe(self, programa, visitante):
        telefono = visitante()
        respuesta = _sellar(telefono, programa)
        card_token = _token_de_tarjeta(respuesta)

        respuesta = telefono.post(
            f"/tarjeta/{card_token}/canjear", data={"codigo": _codigo(programa)}
        )

        assert respuesta.status_code == 200
        assert "no tienes premios" in respuesta.text.lower()

    def test_el_boton_de_canje_no_aparece_sin_pasar_por_la_caja(self, programa, visitante):
        """Abrir la tarjeta desde un marcador muestra el premio, pero no el
        botón: para cobrarlo hay que estar delante del cajero."""
        telefono, card_token = self._con_premio(programa, visitante)

        html = telefono.get(f"/tarjeta/{card_token}").text

        assert "canjear" in html.lower()  # se le dice que lo tiene
        assert f'action="/tarjeta/{card_token}/canjear"' not in html  # pero no puede cobrarlo


class TestLaTarjetaEsDeCadaComercio:
    def test_la_tarjeta_de_un_comercio_no_recibe_sellos_de_otro(self, programa, visitante):
        """La base de clientes es del comercio. Cruzarlas sería repartir entre
        comercios un dato que no es de la plataforma."""
        with SessionLocal() as db:
            otro = Business(name="Otro Local", google_review_url="https://g.page/r/otro/review")
            db.add(otro)
            db.flush()
            ajena = LoyaltyCard(business_id=otro.id)
            db.add(ajena)
            db.commit()
            token_ajeno = ajena.token

        telefono = visitante()
        # Se le planta la cookie de la tarjeta del otro local.
        telefono.cookies.set(f"tarjeta_{programa.token}", token_ajeno)
        _sellar(telefono, programa)

        assert _sellos(token_ajeno) == []
        assert len(_sellos()) == 1


class TestLaTarjetaNoRompeLaPoliticaDeGoogle:
    """La restricción 1 de CLAUDE.md sigue en pie dentro del flujo de sellos.

    El pitch original de la fidelización proponía filtrar por calificación
    después del sello. Eso no se construyó, y estos tests fallan si vuelve."""

    def _tarjeta(self, programa, visitante):
        respuesta = _sellar(visitante(), programa)
        return respuesta.text

    def test_la_tarjeta_ofrece_google_en_un_click(self, programa, visitante):
        html = self._tarjeta(programa, visitante)

        assert f'href="/r/{programa.placa}/go"' in html

    def test_la_tarjeta_no_pide_estrellas_antes_de_google(self, programa, visitante):
        html = self._tarjeta(programa, visitante).lower()

        assert "data-rating" not in html
        assert 'class="star"' not in html
        assert "¿cómo calificarías" not in html

    def test_la_tarjeta_ofrece_el_canal_privado(self, programa, visitante):
        html = self._tarjeta(programa, visitante)

        assert f'href="/r/{programa.placa}"' in html

    def test_los_sellos_no_se_ponen_antes_del_boton_de_google(self, programa, visitante):
        """En la landing, nada puede ir por delante del botón de Google: cada
        paso intermedio le cuesta reseñas al cliente, que es lo que paga."""
        html = visitante().get(f"/r/{programa.negocio.mesa}").text

        assert html.index(f'/r/{programa.negocio.mesa}/go') < html.index("mi-tarjeta")


class TestLaLandingSinPrograma:
    def test_un_negocio_sin_programa_no_muestra_la_tarjeta(self, negocio, visitante):
        html = visitante().get(f"/r/{negocio.mesa}").text

        assert "mi-tarjeta" not in html


class TestVerMiTarjeta:
    def test_lleva_a_la_tarjeta_de_quien_ya_tiene_una(self, programa, visitante):
        telefono = visitante()
        respuesta = _sellar(telefono, programa)
        card_token = _token_de_tarjeta(respuesta)

        respuesta = telefono.get(f"/mi-tarjeta/{programa.token}", follow_redirects=False)

        assert respuesta.status_code == 302
        assert respuesta.headers["location"] == f"/tarjeta/{card_token}"

    def test_a_quien_no_tiene_se_le_explica(self, programa, visitante):
        respuesta = visitante().get(f"/mi-tarjeta/{programa.token}")

        assert respuesta.status_code == 200
        assert "todavía no tienes tarjeta" in respuesta.text.lower()


class TestPanelDelDueno:
    def test_sin_sesion_no_se_configura(self, negocio):
        with TestClient(app, follow_redirects=False) as c:
            respuesta = c.post("/panel/fidelizacion", data={"sellos": 5, "premio": "Café"})

        assert respuesta.status_code == 302
        with SessionLocal() as db:
            assert db.scalars(select(LoyaltyProgram)).all() == []

    def test_activarlo_crea_el_programa_y_su_propia_placa(self, negocio):
        client = _entrar(negocio)

        client.post(
            "/panel/fidelizacion",
            data={"sellos": 4, "premio": "El 5° café gratis", "activo": "si"},
        )

        with SessionLocal() as db:
            prog = db.scalar(select(LoyaltyProgram).where(LoyaltyProgram.business_id == negocio.id))
            assert prog is not None
            assert prog.stamps_required == 4
            assert prog.active is True
            # Placa propia: si las reseñas del flujo de sellos se le sumaran a
            # una mesa, la comparación por soporte mentiría.
            assert prog.placement_id is not None
            assert db.get(Placement, prog.placement_id).label == "Caja (fidelización)"

    def test_no_acepta_una_cantidad_de_sellos_absurda(self, negocio):
        client = _entrar(negocio)

        respuesta = client.post(
            "/panel/fidelizacion", data={"sellos": 0, "premio": "Café", "activo": "si"}
        )

        assert respuesta.status_code == 400
        with SessionLocal() as db:
            assert db.scalars(select(LoyaltyProgram)).all() == []

    def test_exige_decir_cual_es_el_premio(self, negocio):
        client = _entrar(negocio)

        respuesta = client.post(
            "/panel/fidelizacion", data={"sellos": 5, "premio": "  ", "activo": "si"}
        )

        assert respuesta.status_code == 400

    def test_se_puede_apagar_sin_perder_los_sellos(self, programa, visitante):
        _sellar(visitante(), programa)
        client = _entrar(programa.negocio)

        client.post(
            "/panel/fidelizacion",
            data={"sellos": programa.requeridos, "premio": programa.premio},
        )

        with SessionLocal() as db:
            assert db.get(LoyaltyProgram, programa.id).active is False
        assert len(_sellos()) == 1


class TestLaPantallaDeLaCaja:
    def test_sin_sesion_no_se_ve_el_codigo(self, programa):
        """El código *es* el timbre: quien lo ve, puede sellar. No puede quedar
        expuesto a cualquiera que sepa la URL."""
        with TestClient(app, follow_redirects=False) as c:
            respuesta = c.get("/panel/caja/codigo")

        assert respuesta.json().get("error") == "sin sesion"

    def test_sin_sesion_la_pantalla_manda_al_login(self, programa):
        with TestClient(app, follow_redirects=False) as c:
            respuesta = c.get("/panel/caja")

        assert respuesta.status_code == 302
        assert respuesta.headers["location"] == "/panel/login"

    def test_con_sesion_entrega_el_codigo_y_su_qr(self, programa):
        client = _entrar(programa.negocio)

        datos = client.get("/panel/caja/codigo").json()

        assert datos["codigo"] == _codigo(programa)
        assert datos["qr"].startswith("data:image/png;base64,")
        assert 0 < datos["segundos"] <= fidelizacion.VENTANA_SEGUNDOS

    def test_el_codigo_que_entrega_sirve_para_sellar(self, programa, visitante):
        """El extremo a extremo: lo que muestra la caja es lo que sella."""
        client = _entrar(programa.negocio)
        codigo = client.get("/panel/caja/codigo").json()["codigo"]

        respuesta = visitante().get(f"/sello/{programa.token}/{codigo}")

        assert respuesta.status_code == 200
        assert len(_sellos()) == 1


class TestReglasDeTiempo:
    def test_el_dia_se_corta_en_hora_local_y_no_en_utc(self, programa):
        """Un sello a las 21:30 en Chile es del mismo día local que uno a las
        10:00, aunque en UTC ya sea el día siguiente. Sin esto, un cliente
        podría sacar dos sellos la misma tarde."""
        with SessionLocal() as db:
            card = LoyaltyCard(business_id=programa.negocio.id)
            db.add(card)
            db.flush()
            # 2026-09-04 21:30 en Chile = 2026-09-05 01:30 UTC.
            db.add(
                Stamp(
                    card_id=card.id,
                    business_id=programa.negocio.id,
                    created_at=datetime(2026, 9, 5, 1, 30, tzinfo=timezone.utc),
                )
            )
            db.commit()

            momento = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)  # 22:00 local
            assert fidelizacion.sello_hoy(db, card, momento) is True

            siguiente = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)  # 10:00 del día 5
            assert fidelizacion.sello_hoy(db, card, siguiente) is False


class TestLasPaginasDeSellosSobrevivenALaCSP:
    """La lección que este proyecto ya pagó una vez.

    La CSP la aplica el navegador, no el servidor: para un TestClient el HTML
    llega perfecto aunque la política vaya a descartarlo entero. Al informe eso
    le costó llegarle al dueño como texto plano, sin un gráfico, y ningún test
    lo vio.

    Estas páginas son públicas y quedan bajo la política estricta, así que no
    comprueban cómo se ven sino la coherencia entre lo que usan y lo que su
    política permite. La pantalla de la caja es la más frágil de las dos: si su
    JavaScript quedara bloqueado, el QR no se refrescaría nunca y el cajero
    estaría mostrando un código muerto sin que nada avise.
    """

    def _csp(self, respuesta):
        return respuesta.headers["content-security-policy"]

    def test_la_tarjeta_no_depende_de_estilos_en_linea(self, programa, visitante):
        respuesta = _sellar(visitante(), programa)

        assert 'style="' not in respuesta.text
        assert "<style" not in respuesta.text.lower()
        assert "'unsafe-inline'" not in self._csp(respuesta)

    def test_la_pantalla_de_la_caja_no_lleva_scripts_en_linea(self, programa):
        client = _entrar(programa.negocio)

        respuesta = client.get("/panel/caja")
        cuerpo = respuesta.text

        # El único <script> permitido es el que apunta a un archivo propio.
        assert 'src="/static/caja.js"' in cuerpo
        assert "<script>" not in cuerpo
        assert "script-src 'self'" in self._csp(respuesta)

    def test_el_qr_de_la_caja_viaja_como_data_uri_y_la_politica_lo_permite(self, programa):
        client = _entrar(programa.negocio)

        csp = self._csp(client.get("/panel/caja"))
        datos = client.get("/panel/caja/codigo").json()

        assert datos["qr"].startswith("data:image/png;base64,")
        assert "data:" in csp.split("img-src")[1].split(";")[0], (
            "el QR de la caja va como data: URI pero la política lo bloquea: "
            "el cajero vería un recuadro vacío y nadie podría sellar"
        )


class TestLosSellosEntranAlRespaldo:
    """Perder los sellos no es perder historial: es perder una deuda.

    Las visitas, si se pierden, dejan al dueño sin un número. Los sellos dejan a
    un cliente que ya juntó los suyos parado en el mostrador mientras el sistema
    le dice que no tiene nada, sin forma de demostrar lo contrario. Por eso el
    respaldo semanal —que corre `export_data --todos`— tiene que llevárselos.
    """

    def test_la_exportacion_incluye_sellos_y_premios(self, programa, visitante, tmp_path):
        from app.database import SessionLocal as SL
        from scripts.export_data import exportar

        telefono = visitante()
        for _ in range(programa.requeridos):
            _sellar(telefono, programa)
            _atrasar_sellos(1)

        with SL() as db:
            escritos = exportar(db.get(Business, programa.negocio.id), tmp_path)

        nombres = " ".join(p.name for p in escritos)
        assert "sellos" in nombres
        assert "premios" in nombres

    def test_un_negocio_sin_programa_no_genera_archivos_vacios(self, negocio, tmp_path):
        from app.database import SessionLocal as SL
        from scripts.export_data import exportar

        with SL() as db:
            escritos = exportar(db.get(Business, negocio.id), tmp_path)

        nombres = " ".join(p.name for p in escritos)
        assert "sellos" not in nombres

    def test_los_sellos_se_exportan_en_hora_local(self, programa, visitante):
        """Misma regla que el resto del producto: mezclar husos dentro de una
        exportación confunde a cualquiera que después compare columnas."""
        from datetime import datetime as dt

        from app.services import metrics

        with SessionLocal() as db:
            card = LoyaltyCard(business_id=programa.negocio.id)
            db.add(card)
            db.flush()
            db.add(
                Stamp(
                    card_id=card.id,
                    business_id=programa.negocio.id,
                    created_at=dt(2026, 9, 5, 1, 30, tzinfo=timezone.utc),
                )
            )
            db.commit()

        df = metrics.load_sellos(programa.negocio.id)

        # 01:30 UTC del día 5 son las 21:30 del día 4 en Chile.
        assert df.iloc[0]["created_at"].day == 4
        assert df.iloc[0]["created_at"].hour == 21
