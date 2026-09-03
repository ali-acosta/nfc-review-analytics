from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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
