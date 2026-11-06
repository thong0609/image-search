"""Require jobs.image_id to reference an image even without a content version."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_foreign_key("fk_jobs_image_id", "jobs", "images", ["image_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_jobs_image_id", "jobs", type_="foreignkey")
