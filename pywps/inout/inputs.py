##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

import re
import lxml.etree as etree

from pywps.app.Common import Metadata
from pywps.exceptions import InvalidParameterValue
from pywps.inout.formats import Format
from pywps.inout import basic
from copy import deepcopy
from pywps.validator.mode import MODE
from pywps.inout.literaltypes import AnyValue, NoValue, ValuesReference, AllowedValue

CDATA_PATTERN = re.compile(r'<!\[CDATA\[(.*?)\]\]>')


class BoundingBoxInput(basic.BBoxInput):

    """
    :param string identifier: The name of this input.
    :param string title: Human readable title
    :param string abstract: Longer text description
    :param crss: List of supported coordinate reference
                 system (e.g. ['EPSG:4326'])
    :param list keywords: Keywords that characterize this input.
    :param int dimensions: 2 or 3
    :param str workdir: working directory, to save temporary file objects in.
    :param list metadata: TODO
    :param int min_occurs: how many times this input occurs
    :param int max_occurs: how many times this input occurs
    :param metadata: List of metadata advertised by this process. They
                     should be :class:`pywps.app.Common.Metadata` objects.
    :param dict[str,dict[str,str]] translations: The first key is the RFC 4646 language code,
        and the nested mapping contains translated strings accessible by a string property.
        e.g. {"fr-CA": {"title": "Mon titre", "abstract": "Une description"}}
    """

    def __init__(self, identifier, title, crss=None, abstract='', keywords=[],
                 dimensions=2, workdir=None, metadata=[], min_occurs=1,
                 max_occurs=1,
                 mode=MODE.NONE,
                 default=None, default_type=basic.SOURCE_TYPE.DATA,
                 translations=None):

        basic.BBoxInput.__init__(self, identifier, title=title, crss=crss,
                                 abstract=abstract, keywords=keywords,
                                 dimensions=dimensions, workdir=workdir, metadata=metadata,
                                 min_occurs=min_occurs, max_occurs=max_occurs,
                                 mode=mode, default=default,
                                 default_type=default_type,
                                 translations=translations)

        self.as_reference = False

    @property
    def json(self):
        """Get JSON representation of the input
        """
        return {
            'identifier': self.identifier,
            'title': self.title,
            'abstract': self.abstract,
            'keywords': self.keywords,
            'type': 'bbox',
            'crs': self.crs,
            'crss': self.crss,
            'metadata': [m.json for m in self.metadata],
            'bbox': self.data,
            'll': self.ll,
            'ur': self.ur,
            'dimensions': self.dimensions,
            'workdir': self.workdir,
            'mode': self.valid_mode,
            'min_occurs': self.min_occurs,
            'max_occurs': self.max_occurs,
            'translations': self.translations,
        }

    @classmethod
    def from_json(cls, json_input):
        instance = cls(
            identifier=json_input['identifier'],
            title=json_input['title'],
            abstract=json_input['abstract'],
            crss=json_input['crss'],
            keywords=json_input['keywords'],
            metadata=[Metadata.from_json(data) for data in json_input.get('metadata', [])],
            dimensions=json_input['dimensions'],
            workdir=json_input['workdir'],
            mode=json_input['mode'],
            min_occurs=json_input['min_occurs'],
            max_occurs=json_input['max_occurs'],
            translations=json_input.get('translations'),
        )
        instance.data = json_input['bbox']

        return instance

    def clone(self):
        """Create copy of yourself
        """
        return deepcopy(self)


class ComplexInput(basic.ComplexInput):
    """
    Complex data input

    :param str identifier: The name of this input.
    :param str title: Title of the input
    :param pywps.inout.formats.Format supported_formats: List of supported
                                                          formats
    :param pywps.inout.formats.Format data_format: default data format
    :param str abstract: Input abstract
    :param list keywords: Keywords that characterize this input.
    :param str workdir: working directory, to save temporary file objects in.
    :param list metadata: TODO
    :param int min_occurs: minimum occurrence
    :param int max_occurs: maximum occurrence
    :param pywps.validator.mode.MODE mode: validation mode (none to strict)
    :param dict[str,dict[str,str]] translations: The first key is the RFC 4646 language code,
        and the nested mapping contains translated strings accessible by a string property.
        e.g. {"fr-CA": {"title": "Mon titre", "abstract": "Une description"}}
    """

    def __init__(self, identifier, title, supported_formats,
                 data_format=None, abstract='', keywords=[], workdir=None, metadata=[], min_occurs=1,
                 max_occurs=1, mode=MODE.NONE,
                 default=None, default_type=basic.SOURCE_TYPE.DATA, translations=None):
        """constructor"""

        basic.ComplexInput.__init__(self, identifier, title=title,
                                    supported_formats=supported_formats,
                                    data_format=data_format, abstract=abstract,
                                    keywords=keywords, workdir=workdir, metadata=metadata,
                                    min_occurs=min_occurs,
                                    max_occurs=max_occurs, mode=mode,
                                    default=default, default_type=default_type, translations=translations)

        self.as_reference = False
        self.method = ''

    @property
    def json(self):
        """Get JSON representation of the input
        """
        data = {
            'identifier': self.identifier,
            'title': self.title,
            'abstract': self.abstract,
            'keywords': self.keywords,
            'metadata': [m.json for m in self.metadata],
            'type': 'complex',
            'data_format': self.data_format.json,
            'asreference': self.as_reference,
            'supported_formats': [frmt.json for frmt in self.supported_formats],
            'workdir': self.workdir,
            'mode': self.valid_mode,
            'min_occurs': self.min_occurs,
            'max_occurs': self.max_occurs,
            'translations': self.translations,
        }

        if self.prop == 'file':
            data['file'] = self.file
        elif self.prop == 'url':
            data["href"] = self.url
        elif self.prop == 'data':
            data = self._json_data(data)
        elif self.prop == 'stream':
            # we store the stream in the data property
            data = self._json_data(data)

        if self.data_format:
            if self.data_format.mime_type:
                data['mimetype'] = self.data_format.mime_type
            if self.data_format.encoding:
                data['encoding'] = self.data_format.encoding
            if self.data_format.schema:
                data['schema'] = self.data_format.schema

        return data

    @classmethod
    def from_json(cls, json_input):
        data_format = json_input.get('data_format')
        if data_format is not None:
            data_format = Format(
                schema=data_format.get('schema'),
                extension=data_format.get('extension'),
                mime_type=data_format.get('mime_type', ""),
                encoding=data_format.get('encoding')
            )
        instance = cls(
            identifier=json_input['identifier'],
            title=json_input.get('title'),
            abstract=json_input.get('abstract'),
            keywords=json_input.get('keywords', []),
            workdir=json_input.get('workdir'),
            metadata=[Metadata.from_json(data) for data in json_input.get('metadata', [])],
            data_format=data_format,
            supported_formats=[
                Format(
                    schema=infrmt.get('schema'),
                    extension=infrmt.get('extension'),
                    mime_type=infrmt.get('mime_type'),
                    encoding=infrmt.get('encoding')
                ) for infrmt in json_input.get('supported_formats', [])
            ],
            mode=json_input.get('mode', MODE.NONE),
            translations=json_input.get('translations'),
        )
        instance.as_reference = json_input.get('asreference', False)
        if json_input.get('file'):
            instance.file = json_input['file']
        elif json_input.get('href'):
            instance.url = json_input['href']
        elif json_input.get('data'):
            data = json_input['data']
            # remove cdata tag if it exists (issue #553)
            match = CDATA_PATTERN.match(data)
            if match:
                data = match.group(1)
            instance.data = data

        return instance

    def _json_data(self, data):
        """Return Data node
        """

        if self.data:

            if self.data_format.mime_type in ["application/xml", "application/gml+xml", "text/xml"]:
                # Note that in a client-server round trip, the original and returned file will not be identical.
                data_doc = etree.parse(self.file)
                data["data"] = etree.tostring(data_doc, pretty_print=True).decode('utf-8')

            else:
                if self.data_format.encoding == 'base64':
                    data["data"] = self.base64.decode('utf-8')

                else:
                    # Otherwise we assume all other formats are unsafe and need to be enclosed in a CDATA tag.
                    if isinstance(self.data, bytes):
                        out = self.data.encode(self.data_format.encoding or 'utf-8')
                    else:
                        out = self.data

                    data["data"] = '<![CDATA[{}]]>'.format(out)

        return data

    def clone(self):
        """Create copy of yourself
        """
        return deepcopy(self)


class LiteralInput(basic.LiteralInput):
    """
    :param str identifier: The name of this input.
    :param str title: Title of the input
    :param pywps.inout.literaltypes.LITERAL_DATA_TYPES data_type: data type
    :param str workdir: working directory, to save temporary file objects in.
    :param str abstract: Input abstract
    :param list keywords: Keywords that characterize this input.
    :param list metadata: TODO
    :param str uoms: units
    :param int min_occurs: minimum occurence
    :param int max_occurs: maximum occurence
    :param pywps.validator.mode.MODE mode: validation mode (none to strict)
    :param pywps.inout.literaltypes.AnyValue allowed_values: or :py:class:`pywps.inout.literaltypes.AllowedValue` object
    :param metadata: List of metadata advertised by this process. They
                     should be :class:`pywps.app.Common.Metadata` objects.
    :param dict[str,dict[str,str]] translations: The first key is the RFC 4646 language code,
        and the nested mapping contains translated strings accessible by a string property.
        e.g. {"fr-CA": {"title": "Mon titre", "abstract": "Une description"}}
    """

    def __init__(self, identifier, title=None, data_type=None, workdir=None, abstract='', keywords=[],
                 metadata=[], uoms=None,
                 min_occurs=1, max_occurs=1,
                 mode=MODE.SIMPLE, allowed_values=None,
                 default=None, default_type=basic.SOURCE_TYPE.DATA, translations=None):
        """Constructor
        """
        data_type = data_type or 'string'
        basic.LiteralInput.__init__(self, identifier, title=title,
                                    data_type=data_type, workdir=workdir, abstract=abstract,
                                    keywords=keywords, metadata=metadata,
                                    uoms=uoms, min_occurs=min_occurs,
                                    max_occurs=max_occurs, mode=mode,
                                    allowed_values=allowed_values,
                                    default=default, default_type=default_type,
                                    translations=translations)

        self.as_reference = False

    @property
    def json(self):
        """Get JSON representation of the input
        """
        data = {
            'identifier': self.identifier,
            'title': self.title,
            'abstract': self.abstract,
            'keywords': self.keywords,
            'metadata': [m.json for m in self.metadata],
            'type': 'literal',
            'data_type': self.data_type,
            'workdir': self.workdir,
            'allowed_values': [value.json for value in self.allowed_values],
            'any_value': self.any_value,
            'mode': self.valid_mode,
            'min_occurs': self.min_occurs,
            'max_occurs': self.max_occurs,
            'translations': self.translations,
            # other values not set in the constructor
        }
        if self.values_reference:
            data['values_reference'] = self.values_reference.json
        if self.uoms:
            data["uoms"] = [uom.json for uom in self.uoms]
        if self.uom:
            data["uom"] = self.uom.json
        if self.data is not None:
            data['data'] = str(self.data)
        return data

    @classmethod
    def from_json(cls, json_input):
        allowed_values = []
        for allowed_value in json_input.get('allowed_values', []):
            if allowed_value['type'] == 'anyvalue':
                allowed_values.append(AnyValue())
            elif allowed_value['type'] == 'novalue':
                allowed_values.append(NoValue())
            elif allowed_value['type'] == 'valuesreference':
                allowed_values.append(ValuesReference.from_json(allowed_value))
            elif allowed_value['type'] == 'allowedvalue':
                allowed_values.append(AllowedValue.from_json(allowed_value))

        json_input_copy = deepcopy(json_input)
        json_input_copy['allowed_values'] = allowed_values
        json_input_copy['uoms'] = [
            basic.UOM(uom['uom'], uom['reference'])
            for uom in json_input.get('uoms', [])
        ]

        data = json_input_copy.pop('data', None)
        uom = json_input_copy.pop('uom', None)
        metadata = json_input_copy.pop('metadata', [])
        json_input_copy.pop('type', None)
        json_input_copy.pop('any_value', None)
        json_input_copy.pop('values_reference', None)

        instance = cls(**json_input_copy)

        instance.metadata = [Metadata.from_json(d) for d in metadata]
        instance.data = data
        if uom:
            instance.uom = basic.UOM(uom['uom'], uom['reference'])

        return instance

    def clone(self):
        """Create copy of yourself
        """
        return deepcopy(self)


def input_from_json(json_data):
    data_type = json_data.get('type', 'literal')
    if data_type in ['complex', 'reference']:
        inpt = ComplexInput.from_json(json_data)
    elif data_type == 'literal':
        inpt = LiteralInput.from_json(json_data)
    elif data_type == 'bbox':
        inpt = BoundingBoxInput.from_json(json_data)
    else:
        raise InvalidParameterValue("Input type not recognized: {}".format(data_type))

    return inpt
