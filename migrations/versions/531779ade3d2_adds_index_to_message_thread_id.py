"""adds index to message.thread_id

Revision ID: 531779ade3d2
Revises: 780b1dabd51
Create Date: 2018-02-06 15:45:59.965603

"""

# revision identifiers, used by Alembic.
revision = '531779ade3d2'
down_revision = '780b1dabd51'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

def upgrade():
    conn = op.get_bind()
    conn.execute(text("CREATE INDEX `ix_message_thread_id` ON `message` (`thread_id`)"))

def downgrade():
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE message DROP INDEX `ix_message_thread_id`"))
