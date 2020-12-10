##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

"""
OGC OWS and WPS Exceptions

Based on OGC OWS, WPS and

http://lists.opengeospatial.org/pipermail/wps-dev/2013-October/000335.html
"""

import json

from werkzeug.datastructures import MIMEAccept
from werkzeug.http import parse_accept_header
from werkzeug.wrappers import Response
from werkzeug.exceptions import HTTPException
from werkzeug.utils import escape

import logging

from pywps import __version__
from pywps.app.basic import get_json_indent, get_response_type, parse_http_url

__author__ = "Alex Morega & Calin Ciociu"

LOGGER = logging.getLogger('PYWPS')


class NoApplicableCode(HTTPException):
    """No applicable code exception implementation

    also

    Base exception class
    """

    code = 500
    locator = ""

    def __init__(self, description, locator="", code=400):
        self.code = code
        self.description = description
        self.locator = locator
        msg = 'Exception: code: {}, description: {}, locator: {}'.format(self.code, self.description, self.locator)
        LOGGER.exception(msg)

        HTTPException.__init__(self)

    @property
    def name(self):
        """The status name."""
        return self.__class__.__name__

    def get_description(self, environ=None):
        """Get the description."""
        if self.description:
            return '{}'.format(escape(self.description))
        else:
            return ''

    def get_response(self, environ=None):
        args = {
            'version': __version__,
            'code': self.code,
            'locator': escape(self.locator),
            'name': escape(self.name),
            'description': self.get_description(environ)
        }
        accept_mimetypes = parse_accept_header(environ.get("HTTP_ACCEPT"), MIMEAccept)
        request = environ.get('werkzeug.request', None)
        default_mimetype = None if not request else request.args.get('f', None)
        if default_mimetype is None:
            default_mimetype = parse_http_url(request).get('default_mimetype')
        json_response, mimetype = get_response_type(accept_mimetypes, default_mimetype)
        if json_response:
            doc = json.dumps(args, indent=get_json_indent())
        else:
            doc = str((
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!-- PyWPS {version} -->\n'
                '<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.opengis.net/ows/1.1 http://schemas.opengis.net/ows/1.1.0/owsExceptionReport.xsd" version="1.0.0">\n'  # noqa
                '  <ows:Exception exceptionCode="{name}" locator="{locator}" >\n'
                '      <ows:ExceptionText>{description}</ows:ExceptionText>\n'
                '  </ows:Exception>\n'
                '</ows:ExceptionReport>'
            ).format(**args))

        return Response(doc, self.code, mimetype=mimetype)


class InvalidParameterValue(NoApplicableCode):
    """Invalid parameter value exception implementation
    """
    code = 400


class MissingParameterValue(NoApplicableCode):
    """Missing parameter value exception implementation
    """
    code = 400


class FileSizeExceeded(NoApplicableCode):
    """File size exceeded exception implementation
    """
    code = 400


class VersionNegotiationFailed(NoApplicableCode):
    """Version negotiation exception implementation
    """
    code = 400


class OperationNotSupported(NoApplicableCode):
    """Operation not supported exception implementation
    """
    code = 501


class StorageNotSupported(NoApplicableCode):
    """Storage not supported exception implementation
    """
    code = 400


class NotEnoughStorage(NoApplicableCode):
    """Not enough storage exception implementation
    """
    code = 400


class FileStorageError(NoApplicableCode):
    """File storage exception implementation
    """
    code = 400


class ServerBusy(NoApplicableCode):
    """Max number of operations exceeded
    """

    code = 400
    description = 'Maximum number of processes exceeded'

    def get_body(self, environ=None):
        """Get the XML body."""
        args = {
            'name': escape(self.name),
            'description': self.get_description(environ)
        }
        return str((
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ows:ExceptionReport xmlns:ows="http://www.opengis.net/ows/1.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.opengis.net/ows/1.1 ../../../ows/1.1.0/owsExceptionReport.xsd" version="1.0.0">'  # noqa
            '<ows:Exception exceptionCode="{name}">'
            '{description}'
            '</ows:Exception>'
            '</ows:ExceptionReport>'
        ).format(**args))


class FileURLNotSupported(NoApplicableCode):
    """File URL not supported exception implementation
    """
    code = 400
    description = 'File URL not supported as input.'

    def __init__(self, description="", locator="", code=400):
        description = description or self.description
        NoApplicableCode.__init__(self, description=description, locator=locator, code=code)


class SchedulerNotAvailable(NoApplicableCode):
    """Job scheduler not available exception implementation
    """
    code = 400
