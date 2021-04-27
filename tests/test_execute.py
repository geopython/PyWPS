##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

import unittest
import pytest
import lxml.etree
import json
import tempfile
import os.path
from pywps import Service, Process, LiteralOutput, LiteralInput,\
    BoundingBoxOutput, BoundingBoxInput, Format, ComplexInput, ComplexOutput, FORMATS
from pywps.validator.base import emptyvalidator
from pywps.validator.complexvalidator import validategml
from pywps.validator.mode import MODE
from pywps.exceptions import InvalidParameterValue
from pywps import get_inputs_from_xml, get_output_from_xml
from pywps import E, get_ElementMakerForVersion
from pywps.app.basic import get_xpath_ns
from pywps.tests import client_for, assert_response_success, assert_response_success_json
from pywps import configuration

from io import StringIO
from owslib.ows import BoundingBox

try:
    import netCDF4
except ImportError:
    WITH_NC4 = False
else:
    WITH_NC4 = True

DATA_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'data')

VERSION = "1.0.0"

WPS, OWS = get_ElementMakerForVersion(VERSION)

xpath_ns = get_xpath_ns(VERSION)


def create_ultimate_question():
    def handler(request, response):
        response.outputs['outvalue'].data = '42'
        return response

    return Process(handler=handler,
                   identifier='ultimate_question',
                   title='Ultimate Question',
                   outputs=[LiteralOutput('outvalue', 'Output Value', data_type='string')])


def create_greeter():
    def greeter(request, response):
        name = request.inputs['name'][0].data
        assert isinstance(name, str)
        response.outputs['message'].data = "Hello {}!".format(name)
        return response

    return Process(handler=greeter,
                   identifier='greeter',
                   title='Greeter',
                   inputs=[LiteralInput('name', 'Input name', data_type='string')],
                   outputs=[LiteralOutput('message', 'Output message', data_type='string')])


def create_translated_greeter():
    def greeter(request, response):
        name = request.inputs['name'][0].data
        response.outputs['message'].data = "Hello {}!".format(name)
        return response

    return Process(
        handler=greeter,
        identifier='greeter',
        title='Greeter',
        abstract='Say hello',
        inputs=[
            LiteralInput(
                'name',
                'Input name',
                data_type='string',
                abstract='Input description',
                translations={"fr-CA": {"title": "Nom", "abstract": "Description"}},
            )
        ],
        outputs=[
            LiteralOutput(
                'message',
                'Output message',
                data_type='string',
                abstract='Output description',
                translations={"fr-CA": {"title": "Message de retour", "abstract": "Description"}},
            )
        ],
        translations={"fr-CA": {"title": "Salutations", "abstract": "Dire allô"}},
    )


def create_bbox_process():
    def bbox_process(request, response):
        coords = request.inputs['mybbox'][0].data
        assert isinstance(coords, list)
        assert len(coords) == 4
        assert coords[0] == 15.0
        response.outputs['outbbox'].data = coords
        return response

    return Process(handler=bbox_process,
                   identifier='my_bbox_process',
                   title='Bbox process',
                   inputs=[BoundingBoxInput('mybbox', 'Input name', ["EPSG:4326"])],
                   outputs=[BoundingBoxOutput('outbbox', 'Output message', ["EPSG:4326"])])


def create_complex_proces():
    def complex_proces(request, response):
        response.outputs['complex'].data = request.inputs['complex'][0].data
        return response

    frmt = Format(mime_type='application/gml', extension=".gml")  # this is unknown mimetype

    return Process(handler=complex_proces,
                   identifier='my_complex_process',
                   title='Complex process',
                   inputs=[
                       ComplexInput(
                           'complex',
                           'Complex input',
                           default="DEFAULT COMPLEX DATA",
                           supported_formats=[frmt])
                   ],
                   outputs=[
                       ComplexOutput(
                           'complex',
                           'Complex output',
                           supported_formats=[frmt])
                   ])


def create_complex_nc_process():
    def complex_proces(request, response):
        from pywps.dependencies import netCDF4 as nc
        url = request.inputs['dods'][0].url
        with nc.Dataset(url) as D:
            response.outputs['conventions'].data = D.Conventions

        response.outputs['outdods'].url = url
        response.outputs['ncraw'].file = os.path.join(DATA_DIR, 'netcdf', 'time.nc')
        response.outputs['ncraw'].data_format = FORMATS.NETCDF
        return response

    return Process(handler=complex_proces,
                   identifier='my_opendap_process',
                   title='Opendap process',
                   inputs=[
                       ComplexInput(
                           'dods',
                           'Opendap input',
                           supported_formats=[Format('DODS'), Format('NETCDF')],
                           #   mode=MODE.STRICT
                       )
                   ],
                   outputs=[
                       LiteralOutput(
                           'conventions',
                           'NetCDF convention',
                       ),
                       ComplexOutput('outdods', 'Opendap output',
                                     supported_formats=[FORMATS.DODS, ],
                                     as_reference=True),
                       ComplexOutput('ncraw', 'NetCDF raw data output',
                                     supported_formats=[FORMATS.NETCDF, ],
                                     as_reference=False)
                   ])


def create_mimetype_process():
    def _handler(request, response):
        response.outputs['mimetype'].data = response.outputs['mimetype'].data_format.mime_type
        return response

    frmt_txt = Format(mime_type='text/plain')
    frmt_txt2 = Format(mime_type='text/plain+test')

    return Process(handler=_handler,
                   identifier='get_mimetype_process',
                   title='Get mimeType process',
                   inputs=[],
                   outputs=[
                       ComplexOutput(
                           'mimetype',
                           'mimetype of requested output',
                           supported_formats=[frmt_txt, frmt_txt2])
                   ])


def create_metalink_process():
    from .processes.metalinkprocess import MultipleOutputs
    return MultipleOutputs()


def get_output(doc):
    """Return the content of LiteralData, Reference or ComplexData."""

    output = {}
    for output_el in xpath_ns(doc, '/wps:ExecuteResponse'
                                   '/wps:ProcessOutputs/wps:Output'):
        [identifier_el] = xpath_ns(output_el, './ows:Identifier')

        lit_el = xpath_ns(output_el, './wps:Data/wps:LiteralData')
        if lit_el != []:
            output[identifier_el.text] = lit_el[0].text

        ref_el = xpath_ns(output_el, './wps:Reference')
        if ref_el != []:
            output[identifier_el.text] = ref_el[0].attrib['href']

        data_el = xpath_ns(output_el, './wps:Data/wps:ComplexData')
        if data_el != []:
            if data_el[0].text:
                output[identifier_el.text] = data_el[0].text
            else:  # XML children
                ch = list(data_el[0])[0]
                output[identifier_el.text] = lxml.etree.tostring(ch)

    return output


class ExecuteTest(unittest.TestCase):
    """Test for Exeucte request KVP request"""

    @pytest.mark.xfail(reason="test.opendap.org is offline")
    def test_dods(self):
        if not WITH_NC4:
            self.skipTest('netCDF4 not installed')
        my_process = create_complex_nc_process()
        service = Service(processes=[my_process])

        href = "http://test.opendap.org:80/opendap/netcdf/examples/sresa1b_ncar_ccsm3_0_run1_200001.nc"

        """ # Is this how the request should be written ?
        request_doc = WPS.Execute(
            OWS.Identifier('my_opendap_process'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('dods'),
                    WPS.Reference(
                        WPS.Body('request body'),
                        {'{http://www.w3.org/1999/xlink}href': href},
                        method='POST'
                    )
                    #WPS.Data(WPS.ComplexData(href=href, mime_type='application/x-ogc-dods'))
                    # This form is not supported yet. Should it be ?
                )
            ),
            version='1.0.0'
        )
        resp = client.post_xml(doc=request_doc)
        assert_response_success(resp)
        """

        class FakeRequest():
            identifier = 'my_opendap_process'
            service = 'wps'
            operation = 'execute'
            version = '1.0.0'
            raw = True,
            inputs = {'dods': [{
                'identifier': 'dods',
                'href': href,
            }]}
            store_execute = False
            lineage = False
            outputs = ['conventions']
            language = "en-US"

        request = FakeRequest()

        resp = service.execute('my_opendap_process', request, 'fakeuuid')
        self.assertEqual(resp.outputs['conventions'].data, 'CF-1.0')
        self.assertEqual(resp.outputs['outdods'].url, href)
        self.assertTrue(resp.outputs['outdods'].as_reference)
        self.assertFalse(resp.outputs['ncraw'].as_reference)
        with open(os.path.join(DATA_DIR, 'netcdf', 'time.nc'), 'rb') as f:
            data = f.read()
        self.assertEqual(resp.outputs['ncraw'].data, data)

    def test_input_parser(self):
        """Test input parsing
        """
        my_process = create_complex_proces()
        service = Service(processes=[my_process])
        self.assertEqual(len(service.processes), 1)
        self.assertTrue(service.processes['my_complex_process'])

        class FakeRequest():
            identifier = 'complex_process'
            service = 'wps'
            operation = 'execute'
            version = '1.0.0'
            inputs = {'complex': [{
                'identifier': 'complex',
                'mimeType': 'text/gml',
                'data': 'the data'
            }]}
            language = "en-US"

        request = FakeRequest()

        try:
            service.execute('my_complex_process', request, 'fakeuuid')
        except InvalidParameterValue as e:
            self.assertEqual(e.locator, 'mimeType')

        request.inputs['complex'][0]['mimeType'] = 'application/gml'
        parsed_inputs = service.create_complex_inputs(my_process.inputs[0],
                                                      request.inputs['complex'])

        # TODO parse outputs and their validators too

        self.assertEqual(parsed_inputs[0].data_format.validate, emptyvalidator)

        request.inputs['complex'][0]['mimeType'] = 'application/xml+gml'
        try:
            parsed_inputs = service.create_complex_inputs(my_process.inputs[0],
                                                          request.inputs['complex'])
        except InvalidParameterValue as e:
            self.assertEqual(e.locator, 'mimeType')

        try:
            my_process.inputs[0].data_format = Format(mime_type='application/xml+gml')
        except InvalidParameterValue as e:
            self.assertEqual(e.locator, 'mimeType')

        frmt = Format(mime_type='application/xml+gml', validate=validategml)
        self.assertEqual(frmt.validate, validategml)

        my_process.inputs[0].supported_formats = [frmt]
        my_process.inputs[0].data_format = Format(mime_type='application/xml+gml')
        parsed_inputs = service.create_complex_inputs(my_process.inputs[0],
                                                      request.inputs['complex'])

        self.assertEqual(parsed_inputs[0].data_format.validate, validategml)

    def test_input_default(self):
        """Test input parsing
        """
        my_process = create_complex_proces()
        service = Service(processes=[my_process])
        self.assertEqual(len(service.processes), 1)
        self.assertTrue(service.processes['my_complex_process'])

        class FakeRequest():
            identifier = 'complex_process'
            service = 'wps'
            operation = 'execute'
            version = '1.0.0'
            inputs = {}
            raw = False
            outputs = {}
            store_execute = False
            lineage = False
            language = "en-US"

        request = FakeRequest()
        response = service.execute('my_complex_process', request, 'fakeuuid')
        self.assertEqual(response.outputs['complex'].data, 'DEFAULT COMPLEX DATA')

    def test_output_mimetype(self):
        """Test input parsing
        """
        my_process = create_mimetype_process()
        service = Service(processes=[my_process])
        self.assertEqual(len(service.processes), 1)
        self.assertTrue(service.processes['get_mimetype_process'])

        class FakeRequest():
            def __init__(self, mimetype):
                self.outputs = {'mimetype': {
                    'identifier': 'mimetype',
                    'mimetype': mimetype,
                    'data': 'the data'
                }}

            identifier = 'get_mimetype_process'
            service = 'wps'
            operation = 'execute'
            version = '1.0.0'
            inputs = {}
            raw = False
            store_execute = False
            lineage = False
            language = "en-US"

        # valid mimetype
        request = FakeRequest('text/plain+test')
        response = service.execute('get_mimetype_process', request, 'fakeuuid')
        self.assertEqual(response.outputs['mimetype'].data, 'text/plain+test')

        # non valid mimetype
        request = FakeRequest('text/xml')
        with self.assertRaises(InvalidParameterValue):
            response = service.execute('get_mimetype_process', request, 'fakeuuid')

    def test_metalink(self):
        client = client_for(Service(processes=[create_metalink_process()]))
        resp = client.get('?Request=Execute&identifier=multiple-outputs')
        assert resp.status_code == 400

    def test_missing_process_error(self):
        client = client_for(Service(processes=[create_ultimate_question()]))
        resp = client.get('?Request=Execute&identifier=foo')
        assert resp.status_code == 400

    def test_get_with_no_inputs(self):
        client = client_for(Service(processes=[create_ultimate_question()]))
        resp = client.get('?service=wps&version=1.0.0&Request=Execute&identifier=ultimate_question')
        assert_response_success(resp)

        assert get_output(resp.xml) == {'outvalue': '42'}

    def test_post_with_no_inputs(self):
        request = {
            'identifier': 'ultimate_question',
            'version': '1.0.0'
        }
        result = {'outvalue': '42'}

        client = client_for(Service(processes=[create_ultimate_question()]))
        request_doc = WPS.Execute(
            OWS.Identifier(request['identifier']),
            version=request['version']
        )

        resp = client.post_xml(doc=request_doc)
        assert_response_success(resp)
        assert get_output(resp.xml) == result

        resp = client.post_json(doc=request)
        assert_response_success_json(resp, result)

    def test_post_with_string_input(self):
        client = client_for(Service(processes=[create_greeter()]))
        request_doc = WPS.Execute(
            OWS.Identifier('greeter'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('name'),
                    WPS.Data(WPS.LiteralData('foo'))
                )
            ),
            version='1.0.0'
        )
        resp = client.post_xml(doc=request_doc)
        assert_response_success(resp)
        assert get_output(resp.xml) == {'message': "Hello foo!"}

    def test_bbox(self):
        client = client_for(Service(processes=[create_bbox_process()]))
        request_doc = WPS.Execute(
            OWS.Identifier('my_bbox_process'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('mybbox'),
                    WPS.Data(WPS.BoundingBoxData(
                        OWS.LowerCorner('15.0 50.0'),
                        OWS.UpperCorner('16.0 51.0'),
                    ))
                )
            ),
            version='1.0.0'
        )
        resp = client.post_xml(doc=request_doc)
        assert_response_success(resp)

        [output] = xpath_ns(resp.xml, '/wps:ExecuteResponse'
                                      '/wps:ProcessOutputs/wps:Output')
        self.assertEqual('outbbox', xpath_ns(
            output,
            './ows:Identifier')[0].text)

        lower_corner = xpath_ns(output, './wps:Data/wps:BoundingBoxData/ows:LowerCorner')[0].text
        lower_corner = lower_corner.strip().replace('  ', ' ')
        self.assertEqual('15.0 50.0', lower_corner)

        upper_corner = xpath_ns(output, './wps:Data/wps:BoundingBoxData/ows:UpperCorner')[0].text
        upper_corner = upper_corner.strip().replace('  ', ' ')
        self.assertEqual('16.0 51.0', upper_corner)

    def test_output_response_dataType(self):
        client = client_for(Service(processes=[create_greeter()]))
        request_doc = WPS.Execute(
            OWS.Identifier('greeter'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('name'),
                    WPS.Data(WPS.LiteralData('foo'))
                )
            ),
            version='1.0.0'
        )
        resp = client.post_xml(doc=request_doc)
        el = next(resp.xml.iter('{http://www.opengis.net/wps/1.0.0}LiteralData'))
        assert el.attrib['dataType'] == 'string'


class ExecuteTranslationsTest(unittest.TestCase):

    def setUp(self):
        configuration.get_config_value('server', 'language')
        configuration.CONFIG.set('server', 'language', 'en-US,fr-CA')

    def tearDown(self):
        configuration.CONFIG.set('server', 'language', 'en-US')

    def test_translations(self):
        client = client_for(Service(processes=[create_translated_greeter()]))

        request_doc = WPS.Execute(
            OWS.Identifier('greeter'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('name'),
                    WPS.Data(WPS.LiteralData('foo'))
                )
            ),
            WPS.ResponseForm(
                WPS.ResponseDocument(
                    lineage='true',
                )
            ),
            version='1.0.0',
            language='fr-CA',
        )
        resp = client.post_xml(doc=request_doc)

        assert resp.xpath('/wps:ExecuteResponse/@xml:lang')[0] == "fr-CA"

        process_title = [e.text for e in resp.xpath('//wps:Process/ows:Title')]
        assert process_title == ["Salutations"]
        process_abstract = [e.text for e in resp.xpath('//wps:Process/ows:Abstract')]
        assert process_abstract == ["Dire allô"]

        input_titles = [e.text for e in resp.xpath('//wps:Input/ows:Title')]
        assert input_titles == ["Nom"]
        input_abstract = [e.text for e in resp.xpath('//wps:Input/ows:Abstract')]
        assert input_abstract == ["Description"]

        output_titles = [e.text for e in resp.xpath('//wps:OutputDefinitions/wps:Output/ows:Title')]
        assert output_titles == ["Message de retour"]
        output_abstract = [e.text for e in resp.xpath('//wps:OutputDefinitions/wps:Output/ows:Abstract')]
        assert output_abstract == ["Description"]

        output_titles = [e.text for e in resp.xpath('//wps:ProcessOutputs/wps:Output/ows:Title')]
        assert output_titles == ["Message de retour"]
        output_abstract = [e.text for e in resp.xpath('//wps:ProcessOutputs/wps:Output/ows:Abstract')]
        assert output_abstract == ["Description"]


class ExecuteXmlParserTest(unittest.TestCase):
    """Tests for Execute request XML Parser
    """

    def test_empty(self):
        request_doc = WPS.Execute(OWS.Identifier('foo'))
        assert get_inputs_from_xml(request_doc) == {}

    def test_one_string(self):
        request_doc = WPS.Execute(
            OWS.Identifier('foo'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('name'),
                    WPS.Data(WPS.LiteralData('foo'))),
                WPS.Input(
                    OWS.Identifier('name'),
                    WPS.Data(WPS.LiteralData('bar')))
            ))
        rv = get_inputs_from_xml(request_doc)
        self.assertTrue('name' in rv)
        self.assertEqual(len(rv['name']), 2)
        self.assertEqual(rv['name'][0]['data'], 'foo')
        self.assertEqual(rv['name'][1]['data'], 'bar')

    def test_two_strings(self):
        request_doc = WPS.Execute(
            OWS.Identifier('foo'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('name1'),
                    WPS.Data(WPS.LiteralData('foo'))),
                WPS.Input(
                    OWS.Identifier('name2'),
                    WPS.Data(WPS.LiteralData('bar')))))
        rv = get_inputs_from_xml(request_doc)
        self.assertEqual(rv['name1'][0]['data'], 'foo')
        self.assertEqual(rv['name2'][0]['data'], 'bar')

    def test_complex_input(self):
        the_data = E.TheData("hello world")
        request_doc = WPS.Execute(
            OWS.Identifier('foo'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('name'),
                    WPS.Data(
                        WPS.ComplexData(the_data, mimeType='text/foobar')))))
        rv = get_inputs_from_xml(request_doc)
        self.assertEqual(rv['name'][0]['mimeType'], 'text/foobar')
        rv_doc = lxml.etree.parse(StringIO(rv['name'][0]['data'])).getroot()
        self.assertEqual(rv_doc.tag, 'TheData')
        self.assertEqual(rv_doc.text, 'hello world')

    def test_complex_input_raw_value(self):
        the_data = '{ "plot":{ "Version" : "0.1" } }'

        request_doc = WPS.Execute(
            OWS.Identifier('foo'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('json'),
                    WPS.Data(
                        WPS.ComplexData(the_data, mimeType='application/json')))))
        rv = get_inputs_from_xml(request_doc)
        self.assertEqual(rv['json'][0]['mimeType'], 'application/json')
        json_data = json.loads(rv['json'][0]['data'])
        self.assertEqual(json_data['plot']['Version'], '0.1')

    def test_complex_input_base64_value(self):
        the_data = 'eyAicGxvdCI6eyAiVmVyc2lvbiIgOiAiMC4xIiB9IH0='

        request_doc = WPS.Execute(
            OWS.Identifier('foo'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('json'),
                    WPS.Data(
                        WPS.ComplexData(the_data,
                                        encoding='base64',
                                        mimeType='application/json')))))
        rv = get_inputs_from_xml(request_doc)
        self.assertEqual(rv['json'][0]['mimeType'], 'application/json')
        json_data = json.loads(rv['json'][0]['data'].decode())
        self.assertEqual(json_data['plot']['Version'], '0.1')

    def test_bbox_input(self):
        request_doc = WPS.Execute(
            OWS.Identifier('request'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('bbox'),
                    WPS.Data(
                        WPS.BoundingBoxData(
                            OWS.LowerCorner('40 50'),
                            OWS.UpperCorner('60 70'))))))
        rv = get_inputs_from_xml(request_doc)
        bbox = rv['bbox'][0]
        # assert isinstance(bbox, BoundingBox)
        assert bbox['data'] == ['40', '50', '60', '70']
        # assert bbox.minx == '40'
        # assert bbox.miny == '50'
        # assert bbox.maxx == '60'
        # assert bbox.maxy == '70'

    def test_reference_post_input(self):
        request_doc = WPS.Execute(
            OWS.Identifier('foo'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('name'),
                    WPS.Reference(
                        WPS.Body('request body'),
                        {'{http://www.w3.org/1999/xlink}href': 'http://foo/bar/service'},
                        method='POST'
                    )
                )
            )
        )
        rv = get_inputs_from_xml(request_doc)
        self.assertEqual(rv['name'][0]['href'], 'http://foo/bar/service')
        self.assertEqual(rv['name'][0]['method'], 'POST')
        self.assertEqual(rv['name'][0]['body'], 'request body')

    def test_reference_post_bodyreference_input(self):
        request_doc = WPS.Execute(
            OWS.Identifier('foo'),
            WPS.DataInputs(
                WPS.Input(
                    OWS.Identifier('name'),
                    WPS.Reference(
                        WPS.BodyReference(
                            {'{http://www.w3.org/1999/xlink}href': 'http://foo/bar/reference'}),
                        {'{http://www.w3.org/1999/xlink}href': 'http://foo/bar/service'},
                        method='POST'
                    )
                )
            )
        )
        rv = get_inputs_from_xml(request_doc)
        self.assertEqual(rv['name'][0]['href'], 'http://foo/bar/service')
        self.assertEqual(rv['name'][0]['bodyreference'], 'http://foo/bar/reference')

    def test_build_input_file_name(self):
        from pywps.inout.basic import ComplexInput

        h = ComplexInput('ci')
        h.workdir = workdir = tempfile.mkdtemp()

        self.assertEqual(
            h._build_file_name('http://path/to/test.txt'),
            os.path.join(workdir, 'test.txt'))
        self.assertEqual(
            h._build_file_name('http://path/to/test'),
            os.path.join(workdir, 'test'))
        self.assertEqual(
            h._build_file_name('file://path/to/.config'),
            os.path.join(workdir, '.config'))
        self.assertEqual(
            h._build_file_name('https://path/to/test.txt?token=abc&expires_at=1234567'),
            os.path.join(workdir, 'test.txt'))

        h.supported_formats = [FORMATS.TEXT, ]
        h.data_format = FORMATS.TEXT
        self.assertEqual(
            h._build_file_name('http://path/to/test'),
            os.path.join(workdir, 'test.txt'))

        open(os.path.join(workdir, 'duplicate.html'), 'a').close()
        inpt_filename = h._build_file_name('http://path/to/duplicate.html')
        self.assertTrue(inpt_filename.startswith(os.path.join(workdir, 'duplicate_')))
        self.assertTrue(inpt_filename.endswith('.html'))


def load_tests(loader=None, tests=None, pattern=None):
    if not loader:
        loader = unittest.TestLoader()
    suite_list = [
        loader.loadTestsFromTestCase(ExecuteTest),
        loader.loadTestsFromTestCase(ExecuteTranslationsTest),
        loader.loadTestsFromTestCase(ExecuteXmlParserTest),
    ]
    return unittest.TestSuite(suite_list)
