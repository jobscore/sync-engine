"""Index for messagecontactassociation

Revision ID: 291237183b82
Revises: 38a96fe9323e
Create Date: 2018-07-30 18:57:23.934680

"""

# revision identifiers, used by Alembic.
revision = '291237183b82'
down_revision = '38a96fe9323e'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

def upgrade():
    conn = op.get_bind()
    conn.execute(text("CREATE INDEX ix_messagecontactassociation_contact_id"
                      " USING BTREE ON messagecontactassociation (contact_id)"))

def downgrade():
    conn = op.get_bind()
    conn.execute(text("DROP INDEX ix_messagecontactassociation_contact_id"))
