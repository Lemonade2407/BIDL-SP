"""Allow archival without changing frozen content; protect archived members too."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = depends_on = None

FIELDS = (
    "id",
    "dataset_id",
    "version",
    "split_seed",
    "ratios",
    "filter",
    "counts",
    "manifest_key",
    "frozen_at",
    "created_by",
    "created_at",
)


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER dataset_version_immutable ON dataset_version")
        op.execute("""CREATE FUNCTION bidlsp_archive_only() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='UPDATE' AND OLD.status='frozen' AND NEW.status='archived'
             AND (to_jsonb(OLD)-'status'-'updated_at')=(to_jsonb(NEW)-'status'-'updated_at') THEN RETURN NEW; END IF;
          RAISE EXCEPTION 'immutable dataset version';
        END $$""")
        op.execute(
            "CREATE TRIGGER dataset_version_immutable BEFORE UPDATE OR DELETE ON dataset_version FOR EACH ROW WHEN (OLD.status IN ('frozen','archived')) EXECUTE FUNCTION bidlsp_archive_only()"
        )
        op.execute("""CREATE OR REPLACE FUNCTION bidlsp_frozen_item() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP!='INSERT' THEN
            IF EXISTS(SELECT 1 FROM dataset_version WHERE id=OLD.dataset_version_id AND status!='draft') THEN RAISE EXCEPTION 'frozen dataset'; END IF;
          END IF;
          IF TG_OP!='DELETE' THEN
            IF EXISTS(SELECT 1 FROM dataset_version WHERE id=NEW.dataset_version_id AND status!='draft') THEN RAISE EXCEPTION 'frozen dataset'; END IF;
            RETURN NEW;
          END IF;
          RETURN OLD;
        END $$""")
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER dataset_version_no_{action}")
        unchanged = " AND ".join(f'OLD."{field}" IS NEW."{field}"' for field in FIELDS)
        op.execute(
            f"CREATE TRIGGER dataset_version_no_update BEFORE UPDATE ON dataset_version WHEN OLD.status IN ('frozen','archived') AND NOT (OLD.status='frozen' AND NEW.status='archived' AND {unchanged}) BEGIN SELECT RAISE(ABORT, 'immutable version'); END"
        )
        op.execute(
            "CREATE TRIGGER dataset_version_no_delete BEFORE DELETE ON dataset_version WHEN OLD.status IN ('frozen','archived') BEGIN SELECT RAISE(ABORT, 'immutable version'); END"
        )
        for action in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER dataset_item_no_{action}")
            refs = ["NEW"] if action == "insert" else ["OLD"] if action == "delete" else ["OLD", "NEW"]
            checks = " OR ".join(
                f"EXISTS(SELECT 1 FROM dataset_version WHERE id={ref}.dataset_version_id AND status!='draft')"
                for ref in refs
            )
            op.execute(
                f"CREATE TRIGGER dataset_item_no_{action} BEFORE {action.upper()} ON dataset_item WHEN {checks} BEGIN SELECT RAISE(ABORT, 'immutable dataset item'); END"
            )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER dataset_version_immutable ON dataset_version")
        op.execute("DROP FUNCTION bidlsp_archive_only()")
        op.execute(
            "CREATE TRIGGER dataset_version_immutable BEFORE UPDATE OR DELETE ON dataset_version FOR EACH ROW WHEN (OLD.status='frozen') EXECUTE FUNCTION bidlsp_deny_mutation()"
        )
    else:
        for action in ("update", "delete"):
            op.execute(f"DROP TRIGGER dataset_version_no_{action}")
            op.execute(
                f"CREATE TRIGGER dataset_version_no_{action} BEFORE {action.upper()} ON dataset_version WHEN OLD.status='frozen' BEGIN SELECT RAISE(ABORT, 'immutable version'); END"
            )
