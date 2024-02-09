##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

import copy
import logging
import os
import sys
import tempfile
import uuid
from collections import OrderedDict, deque
from typing import Dict, Optional, Sequence
from urllib.parse import urlparse

from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Request, Response
from pywps.app.WPSExecuteRequest import WPSExecuteRequest
from pywps.response import CapabilitiesResponse, DescribeResponse, ExecuteRawResponse, StatusResponse
import pywps.configuration as config
from pywps.app.WPSRequest import WPSRequest
from pywps.dblog import log_request, store_status
from pywps.exceptions import (
    FileURLNotSupported,
    InvalidParameterValue,
    MissingParameterValue,
    NoApplicableCode,
)
from pywps.inout.inputs import BoundingBoxInput, ComplexInput, LiteralInput
from pywps.response.status import WPS_STATUS
from pywps.app.basic import get_response_type, get_default_response_mimetype

LOGGER = logging.getLogger("PYWPS")


class Service(object):
    """The top-level object that represents a WPS service.

    A WSGI application.

    :param processes: A list of :class:`~Process` objects that are
                      provided by this service.

    :param cfgfiles: A list of configuration files
    """

    def __init__(self, processes: Sequence = [], cfgfiles=None, preprocessors: Optional[Dict] = None):
        # ordered dict of processes
        self.processes = OrderedDict((p.identifier, p) for p in processes)
        self.preprocessors = preprocessors or dict()

        if cfgfiles:
            config.load_configuration(cfgfiles)

        if config.get_config_value('logging', 'file') and config.get_config_value('logging', 'level'):
            LOGGER.setLevel(getattr(logging, config.get_config_value('logging', 'level')))
            if not LOGGER.handlers:  # hasHandlers in Python 3.x
                fh = logging.FileHandler(config.get_config_value('logging', 'file'))
                fh.setFormatter(logging.Formatter(config.get_config_value('logging', 'format')))
                LOGGER.addHandler(fh)
        else:  # NullHandler | StreamHandler
            if not LOGGER.handlers:
                LOGGER.addHandler(logging.NullHandler())

    def get_status(self, http_request):
        try:
            _, mimetype = get_response_type(http_request.accept_mimetypes,
                                            "text/xml")
        except Exception:
            mimetype = get_default_response_mimetype()
        from urllib.parse import parse_qs
        request = parse_qs(http_request.environ["QUERY_STRING"])
        return StatusResponse(request.get("version", ["1.0.0"])[0], request["uuid"][0], mimetype)

    def get_capabilities(self, wps_request, uuid):
        return CapabilitiesResponse(wps_request, uuid, version=wps_request.version, processes=self.processes)

    def describe(self, wps_request, uuid, identifiers):
        return DescribeResponse(wps_request, uuid, processes=self.processes, identifiers=identifiers)

    def execute(self, identifier, wps_request, uuid):
        """Parse and perform Execute WPS request call

        :param identifier: process identifier string
        :param wps_request: pywps.WPSRequest structure with parsed inputs, still in memory
        :param uuid: string identifier of the request
        """
        self._set_grass()
        process = self.prepare_process_for_execution(identifier)
        return self._parse_and_execute(process, wps_request, uuid)

    def prepare_process_for_execution(self, identifier):
        """Prepare the process identified by ``identifier`` for execution.
        """
        try:
            process = self.processes[identifier]
        except KeyError:
            raise InvalidParameterValue("Unknown process '{}'".format(identifier), 'Identifier')
        # make deep copy of the process instance
        # so that processes are not overriding each other
        # just for execute
        process = copy.deepcopy(process)
        process.service = self
        workdir = os.path.abspath(config.get_config_value('server', 'workdir'))
        tempdir = tempfile.mkdtemp(prefix='pywps_process_', dir=workdir)
        process.set_workdir(tempdir)
        return process

    def _parse_and_execute(self, process, wps_request, uuid):
        """Parse and execute request
        """

        wps_request = WPSExecuteRequest(process, wps_request)

        wps_response = process.execute(wps_request, uuid)
        if wps_request.wps_request.raw:
            return ExecuteRawResponse(wps_response)
        else:
            # FIXME: this try-except has no pratical meaning, just allow to pass some test.
            try:
                _, mimetype = get_response_type(wps_request.http_request.accept_mimetypes, wps_request.default_mimetype)
            except Exception:
                mimetype = get_default_response_mimetype()
            return StatusResponse(wps_request.version, wps_response.uuid, mimetype)

    def _set_grass(self):
        """Set environment variables needed for GRASS GIS support
        """
        gisbase = config.get_config_value('grass', 'gisbase')
        if gisbase and os.path.isdir(gisbase):
            LOGGER.debug('GRASS GISBASE set to {}'.format(gisbase))

            os.environ['GISBASE'] = gisbase

            os.environ['LD_LIBRARY_PATH'] = '{}:{}'.format(
                os.environ.get('LD_LIBRARY_PATH'),
                os.path.join(gisbase, 'lib'))
            os.putenv('LD_LIBRARY_PATH', os.environ.get('LD_LIBRARY_PATH'))

            os.environ['PATH'] = '{}:{}:{}'.format(
                os.environ.get('PATH'),
                os.path.join(gisbase, 'bin'),
                os.path.join(gisbase, 'scripts'))
            os.putenv('PATH', os.environ.get('PATH'))

            python_path = os.path.join(gisbase, 'etc', 'python')
            os.environ['PYTHONPATH'] = '{}:{}'.format(os.environ.get('PYTHONPATH'),
                                                      python_path)
            os.putenv('PYTHONPATH', os.environ.get('PYTHONPATH'))
            sys.path.insert(0, python_path)

    # May not raise exceptions, this function must return a valid werkzeug.wrappers.Response.
    def call(self, http_request):

        try:
            # This try block handle Exception generated before the request is accepted. Once the request is accepted
            # a valid wps_reponse must exist. To report error use the wps_response using
            # wps_response._update_status(WPS_STATUS.FAILED, ...).
            #
            # We need this behaviour to handle the status file correctly, once the request is accepted, a
            # status file may be created and failure must be reported in this file instead of a raw ows:ExceptionReport
            #
            # Exeception from CapabilityResponse and DescribeResponse are always catched by this try ... except close
            # because they never have status.

            request_uuid = uuid.uuid1()

            environ_cfg = http_request.environ.get('PYWPS_CFG')
            if 'PYWPS_CFG' not in os.environ and environ_cfg:
                LOGGER.debug('Setting PYWPS_CFG to {}'.format(environ_cfg))
                os.environ['PYWPS_CFG'] = environ_cfg

            if http_request.environ["PATH_INFO"] == "/status":
                try:
                    return self.get_status(http_request)
                except Exception as e:
                    store_status(request_uuid, WPS_STATUS.FAILED,
                                 'Request rejected due to exception', 100)
                    raise e
            else:
                wps_request = WPSRequest(http_request, self.preprocessors)
                LOGGER.info('Request: {}'.format(wps_request.operation))
                if wps_request.operation in ['getcapabilities',
                                             'describeprocess',
                                             'execute']:
                    log_request(request_uuid, wps_request)
                    try:
                        response = None
                        if wps_request.operation == 'getcapabilities':
                            response = self.get_capabilities(wps_request, request_uuid)
                            response._update_status(WPS_STATUS.SUCCEEDED, '', 100)

                        elif wps_request.operation == 'describeprocess':
                            response = self.describe(wps_request, request_uuid, wps_request.identifiers)
                            response._update_status(WPS_STATUS.SUCCEEDED, '', 100)

                        elif wps_request.operation == 'execute':
                            response = self.execute(
                                wps_request.identifier,
                                wps_request,
                                request_uuid
                            )
                        return response
                    except Exception as e:
                        # This ensure that logged request get terminated in case of exception while the request is not
                        # accepted
                        store_status(request_uuid, WPS_STATUS.FAILED, 'Request rejected due to exception', 100)
                        raise e
                else:
                    raise RuntimeError("Unknown operation {}".format(wps_request.operation))

        except NoApplicableCode as e:
            return e
        except HTTPException as e:
            return NoApplicableCode(e.description, code=e.code)
        except Exception:
            msg = "No applicable error code, please check error log."
            return NoApplicableCode(msg, code=500)

    @Request.application
    def __call__(self, http_request):
        return self.call(http_request)


def _build_input_file_name(href, workdir, extension=None):
    href = href or ''
    url_path = urlparse(href).path or ''
    file_name = os.path.basename(url_path).strip() or 'input'
    (prefix, suffix) = os.path.splitext(file_name)
    suffix = suffix or extension or ''
    if prefix and suffix:
        file_name = prefix + suffix
    input_file_name = os.path.join(workdir, file_name)
    # build tempfile in case of duplicates
    if os.path.exists(input_file_name):
        input_file_name = tempfile.mkstemp(
            suffix=suffix, prefix=prefix + '_',
            dir=workdir)[1]
    return input_file_name


def _validate_file_input(href):
    href = href or ''
    parsed_url = urlparse(href)
    if parsed_url.scheme != 'file':
        raise FileURLNotSupported('Invalid URL scheme')
    file_path = parsed_url.path
    if not file_path:
        raise FileURLNotSupported('Invalid URL path')
    file_path = os.path.abspath(file_path)
    # build allowed paths list
    inputpaths = config.get_config_value('server', 'allowedinputpaths')
    allowed_paths = [os.path.abspath(p.strip()) for p in inputpaths.split(os.pathsep) if p.strip()]
    for allowed_path in allowed_paths:
        if file_path.startswith(allowed_path):
            LOGGER.debug("Accepted file url as input.")
            return
    raise FileURLNotSupported()


def _extension(complexinput):
    extension = None
    if complexinput.data_format:
        extension = complexinput.data_format.extension
    return extension
