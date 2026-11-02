"""Database-side append-only audit and immutable signed/frozen records."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("""CREATE FUNCTION bidlsp_deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'immutable record'; END $$""")
        op.execute(
            "CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION bidlsp_deny_mutation()"
        )
        for table, field, state in (("report", "status", "signed"), ("dataset_version", "status", "frozen")):
            op.execute(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW WHEN (OLD.{field}='{state}') EXECUTE FUNCTION bidlsp_deny_mutation()"
            )
        op.execute("""CREATE FUNCTION bidlsp_frozen_item() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='INSERT' THEN
            IF EXISTS(SELECT 1 FROM dataset_version WHERE id=NEW.dataset_version_id AND status='frozen') THEN RAISE EXCEPTION 'frozen dataset'; END IF;
            RETURN NEW;
          ELSE
            IF EXISTS(SELECT 1 FROM dataset_version WHERE id=OLD.dataset_version_id AND status='frozen') THEN RAISE EXCEPTION 'frozen dataset'; END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
          END IF;
        END $$""")
        op.execute(
            "CREATE TRIGGER dataset_item_immutable BEFORE INSERT OR UPDATE OR DELETE ON dataset_item FOR EACH ROW EXECUTE FUNCTION bidlsp_frozen_item()"
        )
    elif dialect == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER audit_no_{action.lower()} BEFORE {action} ON audit_log BEGIN SELECT RAISE(ABORT, 'immutable audit'); END"
            )
            for table, state in (("report", "signed"), ("dataset_version", "frozen")):
                op.execute(
                    f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} WHEN OLD.status='{state}' BEGIN SELECT RAISE(ABORT, 'immutable record'); END"
                )
        for action in ("INSERT", "UPDATE", "DELETE"):
            ref = "NEW" if action == "INSERT" else "OLD"
            op.execute(
                f"CREATE TRIGGER dataset_item_no_{action.lower()} BEFORE {action} ON dataset_item WHEN EXISTS (SELECT 1 FROM dataset_version WHERE id={ref}.dataset_version_id AND status='frozen') BEGIN SELECT RAISE(ABORT, 'frozen dataset'); END"
            )


def downgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for name, table in (
            ("audit_append_only", "audit_log"),
            ("report_immutable", "report"),
            ("dataset_version_immutable", "dataset_version"),
            ("dataset_item_immutable", "dataset_item"),
        ):
            op.execute(f"DROP TRIGGER {name} ON {table}")
        op.execute("DROP FUNCTION bidlsp_deny_mutation()")
        op.execute("DROP FUNCTION bidlsp_frozen_item()")
    elif dialect == "sqlite":
        for table in ("audit", "report", "dataset_version", "dataset_item"):
            for action in ("insert", "update", "delete") if table == "dataset_item" else ("update", "delete"):
                op.execute(f"DROP TRIGGER {table}_no_{action}")
