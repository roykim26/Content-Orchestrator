"""add topic note account"""

from alembic import op
import sqlalchemy as sa


revision = "20260522_0004"
down_revision = "20260515_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    topic_columns = {column["name"] for column in inspector.get_columns("topic")}
    with op.batch_alter_table("topic") as batch_op:
        if "note_account" not in topic_columns:
            batch_op.add_column(sa.Column("note_account", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    topic_columns = {column["name"] for column in inspector.get_columns("topic")}
    with op.batch_alter_table("topic") as batch_op:
        if "note_account" in topic_columns:
            batch_op.drop_column("note_account")
