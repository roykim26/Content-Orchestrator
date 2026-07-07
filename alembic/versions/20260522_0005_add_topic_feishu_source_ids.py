"""add topic feishu source ids"""

from alembic import op
import sqlalchemy as sa


revision = "20260522_0005"
down_revision = "20260522_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    topic_columns = {column["name"] for column in inspector.get_columns("topic")}
    with op.batch_alter_table("topic") as batch_op:
        if "feishu_record_id" not in topic_columns:
            batch_op.add_column(sa.Column("feishu_record_id", sa.String(), nullable=True))
        if "feishu_topic_id" not in topic_columns:
            batch_op.add_column(sa.Column("feishu_topic_id", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    topic_columns = {column["name"] for column in inspector.get_columns("topic")}
    with op.batch_alter_table("topic") as batch_op:
        if "feishu_topic_id" in topic_columns:
            batch_op.drop_column("feishu_topic_id")
        if "feishu_record_id" in topic_columns:
            batch_op.drop_column("feishu_record_id")
