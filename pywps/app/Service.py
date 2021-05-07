##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

import logging
import tempfile
from typing import Sequence, Optional, Dict

from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Request, Response
from urllib.parse import urlparse
from pywps.app.WPSRequest import WPSRequest
import pywps.configuration as config
from pywps.exceptions import MissingParameterValue, NoApplicableCode, InvalidParameterValue, FileSizeExceeded, \
    StorageNotSupported, FileURLNotSupported
from pywps.inout.inputs import ComplexInput, LiteralInput, BoundingBoxInput
from pywps.dblog import log_request, store_status
from pywps import response
from pywps.response.status import WPS_STATUS

from collections import deque, OrderedDict
import os
import sys
import uuid
import copy
import shutil


LOGGER = logging.getLogger("PYWPS")


class Service(object):

    """ The top-level object that represents a WPS service. It's a WSGI
    application.

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

    def get_capabilities(self, wps_request, uuid):

        response_cls = response.get_response("capabilities")
        return response_cls(wps_request, uuid, version=wps_request.version, processes=self.processes)

    def describe(self, wps_request, uuid, identifiers):

        response_cls = response.get_response("describe")
        return response_cls(wps_request, uuid, processes=self.processes,
                            identifiers=identifiers)

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

        LOGGER.debug('Checking if all mandatory inputs have been passed')
        data_inputs = {}
        for inpt in process.inputs:
            # Replace the dicts with the dict of Literal/Complex inputs
            # set the input to the type defined in the process.

            request_inputs = None
            if inpt.identifier in wps_request.inputs:
                request_inputs = wps_request.inputs[inpt.identifier]

            if not request_inputs:
                if inpt._default is not None:
                    if not inpt.data_set and isinstance(inpt, ComplexInput):
                        inpt._set_default_value()

                    data_inputs[inpt.identifier] = [inpt.clone()]
            else:

                if isinstance(inpt, ComplexInput):
                    data_inputs[inpt.identifier] = self.create_complex_inputs(
                        inpt, request_inputs)
                elif isinstance(inpt, LiteralInput):
                    data_inputs[inpt.identifier] = self.create_literal_inputs(
                        inpt, request_inputs)
                elif isinstance(inpt, BoundingBoxInput):
                    data_inputs[inpt.identifier] = self.create_bbox_inputs(
                        inpt, request_inputs)

        for inpt in process.inputs:

            if inpt.identifier not in data_inputs:
                if inpt.min_occurs > 0:
                    LOGGER.error('Missing parameter value: {}'.format(inpt.identifier))
                    raise MissingParameterValue(
                        inpt.identifier, inpt.identifier)

        wps_request.inputs = data_inputs

        process.setup_outputs_from_wps_request(wps_request)

        wps_response = process.execute(wps_request, uuid)
        return wps_response

    def create_complex_inputs(self, source, inputs):
        """Create new ComplexInput as clone of original ComplexInput
        because of inputs can be more than one, take it just as Prototype.

        :param source: The process's input definition.
        :param inputs: The request input data.
        :return collections.deque:
        """

        outinputs = deque(maxlen=source.max_occurs)

        for inpt in inputs:
            data_input = source.clone()
            frmt = data_input.supported_formats[0]
            if 'mimeType' in inpt:
                if inpt['mimeType']:
                    frmt = data_input.get_format(inpt['mimeType'])
                else:
                    frmt = data_input.data_format

            if frmt:
                data_input.data_format = frmt
            else:
                raise InvalidParameterValue(
                    'Invalid mimeType value {} for input {}'.format(inpt.get('mimeType'), source.identifier),
                    'mimeType')

            data_input.method = inpt.get('method', 'GET')
            data_input.process(inpt)
            outinputs.append(data_input)

        if len(outinputs) < source.min_occurs:
            description = "At least {} inputs are required. You provided {}.".format(
                source.min_occurs,
                len(outinputs),
            )
            raise MissingParameterValue(description=description, locator=source.identifier)
        return outinputs

    def create_literal_inputs(self, source, inputs):
        """ Takes the http_request and parses the input to objects
        :return collections.deque:
        """

        outinputs = deque(maxlen=source.max_occurs)

        for inpt in inputs:
            newinpt = source.clone()
            # set the input to the type defined in the process
            newinpt.uom = inpt.get('uom')
            data_type = inpt.get('datatype')
            if data_type:
                newinpt.data_type = data_type

            # get the value of the field
            newinpt.data = inpt.get('data')

            outinputs.append(newinpt)

        if len(outinputs) < source.min_occurs:
            description = "At least {} inputs are required. You provided {}.".format(
                source.min_occurs,
                len(outinputs),
            )
            raise MissingParameterValue(description, locator=source.identifier)

        return outinputs

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

    def create_bbox_inputs(self, source, inputs):
        """ Takes the http_request and parses the input to objects
        :return collections.deque:
        """

        outinputs = deque(maxlen=source.max_occurs)

        for inpt in inputs:
            newinpt = source.clone()
            newinpt.data = inpt.get('data')
            LOGGER.debug(f'newinpt bbox data={newinpt.data}')
            newinpt.crs = inpt.get('crs')
            newinpt.dimensions = inpt.get('dimensions')
            outinputs.append(newinpt)

        if len(outinputs) < source.min_occurs:
            description = "At least {} inputs are required. You provided {}.".format(
                source.min_occurs,
                len(outinputs),
            )
            raise MissingParameterValue(description=description, locator=source.identifier)

        return outinputs

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
