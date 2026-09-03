"""Configuración de logs.

En producción un fallo sin registro es invisible: la app responde mal y nadie se
entera hasta que un cliente reclama. Esto no reemplaza a un servicio de
monitoreo, pero deja rastro legible y con marca de tiempo en la salida estándar,
que es lo que capturan los paneles de logs del hosting.
"""

import logging
import sys
from logging.config import dictConfig

FORMATO = "%(asctime)s %(levelname)-7s %(name)s · %(message)s"
FECHA = "%Y-%m-%d %H:%M:%S"


def configure_logging(level: str = "INFO") -> None:
    dictConfig(
        {
            "version": 1,
            # No se desactivan los loggers existentes: uvicorn y sqlalchemy ya
            # crearon los suyos antes de llegar aquí.
            "disable_existing_loggers": False,
            "formatters": {"estandar": {"format": FORMATO, "datefmt": FECHA}},
            "handlers": {
                "consola": {
                    "class": "logging.StreamHandler",
                    "formatter": "estandar",
                    "stream": sys.stdout,
                }
            },
            "root": {"handlers": ["consola"], "level": level},
            "loggers": {
                # El log de acceso de uvicorn duplica lo que ya registra el
                # hosting y ensucia lo que sí importa leer.
                "uvicorn.access": {"level": "WARNING", "propagate": True},
                # A nivel INFO, SQLAlchemy escupe cada consulta.
                "sqlalchemy.engine": {"level": "WARNING", "propagate": True},
            },
        }
    )
    logging.getLogger(__name__).debug("Logging configurado en nivel %s", level)
