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


# def upgrade():
#     op.add_column('secret',
#                   sa.Column('secret', sa.String(length=512), nullable=True))

#     import nacl.secret
#     import nacl.utils
#     from inbox.ignition import engine, engine_manager
#     from inbox.models.session import session_scope
#     from inbox.config import config

#     print engine_manager.engines
#     _engine = engine_manager.engines[0]
#     Base = sa.ext.declarative.declarative_base()
#     Base.metadata.reflect(_engine)

#     key = config.get_required('SECRET_ENCRYPTION_KEY')

#     class Secret(Base):
#         __table__ = Base.metadata.tables['secret']

#     with session_scope(0, versioned=False) as db_session:
#         secrets = db_session.query(Secret).filter(
#             Secret.encryption_scheme == 0,
#             Secret._secret.isnot(None)).order_by(Secret.id).all()

#         for s in secrets:
#             unencrypted = s._secret

#             nonce = nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)

#             s.secret = nacl.secret.SecretBox(
#                 key=key,
#                 encoder=nacl.encoding.HexEncoder
#             ).encrypt(
#                 plaintext=unencrypted,
#                 nonce=nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)
#             )

#             # Picked arbitrarily
#             # s.acl_id = 0
#             # s.type = 0

#             db_session.add(s)

#         db_session.commit()

#     op.drop_column('secret', '_secret')

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

    class GenericAccount(Base):
        __table__ = Base.metadata.tables['genericaccount']

    with session_scope(shard_id, versioned=False) as db_session:
        secrets = db_session.query(Secret).filter(
            Secret._secret.isnot(None),
            Secret.encryption_scheme == 0).all()

        # Join on the genericaccount and optionally easaccount tables to
        # determine which secrets should have type 'password'.
        generic_query = db_session.query(Secret.id).join(
            GenericAccount, Secret.id == GenericAccount.password_id)
        password_secrets = [id_ for id_, in generic_query]
        if engine.has_table('easaccount'):
            class EASAccount(Base):
                __table__ = Base.metadata.tables['easaccount']

            eas_query = db_session.query(Secret.id).join(
                EASAccount).filter(Secret.id == EASAccount.password_id)
            password_secrets.extend([id_ for id_, in eas_query])

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

            if s.id in password_secrets:
                s.type = 'password'
            else:
                s.type = 'token'

            db_session.add(s)

        db_session.commit()


def downgrade():
    pass
