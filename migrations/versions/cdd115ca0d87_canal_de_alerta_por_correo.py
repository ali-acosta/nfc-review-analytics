"""canal de alerta por correo

Revision ID: cdd115ca0d87
Revises: 6ab5d4601b89
Create Date: 2026-09-02 23:22:29.277505
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'cdd115ca0d87'
down_revision: Union[str, None] = '6ab5d4601b89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default no lo pone el autogenerado, pero es obligatorio aquí: sin
    # él, agregar una columna NOT NULL a una tabla que ya tiene negocios falla.
    # El default vive solo en esta migración; en el modelo basta default="".
    with op.batch_alter_table("businesses", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("alert_email", sa.String(length=255), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("businesses", schema=None) as batch_op:
        batch_op.drop_column("alert_email")
