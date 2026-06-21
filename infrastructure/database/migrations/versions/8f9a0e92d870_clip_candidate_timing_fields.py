"""clip_candidate_timing_fields

Revision ID: 8f9a0e92d870
Revises: 9c9cb49f2472
Create Date: 2026-06-09 14:12:20.479397
"""
from __future__ import annotations
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '8f9a0e92d870'
down_revision: Union[str, None] = '9c9cb49f2472'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns (simple ADD COLUMN, supported by SQLite)
    op.add_column('clip_candidates', sa.Column('source_file_id', sa.Integer(), nullable=True))
    op.add_column('clip_candidates', sa.Column('start_s', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('end_s', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('duration_s', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('source_filename', sa.String(length=512), nullable=True))
    op.add_column('clip_candidates', sa.Column('sharpness', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('brightness', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('camera_shake', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('camera_motion_type', sa.String(length=32), nullable=True))
    op.add_column('clip_candidates', sa.Column('has_face', sa.Boolean(), nullable=True))
    op.add_column('clip_candidates', sa.Column('has_person', sa.Boolean(), nullable=True))
    op.add_column('clip_candidates', sa.Column('scene_tags', sa.JSON(), nullable=True))
    op.add_column('clip_candidates', sa.Column('is_duplicate', sa.Boolean(), nullable=True))
    op.add_column('clip_candidates', sa.Column('reject_reason', sa.Text(), nullable=True))
    # NOTE: SQLite does not support ALTER COLUMN to drop NOT NULL.
    # scene_id nullable constraint change is handled via batch migration.
    with op.batch_alter_table('clip_candidates', recreate='always') as batch_op:
        batch_op.alter_column('scene_id', existing_type=sa.INTEGER(), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('clip_candidates', recreate='always') as batch_op:
        batch_op.alter_column('scene_id', existing_type=sa.INTEGER(), nullable=False)
    op.drop_column('clip_candidates', 'reject_reason')
    op.drop_column('clip_candidates', 'is_duplicate')
    op.drop_column('clip_candidates', 'scene_tags')
    op.drop_column('clip_candidates', 'has_person')
    op.drop_column('clip_candidates', 'has_face')
    op.drop_column('clip_candidates', 'camera_motion_type')
    op.drop_column('clip_candidates', 'camera_shake')
    op.drop_column('clip_candidates', 'brightness')
    op.drop_column('clip_candidates', 'sharpness')
    op.drop_column('clip_candidates', 'source_filename')
    op.drop_column('clip_candidates', 'duration_s')
    op.drop_column('clip_candidates', 'end_s')
    op.drop_column('clip_candidates', 'start_s')
    op.drop_column('clip_candidates', 'source_file_id')
