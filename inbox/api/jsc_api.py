import sys
import urllib
import requests
import simplejson
from flask import request, g, Blueprint, make_response
from flask import jsonify as flask_jsonify
from flask.ext.restful import reqparse
from inbox.api.validation import bounded_str, strict_parse_args, ValidatableArgument
from inbox.basicauth import NotSupportedError, ValidationError
from inbox.models.session import session_scope
from inbox.api.err import APIException, InputError, log_exception
from inbox.auth.gmail import GmailAuthHandler
from inbox.models import Account
from inbox.auth.base import handler_from_provider
from inbox.util.url import provider_from_address
from inbox.providers import providers

app = Blueprint(
    'jobscore_custom_api',
    __name__,
    url_prefix='/c')

app.log_exception = log_exception

DEFAULT_IMAP_PORT = 143
DEFAULT_IMAP_SSL_PORT = 993
DEFAULT_SMTP_PORT = 25
DEFAULT_SMTP_SSL_PORT = 465

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

        updating_account = False
        if account is not None:
            updating_account = True

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

        if u'error' in resp_dict:
            raise APIException('Internal error: ' + str(resp_dict['error']))

        access_token = resp_dict['access_token']
        validation_dict = auth_handler.validate_token(access_token)
        userinfo_dict = auth_handler._get_user_info(access_token)

        if userinfo_dict['email'] != args['email']:
            raise InputError('Email mismatch')

        resp_dict.update(validation_dict)
        resp_dict.update(userinfo_dict)
        resp_dict['contacts'] = True
        resp_dict['events'] = True

        auth_info = { 'provider': 'gmail' }
        auth_info.update(resp_dict)

        if updating_account:
            account.auth_handler.update_account(account, auth_info)
        else:
            account = auth_handler.create_account(args['email'], auth_info)

        try:
            if auth_handler.verify_account(account):
                db_session.add(account)
                db_session.commit()
        except NotSupportedError:
            raise APIException('Internal error: ' + str(resp_dict['error']))

        resp = simplejson.dumps({
            'account_id': account.public_id,
            'namespace_id': account.namespace.public_id
        })

        return make_response( (resp, 201, { 'Content-Type': 'application/json' }))

@app.route('/create_account', methods=['POST'])
def create_account():
    g.parser.add_argument('target', type=int, location='args')
    g.parser.add_argument('email', required=True, type=bounded_str, location='form')
    g.parser.add_argument('smtp_host', required=True, type=bounded_str, location='form')
    g.parser.add_argument('smtp_port', type=int, location='form')
    g.parser.add_argument('smtp_username', required=True, type=bounded_str, location='form')
    g.parser.add_argument('smtp_password', required=True, type=bounded_str, location='form')
    g.parser.add_argument('imap_host', required=True, type=bounded_str, location='form')
    g.parser.add_argument('imap_port', type=int, location='form')
    g.parser.add_argument('imap_username', required=True, type=bounded_str, location='form')
    g.parser.add_argument('imap_password', required=True, type=bounded_str, location='form')
    g.parser.add_argument('ssl_required', required=True, type=bool, location='form')

    args = strict_parse_args(g.parser, request.args)
    shard = (args.get('target') or 0) >> 48

    with session_scope(shard) as db_session:
        account = db_session.query(Account).filter_by(email_address=args['email']).first()

        provider_auth_info = dict(provider='custom',
                                  email=args['email'],
                                  imap_server_host=args['imap_host'],
                                  imap_server_port=args.get('imap_port', DEFAULT_IMAP_SSL_PORT),
                                  imap_username=args['imap_username'],
                                  imap_password=args['imap_password'],
                                  smtp_server_host=args['smtp_host'],
                                  smtp_server_port=args.get('smtp_port', DEFAULT_SMTP_SSL_PORT),
                                  smtp_username=args['smtp_username'],
                                  smtp_password=args['smtp_password'],
                                  ssl_required=args['ssl_required'])

        auth_handler = handler_from_provider(provider_auth_info['provider'])

        if account is None:
            account = auth_handler.create_account(args['email'], provider_auth_info)
        else:
            account = account.auth_handler.update_account(account, provider_auth_info)

        try:
            resp = None

            if auth_handler.verify_account(account):
                db_session.add(account)
                db_session.commit()
                resp = simplejson.dumps({
                    'account_id': account.public_id,
                    'namespace_id': account.namespace.public_id
                })
                return make_response((resp, 201, { 'Content-Type': 'application/json' }))
            else:
                resp = simplejson.dumps({ 'message': 'Account verification failed', 'type': 'api_error' })
                return make_response((resp, 422, { 'Content-Type': 'application/json' }))
        except ValidationError as e:
            resp = simplejson.dumps({ 'message': e.message.message, 'type': 'api_error' })
            return make_response((resp, 422, { 'Content-Type': 'application/json' }))
        except NotSupportedError as e:
            resp = simplejson.dumps({ 'message': str(e), 'type': 'custom_api_error' })
            return make_response((resp, 400, { 'Content-Type': 'application/json' }))

@app.route('/provider_from_email', methods=['get'])
def provider_from_email():
    g.parser.add_argument('email', required=True, type=bounded_str, location='args')
    args = strict_parse_args(g.parser, request.args)

    try:
        provider_name = provider_from_address(args['email'])
        provider_info = providers[provider_name] if provider_name != 'unknown' else 'unknown'

        resp = simplejson.dumps({
            'provider_name': provider_name,
            'provider_info': provider_info
        })

        return make_response((resp, 200, { 'Content-Type': 'application/json' }))
    except NotSupportedError as e:
        resp = simplejson.dumps({ 'message': str(e), 'type': 'custom_api_error' })
        return make_response((resp, 400, { 'Content-Type': 'application/json' }))

