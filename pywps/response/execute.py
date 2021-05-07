##################################################################
# Copyright 2018 Open Source Geospatial Foundation and others    #
# licensed under MIT, Please consult LICENSE.txt for details     #
##################################################################

import logging
import time
from werkzeug.wrappers import Request
from pywps import get_ElementMakerForVersion
from pywps.exceptions import NoApplicableCode
import pywps.configuration as config
from werkzeug.wrappers import Response

from pywps.response.status import WPS_STATUS
from pywps.response import WPSResponse
from pywps.inout.formats import FORMATS
from pywps.inout.outputs import ComplexOutput

import urllib.parse as urlparse
from urllib.parse import urlencode

LOGGER = logging.getLogger("PYWPS")

WPS, OWS = get_ElementMakerForVersion("1.0.0")


class ExecuteResponse(WPSResponse):

    def __init__(self, wps_request, uuid, **kwargs):
        """constructor

        :param pywps.app.WPSRequest.WPSRequest wps_request:
        :param pywps.app.Process.Process process:
        :param uuid: string this request uuid
        """

        super(ExecuteResponse, self).__init__(wps_request, uuid)

        self.process = kwargs["process"]
        self.outputs = {o.identifier: o for o in self.process.outputs}
        self.store_status_file = False

    # override WPSResponse._update_status
    def _update_status(self, status, message, status_percentage, clean=True):
        """
        Updates status report of currently running process instance:

        * Updates the status document.
        * Updates the status file (if requested).
        * Cleans the working directory when process has finished.

        This method is *only* called by pywps internally.
        """
        super(ExecuteResponse, self)._update_status(status, message, status_percentage)
        LOGGER.debug("_update_status: status={}, clean={}".format(status, clean))
        self._update_status_doc()
        if self.store_status_file:
            self._update_status_file()
        if clean:
            if self.status == WPS_STATUS.SUCCEEDED or self.status == WPS_STATUS.FAILED:
                LOGGER.debug("clean workdir: status={}".format(status))
                self.process.clean()

    def update_status(self, message, status_percentage=None):
        """
        Update status report of currently running process instance.

        This method is *only* called by the user provided process.
        The status is handled internally in pywps.

        :param str message: Message you need to share with the client
        :param int status_percentage: Percent done (number betwen <0-100>)
        """
        if status_percentage is None:
            status_percentage = self.status_percentage
        self._update_status(self.status, message, status_percentage, False)

    def _update_status_doc(self):
        try:
            # rebuild the doc
            self.doc = self._construct_doc()
        except Exception as e:
            raise NoApplicableCode('Building Response Document failed with : {}'.format(e))

    def _update_status_file(self):
        # TODO: check if file/directory is still present, maybe deleted in mean time
        try:
            # update the status xml file
            self.process.status_store.write(
                self.doc,
                self.process.status_filename,
                data_format=FORMATS.XML)
        except Exception as e:
            raise NoApplicableCode('Writing Response Document failed with : {}'.format(e))

    def _process_accepted(self):
        percent = int(self.status_percentage)
        if percent > 99:
            percent = 99
        return {
            "status": "accepted",
            "time": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.localtime()),
            "percent_done": str(percent),
            "message": self.message
        }

    def _process_started(self):
        data = self._process_accepted()
        data.update({
            "status": "started",
        })
        return data

    def _process_paused(self):
        data = self._process_accepted()
        data.update({
            "status": "paused",
        })
        return data

    def _process_succeeded(self):
        data = self._process_accepted()
        data.update({
            "status": "succeeded",
            "percent_done": "100"
        })
        return data

    def _process_failed(self):
        data = self._process_accepted()
        data.update({
            "status": "failed",
            "code": "NoApplicableCode",
            "locator": "None",
        })
        return data

    def _get_serviceinstance(self):

        url = config.get_config_value("server", "url")
        params = {'request': 'GetCapabilities', 'service': 'WPS'}

        url_parts = list(urlparse.urlparse(url))
        query = dict(urlparse.parse_qsl(url_parts[4]))
        query.update(params)

        url_parts[4] = urlencode(query)
        return urlparse.urlunparse(url_parts).replace("&", "&amp;")

    @property
    def json(self):
        data = {}
        data["language"] = self.wps_request.language
        data["service_instance"] = self._get_serviceinstance()
        data["process"] = self.process.json

        if self.store_status_file:
            if self.process.status_location:
                data["status_location"] = self.process.status_url

        if self.status == WPS_STATUS.ACCEPTED:
            self.message = 'PyWPS Process {} accepted'.format(self.process.identifier)
            data["status"] = self._process_accepted()
        elif self.status == WPS_STATUS.STARTED:
            data["status"] = self._process_started()
        elif self.status == WPS_STATUS.FAILED:
            # check if process failed and display fail message
            data["status"] = self._process_failed()
        elif self.status == WPS_STATUS.PAUSED:
            # TODO: handle paused status
            data["status"] = self._process_paused()
        elif self.status == WPS_STATUS.SUCCEEDED:
            data["status"] = self._process_succeeded()
            # Process outputs XML
            data["outputs"] = [self.outputs[o].json for o in self.outputs]
        # lineage: add optional lineage when process has finished
        if self.status in [WPS_STATUS.SUCCEEDED, WPS_STATUS.FAILED]:
            # DataInputs and DataOutputs definition XML if lineage=true
            if self.wps_request.lineage == 'true':
                data["lineage"] = True
                try:
                    # TODO: stored process has ``pywps.inout.basic.LiteralInput``
                    # instead of a ``pywps.inout.inputs.LiteralInput``.
                    data["input_definitions"] = [self.wps_request.inputs[i][0].json for i in self.wps_request.inputs]
                except Exception as e:
                    LOGGER.error("Failed to update lineage for input parameter. {}".format(e))

                data["output_definitions"] = [self.outputs[o].json for o in self.outputs]
        return data

    def _construct_doc(self):
        template = self.template_env.get_template(self.version + '/execute/main.xml')
        doc = template.render(**self.json)
        return doc

    @Request.application
    def __call__(self, request):
        if self.wps_request.raw:
            if self.status == WPS_STATUS.FAILED:
                return NoApplicableCode(self.message)
            else:
                wps_output_identifier = next(iter(self.wps_request.outputs))  # get the first key only
                wps_output_value = self.outputs[wps_output_identifier]
                if wps_output_value.source_type is None:
                    return NoApplicableCode("Expected output was not generated")
                suffix = ''
                if isinstance(wps_output_value, ComplexOutput):
                    if wps_output_value.data_format.extension is not None:
                        suffix = wps_output_value.data_format.extension
                return Response(wps_output_value.data,
                                mimetype=wps_output_value.data_format.mime_type,
                                headers={'Content-Disposition': 'attachment; filename="{}"'.format(wps_output_identifier+suffix)})
        else:
            if not self.doc:
                return NoApplicableCode("Output was not generated")
            return Response(self.doc, mimetype='text/xml')
