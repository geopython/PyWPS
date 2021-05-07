import json

from werkzeug.wrappers import Request
import pywps.configuration as config
from pywps.app.basic import make_response, get_response_type, get_json_indent
from pywps.response import WPSResponse
from pywps import __version__
from pywps.exceptions import NoApplicableCode
import os


class CapabilitiesResponse(WPSResponse):

    def __init__(self, wps_request, uuid, version, **kwargs):

        super(CapabilitiesResponse, self).__init__(wps_request, uuid, version)

        self.processes = kwargs["processes"]

    @property
    def json(self):
        """Convert the response to JSON structure
        """

        processes = [p.json for p in self.processes.values()]
        return {
            'pywps_version': __version__,
            'version': self.version,
            'title': config.get_config_value('metadata:main', 'identification_title'),
            'abstract': config.get_config_value('metadata:main', 'identification_abstract'),
            'keywords': config.get_config_value('metadata:main', 'identification_keywords').split(","),
            'keywords_type': config.get_config_value('metadata:main', 'identification_keywords_type').split(","),
            'fees': config.get_config_value('metadata:main', 'identification_fees'),
            'accessconstraints': config.get_config_value(
                'metadata:main',
                'identification_accessconstraints'
            ).split(','),
            'profile': config.get_config_value('metadata:main', 'identification_profile'),
            'provider': {
                'name': config.get_config_value('metadata:main', 'provider_name'),
                'site': config.get_config_value('metadata:main', 'provider_url'),
                'individual': config.get_config_value('metadata:main', 'contact_name'),
                'position': config.get_config_value('metadata:main', 'contact_position'),
                'voice': config.get_config_value('metadata:main', 'contact_phone'),
                'fascimile': config.get_config_value('metadata:main', 'contaact_fax'),
                'address': {
                    'delivery': config.get_config_value('metadata:main', 'deliveryPoint'),
                    'city': config.get_config_value('metadata:main', 'contact_city'),
                    'state': config.get_config_value('metadata:main', 'contact_stateorprovince'),
                    'postalcode': config.get_config_value('metadata:main', 'contact_postalcode'),
                    'country': config.get_config_value('metadata:main', 'contact_country'),
                    'email': config.get_config_value('metadata:main', 'contact_email')
                },
                'url': config.get_config_value('metadata:main', 'contact_url'),
                'hours': config.get_config_value('metadata:main', 'contact_hours'),
                'instructions': config.get_config_value('metadata:main', 'contact_instructions'),
                'role': config.get_config_value('metadata:main', 'contact_role')
            },
            'serviceurl': config.get_config_value('server', 'url'),
            'languages': config.get_config_value('server', 'language').split(','),
            'language': self.wps_request.language,
            'processes': processes
        }

    @staticmethod
    def _render_json_response(jdoc):
        return jdoc

    def _construct_doc(self):
        doc = self.json
        json_response, mimetype = get_response_type(
            self.wps_request.http_request.accept_mimetypes, self.wps_request.default_mimetype)
        if json_response:
            doc = json.dumps(self._render_json_response(doc), indent=get_json_indent())
        else:
            template = self.template_env.get_template(self.version + '/capabilities/main.xml')
            doc = template.render(**doc)
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
