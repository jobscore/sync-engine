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


def notify_message_created(message, db_session):
    from inbox.models import Namespace

    log.info('Message prepared to enqueue',
             message_id=message.public_id)
    namespace = db_session.query(Namespace).get(message.namespace_id)
    job = {
        'class': 'ProcessMessageQueue',
        'args': [
            'nylas_notification',
            namespace.public_id,
            message.public_id
        ]
    }

    nylas_queue = get_nylas_queue(db_session, message)
    redis_client = get_redis_client()
    try:
        pipeline = redis_client.pipeline()
        pipeline.sadd('resque:queues', nylas_queue)
        pipeline.lpush('resque:queue:' + nylas_queue, json.dumps(job))
        log.info('Message enqueued',
                 message_id=message.public_id,
                 namespace_id=message.namespace_id,
                 job_details=job)
        pipeline.execute()
        pipeline.reset()
    except Exception as e:
        log.error('Message not enqueued!',
                  message_id=message.public_id,
                  namespace_id=message.namespace_id,
                  job_details=job,
                  error=e)
        raise e


def get_nylas_queue(db_session, message):
    from inbox.models import Message, Namespace
    account = db_session.query(Namespace) \
                        .get(message.namespace_id) \
                        .account

    if message.received_date < account.created_at:
        return 'nylas_low'
    else:
        return 'nylas_default'


def get_redis_client():
    return StrictRedis(connection_pool=redis_pool)
