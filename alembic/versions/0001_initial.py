"""initial schema — users, generations, payments

Revision ID: 0001
Revises:
Create Date: 2026-05-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# native_enum=False — порто-кросс-совместимо: VARCHAR + CHECK на SQLite и Postgres
_generation_status = sa.Enum(
    "pending", "generated", "published", "failed",
    name="generationstatus",
    native_enum=False,
)
_payment_status = sa.Enum(
    "pending", "completed", "failed",
    name="paymentstatus",
    native_enum=False,
)


def upgrade() -> None:
    # ── users ───────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_username", sa.String(64), nullable=True),
        sa.Column("telegram_first_name", sa.String(128), nullable=True),
        sa.Column("linkedin_person_urn", sa.String(128), nullable=True),
        sa.Column("linkedin_access_token", sa.Text(), nullable=True),
        sa.Column("linkedin_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("oauth_state", sa.String(64), nullable=True),
        sa.Column("interests_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("daily_notifications", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notification_time", sa.String(5), nullable=False, server_default="18:00"),
        sa.Column("notification_days_json", sa.Text(), nullable=False, server_default="[0,1,2,3,4,5,6]"),
        sa.Column("balance_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("ix_users_oauth_state", "users", ["oauth_state"])

    # ── generations ─────────────────────────────────────────────────────────
    op.create_table(
        "generations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("post_text", sa.Text(), nullable=True),
        sa.Column("image_prompts_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("image_paths_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("linkedin_post_id", sa.String(128), nullable=True),
        sa.Column("cost_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", _generation_status, nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_generations_user_id", "generations", ["user_id"])

    # ── payments ────────────────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(32), nullable=False, server_default="mock"),
        sa.Column("status", _payment_status, nullable=False, server_default="completed"),
        sa.Column("note", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_payments_user_id", "payments", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_table("payments")

    op.drop_index("ix_generations_user_id", table_name="generations")
    op.drop_table("generations")

    op.drop_index("ix_users_oauth_state", table_name="users")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
