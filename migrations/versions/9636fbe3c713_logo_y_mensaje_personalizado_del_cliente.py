"""logo y mensaje personalizado del cliente

Revision ID: 9636fbe3c713
Revises: 53f661c21212
Create Date: 2026-09-03 20:26:04.367290

Personalización de la landing: el logo del local y un mensaje propio, para que la
página se vea del negocio y no de una plataforma genérica.

El logo se guarda en la base y no como archivo porque el hosting no tiene disco
persistente: un archivo desaparecería en el siguiente despliegue y el cliente
vería su logo esfumarse sin que nadie tocara nada.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9636fbe3c713'
down_revision: Union[str, None] = '53f661c21212'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("businesses", schema=None) as batch_op:
        # Nullable: un cliente sin logo es el caso normal, no una excepción.
        batch_op.add_column(sa.Column("logo_data", sa.LargeBinary(), nullable=True))
        # server_default corregido a mano: el autogenerado lo omite y sin él una
        # columna NOT NULL falla en cualquier tabla que ya tenga filas. Ya pasó
        # una vez en este proyecto (ver cdd115ca0d87). El default vive solo aquí;
        # en el modelo basta con default="".
        batch_op.add_column(
            sa.Column("welcome_message", sa.String(length=300), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("businesses", schema=None) as batch_op:
        batch_op.drop_column("welcome_message")
        batch_op.drop_column("logo_data")
