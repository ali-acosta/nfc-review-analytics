"""Las migraciones son lo único que separa un cambio de esquema de perder el
historial de un cliente. Si se desincronizan de los modelos, el despliegue
arranca contra una base que no es la que el código espera."""

import os
import subprocess
import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.database import Base

RAIZ = Path(__file__).resolve().parent.parent


def _migrar_a_base_nueva(destino: Path) -> str:
    url = f"sqlite:///{destino.as_posix()}"
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=RAIZ,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, f"alembic upgrade falló:\n{resultado.stderr}"
    return url


class TestMigraciones:
    def test_no_divergen_de_los_modelos(self, tmp_path):
        """El test que importa: si alguien agrega una columna y olvida la
        migración, esto falla antes de llegar a producción."""
        url = _migrar_a_base_nueva(tmp_path / "migrada.db")

        with create_engine(url).connect() as conexion:
            diferencias = compare_metadata(MigrationContext.configure(conexion), Base.metadata)

        assert diferencias == [], f"modelos y migraciones divergieron: {diferencias}"

    def test_crean_todas_las_tablas(self, tmp_path):
        url = _migrar_a_base_nueva(tmp_path / "migrada.db")

        tablas = set(inspect(create_engine(url)).get_table_names())

        assert {"businesses", "placements", "taps", "feedbacks"} <= tablas

    def test_conservan_los_indices_que_usan_las_consultas(self, tmp_path):
        """Sin estos índices el panel hace scan completo en cada refresco."""
        url = _migrar_a_base_nueva(tmp_path / "migrada.db")
        inspector = inspect(create_engine(url))

        indices_taps = {i["name"] for i in inspector.get_indexes("taps")}

        assert "ix_taps_business_id" in indices_taps
        assert "ix_taps_session_id" in indices_taps
        assert "ix_taps_is_bot" in indices_taps

    def test_el_despliegue_migra_antes_de_arrancar(self):
        blueprint = (RAIZ / "render.yaml").read_text(encoding="utf-8")

        assert "alembic upgrade head &&" in blueprint, (
            "el startCommand debe migrar antes de levantar la app"
        )

    def test_la_url_no_esta_escrita_en_el_ini(self):
        """Debe salir de app.config para no poder apuntar a una base distinta
        que la aplicación, y para no dejar credenciales en el repo."""
        ini = (RAIZ / "alembic.ini").read_text(encoding="utf-8")

        assert "sqlalchemy.url =" not in ini
