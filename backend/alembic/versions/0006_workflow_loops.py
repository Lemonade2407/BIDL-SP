"""Notifications, return paths and immutable report corrections."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = depends_on = None

ADDITIONS = {
    "annotation_task": [("overdue_at", sa.DateTime(timezone=True))],
    "screen_task": [
        ("overdue_at", sa.DateTime(timezone=True)),
        ("returned_by", sa.String(36)),
        ("returned_at", sa.DateTime(timezone=True)),
        ("return_reason", sa.String(512)),
        ("follow_up", sa.String(16)),
        ("return_count", sa.Integer()),
        ("retry_task_ids", sa.JSON()),
    ],
    "study_review": [("return_action", sa.String(16))],
    "report": [
        ("previous_report_id", sa.String(36)),
        ("rejected_at", sa.DateTime(timezone=True)),
        ("voided_at", sa.DateTime(timezone=True)),
        ("voided_by", sa.String(36)),
        ("void_reason", sa.String(512)),
    ],
}


def drop_report_triggers():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER report_immutable ON report")
    else:
        op.execute("DROP TRIGGER report_no_update")
        op.execute("DROP TRIGGER report_no_delete")


def upgrade():
    drop_report_triggers()
    for table, columns in ADDITIONS.items():
        for name, kind in columns:
            # Additive migration: existing records and signed PDF keys are retained.
            args = []
            if name in ("returned_by", "voided_by", "previous_report_id"):
                target = "report" if name == "previous_report_id" else "app_user"
                if op.get_bind().dialect.name == "sqlite":
                    op.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} VARCHAR(36) REFERENCES {target}(id) ON DELETE RESTRICT"
                    )
                    continue
                args = [sa.ForeignKey(target + ".id", name=f"fk_{table}_{name}", ondelete="RESTRICT")]
            op.add_column(
                table,
                sa.Column(
                    name,
                    kind,
                    *args,
                    nullable=name != "return_count",
                    server_default="0" if name == "return_count" else None,
                ),
            )
    op.create_table(
        "notification",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("object_type", sa.String(32), nullable=False),
        sa.Column("object_id", sa.String(36), nullable=False),
        sa.Column("link", sa.String(512), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notification_recipient_event"),
    )
    op.create_index("ix_notification_user_id", "notification", ["user_id"])
    op.create_index("ix_notification_created_at", "notification", ["created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION bidlsp_report_correction() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='UPDATE' AND OLD.status='signed' AND NEW.status='voided'
             AND NEW.voided_by IS NOT NULL AND NEW.voided_at IS NOT NULL
             AND length(trim(NEW.void_reason))>0
             AND (to_jsonb(OLD)-ARRAY['status','updated_at','voided_by','voided_at','void_reason'])
               = (to_jsonb(NEW)-ARRAY['status','updated_at','voided_by','voided_at','void_reason'])
             THEN RETURN NEW; END IF;
          RAISE EXCEPTION 'immutable report';
        END $$""")
        op.execute(
            "CREATE TRIGGER report_immutable BEFORE UPDATE OR DELETE ON report FOR EACH ROW WHEN (OLD.status IN ('signed','rejected','voided')) EXECUTE FUNCTION bidlsp_report_correction()"
        )
        op.execute("""CREATE FUNCTION bidlsp_notification_read_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='UPDATE' AND (to_jsonb(OLD)-ARRAY['read_at','updated_at'])=(to_jsonb(NEW)-ARRAY['read_at','updated_at']) THEN RETURN NEW; END IF;
          RAISE EXCEPTION 'immutable notification';
        END $$""")
        op.execute(
            "CREATE TRIGGER notification_immutable BEFORE UPDATE OR DELETE ON notification FOR EACH ROW EXECUTE FUNCTION bidlsp_notification_read_only()"
        )
    else:
        allowed = {"status", "updated_at", "voided_by", "voided_at", "void_reason"}
        fields = [
            c["name"] for c in sa.inspect(op.get_bind()).get_columns("report") if c["name"] not in allowed
        ]
        same = " AND ".join(f'OLD."{f}" IS NEW."{f}"' for f in fields)
        op.execute(f"""CREATE TRIGGER report_no_update BEFORE UPDATE ON report
          WHEN OLD.status IN ('signed','rejected','voided') AND NOT (
            OLD.status='signed' AND NEW.status='voided' AND NEW.voided_by IS NOT NULL
            AND NEW.voided_at IS NOT NULL AND coalesce(length(trim(NEW.void_reason)),0)>0 AND {same})
          BEGIN SELECT RAISE(ABORT, 'immutable report'); END""")
        op.execute(
            "CREATE TRIGGER report_no_delete BEFORE DELETE ON report WHEN OLD.status IN ('signed','rejected','voided') BEGIN SELECT RAISE(ABORT, 'immutable report'); END"
        )
        fields = [
            c["name"]
            for c in sa.inspect(op.get_bind()).get_columns("notification")
            if c["name"] not in {"read_at", "updated_at"}
        ]
        same = " AND ".join(f'OLD."{f}" IS NEW."{f}"' for f in fields)
        op.execute(
            f"CREATE TRIGGER notification_no_update BEFORE UPDATE ON notification WHEN NOT ({same}) BEGIN SELECT RAISE(ABORT, 'immutable notification'); END"
        )
        op.execute(
            "CREATE TRIGGER notification_no_delete BEFORE DELETE ON notification BEGIN SELECT RAISE(ABORT, 'immutable notification'); END"
        )


def downgrade():
    drop_report_triggers()
    op.drop_table("notification")
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("DROP FUNCTION bidlsp_report_correction()")
        op.execute("DROP FUNCTION bidlsp_notification_read_only()")
    for table, columns in reversed(list(ADDITIONS.items())):
        for name, _ in reversed(columns):
            op.drop_column(table, name)
    if postgres:
        op.execute(
            "CREATE TRIGGER report_immutable BEFORE UPDATE OR DELETE ON report FOR EACH ROW WHEN (OLD.status='signed') EXECUTE FUNCTION bidlsp_deny_mutation()"
        )
    else:
        for action in ("update", "delete"):
            op.execute(
                f"CREATE TRIGGER report_no_{action} BEFORE {action.upper()} ON report WHEN OLD.status='signed' BEGIN SELECT RAISE(ABORT, 'immutable report'); END"
            )
