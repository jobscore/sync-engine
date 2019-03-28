from redis import StrictRedis, BlockingConnectionPool
from inbox.config import config
import json

REDIS_HOSTNAME = config.get('NOTIFY_QUEUE_REDIS_HOSTNAME')
REDIS_DB = int(config.get('NOTIFY_QUEUE_REDIS_DB'))

MAX_CONNECTIONS = 40

redis_pool = BlockingConnectionPool(
    max_connections=MAX_CONNECTIONS,
    host=REDIS_HOSTNAME, port=6379, db=REDIS_DB)

def notify_transaction(transaction, db_session):
    from inbox.models import Namespace

    # We're only interested in "message created" events
    if transaction.command != 'insert' or transaction.object_type != 'message':
        return

    namespace = db_session.query(Namespace).get(transaction.namespace_id)
    redis_client = StrictRedis(connection_pool=redis_pool)
    job = {
        'class': 'ProcessMessageQueue',
        'args': [
            'nylas_notification',
            namespace.public_id,
            transaction.object_public_id
        ]
    }

    pipeline = redis_client.pipeline()
    pipeline.sadd('resque:queues', 'nylas_default')
    pipeline.lpush('resque:queue:nylas_default', json.dumps(job))
    pipeline.execute()
    pipeline.reset()
