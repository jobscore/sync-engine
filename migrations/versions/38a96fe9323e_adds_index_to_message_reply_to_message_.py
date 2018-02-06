"""adds index to message.reply_to_message_id

Revision ID: 38a96fe9323e
Revises: 531779ade3d2
Create Date: 2018-02-06 15:52:34.142593

"""

# revision identifiers, used by Alembic.
revision = '38a96fe9323e'
down_revision = '531779ade3d2'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

def upgrade():
    conn = op.get_bind()
    conn.execute(text("CREATE INDEX `ix_message_reply_to_message_id` ON `message` (`reply_to_message_id`)"))

def downgrade():
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE message DROP INDEX `ix_message_reply_to_message_id`"))
