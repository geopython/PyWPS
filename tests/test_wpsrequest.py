##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

from basic import TestBase
from pywps.app import WPSRequest
import tempfile
import datetime
import json

from pywps.inout.literaltypes import AnyValue


class WPSRequestTest(TestBase):

    def setUp(self):
        super().setUp()

        self.request = WPSRequest()
        self.tempfile = tempfile.mktemp(dir=self.tmpdir.name)

        x = open(self.tempfile, 'w')
        x.write("ahoj")
        x.close()

    def test_json_in(self):

        obj = {
            'operation': 'getcapabilities',
            'version': '1.0.0',
            'language': 'eng',
            'identifier': 'ahoj',
            'identifiers': 'ahoj',  # TODO: why identifierS?
            'store_execute': True,
            'status': True,
            'lineage': True,
            'inputs': {
                'myin': [{
                    'identifier': 'myin',
                    'type': 'complex',
                    'supported_formats': [{
                        'mime_type': 'tralala'
                    }],
                    'file': self.tempfile,
                    'data_format': {'mime_type': 'tralala'}
                }],
                'myliteral': [{
                    'identifier': 'myliteral',
                    'type': 'literal',
                    'data_type': 'integer',
                    'allowed_values': [{'type': 'anyvalue'}],
                    'data': 1
                }]
            },
            'outputs': {},
            'raw': False
        }

        self.request = WPSRequest()
        self.request.json = obj

        self.assertEqual(self.request.inputs['myliteral'][0]['data'], 1, 'Data are in the file')

    def test_json_inout_datetime(self):
        obj = {
            'operation': 'getcapabilities',
            'version': '1.0.0',
            'language': 'eng',
            'identifier': 'moinmoin',
            'identifiers': 'moinmoin',  # TODO: why identifierS?
            'store_execute': True,
            'status': True,
            'lineage': True,
            'inputs': {
                'datetime': [{
                    'identifier': 'datetime',
                    'type': 'literal',
                    'data_type': 'dateTime',
                    'data': '2017-04-20T12:00:00',
                    'allowed_values': [{'type': 'anyvalue'}],
                }],
                'date': [{
                    'identifier': 'date',
                    'type': 'literal',
                    'data_type': 'date',
                    'data': '2017-04-20',
                    'allowed_values': [{'type': 'anyvalue'}],
                }],
                'time': [{
                    'identifier': 'time',
                    'type': 'literal',
                    'data_type': 'time',
                    'data': '09:00:00',
                    'allowed_values': [{'type': 'anyvalue'}],
                }],
            },
            'outputs': {},
            'raw': False
        }

        self.request = WPSRequest()
        self.request.json = obj

        self.assertEqual(self.request.inputs['datetime'][0]['data'], '2017-04-20T12:00:00', 'Datatime set')
        self.assertEqual(self.request.inputs['date'][0]['data'], '2017-04-20', 'Data set')
        self.assertEqual(self.request.inputs['time'][0]['data'], '09:00:00', 'Time set')

        # dump to json and reload
        dump = self.request.json
        self.request.json = json.loads(dump)

        self.assertEqual(self.request.inputs['datetime'][0]['data'], '2017-04-20T12:00:00', 'Datatime set')
        self.assertEqual(self.request.inputs['date'][0]['data'], '2017-04-20', 'Data set')
        self.assertEqual(self.request.inputs['time'][0]['data'], '09:00:00', 'Time set')

    def test_json_inout_bbox(self):
        obj = {
            'operation': 'getcapabilities',
            'version': '1.0.0',
            'language': 'eng',
            'identifier': 'arghhhh',
            'identifiers': 'arghhhh',  # TODO: why identifierS?
            'store_execute': True,
            'status': True,
            'lineage': True,
            'inputs': {
                'bbox': [{
                    'identifier': 'bbox',
                    'type': 'bbox',
                    'bbox': '6.117602,46.176194,6.22283,46.275832',
                    'crs': 'urn:ogc:def:crs:EPSG::4326',
                    'crss': ['epsg:4326'],
                    'dimensions': 2,
                    'translations': None
                }],
            },
            'outputs': {},
            'raw': False
        }

        self.request = WPSRequest()
        self.request.json = obj

        self.assertEqual(self.request.inputs['bbox'][0]['bbox'], '6.117602,46.176194,6.22283,46.275832', 'BBox data set')
        self.assertTrue(isinstance(self.request.inputs['bbox'][0]['crs'], str), 'CRS is a string')
        self.assertEqual(self.request.inputs['bbox'][0]['crs'], 'urn:ogc:def:crs:EPSG::4326', 'CRS data correctly parsed')

        # dump to json and reload
        dump = self.request.json
        self.request.json = json.loads(dump)

        self.assertEqual(self.request.inputs['bbox'][0]['bbox'], '6.117602,46.176194,6.22283,46.275832', 'BBox data set')
        self.assertTrue(isinstance(self.request.inputs['bbox'][0]['crs'], str), 'CRS is a string')
        self.assertEqual(self.request.inputs['bbox'][0]['crs'], 'urn:ogc:def:crs:EPSG::4326', 'CRS data correctly parsed')


def load_tests(loader=None, tests=None, pattern=None):
    import unittest

    if not loader:
        loader = unittest.TestLoader()
    suite_list = [
        loader.loadTestsFromTestCase(WPSRequestTest)
    ]
    return unittest.TestSuite(suite_list)
