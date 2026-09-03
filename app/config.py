from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty: una variable definida pero vacía usa el valor por defecto
    # en vez de intentar convertirla. Sin esto, un secret que no existe llega como
    # cadena vacía y SMTP_PORT="" tumba el proceso entero al arrancar, porque no
    # se puede convertir a entero. Un canal de aviso mal configurado no puede
    # impedir que la app levante.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True
    )

    database_url: str = "sqlite:///./nfc_analytics.db"
    base_url: str = "http://localhost:8000"

    # Zona horaria del negocio. Los eventos se guardan en UTC, pero los
    # informes y los gráficos se agrupan en hora local: si no, la cena de un
    # restaurante (que en Chile cae después de medianoche UTC) aparecería al
    # día siguiente, y el último día del mes se iría al informe siguiente.
    # Hoy es global porque todos los clientes son chilenos; si algún día hay
    # clientes en otro huso, pasa a ser una columna de Business.
    timezone: str = "America/Santiago"

    # Firma las cookies de sesión del panel. Si se deja vacío se genera una al
    # arrancar, lo que sirve en desarrollo pero cierra la sesión de todos los
    # clientes en cada reinicio: en producción hay que fijarla.
    session_secret: str = ""

    # DEBUG deja rastro de cada consulta y llena el panel de logs del
    # hosting; INFO es lo razonable en producción.
    log_level: str = "INFO"

    # Credencial del panel de administración, guardada como hash scrypt (nunca en
    # texto plano). Vacío = el panel NO EXISTE: responde 404 y no hay forma de
    # entrar. Ese es el valor por defecto a propósito: un panel que ve y modifica
    # a todos los clientes no puede quedar accesible por olvidar configurarlo.
    # Se genera con: python -m scripts.admin_password
    admin_password_hash: str = ""

    # Monitoreo de errores. Vacío = apagado, que es el estado por defecto: la
    # integración viaja lista en el código y se enciende sola cuando se pega el
    # DSN, sin tocar nada más. Sin esto, un error 500 en producción solo se
    # descubre si un cliente lo cuenta, y un cliente parado en un mostrador no
    # cuenta nada: se va.
    sentry_dsn: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # SMTP para las alertas por correo. Funciona con cualquier proveedor
    # (Brevo, Gmail, Zoho); el free tier de Brevo alcanza de sobra.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""


settings = Settings()
