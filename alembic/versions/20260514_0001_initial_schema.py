"""initial schema"""

from alembic import op
import sqlalchemy as sa


revision = "20260514_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topic",
        sa.Column("master_topic", sa.String(), nullable=False),
        sa.Column("topic_cluster", sa.String(), nullable=False),
        sa.Column("business_goal", sa.String(), nullable=False),
        sa.Column("target_keyword", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("target_platforms", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("brief", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "distributiontask",
        sa.Column("topic_id", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("task_type", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False),
        sa.Column("angle", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("depends_on", sa.JSON(), nullable=True),
        sa.Column("artifact_id", sa.String(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "contentartifact",
        sa.Column("topic_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("angle", sa.String(), nullable=False),
        sa.Column("artifact_title", sa.String(), nullable=True),
        sa.Column("artifact_summary", sa.String(), nullable=True),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("generation_model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("review_notes", sa.String(), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("claimed_by", sa.String(), nullable=True),
        sa.Column("publish_started_at", sa.DateTime(), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), nullable=False),
        sa.Column("published_url", sa.String(), nullable=True),
        sa.Column("external_publish_id", sa.String(), nullable=True),
        sa.Column("extra_metadata", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "seoasset",
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("topic_id", sa.String(), nullable=False),
        sa.Column("source_platform", sa.String(), nullable=False),
        sa.Column("source_url", sa.String(), nullable=False),
        sa.Column("target_url", sa.String(), nullable=False),
        sa.Column("anchor_text", sa.String(), nullable=False),
        sa.Column("rd_domain", sa.String(), nullable=False),
        sa.Column("indexed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("seoasset")
    op.drop_table("contentartifact")
    op.drop_table("distributiontask")
    op.drop_table("topic")
