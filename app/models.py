import secrets
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """Guarda instantes siempre en UTC, sea cual sea el motor.

    SQLite no tiene tipo fecha: descarta el offset y guarda la hora de pared tal
    cual, así que un datetime en otra zona quedaría registrado como un instante
    distinto del que ocurrió. Postgres, con el mismo código, sí lo convertiría
    bien. Esa divergencia entre desarrollo y producción es difícil de detectar
    —los números salen apenas corridos—, así que se normaliza aquí y no se
    confía en que quien escriba se acuerde de pasar UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)  # los naive se asumen UTC
        value = value.astimezone(timezone.utc)
        # SQLite guarda el texto tal cual: se le entrega ya sin zona para que no
        # quede un offset escrito que después nadie relea.
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def new_token(nbytes: int = 6) -> str:
    """Short, non-enumerable, URL-safe token (~8 chars).

    These end up burned into NFC chips and printed on QR codes, so they must be
    impossible to enumerate: a guessable id would let anyone scrape the client
    list or poison a client's analytics by hitting their /go endpoint.
    """
    return secrets.token_urlsafe(nbytes)


class Business(Base):
    """A tenant: one local business paying for the service."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    google_review_url: Mapped[str] = mapped_column(String(512))
    # Capability URL for the owner's dashboard (/dashboard/?t=<token>).
    dashboard_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=new_token)
    # Credenciales del dueño para entrar al panel. El dashboard_token sigue
    # existiendo, pero solo para los enlaces de informe que se envían por correo
    # al propio dueño: el panel interactivo exige contraseña.
    login_email: Mapped[str] = mapped_column(String(255), default="", index=True)
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    # Canales de aviso. Se puede tener uno, los dos o ninguno: el correo existe
    # porque un dueño de pyme revisa su correo, no necesariamente Telegram.
    telegram_chat_id: Mapped[str] = mapped_column(String(64), default="")
    alert_email: Mapped[str] = mapped_column(String(255), default="")

    # Personalización de la landing. Hace que la página se vea del local y no de
    # una plataforma genérica, que es lo que un cliente que paga espera ver
    # cuando le muestra el producto a su propio cliente.
    #
    # El logo va en la base y no en un archivo: el hosting no tiene disco
    # persistente, así que un archivo desaparecería en el próximo despliegue.
    # Se guarda ya reprocesado a PNG por app/services/logo.py, nunca los bytes
    # que llegaron.
    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    welcome_message: Mapped[str] = mapped_column(String(300), default="")

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    placements: Mapped[list["Placement"]] = relationship(back_populates="business")
    taps: Mapped[list["Tap"]] = relationship(back_populates="business")
    feedbacks: Mapped[list["Feedback"]] = relationship(back_populates="business")


class Placement(Base):
    """One physical support: a plaque, a card, a sticker, a QR on a receipt.

    Each placement gets its own token because the whole point of the dynamic
    link is knowing *which* support converts best. This is also why placements
    are modelled separately from businesses: once a token is burned into a chip
    and the plaque is glued to a table, it can never be changed.
    """

    __tablename__ = "placements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=new_token)
    label: Mapped[str] = mapped_column(String(120))  # "Mesa 5", "Mesón", "Boleta"
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    business: Mapped["Business"] = relationship(back_populates="placements")
    taps: Mapped[list["Tap"]] = relationship(back_populates="placement")


class Tap(Base):
    """One event in the funnel.

    `session_id` is what makes a real funnel possible: without it there is no
    way to tell which "landed" event corresponds to which "went_to_google" one,
    so conversion cannot be computed honestly.
    """

    __tablename__ = "taps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    placement_id: Mapped[int] = mapped_column(ForeignKey("placements.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    # Crawlers and link-preview bots would otherwise inflate the tap count,
    # which is exactly the number a client is paying to trust.
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), default="landed")
    # outcome: "landed" | "went_to_google" | "left_private_feedback"

    business: Mapped["Business"] = relationship(back_populates="taps")
    placement: Mapped["Placement"] = relationship(back_populates="taps")


class LoyaltyProgram(Base):
    """El programa de sellos de un comercio. Uno por negocio.

    Existe como tabla aparte y no como columnas de `Business` porque un negocio
    puede no tener programa: la fidelización se vende como agregado, y un
    comercio sin programa no debe cargar con sus columnas ni aparecer en sus
    consultas.

    `secret` es lo que hace que el token público no alcance para regalarse
    sellos: el código de la caja se deriva de él y nunca sale del servidor.
    """

    __tablename__ = "loyalty_programs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), unique=True, index=True)
    # Identificador público del programa: viaja en el QR que muestra la caja.
    # Es público a propósito, igual que el token de una placa; conocerlo no
    # permite sumar un sello porque hace falta además el código rotativo.
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=new_token)
    # Semilla del código rotativo. Nunca se muestra ni viaja en una URL.
    secret: Mapped[str] = mapped_column(String(128), default=lambda: secrets.token_urlsafe(32))

    stamps_required: Mapped[int] = mapped_column(Integer, default=5)
    # Texto libre porque el premio es del comercio, no de la plataforma:
    # "el 5° café gratis", "10% de descuento", "un corte gratis".
    reward: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Placa a la que se atribuyen las reseñas que salgan del flujo de sellos.
    # Se crea una propia ("Caja") al activar el programa en vez de reutilizar
    # una existente: así la comparación por soporte sigue diciendo la verdad y,
    # de paso, el dueño puede ver si el camino de fidelización convierte mejor
    # que una mesa.
    placement_id: Mapped[int | None] = mapped_column(
        ForeignKey("placements.id"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    business: Mapped["Business"] = relationship()
    placement: Mapped["Placement | None"] = relationship()


class LoyaltyCard(Base):
    """La tarjeta de un cliente final *en un comercio*.

    Alcanzada por negocio a propósito: el mismo teléfono en dos locales son dos
    tarjetas. La base de clientes es del comercio, y cruzarla entre comercios
    sería repartir un dato que no es de la plataforma.

    No lleva ningún dato personal. La tarjeta *es* su token: una URL capacidad
    que el cliente guarda en su teléfono, como la de papel que reemplaza. Si la
    pierde, pierde sus sellos —exactamente lo que pasa hoy con la de cartón—, y
    esa es la razón por la que la Fase 1 no necesita pedir teléfono ni correo, y
    por tanto no necesita consentimiento ni plazo de borrado.
    """

    __tablename__ = "loyalty_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=new_token)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)

    business: Mapped["Business"] = relationship()
    stamps: Mapped[list["Stamp"]] = relationship(back_populates="card")


class Stamp(Base):
    """Un sello. **Solo se agrega: nunca se edita ni se borra.**

    Es lo que respalda un premio, o sea plata del comercio, así que tiene que
    poder auditarse. Por eso el consumo de sellos no se marca aquí (lo lleva
    `Reward.stamps_consumed`): tocar una fila de esta tabla sería reescribir el
    registro de algo que ya ocurrió.
    """

    __tablename__ = "loyalty_stamps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("loyalty_cards.id"), index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    card: Mapped["LoyaltyCard"] = relationship(back_populates="stamps")


class Reward(Base):
    """Un premio ganado, y su canje.

    `redeemed_at` nulo = ganado y sin cobrar. Cobrarlo dos veces es plata del
    comercio, así que el canje se hace en una actualización condicionada a que
    siga nulo: dos toques al mismo botón no pueden cobrarlo dos veces.

    `stamps_consumed` guarda cuántos sellos costó y no se recalcula desde el
    programa: si el dueño cambia mañana el premio de 5 a 8 sellos, los premios
    ya emitidos tienen que seguir contando lo que costaron el día que se
    emitieron, o el saldo de todas las tarjetas se movería solo.
    """

    __tablename__ = "loyalty_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("loyalty_cards.id"), index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    stamps_consumed: Mapped[int] = mapped_column(Integer, default=0)
    # Copia del texto del premio al momento de ganarlo, por la misma razón que
    # stamps_consumed: el dueño puede cambiar el premio y quien ya lo ganó tiene
    # que poder cobrar el que le prometieron.
    reward_text: Mapped[str] = mapped_column(String(200), default="")
    issued_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    redeemed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    card: Mapped["LoyaltyCard"] = relationship()


class Feedback(Base):
    """A private complaint that the customer chose to send to the business
    instead of (or before) posting publicly."""

    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    placement_id: Mapped[int] = mapped_column(ForeignKey("placements.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    # Optional: asked inside the private form, after the customer already
    # self-selected as unhappy — never as a gate before reaching Google.
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact: Mapped[str] = mapped_column(String(255), default="")
    message: Mapped[str] = mapped_column(String(2000), default="")
    # Cuándo el dueño la dio por atendida. Nulo = pendiente. Sin esto la bandeja
    # solo crece y deja de servir para trabajar: el valor de la queja privada
    # está en resolverla, no en leerla.
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="feedbacks")
