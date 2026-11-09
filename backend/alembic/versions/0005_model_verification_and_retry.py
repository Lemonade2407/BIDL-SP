"""Model verification metadata and batch retry attempts."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("model_version") as batch:
        batch.add_column(sa.Column("regression", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("metrics_source", sa.String(length=16), nullable=False, server_default="registration")
        )
        batch.add_column(sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("evaluation_job_id", sa.String(length=36), nullable=True))
    with op.batch_alter_table("inference_task") as batch:
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))


def downgrade():
    with op.batch_alter_table("inference_task") as batch:
        batch.drop_column("attempt")
    with op.batch_alter_table("model_version") as batch:
        batch.drop_column("evaluation_job_id")
        batch.drop_column("evaluated_at")
        batch.drop_column("metrics_source")
        batch.drop_column("regression")
