"""add topic generation fields

Revision ID: 20260528_0007
Revises: 20260528_0006
Create Date: 2026-05-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260528_0007"
down_revision: Union[str, None] = "20260528_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("topic", sa.Column("secondary_keyword", sa.String(), nullable=True))
    op.add_column("topic", sa.Column("secondary_keywords", sa.JSON(), nullable=True))
    op.add_column("topic", sa.Column("target_audience", sa.String(), nullable=True))
    op.add_column("topic", sa.Column("article_type", sa.String(), nullable=True))
    op.add_column("topic", sa.Column("content_focus", sa.String(), nullable=True))
    op.add_column("topic", sa.Column("scenes", sa.JSON(), nullable=True))
    op.add_column("topic", sa.Column("target_url", sa.String(), nullable=True))
    op.add_column("topic", sa.Column("brand_name", sa.String(), nullable=True))
    op.add_column("topic", sa.Column("site", sa.String(), nullable=True))
    op.add_column("topic", sa.Column("language", sa.String(), nullable=True))
    op.add_column("topic", sa.Column("extra_rules", sa.String(), nullable=True))
    op.execute("UPDATE topic SET secondary_keywords = '[]' WHERE secondary_keywords IS NULL")
    op.execute("UPDATE topic SET scenes = '[]' WHERE scenes IS NULL")


def downgrade() -> None:
    op.drop_column("topic", "extra_rules")
    op.drop_column("topic", "language")
    op.drop_column("topic", "site")
    op.drop_column("topic", "brand_name")
    op.drop_column("topic", "target_url")
    op.drop_column("topic", "scenes")
    op.drop_column("topic", "content_focus")
    op.drop_column("topic", "article_type")
    op.drop_column("topic", "target_audience")
    op.drop_column("topic", "secondary_keywords")
    op.drop_column("topic", "secondary_keyword")
