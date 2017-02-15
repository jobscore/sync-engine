import sys
import urllib
import requests
import simplejson
from flask import (request, g, Blueprint, make_response, Response)
from flask import jsonify as flask_jsonify
from flask.ext.restful import reqparse
from sqlalchemy import asc, func
from sqlalchemy.orm.exc import NoResultFound

from inbox.models import (Message, Block, Part, Thread, Namespace,
                          Contact, Calendar, Event, Transaction,
                          DataProcessingCache, Category, MessageCategory)
from inbox.models.event import RecurringEvent, RecurringEventOverride
from inbox.models.category import EPOCH
from inbox.models.backends.generic import GenericAccount
from inbox.api.sending import (send_draft, send_raw_mime, send_draft_copy,
                               update_draft_on_send)
from inbox.api.update import update_message, update_thread
from inbox.api.kellogs import APIEncoder
from inbox.api import filtering
from inbox.api.validation import (valid_account, get_attachments, get_calendar,
                                  get_recipients, get_draft, valid_public_id,
                                  valid_event, valid_event_update, timestamp,
                                  bounded_str, view, strict_parse_args,
                                  limit, offset, ValidatableArgument,
                                  strict_bool, validate_draft_recipients,
                                  valid_delta_object_types, valid_display_name,
                                  noop_event_update, valid_category_type,
                                  comma_separated_email_list,
                                  get_sending_draft)
from inbox.config import config
from inbox.contacts.algorithms import (calculate_contact_scores,
                                       calculate_group_scores,
                                       calculate_group_counts, is_stale)
import inbox.contacts.crud
from inbox.contacts.search import ContactSearchClient
from inbox.sendmail.base import (create_message_from_json, update_draft,
                                 delete_draft, create_draft_from_mime,
                                 SendMailException)
from inbox.ignition import engine_manager
from inbox.models.action_log import schedule_action
from inbox.models.session import new_session, session_scope
from inbox.search.base import get_search_client, SearchBackendException
from inbox.transactions import delta_sync
from inbox.api.err import (err, APIException, NotFoundError, InputError,
                           AccountDoesNotExistError, log_exception)
from inbox.events.ical import generate_rsvp, send_rsvp
from inbox.events.util import removed_participants
from inbox.util.blockstore import get_from_blockstore
from inbox.util.misc import imap_folder_path
from inbox.actions.backends.generic import remote_delete_sent
from inbox.crispin import writable_connection_pool
from inbox.auth.gmail import GmailAuthHandler
from inbox.models import Account
from inbox.auth.base import handler_from_provider

app = Blueprint(
    'jobscore_custom_api',
    __name__,
    url_prefix='/c')

app.log_exception = log_exception

@app.before_request
def start():
    request.environ['log_context'] = {
        'endpoint': request.endpoint,
    }
    # g.encoder = APIEncoder(g.namespace.public_id, is_n1=is_n1)
    g.parser = reqparse.RequestParser(argument_class=ValidatableArgument)


@app.errorhandler(APIException)
def handle_input_error(error):
    # these "errors" are normal, so we don't need to save a traceback
    request.environ['log_context']['error'] = error.__class__.__name__
    request.environ['log_context']['error_message'] = error.message
    response = flask_jsonify(message=error.message,
                             type='invalid_request_error')
    response.status_code = error.status_code
    return response


@app.errorhandler(Exception)
def handle_generic_error(error):
    log_exception(sys.exc_info())
    response = flask_jsonify(message=error.message,
                             type='api_error')
    response.status_code = 500
    return response


@app.route('/auth_callback')
def auth_callback():
    g.parser.add_argument('authorization_code', type=bounded_str,
        location='args', required=True)
    g.parser.add_argument('email', required=True, type=bounded_str, location='args')
    g.parser.add_argument('target', type=int, location='args')
    args = strict_parse_args(g.parser, request.args)

    shard = args.get('target', 0) >> 48

    with session_scope(shard) as db_session:
        account = db_session.query(Account).filter_by(email_address=args['email']).first()
        if account is not None:
            return 'Account is already registered', 400

        auth_handler = handler_from_provider('gmail')

        request_args = {
            'client_id': GmailAuthHandler.OAUTH_CLIENT_ID,
            'client_secret': GmailAuthHandler.OAUTH_CLIENT_SECRET,
            'redirect_uri': GmailAuthHandler.OAUTH_REDIRECT_URI,
            'code': args['authorization_code'],
            'grant_type': 'authorization_code'
        }

        headers = {'Content-type': 'application/x-www-form-urlencoded',
                   'Accept': 'text/plain'}

        data = urllib.urlencode(request_args)
        resp_dict = requests.post(auth_handler.OAUTH_ACCESS_TOKEN_URL, data=data, headers=headers).json()

        # import pdb; pdb.set_trace();

        if u'error' in resp_dict:
            return 'Internal error: ' + str(resp_dict['error']), 500

        access_token = resp_dict['access_token']
        validation_dict = auth_handler.validate_token(access_token)
        userinfo_dict = auth_handler._get_user_info(access_token)

        resp_dict.update(validation_dict)
        resp_dict.update(userinfo_dict)
        resp_dict['contacts'] = True
        resp_dict['events'] = True

        auth_info = { 'provider': 'gmail' }
        auth_info.update(resp_dict)

        account = auth_handler.create_account(args['email'], auth_info)
        try:
            if auth_handler.verify_account(account):
                db_session.add(account)
                db_session.commit()
        except NotSupportedError as e:
            return 'Internal error: ' + str(resp_dict['error']), 500

        resp = simplejson.dumps({
            'account_id': account.public_id,
            'namespace_id': account.namespace.public_id
        })

        return make_response( (resp, 201, { 'Content-Type': 'application/json' }))
