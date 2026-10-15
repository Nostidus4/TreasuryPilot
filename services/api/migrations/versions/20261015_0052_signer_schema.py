"""add the isolated signer nonce and attestation-use store

Revision ID: 20261015_0052
Revises: 20261015_0051
Create Date: 2026-10-15 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261015_0052"
down_revision: str | None = "20261015_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The application connects as this role. Its privileges are limited to the signer schema;
    # services using the normal app role cannot write signer state.
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'treasurypilot_signer') THEN "
        "CREATE ROLE treasurypilot_signer NOLOGIN; "
        "END IF; END $$"
    )
    # The application role used by the signer must be able to SET ROLE after startup. When
    # migrations and the signer share a DB login this provisions that membership automatically.
    op.execute("GRANT treasurypilot_signer TO CURRENT_USER")
    op.execute("CREATE SCHEMA signer AUTHORIZATION treasurypilot_signer")
    op.execute(
        "CREATE TABLE signer.nonces ("
        "address bytea PRIMARY KEY CHECK (octet_length(address) = 20), "
        "next_nonce numeric(78, 0) NOT NULL CHECK (next_nonce >= 0), "
        "updated_at timestamptz NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE TABLE signer.nonce_bindings ("
        "nonce numeric(78, 0) PRIMARY KEY CHECK (nonce >= 0), "
        "plan_hash bytea NOT NULL CHECK (octet_length(plan_hash) = 32), "
        "first_used_at timestamptz NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE TABLE signer.attestation_uses ("
        "nonce numeric(78, 0) NOT NULL REFERENCES signer.nonce_bindings(nonce) ON DELETE RESTRICT, "
        "plan_hash bytea NOT NULL CHECK (octet_length(plan_hash) = 32), "
        "step_id bytea NOT NULL CHECK (octet_length(step_id) = 32), "
        "payload_hash bytea NOT NULL CHECK (octet_length(payload_hash) = 32), "
        "executor bytea NOT NULL CHECK (octet_length(executor) = 20), "
        "transaction_nonce numeric(78, 0) NOT NULL CHECK (transaction_nonce >= 0), "
        "first_signed_at timestamptz NOT NULL DEFAULT now(), "
        "PRIMARY KEY (nonce, step_id))"
    )
    op.execute("REVOKE ALL ON SCHEMA signer FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA signer FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA signer TO treasurypilot_signer")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON signer.nonces, signer.nonce_bindings, "
        "signer.attestation_uses TO treasurypilot_signer"
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA signer CASCADE")
    op.execute("REVOKE treasurypilot_signer FROM CURRENT_USER")
    op.execute("DROP ROLE treasurypilot_signer")
