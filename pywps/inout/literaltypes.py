##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

"""Literaltypes are used for LiteralInputs, to make sure, input data are OK
"""
from urllib.parse import urlparse
from dateutil.parser import parse as date_parser
import datetime
from pywps.exceptions import InvalidParameterValue
from pywps.validator.allowed_value import RANGECLOSURETYPE
from pywps.validator.allowed_value import ALLOWEDVALUETYPE

import logging
LOGGER = logging.getLogger('PYWPS')

LITERAL_DATA_TYPES = ('float', 'boolean', 'integer', 'string',
                      'positiveInteger', 'anyURI', 'time', 'date', 'dateTime',
                      'scale', 'angle',
                      'nonNegativeInteger', None)

# currently we are supporting just ^^^ data types, feel free to add support for
# more
# 'measure', 'angleList',
# 'angle', 'integerList',
# 'positiveIntegerList',
# 'lengthOrAngle', 'gridLength',
# 'measureList', 'lengthList',
# 'gridLengthList', 'scaleList', 'timeList',
# 'nonNegativeInteger', 'length'


class AnyValue(object):
    """Specifies that any value is allowed for this quantity.
    """

    @property
    def value(self):
        return None

    @property
    def json(self):
        return {
            'type': 'anyvalue',
        }

    def __eq__(self, other):
        return isinstance(other, AnyValue) and self.json == other.json


class NoValue(object):
    """No value allowed
    NOTE: not really implemented
    """

    @property
    def value(self):
        return None

    @property
    def json(self):
        return {'type': 'novalue'}

    def __eq__(self, other):
        return isinstance(other, NoValue) and self.json == other.json


class ValuesReference(object):
    """Reference to list of all valid values and/or ranges of values for this quantity.
    NOTE: Validation of values is not implemented.

    :param: reference: URL from which this set of ranges and values can be retrieved
    :param: values_form: Reference to a description of the mimetype, encoding,
        and schema used for this set of values and ranges.
    """

    def __init__(self, reference=None, values_form=None):
        self.reference = reference
        self.values_form = values_form

        if not self.reference:
            raise InvalidParameterValue("values reference is missing.")

    @property
    def value(self):
        return None

    @property
    def json(self):
        return {
            'type': 'valuesreference',
            'reference': self.reference,
            'values_form': self.values_form
        }

    @classmethod
    def from_json(cls, json_input):
        instance = cls(
            reference=json_input['reference'],
            values_form=json_input['values_form'],
        )
        return instance

    def __eq__(self, other):
        return isinstance(other, ValuesReference) and self.json == other.json


class AllowedValue(object):
    """List of all valid values and/or ranges of values for this quantity.
    The values are evaluated in literal validator functions

    :param pywps.validator.allowed_value.ALLOWEDVALUETYPE allowed_type: VALUE or RANGE
    :param value: single value
    :param minval: minimal value in case of Range
    :param maxval: maximal value in case of Range
    :param spacing: spacing in case of Range
    :param pywps.input.literaltypes.RANGECLOSURETYPE range_closure:
    """

    def __init__(self, allowed_type=None, value=None,
                 minval=None, maxval=None, spacing=None,
                 range_closure=RANGECLOSURETYPE.CLOSED):

        self.allowed_type = allowed_type
        self.value = value
        self.minval = minval
        self.maxval = maxval
        self.spacing = spacing
        self.range_closure = range_closure

        if not self.allowed_type:
            # automatically set allowed_type: RANGE or VALUE
            if self.minval or self.maxval or self.spacing:
                self.allowed_type = ALLOWEDVALUETYPE.RANGE
            else:
                self.allowed_type = ALLOWEDVALUETYPE.VALUE

    def __eq__(self, other):
        return isinstance(other, AllowedValue) and self.json == other.json

    @property
    def json(self):
        value = self.value
        if hasattr(value, 'json'):
            value = value.json
        return {
            'type': 'allowedvalue',
            'allowed_type': self.allowed_type,
            'value': value,
            'minval': self.minval,
            'maxval': self.maxval,
            'spacing': self.spacing,
            'range_closure': self.range_closure
        }

    @classmethod
    def from_json(cls, json_input):
        instance = cls(
            allowed_type=json_input['allowed_type'],
            value=json_input['value'],
            minval=json_input['minval'],
            maxval=json_input['maxval'],
            spacing=json_input['spacing'],
            range_closure=json_input['range_closure']
        )
        return instance


ALLOWED_VALUES_TYPES = (AllowedValue, AnyValue, NoValue, ValuesReference)


def get_converter(convertor):
    """function for decoration of convert
    """

    def decorator_selector(data_type, data):
        convert = None
        if data_type in LITERAL_DATA_TYPES:
            if data_type == 'string':
                convert = convert_string
            elif data_type == 'integer':
                convert = convert_integer
            elif data_type == 'float':
                convert = convert_float
            elif data_type == 'boolean':
                convert = convert_boolean
            elif data_type == 'positiveInteger':
                convert = convert_positiveInteger
            elif data_type == 'anyURI':
                convert = convert_anyURI
            elif data_type == 'time':
                convert = convert_time
            elif data_type == 'date':
                convert = convert_date
            elif data_type == 'dateTime':
                convert = convert_datetime
            elif data_type == 'scale':
                convert = convert_scale
            elif data_type == 'angle':
                convert = convert_angle
            elif data_type == 'nonNegativeInteger':
                convert = convert_positiveInteger
            else:
                raise InvalidParameterValue(
                    "Invalid data_type value of LiteralInput "
                    "set to '{}'".format(data_type))
        try:
            return convert(data)
        except ValueError:
            raise InvalidParameterValue(
                "Could not convert value '{}' to format '{}'".format(
                    data, data_type))

    return decorator_selector


@get_converter
def convert(data_type, data):
    """Convert data to target value
    """

    return data_type, data


def convert_boolean(inpt):
    """Return boolean value from input boolean input

    >>> convert_boolean('1')
    True
    >>> convert_boolean('-1')
    True
    >>> convert_boolean('FaLsE')
    False
    >>> convert_boolean('FaLsEx')
    True
    >>> convert_boolean(0)
    False
    """

    val = False
    if str(inpt).lower() in ['false', 'f']:
        val = False
    else:
        try:
            val = int(inpt)
            if val == 0:
                val = False
            else:
                val = True
        except Exception:
            val = True
    return val


def convert_float(inpt):
    """Return float value from inpt

    >>> convert_float('1')
    1.0
    """

    return float(inpt)


def convert_integer(inpt):
    """Return integer value from input inpt

    >>> convert_integer('1.0')
    1
    """

    return int(float(inpt))


def convert_string(inpt):
    """Return string value from input lit_input

    >>> convert_string(1)
    '1'
    """
    return str(inpt)


def convert_positiveInteger(inpt):
    """Return value of input"""

    inpt = convert_integer(inpt)
    if inpt < 0:
        raise InvalidParameterValue(
            'The value "{}" is not of type positiveInteger'.format(inpt))
    else:
        return inpt


def convert_anyURI(inpt):
    """Return value of input

    :rtype: url components
    """
    inpt = convert_string(inpt)
    components = urlparse(inpt)

    if (components[0] and components[1]) or components[0] == 'file':
        return components
    else:
        raise InvalidParameterValue(
            'The value "{}" does not seem to be of type anyURI'.format(inpt))


def convert_time(inpt):
    """Return value of input
    time formating assumed according to ISO standard:

    https://www.w3.org/TR/xmlschema-2/#time

    Examples: 12:00:00

    :rtype: datetime.time object
    """
    if not isinstance(inpt, datetime.time):
        inpt = convert_datetime(inpt).time()
    return inpt


def convert_date(inpt):
    """Return value of input
    date formating assumed according to ISO standard:

    https://www.w3.org/TR/xmlschema-2/#date

    Examples: 2016-09-20

    :rtype: datetime.date object
    """
    if not isinstance(inpt, datetime.date):
        inpt = convert_datetime(inpt).date()
    return inpt


def convert_datetime(inpt):
    """Return value of input
    dateTime formating assumed according to ISO standard:

    * http://www.w3.org/TR/NOTE-datetime
    * https://www.w3.org/TR/xmlschema-2/#dateTime

    Examples: 2016-09-20T12:00:00, 2012-12-31T06:30:00Z,
              2017-01-01T18:00:00+01:00

    :rtype: datetime.datetime object
    """
    # TODO: %z directive works only with python 3
    # time_format = '%Y-%m-%dT%H:%M:%S%z'
    # time_format = '%Y-%m-%dT%H:%M:%S%Z'
    # inpt = time.strptime(convert_string(inpt), time_format)
    if not isinstance(inpt, datetime.datetime):
        inpt = convert_string(inpt)
        inpt = date_parser(inpt)
    return inpt


def convert_scale(inpt):
    """Return value of input"""

    return convert_float(inpt)


def convert_angle(inpt):
    """Return value of input

    return degrees
    """

    inpt = convert_float(inpt)
    return inpt % 360


def make_allowedvalues(allowed_values):
    """convert given value list to AllowedValue objects

    :return: list of pywps.inout.literaltypes.AllowedValue
    """

    new_allowedvalues = []

    if not isinstance(allowed_values, (tuple, list)):
        allowed_values = [allowed_values]

    for value in allowed_values:

        if value in ALLOWED_VALUES_TYPES:
            # value is equal to one of the allowed classes objects
            new_allowedvalues.append(value())
        elif isinstance(value, ALLOWED_VALUES_TYPES):
            # value is an instance of one of the allowed classes
            new_allowedvalues.append(value)

        elif type(value) == tuple or type(value) == list:
            spacing = None
            if len(value) == 2:
                minval = value[0]
                maxval = value[1]
            else:
                minval = value[0]
                spacing = value[1]
                maxval = value[2]
            new_allowedvalues.append(
                AllowedValue(minval=minval, maxval=maxval,
                             spacing=spacing)
            )

        else:
            new_allowedvalues.append(AllowedValue(value=value))

    return new_allowedvalues


def is_anyvalue(value):
    """Check for any value object of given value
    """

    is_av = False

    if value is AnyValue:
        is_av = True
    elif value is None:
        is_av = True
    elif isinstance(value, AnyValue):
        is_av = True
    elif str(value).lower() == 'anyvalue':
        is_av = True

    return is_av


def is_values_reference(value):
    """Check for ValuesReference in given value
    """

    check = False

    if value is ValuesReference:
        check = True
    elif value is None:
        check = False
    elif isinstance(value, ValuesReference):
        check = True
    elif str(value).lower() == 'valuesreference':
        check = True

    return check
