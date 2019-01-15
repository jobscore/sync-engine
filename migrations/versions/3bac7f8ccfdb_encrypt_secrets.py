"""encrypt_secrets

Revision ID: 3bac7f8ccfdb
Revises: 291237183b82
Create Date: 2019-01-14 17:35:58.872052

"""

# revision identifiers, used by Alembic.
revision = '3bac7f8ccfdb'
down_revision = '291237183b82'

from alembic import op, context
import sqlalchemy as sa


def upgrade():
    from inbox.config import config
    import nacl.secret
    import nacl.utils
    from inbox.ignition import engine_manager
    from inbox.models.session import session_scope

    shard_id = int(context.get_x_argument(as_dictionary=True).get('shard_id'))
    engine = engine_manager.engines[shard_id]
    Base = sa.ext.declarative.declarative_base()
    Base.metadata.reflect(engine)

    class Secret(Base):
        __table__ = Base.metadata.tables['secret']

    with session_scope(shard_id, versioned=False) as db_session:
        secrets = db_session.query(Secret).filter(
            Secret._secret.isnot(None),
            Secret.encryption_scheme == 0).all()

        for s in secrets:
            plain = s._secret.encode('utf-8') if isinstance(s._secret, unicode) \
                else s._secret
            if config.get_required('ENCRYPT_SECRETS'):

                s._secret = nacl.secret.SecretBox(
                    key=config.get_required('SECRET_ENCRYPTION_KEY'),
                    encoder=nacl.encoding.HexEncoder
                ).encrypt(
                    plaintext=plain,
                    nonce=nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE))

                # 1 is EncryptionScheme.SECRETBOX_WITH_STATIC_KEY
                s.encryption_scheme = 1
            else:
                s._secret = plain

            db_session.add(s)

        db_session.commit()


def downgrade():
    pass
