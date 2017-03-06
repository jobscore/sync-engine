import sys
import urllib
import requests
import simplejson
from flask import request, g, Blueprint, make_response
from flask import jsonify as flask_jsonify
from flask.ext.restful import reqparse
from inbox.api.validation import bounded_str, strict_parse_args, ValidatableArgument
from inbox.basicauth import NotSupportedError
from inbox.models.session import session_scope
from inbox.api.err import APIException, InputError, log_exception
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
            raise InputError('Account is already registered')

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
