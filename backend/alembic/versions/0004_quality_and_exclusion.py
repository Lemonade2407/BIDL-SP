"""Image exclusion flags, dual annotation and consistency tracking."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("image") as batch:
        batch.add_column(sa.Column("exclude_reason", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("excluded_by", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_image_excluded_by", "app_user", ["excluded_by"], ["id"], ondelete="RESTRICT"
        )
    with op.batch_alter_table("annotation_task") as batch:
        batch.add_column(
            sa.Column("required_annotators", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("consistency", sa.JSON(), nullable=True))
    op.create_table(
        "annotation_assignment",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("annotator_id", sa.String(length=36), nullable=False),
        sa.Column("annotation_id", sa.String(length=36)),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="in_progress"),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["annotation_task.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["annotator_id"], ["app_user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["annotation_id"], ["annotation.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("task_id", "annotator_id", name="uq_task_annotator"),
    )
    op.create_index("ix_annotation_assignment_task_id", "annotation_assignment", ["task_id"])
    op.create_index("ix_annotation_assignment_created_at", "annotation_assignment", ["created_at"])


def downgrade():
    op.drop_index("ix_annotation_assignment_created_at", table_name="annotation_assignment")
    op.drop_index("ix_annotation_assignment_task_id", table_name="annotation_assignment")
    op.drop_table("annotation_assignment")
    with op.batch_alter_table("annotation_task") as batch:
        batch.drop_column("consistency")
        batch.drop_column("required_annotators")
    with op.batch_alter_table("image") as batch:
        batch.drop_constraint("fk_image_excluded_by", type_="foreignkey")
        batch.drop_column("excluded_at")
        batch.drop_column("excluded_by")
        batch.drop_column("exclude_reason")
