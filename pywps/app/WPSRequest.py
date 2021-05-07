##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

import logging
import lxml
import lxml.etree
from werkzeug.exceptions import MethodNotAllowed
from pywps import get_ElementMakerForVersion
import base64
import datetime
from pywps.app.basic import get_xpath_ns, parse_http_url
from pywps.inout.inputs import input_from_json
from pywps.exceptions import NoApplicableCode, OperationNotSupported, MissingParameterValue, VersionNegotiationFailed, \
    InvalidParameterValue, FileSizeExceeded
from pywps import configuration
from pywps.configuration import wps_strict
from pywps import get_version_from_ns

import json
from urllib.parse import unquote

LOGGER = logging.getLogger("PYWPS")
default_version = '1.0.0'


class WPSRequest(object):

    def __init__(self, http_request=None, preprocessors=None):
        self.http_request = http_request

        self.operation = None
        self.version = None
        self.api = None
        self.default_mimetype = None
        self.language = None
        self.identifier = None
        self.identifiers = None
        self.store_execute = None
        self.status = None
        self.lineage = None
        self.inputs = {}
        self.output_ids = None
        self.outputs = {}
        self.raw = None
        self.WPS = None
        self.OWS = None
        self.xpath_ns = None
        self.preprocessors = preprocessors or dict()
        self.preprocess_request = None
        self.preprocess_response = None

        if http_request:
            d = parse_http_url(http_request)
            self.operation = d.get('operation')
            self.identifier = d.get('identifier')
            self.output_ids = d.get('output_ids')
            self.api = d.get('api')
            self.default_mimetype = d.get('default_mimetype')
            request_parser = self._get_request_parser_method(http_request.method)
            request_parser()

    def _get_request_parser_method(self, method):

        if method == 'GET':
            return self._get_request
        elif method == 'POST':
            return self._post_request
        else:
            raise MethodNotAllowed()

    def _get_request(self):
        """HTTP GET request parser
        """

        # service shall be WPS
        service = _get_get_param(self.http_request, 'service', None if wps_strict else 'wps')
        if service:
            if str(service).lower() != 'wps':
                raise InvalidParameterValue(
                    'parameter SERVICE [{}] not supported'.format(service), 'service')
        else:
            raise MissingParameterValue('service', 'service')

        self.operation = _get_get_param(self.http_request, 'request', self.operation)

        language = _get_get_param(self.http_request, 'language')
        self.check_and_set_language(language)

        request_parser = self._get_request_parser(self.operation)
        request_parser(self.http_request)

    def _post_request(self):
        """HTTP GET request parser
        """
        # check if input file size was not exceeded
        maxsize = configuration.get_config_value('server', 'maxrequestsize')
        maxsize = configuration.get_size_mb(maxsize) * 1024 * 1024
        if self.http_request.content_length > maxsize:
            raise FileSizeExceeded('File size for input exceeded.'
                                   ' Maximum request size allowed: {} megabytes'.format(maxsize / 1024 / 1024))

        content_type = self.http_request.content_type # or self.http_request.mimetype
        json_input = 'json' in content_type
        if not json_input:
            try:
                doc = lxml.etree.fromstring(self.http_request.get_data())
            except Exception as e:
                raise NoApplicableCode(e.msg)
            operation = doc.tag
            version = get_version_from_ns(doc.nsmap[doc.prefix])
            self.set_version(version)

            language = doc.attrib.get('language')
            self.check_and_set_language(language)

            request_parser = self._post_request_parser(operation)
            request_parser(doc)
        else:
            try:
                jdoc = json.loads(self.http_request.get_data())
            except Exception as e:
                raise NoApplicableCode(e.msg)
            if self.identifier is not None:
                jdoc = {'inputs': jdoc}
            else:
                self.identifier = jdoc.get('identifier', None)

            self.operation = jdoc.get('operation', self.operation)

            preprocessor_tuple = self.preprocessors.get(self.identifier, None)
            if preprocessor_tuple:
                self.identifier = preprocessor_tuple[0]
                self.preprocess_request = preprocessor_tuple[1]
                self.preprocess_response = preprocessor_tuple[2]

            jdoc['operation'] = self.operation
            jdoc['identifier'] = self.identifier
            jdoc['api'] = self.api
            jdoc['default_mimetype'] = self.default_mimetype

            if self.preprocess_request is not None:
                jdoc = self.preprocess_request(jdoc)
            self.json = jdoc

            version = jdoc.get('version')
            self.set_version(version)

            language = jdoc.get('language')
            self.check_and_set_language(language)

            request_parser = self._post_json_request_parser()
            request_parser(jdoc)

    def _get_request_parser(self, operation):
        """Factory function returing propper parsing function
        """

        wpsrequest = self

        def parse_get_getcapabilities(http_request):
            """Parse GET GetCapabilities request
            """

            acceptedversions = _get_get_param(http_request, 'acceptversions')
            wpsrequest.check_accepted_versions(acceptedversions)

        def parse_get_describeprocess(http_request):
            """Parse GET DescribeProcess request
            """
            version = _get_get_param(http_request, 'version')
            wpsrequest.check_and_set_version(version)

            wpsrequest.identifiers = _get_get_param(
                http_request, 'identifier', wpsrequest.identifiers, aslist=True)
            if wpsrequest.identifiers is None and self.identifier is not None:
                wpsrequest.identifiers = [wpsrequest.identifier]

        def parse_get_execute(http_request):
            """Parse GET Execute request
            """
            version = _get_get_param(http_request, 'version')
            wpsrequest.check_and_set_version(version)

            wpsrequest.identifier = _get_get_param(http_request, 'identifier', wpsrequest.identifier)
            wpsrequest.store_execute = _get_get_param(
                http_request, 'storeExecuteResponse', 'false')
            wpsrequest.status = _get_get_param(http_request, 'status', 'false')
            wpsrequest.lineage = _get_get_param(
                http_request, 'lineage', 'false')
            wpsrequest.inputs = get_data_from_kvp(
                _get_get_param(http_request, 'DataInputs'), 'DataInputs')
            if self.inputs is None:
                self.inputs = {}

            # take responseDocument preferably
            raw, output_ids = False, _get_get_param(http_request, 'ResponseDocument')
            if output_ids is None:
                raw, output_ids = True, _get_get_param(http_request, 'RawDataOutput')
            if output_ids is not None:
                wpsrequest.raw, wpsrequest.output_ids = raw, output_ids
            elif wpsrequest.raw is None:
                wpsrequest.raw = wpsrequest.output_ids is not None

            wpsrequest.default_mimetype = _get_get_param(http_request, 'f', wpsrequest.default_mimetype)
            wpsrequest.outputs = get_data_from_kvp(wpsrequest.output_ids) or {}
            if wpsrequest.raw:
                # executeResponse XML will not be stored and no updating of
                # status
                wpsrequest.store_execute = 'false'
                wpsrequest.status = 'false'

        if operation:
            self.operation = operation.lower()
        else:
            if wps_strict:
                raise MissingParameterValue('Missing request value', 'request')
            self.operation = 'execute'

        if self.operation == 'getcapabilities':
            return parse_get_getcapabilities
        elif self.operation == 'describeprocess':
            return parse_get_describeprocess
        elif self.operation == 'execute':
            return parse_get_execute
        else:
            raise OperationNotSupported(
                'Unknown request {}'.format(self.operation), operation)

    def _post_request_parser(self, tagname):
        """Factory function returing propper parsing function
        """

        wpsrequest = self

        def parse_post_getcapabilities(doc):
            """Parse POST GetCapabilities request
            """
            acceptedversions = self.xpath_ns(
                doc, '/wps:GetCapabilities/ows:AcceptVersions/ows:Version')
            acceptedversions = ','.join(
                [v.text for v in acceptedversions])
            wpsrequest.check_accepted_versions(acceptedversions)

        def parse_post_describeprocess(doc):
            """Parse POST DescribeProcess request
            """

            version = doc.attrib.get('version')
            wpsrequest.check_and_set_version(version)

            wpsrequest.operation = 'describeprocess'
            wpsrequest.identifiers = [identifier_el.text for identifier_el in
                                      self.xpath_ns(doc, './ows:Identifier')]

        def parse_post_execute(doc):
            """Parse POST Execute request
            """
            version = doc.attrib.get('version')
            wpsrequest.check_and_set_version(version)

            wpsrequest.operation = 'execute'

            identifier = self.xpath_ns(doc, './ows:Identifier')

            if not identifier:
                raise MissingParameterValue(
                    'Process identifier not set', 'Identifier')

            wpsrequest.identifier = identifier[0].text
            wpsrequest.lineage = 'false'
            wpsrequest.store_execute = 'false'
            wpsrequest.status = 'false'
            wpsrequest.inputs = get_inputs_from_xml(doc)
            wpsrequest.outputs = get_output_from_xml(doc)
            wpsrequest.raw = False
            if self.xpath_ns(doc, '/wps:Execute/wps:ResponseForm/wps:RawDataOutput'):
                wpsrequest.raw = True
                # executeResponse XML will not be stored
                wpsrequest.store_execute = 'false'

            # check if response document tag has been set then retrieve
            response_document = self.xpath_ns(
                doc, './wps:ResponseForm/wps:ResponseDocument')
            if len(response_document) > 0:
                wpsrequest.lineage = response_document[
                    0].attrib.get('lineage', 'false')
                wpsrequest.store_execute = response_document[
                    0].attrib.get('storeExecuteResponse', 'false')
                wpsrequest.status = response_document[
                    0].attrib.get('status', 'false')

        if tagname == self.WPS.GetCapabilities().tag:
            self.operation = 'getcapabilities'
            return parse_post_getcapabilities
        elif tagname == self.WPS.DescribeProcess().tag:
            self.operation = 'describeprocess'
            return parse_post_describeprocess
        elif tagname == self.WPS.Execute().tag:
            self.operation = 'execute'
            return parse_post_execute
        else:
            raise InvalidParameterValue(
                'Unknown request {}'.format(tagname), 'request')

    def _post_json_request_parser(self):
        """Factory function returing propper parsing function
        """

        wpsrequest = self

        def parse_json_post_getcapabilities(jdoc):
            """Parse POST GetCapabilities request
            """
            acceptedversions = jdoc.get('acceptedversions')
            wpsrequest.check_accepted_versions(acceptedversions)

        def parse_json_post_describeprocess(jdoc):
            """Parse POST DescribeProcess request
            """

            version = jdoc.get('version')
            wpsrequest.check_and_set_version(version)
            wpsrequest.identifiers = [identifier_el.text for identifier_el in
                                      self.xpath_ns(jdoc, './ows:Identifier')]

        def parse_json_post_execute(jdoc):
            """Parse POST Execute request
            """
            version = jdoc.get('version')
            wpsrequest.check_and_set_version(version)

            wpsrequest.identifier = jdoc.get('identifier')
            if wpsrequest.identifier is None:
                raise MissingParameterValue(
                    'Process identifier not set', 'Identifier')

            wpsrequest.lineage = 'false'
            wpsrequest.store_execute = 'false'
            wpsrequest.status = 'false'
            wpsrequest.inputs = get_inputs_from_json(jdoc)

            if wpsrequest.output_ids is None:
                wpsrequest.output_ids = jdoc.get('outputs', {})
                wpsrequest.raw = jdoc.get('raw', False)
            wpsrequest.raw, wpsrequest.outputs = get_output_from_dict(wpsrequest.output_ids, wpsrequest.raw)

            if wpsrequest.raw:
                # executeResponse XML will not be stored
                wpsrequest.store_execute = 'false'

            # todo: parse response_document like in the xml version?

        if self.operation is None:
            self.operation = 'execute'
        else:
            self.operation = self.operation.lower()
        if self.operation == 'getcapabilities':
            return parse_json_post_getcapabilities
        elif self.operation == 'describeprocess':
            return parse_json_post_describeprocess
        elif self.operation == 'execute':
            return parse_json_post_execute
        else:
            raise InvalidParameterValue(
                'Unknown request {}'.format(self.operation), 'request')

    def set_version(self, version):
        self.version = version
        self.xpath_ns = get_xpath_ns(version)
        self.WPS, self.OWS = get_ElementMakerForVersion(self.version)

    def check_accepted_versions(self, acceptedversions):
        """
        :param acceptedversions: string
        """

        version = None

        if acceptedversions:
            acceptedversions_array = acceptedversions.split(',')
            for aversion in acceptedversions_array:
                if _check_version(aversion):
                    version = aversion
        else:
            version = '1.0.0'

        if version:
            self.check_and_set_version(version)
        else:
            raise VersionNegotiationFailed(
                'The requested version "{}" is not supported by this server'.format(acceptedversions), 'version')

    def check_and_set_version(self, version, allow_default=True):
        """set this.version
        """

        if not version:
            if allow_default:
                version = default_version
            else:
                raise MissingParameterValue('Missing version', 'version')
        if not _check_version(version):
            raise VersionNegotiationFailed(
                'The requested version "{}" is not supported by this server'.format(version), 'version')
        else:
            self.set_version(version)

    def check_and_set_language(self, language):
        """set this.language
        """
        supported_languages = configuration.get_config_value('server', 'language').split(',')
        supported_languages = [lang.strip() for lang in supported_languages]

        if not language:
            # default to the first supported language
            language = supported_languages[0]

        if language not in supported_languages:
            raise InvalidParameterValue(
                'The requested language "{}" is not supported by this server'.format(language),
                'language',
            )

        self.language = language

    @property
    def json(self):
        """Return JSON encoded representation of the request
        """
        class ExtendedJSONEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, datetime.date) or isinstance(obj, datetime.time):
                    encoded_object = obj.isoformat()
                else:
                    encoded_object = json.JSONEncoder.default(self, obj)
                return encoded_object

        obj = {
            'operation': self.operation,
            'version': self.version,
            'api': self.api,
            'default_mimetype': self.default_mimetype,
            'language': self.language,
            'identifier': self.identifier,
            'identifiers': self.identifiers,
            'store_execute': self.store_execute,
            'status': self.status,
            'lineage': self.lineage,
            'inputs': dict((i, [inpt.json for inpt in self.inputs[i]]) for i in self.inputs),
            'outputs': self.outputs,
            'raw': self.raw
        }

        return json.dumps(obj, allow_nan=False, cls=ExtendedJSONEncoder)

    @json.setter
    def json(self, value):
        """init this request from json back again

        :param value: the json (not string) representation
        """

        self.operation = value.get('operation')
        self.version = value.get('version')
        self.api = value.get('api')
        self.default_mimetype = value.get('default_mimetype')
        self.language = value.get('language')
        self.identifier = value.get('identifier')
        self.identifiers = value.get('identifiers')
        self.store_execute = value.get('store_execute')
        self.status = value.get('status', False)
        self.lineage = value.get('lineage', False)
        self.outputs = value.get('outputs')
        self.raw = value.get('raw', False)
        self.inputs = {}

        for identifier in value.get('inputs', []):
            inpt_defs = value['inputs'][identifier]
            if not isinstance(inpt_defs, (list, tuple)):
                inpt_defs = [inpt_defs]
            self.inputs[identifier] = []
            for inpt_def in inpt_defs:
                if not isinstance(inpt_def, dict):
                    inpt_def = {"data": inpt_def}
                if 'identifier' not in inpt_def:
                    inpt_def['identifier'] = identifier
                inpt = input_from_json(inpt_def)
                self.inputs[identifier].append(inpt)


def get_inputs_from_xml(doc):
    the_inputs = {}
    version = get_version_from_ns(doc.nsmap[doc.prefix])
    xpath_ns = get_xpath_ns(version)
    for input_el in xpath_ns(doc, '/wps:Execute/wps:DataInputs/wps:Input'):
        [identifier_el] = xpath_ns(input_el, './ows:Identifier')
        identifier = identifier_el.text

        if identifier not in the_inputs:
            the_inputs[identifier] = []

        literal_data = xpath_ns(input_el, './wps:Data/wps:LiteralData')
        if literal_data:
            value_el = literal_data[0]
            inpt = {}
            inpt['identifier'] = identifier_el.text
            inpt['data'] = str(value_el.text)
            inpt['uom'] = value_el.attrib.get('uom', '')
            inpt['datatype'] = value_el.attrib.get('datatype', '')
            the_inputs[identifier].append(inpt)
            continue

        complex_data = xpath_ns(input_el, './wps:Data/wps:ComplexData')
        if complex_data:
            complex_data_el = complex_data[0]
            inpt = {}
            inpt['identifier'] = identifier_el.text
            inpt['mimeType'] = complex_data_el.attrib.get('mimeType', None)
            inpt['encoding'] = complex_data_el.attrib.get('encoding', '').lower()
            inpt['schema'] = complex_data_el.attrib.get('schema', '')
            inpt['method'] = complex_data_el.attrib.get('method', 'GET')
            if len(complex_data_el.getchildren()) > 0:
                value_el = complex_data_el[0]
                inpt['data'] = _get_dataelement_value(value_el)
            else:
                inpt['data'] = _get_rawvalue_value(
                    complex_data_el.text, inpt['encoding'])
            the_inputs[identifier].append(inpt)
            continue

        reference_data = xpath_ns(input_el, './wps:Reference')
        if reference_data:
            reference_data_el = reference_data[0]
            inpt = {}
            inpt['identifier'] = identifier_el.text
            inpt[identifier_el.text] = reference_data_el.text
            inpt['href'] = reference_data_el.attrib.get(
                '{http://www.w3.org/1999/xlink}href', '')
            inpt['mimeType'] = reference_data_el.attrib.get('mimeType', None)
            inpt['method'] = reference_data_el.attrib.get('method', 'GET')
            header_element = xpath_ns(reference_data_el, './wps:Header')
            if header_element:
                inpt['header'] = _get_reference_header(header_element)
            body_element = xpath_ns(reference_data_el, './wps:Body')
            if body_element:
                inpt['body'] = _get_reference_body(body_element[0])
            bodyreference_element = xpath_ns(reference_data_el,
                                             './wps:BodyReference')
            if bodyreference_element:
                inpt['bodyreference'] = _get_reference_bodyreference(
                    bodyreference_element[0])
            the_inputs[identifier].append(inpt)
            continue

        # Using OWSlib BoundingBox
        from owslib.ows import BoundingBox
        bbox_datas = xpath_ns(input_el, './wps:Data/wps:BoundingBoxData')
        if bbox_datas:
            for bbox_data in bbox_datas:
                bbox = BoundingBox(bbox_data)
                LOGGER.debug("parse bbox: minx={}, miny={}, maxx={},maxy={}".format(
                    bbox.minx, bbox.miny, bbox.maxx, bbox.maxy))
                inpt = {}
                inpt['identifier'] = identifier_el.text
                inpt['data'] = [bbox.minx, bbox.miny, bbox.maxx, bbox.maxy]
                inpt['crs'] = bbox.crs
                inpt['dimensions'] = bbox.dimensions
                the_inputs[identifier].append(inpt)
    return the_inputs


def get_output_from_xml(doc):
    the_output = {}

    version = get_version_from_ns(doc.nsmap[doc.prefix])
    xpath_ns = get_xpath_ns(version)

    if xpath_ns(doc, '/wps:Execute/wps:ResponseForm/wps:ResponseDocument'):
        for output_el in xpath_ns(doc, '/wps:Execute/wps:ResponseForm/wps:ResponseDocument/wps:Output'):
            [identifier_el] = xpath_ns(output_el, './ows:Identifier')
            outpt = {}
            outpt[identifier_el.text] = ''
            outpt['mimetype'] = output_el.attrib.get('mimeType', None)
            outpt['encoding'] = output_el.attrib.get('encoding', '')
            outpt['schema'] = output_el.attrib.get('schema', '')
            outpt['uom'] = output_el.attrib.get('uom', '')
            outpt['asReference'] = output_el.attrib.get('asReference', 'false')
            the_output[identifier_el.text] = outpt

    elif xpath_ns(doc, '/wps:Execute/wps:ResponseForm/wps:RawDataOutput'):
        for output_el in xpath_ns(doc, '/wps:Execute/wps:ResponseForm/wps:RawDataOutput'):
            [identifier_el] = xpath_ns(output_el, './ows:Identifier')
            outpt = {}
            outpt[identifier_el.text] = ''
            outpt['mimetype'] = output_el.attrib.get('mimeType', None)
            outpt['encoding'] = output_el.attrib.get('encoding', '')
            outpt['schema'] = output_el.attrib.get('schema', '')
            outpt['uom'] = output_el.attrib.get('uom', '')
            the_output[identifier_el.text] = outpt

    return the_output


def get_inputs_from_json(jdoc):
    the_inputs = {}
    inputs_dict = jdoc.get('inputs', {})
    for identifier, inpt_defs in inputs_dict.items():
        if not isinstance(inpt_defs, (list, tuple)):
            inpt_defs = [inpt_defs]
        the_inputs[identifier] = []
        for inpt_def in inpt_defs:
            if not isinstance(inpt_def, dict):
                inpt_def = {"data": inpt_def}
            data_type = inpt_def.get('type', 'literal')
            if data_type == 'literal':
                inpt = {}
                inpt['identifier'] = identifier
                inpt['data'] = inpt_def.get('data')
                inpt['uom'] = inpt_def.get('uom', '')
                inpt['datatype'] = inpt_def.get('datatype', '')
                the_inputs[identifier].append(inpt)
                continue

            if data_type == 'complex':
                inpt = {}
                inpt['identifier'] = identifier
                inpt['mimeType'] = inpt_def.get('mimeType', None)
                inpt['encoding'] = inpt_def.get('encoding', '').lower()
                inpt['schema'] = inpt_def.get('schema', '')
                inpt['method'] = inpt_def.get('method', 'GET')
                # if len(complex_data_el.getchildren()) > 0:
                #     value_el = complex_data_el[0]
                #     inpt['data'] = _get_dataelement_value(value_el)
                # else:
                if True:
                    inpt['data'] = _get_rawvalue_value(inpt_def, inpt['encoding'])
                the_inputs[identifier].append(inpt)
                continue

            if data_type == 'reference':
                inpt = {}
                inpt['identifier'] = identifier
                inpt[identifier] = inpt_def
                inpt['href'] = inpt_def.get('href', '')
                inpt['mimeType'] = inpt_def.get('mimeType', None)
                inpt['method'] = inpt_def.get('method', 'GET')
                inpt['header'] = inpt_def.get('header', '')
                inpt['body'] = inpt_def.get('body', '')
                inpt['bodyreference'] = inpt_def.get('bodyreference', '')
                the_inputs[identifier].append(inpt)
                continue

            if data_type == 'bbox':
                # Using OWSlib BoundingBox
                from owslib.ows import BoundingBox
                bbox_datas = inpt_def
                for bbox_data in bbox_datas:
                    bbox_data_el = bbox_data
                    bbox = BoundingBox(bbox_data_el)
                    the_inputs[identifier].append(bbox)
                    LOGGER.debug("parse bbox: {},{},{},{}".format(bbox.minx, bbox.miny, bbox.maxx, bbox.maxy))
    return the_inputs


def get_output_from_dict(output_ids, raw):
    the_output = {}
    if isinstance(output_ids, dict):
        pass
    elif isinstance(output_ids, (tuple, list)):
        output_ids = {x: {} for x in output_ids}
    else:
        output_ids = {output_ids: {}}
        raw = True  # single non-dict output means raw output
    for identifier, output_el in output_ids.items():
        if isinstance(output_el, list):
            output_el = output_el[0]
        outpt = {}
        outpt[identifier] = ''
        outpt['mimetype'] = output_el.get('mimeType', None)
        outpt['encoding'] = output_el.get('encoding', '')
        outpt['schema'] = output_el.get('schema', '')
        outpt['uom'] = output_el.get('uom', '')
        if not raw:
            outpt['asReference'] = output_el.get('asReference', 'false')
        the_output[identifier] = outpt

    return raw, the_output


def get_data_from_kvp(data, part=None):
    """Get execute DataInputs and ResponseDocument from URL (key-value-pairs) encoding
    :param data: key:value pair list of the datainputs and responseDocument parameter
    :param part: DataInputs or similar part of input url
    """

    the_data = {}

    if data is None:
        return None

    for d in data.split(";"):
        try:
            io = {}
            fields = d.split('@')

            # First field is identifier and its value
            (identifier, val) = fields[0].split("=")
            io['identifier'] = identifier
            io['data'] = unquote(val)

            # Get the attributes of the data
            for attr in fields[1:]:
                (attribute, attr_val) = attr.split('=', 1)
                if attribute == 'xlink:href':
                    io['href'] = unquote(attr_val)
                else:
                    io[attribute] = unquote(attr_val)

            # Add the input/output with all its attributes and values to the
            # dictionary
            if part == 'DataInputs':
                if identifier not in the_data:
                    the_data[identifier] = []
                the_data[identifier].append(io)
            else:
                the_data[identifier] = io
        except Exception as e:
            LOGGER.warning(e)
            the_data[d] = {'identifier': d, 'data': ''}

    return the_data


def _check_version(version):
    """ check given version
    """
    if version not in ['1.0.0', '2.0.0']:
        return False
    else:
        return True


def _get_get_param(http_request, key, default=None, aslist=False):
    """Returns value from the key:value pair, of the HTTP GET request, for
    example 'service' or 'request'

    :param http_request: http_request object
    :param key: key value you need to dig out of the HTTP GET request
    """

    key = key.lower()
    value = default
    # http_request.args.keys will make + sign disappear in GET url if not
    # urlencoded
    for k in http_request.args.keys():
        if k.lower() == key:
            value = http_request.args.get(k)
            if aslist:
                value = value.split(",")

    return value


def _get_dataelement_value(value_el):
    """Return real value of XML Element (e.g. convert Element.FeatureCollection
    to String
    """

    if isinstance(value_el, lxml.etree._Element):
        return lxml.etree.tostring(value_el, encoding=str)
    else:
        return value_el


def _get_rawvalue_value(data, encoding=None):
    """Return real value of CDATA section"""

    try:
        LOGGER.debug("encoding={}".format(encoding))
        if encoding is None or encoding == "":
            return data
        elif encoding == "utf-8":
            return data
        elif encoding == 'base64':
            return base64.b64decode(data)
        return base64.b64decode(data)
    except Exception:
        LOGGER.warning("failed to decode base64")
        return data


def _get_reference_header(header_element):
    """Parses ReferenceInput Header element
    """
    header = {}
    header['key'] = header_element.attrib('key')
    header['value'] = header_element.attrib('value')
    return header


def _get_reference_body(body_element):
    """Parses ReferenceInput Body element
    """

    body = None
    if len(body_element.getchildren()) > 0:
        value_el = body_element[0]
        body = _get_dataelement_value(value_el)
    else:
        body = _get_rawvalue_value(body_element.text)

    return body


def _get_reference_bodyreference(referencebody_element):
    """Parse ReferenceInput BodyReference element
    """
    return referencebody_element.attrib.get(
        '{http://www.w3.org/1999/xlink}href', '')
