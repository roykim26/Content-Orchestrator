"""sync contentartifact runtime columns"""

from alembic import op
import sqlalchemy as sa


revision = "20260515_0003"
down_revision = "20260515_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    contentartifact_columns = {column["name"] for column in inspector.get_columns("contentartifact")}
    with op.batch_alter_table("contentartifact") as batch_op:
        if "claimed_by" not in contentartifact_columns:
            batch_op.add_column(sa.Column("claimed_by", sa.String(), nullable=True))
        if "publish_started_at" not in contentartifact_columns:
            batch_op.add_column(sa.Column("publish_started_at", sa.DateTime(), nullable=True))
        if "publish_attempts" not in contentartifact_columns:
            batch_op.add_column(
                sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0")
            )

    indexes = {index["name"] for index in inspector.get_indexes("automationrun")}
    if "ix_automationrun_type_run_key" not in indexes:
        op.create_index(
            "ix_automationrun_type_run_key",
            "automationrun",
            ["automation_type", "run_key"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes = {index["name"] for index in inspector.get_indexes("automationrun")}
    if "ix_automationrun_type_run_key" in indexes:
        op.drop_index("ix_automationrun_type_run_key", table_name="automationrun")

    contentartifact_columns = {column["name"] for column in inspector.get_columns("contentartifact")}
    with op.batch_alter_table("contentartifact") as batch_op:
        if "publish_attempts" in contentartifact_columns:
            batch_op.drop_column("publish_attempts")
        if "publish_started_at" in contentartifact_columns:
            batch_op.drop_column("publish_started_at")
        if "claimed_by" in contentartifact_columns:
            batch_op.drop_column("claimed_by")
