##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################
import json
import tempfile
from pathlib import Path

import lxml.etree
import requests
from werkzeug.test import Client
from werkzeug.wrappers import BaseResponse
from pywps import __version__
from pywps import Process
from pywps.inout import LiteralInput, LiteralOutput, ComplexInput, ComplexOutput, BoundingBoxInput, BoundingBoxOutput
from pywps.inout import Format
from pywps.app.Common import Metadata, MetadataUrl

import re

import logging

logging.disable(logging.CRITICAL)


def service_ok(url, timeout=5):
    try:
        resp = requests.get(url, timeout=timeout)
        if 'html' in resp.headers['content-type']:
            ok = False
        else:
            ok = resp.ok
    except requests.exceptions.ReadTimeout:
        ok = False
    except requests.exceptions.ConnectTimeout:
        ok = False
    except Exception:
        ok = False
    return ok


class DocExampleProcess(Process):
    """This first line is going to be skipped by the :skiplines:1 option.

    Notes
    -----

    This is additional documentation that can be added following the Numpy docstring convention.
    """

    def __init__(self):
        inputs = [
            LiteralInput(
                'literal_input', "Literal input title", 'integer', abstract="Literal input value abstract.",
                min_occurs=0, max_occurs=1, uoms=['meters', 'feet'], default=1
            ),
            LiteralInput('date_input', 'The title is shown when no abstract is provided.', 'date',
                         allowed_values=['2000-01-01', '2018-01-01']),
            ComplexInput('complex_input', 'Complex input title',
                         [Format('application/json'), Format('application/x-netcdf')],
                         abstract="Complex input abstract.", ),
            BoundingBoxInput('bb_input', 'BoundingBox input title', ['EPSG:4326', ],
                             metadata=[Metadata('EPSG.io', 'http://epsg.io/'), ]),
        ]
        outputs = [
            LiteralOutput(
                'literal_output', 'Literal output title', 'boolean', abstract='Boolean output abstract.'
            ),
            ComplexOutput('complex_output', 'Complex output', [Format('text/plain'), ], ),
            BoundingBoxOutput('bb_output', 'BoundingBox output title', ['EPSG:4326', ])
        ]

        super(DocExampleProcess, self).__init__(
            self._handler,
            identifier='doc_example_process_identifier',
            title="Process title",
            abstract="Multiline process abstract.",
            version="4.0",
            metadata=[Metadata('PyWPS docs', 'https://pywps.org'),
                      Metadata('NumPy docstring conventions',
                               'https://github.com/numpy/numpy/blob/master/doc/HOWTO_DOCUMENT.rst.txt'),
                      MetadataUrl('Duplicate label', 'http://one.example.com', anonymous=True),
                      MetadataUrl('Duplicate label', 'http://two.example.com', anonymous=True),
                      ],
            inputs=inputs,
            outputs=outputs,
        )

    def _handler(self, request, response):
        pass


class WpsClient(Client):

    def post_xml(self, *args, **kwargs):
        return True
        doc = kwargs.pop('doc')
        data = lxml.etree.tostring(doc, pretty_print=True)
        kwargs['data'] = data
        return self.post(*args, **kwargs)

    def post_json(self, *args, **kwargs):
        doc = kwargs.pop('doc')
        # data = json.dumps(doc, indent=2)
        # kwargs['data'] = data
        kwargs['json'] = doc
        # kwargs['content_type'] = 'application/json'  # input is json, redundant as it's deducted from the json kwarg
        # kwargs['mimetype'] = 'application/json'  # output is json
        kwargs['environ_base'] = {'HTTP_ACCEPT': 'application/json'}  # output is json
        return self.post(*args, **kwargs)


class WpsTestResponse(BaseResponse):

    def __init__(self, *args):
        super(WpsTestResponse, self).__init__(*args)
        if re.match(r'text/xml(;\s*charset=.*)?', self.headers.get('Content-Type')):
            self.xml = lxml.etree.fromstring(self.get_data())

    def xpath(self, path):
        version = self.xml.attrib["version"]
        if version == "2.0.0":
            from pywps import namespaces200
            namespaces = namespaces200
        else:
            from pywps import namespaces100
            namespaces = namespaces100
        return self.xml.xpath(path, namespaces=namespaces)

    def xpath_text(self, path):
        return ' '.join(e.text for e in self.xpath(path))


def client_for(service):
    return WpsClient(service, WpsTestResponse)


def assert_response_accepted(resp):
    assert resp.status_code == 200
    assert re.match(r'text/xml(;\s*charset=.*)?', resp.headers['Content-Type'])
    success = resp.xpath_text('/wps:ExecuteResponse'
                              '/wps:Status'
                              '/wps:ProcessAccepted')
    assert success is not None
    # TODO: assert status URL is present


def assert_process_started(resp):
    assert resp.status_code == 200
    assert re.match(r'text/xml(;\s*charset=.*)?', resp.headers['Content-Type'])
    success = resp.xpath_text('/wps:ExecuteResponse'
                              '/wps:Status'
                              'ProcessStarted')
    # Is it still like this in PyWPS-4 ?
    assert success.split[0] == "processstarted"


def assert_response_success_json(resp, expected_data):
    assert resp.status_code == 200

    content_type = resp.headers['Content-Type']
    expected_contect_type = 'application/json'
    re_content_type = rf'{expected_contect_type}(;\s*charset=.*)?'
    assert re.match(re_content_type, content_type)

    data = json.loads(resp.data)

    success = data['status']['status']
    assert success == 'succeeded'

    if expected_data:
        outputs = data['outputs']
        assert outputs == expected_data


def assert_response_success(resp):
    assert resp.status_code == 200
    content_type = resp.headers['Content-Type']
    expected_contect_type = 'text/xml'
    re_content_type = rf'{expected_contect_type}(;\s*charset=.*)?'
    assert re.match(re_content_type, content_type)
    success = resp.xpath('/wps:ExecuteResponse/wps:Status/wps:ProcessSucceeded')
    assert len(success) == 1


def assert_process_exception(resp, code=None):
    assert resp.status_code == 400
    assert re.match(r'text/xml(;\s*charset=.*)?', resp.headers['Content-Type'])
    elem = resp.xpath('/ows:ExceptionReport'
                      '/ows:Exception')
    assert elem[0].attrib['exceptionCode'] == code


def assert_pywps_version(resp):
    # get first child of root element
    root_firstchild = resp.xpath('/*')[0].getprevious()
    assert isinstance(root_firstchild, lxml.etree._Comment)
    tokens = root_firstchild.text.split()
    assert len(tokens) == 2
    assert tokens[0] == 'PyWPS'
    assert tokens[1] == __version__


def assert_wps_version(response, version="1.0.0"):
    elem = response.xpath('/wps:Capabilities'
                          '/ows:ServiceIdentification'
                          '/ows:ServiceTypeVersion')
    found_version = elem[0].text
    assert version == found_version
    tmp = Path(tempfile.mkdtemp())
    with open(tmp / "out.xml", "wb") as out:
        out.writelines(response.response)
