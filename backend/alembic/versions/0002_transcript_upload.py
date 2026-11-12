"""transcript upload

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('transcript_asset',
    sa.Column('lesson_id', sa.BigInteger(), nullable=False),
    sa.Column('storage_key', sa.String(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['lesson_id'], ['lesson.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transcript_asset_lesson_id'), 'transcript_asset', ['lesson_id'], unique=False)
    op.add_column('video_asset', sa.Column('transcript_asset_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('video_asset_transcript_asset_id_fkey', 'video_asset', 'transcript_asset', ['transcript_asset_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('video_asset_transcript_asset_id_fkey', 'video_asset', type_='foreignkey')
    op.drop_column('video_asset', 'transcript_asset_id')
    op.drop_index(op.f('ix_transcript_asset_lesson_id'), table_name='transcript_asset')
    op.drop_table('transcript_asset')
