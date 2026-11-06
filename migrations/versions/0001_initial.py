"""Initial nine application tables; frozen schema snapshot."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email_normalized", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="user"),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("email_normalized"),
        sa.CheckConstraint("role IN ('user','admin')", name="users_role"),
        sa.CheckConstraint("status IN ('active','disabled')", name="users_status"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["family_id"], ["refresh_tokens.id"], deferrable=True, initially="DEFERRED"
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["refresh_tokens.id"]),
        sa.UniqueConstraint("token_hash"),
        sa.UniqueConstraint("parent_id"),
    )
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('active','disabled')", name="collections_status"),
    )
    op.create_table(
        "images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_item_key", sa.Text(), nullable=False),
        sa.Column("latest_input_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lifecycle", sa.Text(), nullable=False, server_default="active"),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("desired_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"]),
        sa.UniqueConstraint("source_id", "source_item_key"),
        sa.CheckConstraint("lifecycle IN ('active','deleted')", name="images_lifecycle"),
        sa.CheckConstraint("desired_version > 0 AND metadata_revision > 0", name="images_versions"),
    )
    op.create_table(
        "image_versions",
        sa.Column("image_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("input_revision", sa.Integer(), nullable=False),
        sa.Column("input_payload_hash", sa.Text(), nullable=False),
        sa.Column("source_config_ref", sa.Text(), nullable=False),
        sa.Column("source_config_hash", sa.Text(), nullable=False),
        sa.Column("source_object_version", sa.Text(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("thumbnail_key", sa.Text(), nullable=True),
        sa.Column("metadata_snapshot_key", sa.Text(), nullable=True),
        sa.Column("metadata_snapshot_hash", sa.Text(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("processing_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "index_state", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("image_id", "version"),
        sa.ForeignKeyConstraint(["image_id"], ["images.id"]),
        sa.CheckConstraint("version > 0 AND input_revision > 0", name="image_versions_positive"),
        sa.CheckConstraint("byte_size IS NULL OR byte_size > 0", name="image_versions_size"),
    )
    op.create_table(
        "search_configs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.Text(), nullable=False, server_default="building"),
        sa.Column(
            "encoder_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "vector_index",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "keyword_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "graph_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "fusion_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "reranker_config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "failure_policy",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_config_ref", sa.Text(), nullable=True),
        sa.Column("source_config_hash", sa.Text(), nullable=True),
        sa.Column("graph_revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("graph_manifest_key", sa.Text(), nullable=True),
        sa.Column("graph_manifest_hash", sa.Text(), nullable=True),
        sa.Column(
            "maintenance", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('building','validating','active','retired','failed')",
            name="search_configs_status",
        ),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("image_id", sa.Uuid(), nullable=True),
        sa.Column("content_version", sa.Integer(), nullable=True),
        sa.Column("config_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=True),
        sa.Column("target_generation", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("request_hash", sa.Text(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "depends_on", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["parent_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(
            ["image_id", "content_version"], ["image_versions.image_id", "image_versions.version"]
        ),
        sa.ForeignKeyConstraint(["config_id"], ["search_configs.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.UniqueConstraint("dedupe_key"),
        sa.CheckConstraint(
            "status IN ('pending','running','retry_wait','succeeded','failed',"
            "'superseded','cancelled','skipped')",
            name="jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="jobs_attempts"),
    )
    op.create_table(
        "search_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("owner_key_hash", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.Text(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column(
            "filters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("config_id", sa.Uuid(), nullable=False),
        sa.Column("graph_revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "hard_graph_constraints",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "query_plan", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "items", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("degradation_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["config_id"], ["search_configs.id"]),
        sa.CheckConstraint(
            "jsonb_typeof(items) = 'array' AND jsonb_array_length(items) <= 200",
            name="search_sessions_items",
        ),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column(
            "safe_context",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
    )
    op.create_index(
        "uq_search_configs_active",
        "search_configs",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_jobs_ready", "jobs", ["status", "next_attempt_at"], unique=False)
    op.create_index("ix_jobs_parent", "jobs", ["parent_id", "type", "status"], unique=False)
    op.create_index("ix_jobs_lease", "jobs", ["lease_until"], unique=False)
    op.create_index("ix_refresh_family", "refresh_tokens", ["family_id"], unique=False)
    op.create_index("ix_refresh_user", "refresh_tokens", ["user_id"], unique=False)
    op.create_index("ix_sessions_expiry", "search_sessions", ["expires_at"], unique=False)
    op.create_index("ix_images_lifecycle", "images", ["collection_id", "lifecycle"], unique=False)
    op.create_foreign_key(
        "fk_images_current_version",
        "images",
        "image_versions",
        ["id", "current_version"],
        ["image_id", "version"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade():
    op.drop_constraint("fk_images_current_version", "images", type_="foreignkey")
    op.drop_table("audit_events")
    op.drop_table("search_sessions")
    op.drop_table("jobs")
    op.drop_table("search_configs")
    op.drop_table("image_versions")
    op.drop_table("images")
    op.drop_table("collections")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
