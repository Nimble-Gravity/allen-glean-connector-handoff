from glean_indexing_api_client.api import troubleshooting_api
from glean_indexing_api_client.model.check_document_access_request import CheckDocumentAccessRequest
from glean_indexing_api_client.model.check_document_access_response import CheckDocumentAccessResponse
from pprint import pprint
# Please refer to the Getting Started page for more details on how to setup api_client
troubleshoot_api = troubleshooting_api.TroubleshootingApi(api_client)
check_document_access_request = CheckDocumentAccessRequest(
    datasource=dotenv.get("GLEAN_DATASOURCE"),
    object_type="Article",
    doc_id="art123",
    user_email="user1@example.com"
)
try:
    api_response = troubleshoot_api.checkdocumentaccess_post(check_document_access_request)
    pprint(api_response)
except glean_indexing_api_client.ApiException as e:
    print("Exception when calling TroubleshootingApi->checkdocumentaccess_post: %s\n" % e)