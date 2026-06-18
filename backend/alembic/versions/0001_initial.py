"""initial

Revision ID: 0001_initial
Revises: 
Create Date: 2026-06-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'files',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=64), nullable=True),
        sa.Column('path', sa.String(length=1024), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), nullable=True),
        sa.Column('size', sa.Integer(), nullable=True),
    )

    op.create_table(
        'analyses',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('file_id', sa.Integer(), sa.ForeignKey('files.id'), nullable=True),
        sa.Column('analysis_id', sa.String(length=64), nullable=True, unique=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('full_result_path', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('is_free', sa.Boolean(), nullable=True),
    )

    op.create_table(
        'unlock_codes',
        sa.Column('code', sa.String(length=64), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('email', sa.String(length=256), nullable=True),
        sa.Column('order_id', sa.String(length=64), nullable=True),
        sa.Column('is_multi_use', sa.Boolean(), nullable=True),
    )

    op.create_table(
        'orders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.String(length=128), nullable=True, unique=True),
        sa.Column('email', sa.String(length=256), nullable=True),
        sa.Column('variant_name', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('orders')
    op.drop_table('unlock_codes')
    op.drop_table('analyses')
    op.drop_table('files')
