"""add pipeline_trace to search_runs

Revision ID: 6d7f7f6a3f1b
Revises: 2284e01472ba
Create Date: 2026-04-08 15:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6d7f7f6a3f1b"
down_revision: Union[str, None] = "2284e01472ba"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "search_runs",
        sa.Column(
            "pipeline_trace",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.alter_column("search_runs", "pipeline_trace", server_default=None)


def downgrade() -> None:
    op.drop_column("search_runs", "pipeline_trace")
