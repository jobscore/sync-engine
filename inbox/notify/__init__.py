import json
from redis import StrictRedis, BlockingConnectionPool
from inbox.config import config
from nylas.logging import get_logger
log = get_logger()

REDIS_HOSTNAME = config.get('NOTIFY_QUEUE_REDIS_HOSTNAME')
REDIS_PORT = int(config.get('NOTIFY_QUEUE_REDIS_PORT', 6379))
REDIS_DB = int(config.get('NOTIFY_QUEUE_REDIS_DB'))

MAX_CONNECTIONS = 40

redis_pool = BlockingConnectionPool(
    max_connections=MAX_CONNECTIONS,
    host=REDIS_HOSTNAME, port=REDIS_PORT, db=REDIS_DB)


def notify_transaction(transaction, db_session):
    from inbox.models import Namespace

    # We're only interested in "message created" events
    if transaction.command != 'insert' or transaction.object_type != 'message':
        return

    log.info('Transaction prepared to enqueue',
             transaction_id=transaction.record_id)
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

    try:
        pipeline = redis_client.pipeline()
        pipeline.sadd('resque:queues', 'nylas_default')
        pipeline.lpush('resque:queue:nylas_default', json.dumps(job))
        log.info('Transaction enqueued',
                 transaction_id=transaction.record_id,
                 namespace_id=transaction.namespace_id,
                 job_details=job)
        pipeline.execute()
        pipeline.reset()
    except Exception as e:
        log.error('Transaction not enqueued!',
                  transaction_id=transaction.record_id,
                  namespace_id=transaction.namespace_id,
                  job_details=job,
                  error=e)
        raise e
