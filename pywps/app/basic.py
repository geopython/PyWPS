##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################
"""
XML tools
"""

import logging
from typing import Optional

from werkzeug.wrappers import Response
import pywps.configuration as config

LOGGER = logging.getLogger('PYWPS')


def get_xpath_ns(version):
    """Get xpath namespace for specified WPS version
    currently 1.0.0 or 2.0.0 are supported
    """

    def xpath_ns(ele, path):
        """Function, which will return xpath namespace for given
        element and xpath
        """
        if version == "1.0.0":
            from pywps import namespaces100
            nsp = namespaces100
        elif version == "2.0.0":
            from pywps import namespaces200
            nsp = namespaces200
        return ele.xpath(path, namespaces=nsp)

    return xpath_ns


def make_response(doc, content_type):
    """response serializer"""
    if not content_type:
        content_type = get_default_response_mimetype()
    response = Response(doc, content_type=content_type)
    response.status_percentage = 100
    return response


def get_default_response_mimetype():
    default_mimetype = config.get_config_value('server', 'default_mimetype')
    if not default_mimetype:
        default_mimetype = 'text/xml'
        # default_mimetype = 'application/json'
    return default_mimetype


def get_json_indent():
    json_ident = int(config.get_config_value('server', 'json_indent', 2))
    return json_ident if json_ident >= 0 else None


def get_response_type(accept_mimetypes, default_mimetype):
    accept_json = \
        accept_mimetypes.accept_json or \
        accept_mimetypes.best is None or \
        'json' in accept_mimetypes.best.lower()
    accept_xhtml = \
        accept_mimetypes.accept_xhtml or \
        accept_mimetypes.best is None or \
        'xml' in accept_mimetypes.best.lower()
    if not default_mimetype:
        default_mimetype = get_default_response_mimetype()
    json_is_default = 'json' in default_mimetype or '*' in default_mimetype
    json_response = (accept_json and (not accept_xhtml or json_is_default)) or \
                    (json_is_default and accept_json == accept_xhtml)
    mimetype = 'application/json' if json_response else 'text/xml' if accept_xhtml else ''
    return json_response, mimetype


def parse_http_url(http_request) -> dict:
    operation = api = identifier = output_ids = default_mimetype = base_url = None
    if http_request:
        parts = str(http_request.path[1:]).split('/')
        i = 0
        if len(parts) > i:
            base_url = parts[i].lower()
            if base_url == 'wps':
                default_mimetype = 'xml'
            elif base_url in ['processes', 'jobs', 'api']:
                default_mimetype = 'json'
            i += 1
            if base_url == 'api':
                api = parts[i]
                i += 1
            if len(parts) > i:
                identifier = parts[i]
                i += 1
                if len(parts) > i:
                    output_ids = parts[i]
                    if not output_ids:
                        output_ids = None
    if base_url in ['jobs', 'api']:
        operation = 'execute'
    elif base_url == 'processes':
        if identifier:
            operation = 'describeprocess'
        else:
            operation = 'getcapabilities'
    d = {}
    if operation:
        d['operation'] = operation
    if identifier:
        d['identifier'] = identifier
    if output_ids:
        d['output_ids'] = output_ids
    if default_mimetype:
        d['default_mimetype'] = default_mimetype
    if api:
        d['api'] = api
    if base_url:
        d['base_url'] = base_url
    return d
