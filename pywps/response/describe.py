import json

from werkzeug.wrappers import Request
import pywps.configuration as config
from pywps.app.basic import make_response, get_response_type, get_json_indent
from pywps.exceptions import NoApplicableCode
from pywps.exceptions import MissingParameterValue
from pywps.exceptions import InvalidParameterValue
from pywps.response import WPSResponse
from pywps import __version__
import os


class DescribeResponse(WPSResponse):

    def __init__(self, wps_request, uuid, **kwargs):

        super(DescribeResponse, self).__init__(wps_request, uuid)

        self.identifiers = None
        if "identifiers" in kwargs:
            self.identifiers = kwargs["identifiers"]
        self.processes = kwargs["processes"]

    @property
    def json(self):

        processes = []

        if 'all' in (ident.lower() for ident in self.identifiers):
            processes = (self.processes[p].json for p in self.processes)
        else:
            for identifier in self.identifiers:
                if identifier not in self.processes:
                    msg = "Unknown process {}".format(identifier)
                    raise InvalidParameterValue(msg, "identifier")
                else:
                    processes.append(self.processes[identifier].json)

        return {
            'pywps_version': __version__,
            'processes': processes,
            'language': self.wps_request.language,
        }

    @staticmethod
    def _render_json_response(jdoc):
        return jdoc

    def _construct_doc(self):
        if not self.identifiers:
            raise MissingParameterValue('Missing parameter value "identifier"', 'identifier')

        doc = self.json
        json_response, mimetype = get_response_type(
            self.wps_request.http_request.accept_mimetypes, self.wps_request.default_mimetype)
        if json_response:
            doc = json.dumps(self._render_json_response(doc), indent=get_json_indent())
        else:
            template = self.template_env.get_template(self.version + '/describe/main.xml')
            max_size = int(config.get_size_mb(config.get_config_value('server', 'maxsingleinputsize')))
            doc = template.render(max_size=max_size, **doc)
        return doc, mimetype

    @Request.application
    def __call__(self, request):
        # This function must return a valid response.
        try:
            doc, content_type = self.get_response_doc()
            return make_response(doc, content_type=content_type)
        except NoApplicableCode as e:
            return e
        except Exception as e:
            return NoApplicableCode(str(e))
