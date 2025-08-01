from requests.exceptions import HTTPError

from django.test import TestCase
from django.test.client import RequestFactory
from django.test.utils import override_settings
from django.urls import reverse

from allauth.socialaccount.models import SocialToken
from allauth.socialaccount.providers.ynab.provider import YNABProvider
from tests.apps.socialaccount.base import OAuth2TestsMixin
from tests.mocking import MockedResponse, mocked_response


@override_settings(
    SOCIALACCOUNT_AUTO_SIGNUP=True,
    ACCOUNT_SIGNUP_FORM_CLASS=None,
)
# ACCOUNT_EMAIL_VERIFICATION=account_settings
# .EmailVerificationMethod.MANDATORY)
class YNABTests(OAuth2TestsMixin, TestCase):
    provider_id = YNABProvider.id

    def get_mocked_response(self):
        return MockedResponse(
            200,
            """
              {"data": {
        "user":{
        "id": "abcd1234xyz5678"
                    }
                }
              }
        """,
        )

    def get_expected_to_str(self):
        return "YNAB"

    def test_ynab_compelete_login_401(self):
        from allauth.socialaccount.providers.ynab.views import YNABOAuth2Adapter

        class LessMockedResponse(MockedResponse):
            def raise_for_status(self):
                if self.status_code != 200:
                    raise HTTPError(None)

        request = RequestFactory().get(
            reverse(self.provider.id + "_login"), dict(process="login")
        )

        adapter = YNABOAuth2Adapter(request)
        app = adapter.get_provider().app
        token = SocialToken(token="some_token")
        response_with_401 = LessMockedResponse(
            401,
            """
            {"error": {
              "errors": [{
                "domain": "global",
                "reason": "authError",
                "message": "Invalid Credentials",
                "locationType": "header",
                "location": "Authorization" } ],
              "code": 401,
              "message": "Invalid Credentials" }
            }""",
        )
        with mocked_response(response_with_401):
            with self.assertRaises(HTTPError):
                adapter.complete_login(request, app, token)
