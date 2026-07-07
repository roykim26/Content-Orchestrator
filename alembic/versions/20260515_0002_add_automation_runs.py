"""add automation runs"""

from alembic import op
import sqlalchemy as sa


revision = "20260515_0002"
down_revision = "20260514_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automationrun",
        sa.Column("automation_type", sa.String(), nullable=False),
        sa.Column("run_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_automationrun_type_run_key",
        "automationrun",
        ["automation_type", "run_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_automationrun_type_run_key", table_name="automationrun")
    op.drop_table("automationrun")
