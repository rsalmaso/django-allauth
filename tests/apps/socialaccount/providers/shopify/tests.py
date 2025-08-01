import json
from urllib.parse import parse_qs, urlparse

from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.http import urlencode

from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.shopify.provider import ShopifyProvider
from tests.apps.socialaccount.base import OAuth2TestsMixin
from tests.mocking import MockedResponse, mocked_response


class ShopifyTests(OAuth2TestsMixin, TestCase):
    provider_id = ShopifyProvider.id

    def _complete_shopify_login(self, q, resp, resp_mock, with_refresh_token):
        complete_url = reverse(self.provider.id + "_callback")
        self.assertGreater(q["redirect_uri"][0].find(complete_url), 0)
        response_json = self.get_login_response_json(
            with_refresh_token=with_refresh_token
        )
        with mocked_response(
            MockedResponse(200, response_json, {"content-type": "application/json"}),
            resp_mock,
        ):
            resp = self.client.get(
                complete_url,
                {
                    "code": "test",
                    "state": q["state"][0],
                    "shop": "test",
                },
            )
        return resp

    def login(self, resp_mock, process="login", with_refresh_token=True):
        url = (
            reverse(self.provider.id + "_login")
            + "?"
            + urlencode({"process": process, "shop": "test"})
        )
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        p = urlparse(resp["location"])
        q = parse_qs(p.query)
        resp = self._complete_shopify_login(q, resp, resp_mock, with_refresh_token)
        return resp

    def get_mocked_response(self):
        return MockedResponse(
            200,
            """
        {
            "shop": {
                "id": "1234566",
                "name": "Test Shop",
                "email": "email@example.com"
            }
        }
        """,
        )

    def get_expected_to_str(self):
        return "email@example.com"


@override_settings(SOCIALACCOUNT_PROVIDERS={"shopify": {"IS_EMBEDDED": True}})
class ShopifyEmbeddedTests(ShopifyTests):
    """
    Shopify embedded apps (that run within an iFrame) require a JS (not server)
    redirect for starting the oauth2 process.

    See Also:
    https://help.shopify.com/api/sdks/embedded-app-sdk/getting-started#oauth
    """

    def login(self, resp_mock, process="login", with_refresh_token=True):
        resp = self.client.post(
            reverse(self.provider.id + "_login")
            + "?"
            + urlencode({"process": process, "shop": "test"}),
        )
        self.assertEqual(resp.status_code, 200)  # No re-direct, JS must do it
        actual_content = resp.content.decode("utf8")
        self.assertTrue(
            "script" in actual_content,
            "Content missing script tag. [Actual: {}]".format(actual_content),
        )
        self.assertTrue(
            resp.xframe_options_exempt,
            "Redirect JS must be allowed to run in Shopify iframe",
        )
        self.assertTrue(
            "<!DOCTYPE html><html><head>" in actual_content
            and "</head><body></body></html>" in actual_content,
            "Expected standard HTML skeleton. [Actual: {}]".format(actual_content),
        )
        p = urlparse(
            actual_content.split(";</script>")[0].split('location.href = "')[1]
        )
        q = parse_qs(p.query)
        resp = self._complete_shopify_login(q, resp, resp_mock, with_refresh_token)
        return resp


@override_settings(
    SOCIALACCOUNT_PROVIDERS={
        "shopify": {"AUTH_PARAMS": {"grant_options[]": "per-user"}}
    }
)
class ShopifyPerUserAccessTests(ShopifyTests):
    """
    Shopify has two access modes, offline (the default) and online/per-user.
    Enabling 'online' access should cause all-auth to tie the logged in
    Shopify user to the all-auth account (rather than the shop as a whole).

    See Also:
    https://help.shopify.com/api/getting-started/authentication/
    oauth#api-access-modes
    """

    def get_login_response_json(self, with_refresh_token=True):
        response_data = {
            "access_token": "testac",
            "scope": "write_orders,read_customers",
            "expires_in": 86399,
            "associated_user_scope": "write_orders",
            "associated_user": {
                "id": 902541635,
                "first_name": "Jon",
                "last_name": "Smith",
                "email": "jon@example.com",
                "account_owner": True,
            },
        }
        if with_refresh_token:
            response_data["refresh_token"] = "testrf"

        return json.dumps(response_data)

    @override_settings(
        SOCIALACCOUNT_AUTO_SIGNUP=True,
        SOCIALACCOUNT_EMAIL_REQUIRED=True,
        ACCOUNT_EMAIL_REQUIRED=True,
    )
    def test_associated_user(self):
        resp_mocks = self.get_mocked_response()
        resp = self.login(resp_mocks)
        self.assertRedirects(resp, "/accounts/profile/", fetch_redirect_response=False)

        social_account = SocialAccount.objects.filter(
            provider=self.provider.id,
            uid=902541635,
        ).first()
        self.assertIsNotNone(social_account)
        self.assertTrue("associated_user" in social_account.extra_data)

        self.assertEqual(social_account.user.email, "jon@example.com")
        self.assertEqual(social_account.user.first_name, "Jon")
        self.assertEqual(social_account.user.last_name, "Smith")
