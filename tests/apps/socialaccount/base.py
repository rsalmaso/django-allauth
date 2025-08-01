import base64
import hashlib
import json
import random
import requests
import uuid
import warnings
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils.http import urlencode

import jwt

import allauth.app_settings
from allauth.account.models import EmailAddress
from allauth.account.utils import user_email, user_username
from allauth.socialaccount import app_settings
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.models import SocialAccount, SocialApp
from tests.mocking import MockedResponse, mocked_response


def setup_app(provider_id):
    request = RequestFactory().get("/")
    apps = get_adapter().list_apps(request, provider_id)
    if apps:
        return apps[0]

    app = SocialApp.objects.create(
        provider=provider_id,
        name=provider_id,
        client_id="app123id",
        key=provider_id,
        secret="dummy",
    )
    if allauth.app_settings.SITES_ENABLED:
        from django.contrib.sites.models import Site

        app.sites.add(Site.objects.get_current())
    return app


class OAuthTestsMixin:
    provider_id: str

    def get_mocked_response(self):
        pass

    def get_expected_to_str(self):
        raise NotImplementedError

    def setUp(self):
        super(OAuthTestsMixin, self).setUp()
        self.app = setup_app(self.provider_id)
        request = RequestFactory().get("/")
        self.provider = self.app.get_provider(request)

    @override_settings(SOCIALACCOUNT_AUTO_SIGNUP=False)
    def test_login(self):
        resp_mocks = self.get_mocked_response()
        if resp_mocks is None:
            warnings.warn("Cannot test provider %s, no oauth mock" % self.provider.id)
            return
        resp = self.login(resp_mocks)
        self.assertRedirects(resp, reverse("socialaccount_signup"))
        resp = self.client.get(reverse("socialaccount_signup"))
        sociallogin = resp.context["form"].sociallogin
        data = dict(
            email=user_email(sociallogin.user),
            username=str(random.randrange(1000, 10000000)),
        )
        resp = self.client.post(reverse("socialaccount_signup"), data=data)
        self.assertRedirects(resp, "/accounts/profile/", fetch_redirect_response=False)
        user = resp.context["user"]
        self.assertFalse(user.has_usable_password())
        account = SocialAccount.objects.get(user=user, provider=self.provider.id)
        provider_account = account.get_provider_account()
        self.assertEqual(provider_account.to_str(), self.get_expected_to_str())
        # The following lines don't actually test that much, but at least
        # we make sure that the code is hit.
        provider_account.get_avatar_url()
        provider_account.get_profile_url()
        provider_account.get_brand()

    @override_settings(
        SOCIALACCOUNT_AUTO_SIGNUP=True,
        SOCIALACCOUNT_EMAIL_REQUIRED=False,
        ACCOUNT_EMAIL_REQUIRED=False,
    )
    def test_auto_signup(self):
        resp_mocks = self.get_mocked_response()
        if not resp_mocks:
            warnings.warn("Cannot test provider %s, no oauth mock" % self.provider.id)
            return
        resp = self.login(resp_mocks)
        self.assertRedirects(resp, "/accounts/profile/", fetch_redirect_response=False)
        self.assertFalse(resp.context["user"].has_usable_password())

    def login(self, resp_mocks, process="login"):
        with mocked_response(
            MockedResponse(
                200,
                "oauth_token=token&oauth_token_secret=psst",
                {"content-type": "text/html"},
            )
        ):
            resp = self.client.post(
                reverse(self.provider.id + "_login")
                + "?"
                + urlencode(dict(process=process))
            )
        p = urlparse(resp["location"])
        q = parse_qs(p.query)
        complete_url = reverse(self.provider.id + "_callback")
        self.assertGreater(q["oauth_callback"][0].find(complete_url), 0)
        with mocked_response(self.get_access_token_response(), *resp_mocks):
            resp = self.client.get(complete_url)
        return resp

    def get_access_token_response(self):
        return MockedResponse(
            200,
            "oauth_token=token&oauth_token_secret=psst",
            {"content-type": "text/html"},
        )

    def test_authentication_error(self):
        resp = self.client.get(reverse(self.provider.id + "_callback"))
        self.assertTemplateUsed(
            resp,
            "socialaccount/authentication_error.%s"
            % getattr(settings, "ACCOUNT_TEMPLATE_EXTENSION", "html"),
        )


# For backward-compatibility with third-party provider tests that call
# create_oauth_tests() rather than using the mixin directly.
def create_oauth_tests(provider):
    class Class(OAuthTestsMixin, TestCase):
        provider_id = provider.id

    Class.__name__ = "OAuthTests_" + provider.id
    return Class


class OAuth2TestsMixin:
    provider_id: str

    def get_mocked_response(self):
        pass

    def get_expected_to_str(self):
        raise NotImplementedError

    def get_access_token(self) -> str:
        return "testac"

    def get_refresh_token(self) -> str:
        return "testrf"

    def get_login_response_json(self, with_refresh_token=True):
        response = {
            "uid": uuid.uuid4().hex,
            "access_token": self.get_access_token(),
        }
        if with_refresh_token:
            response["refresh_token"] = self.get_refresh_token()
        return json.dumps(response)

    def mocked_response(self, *responses):
        return mocked_response(*responses)

    def setUp(self):
        super(OAuth2TestsMixin, self).setUp()
        self.setup_provider()

    def setup_provider(self):
        self.app = setup_app(self.provider_id)
        self.request = RequestFactory().get("/")
        self.provider = self.app.get_provider(self.request)

    def test_provider_has_no_pkce_params(self):
        provider_settings = app_settings.PROVIDERS.get(self.app.provider, {})
        provider_settings_with_pkce_set = provider_settings.copy()
        provider_settings_with_pkce_set["OAUTH_PKCE_ENABLED"] = False

        with self.settings(
            SOCIALACCOUNT_PROVIDERS={self.app.provider: provider_settings_with_pkce_set}
        ):
            self.assertEqual(self.provider.get_pkce_params(), {})

    def test_provider_has_pkce_params(self):
        provider_settings = app_settings.PROVIDERS.get(self.app.provider, {})
        provider_settings_with_pkce_set = provider_settings.copy()
        provider_settings_with_pkce_set["OAUTH_PKCE_ENABLED"] = True

        with self.settings(
            SOCIALACCOUNT_PROVIDERS={self.app.provider: provider_settings_with_pkce_set}
        ):
            pkce_params = self.provider.get_pkce_params()
            self.assertEqual(
                set(pkce_params.keys()),
                {"code_challenge", "code_challenge_method", "code_verifier"},
            )
            hashed_verifier = hashlib.sha256(
                pkce_params["code_verifier"].encode("ascii")
            )
            code_challenge = base64.urlsafe_b64encode(hashed_verifier.digest())
            code_challenge_without_padding = code_challenge.rstrip(b"=")
            assert pkce_params["code_challenge"] == code_challenge_without_padding

    @override_settings(SOCIALACCOUNT_AUTO_SIGNUP=False)
    def test_login(self):
        resp_mock = self.get_mocked_response()
        if not resp_mock:
            warnings.warn("Cannot test provider %s, no oauth mock" % self.provider.id)
            return
        resp = self.login(
            resp_mock,
        )
        self.assertRedirects(resp, reverse("socialaccount_signup"))

    @override_settings(SOCIALACCOUNT_AUTO_SIGNUP=False)
    def test_login_with_pkce_disabled(self):
        provider_settings = app_settings.PROVIDERS.get(self.app.provider, {})
        provider_settings_with_pkce_disabled = provider_settings.copy()
        provider_settings_with_pkce_disabled["OAUTH_PKCE_ENABLED"] = False

        with self.settings(
            SOCIALACCOUNT_PROVIDERS={
                self.app.provider: provider_settings_with_pkce_disabled
            }
        ):
            resp_mock = self.get_mocked_response()
            if not resp_mock:
                warnings.warn(
                    "Cannot test provider %s, no oauth mock" % self.provider.id
                )
                return
            resp = self.login(
                resp_mock,
            )
            self.assertRedirects(resp, reverse("socialaccount_signup"))

    @override_settings(SOCIALACCOUNT_AUTO_SIGNUP=False)
    def test_login_with_pkce_enabled(self):
        provider_settings = app_settings.PROVIDERS.get(self.app.provider, {})
        provider_settings_with_pkce_enabled = provider_settings.copy()
        provider_settings_with_pkce_enabled["OAUTH_PKCE_ENABLED"] = True
        with self.settings(
            SOCIALACCOUNT_PROVIDERS={
                self.app.provider: provider_settings_with_pkce_enabled
            }
        ):
            resp_mock = self.get_mocked_response()
            if not resp_mock:
                warnings.warn(
                    "Cannot test provider %s, no oauth mock" % self.provider.id
                )
                return

            resp = self.login(
                resp_mock,
            )
            self.assertRedirects(resp, reverse("socialaccount_signup"))

    @override_settings(SOCIALACCOUNT_STORE_TOKENS=True)
    def test_account_tokens(self, multiple_login=False):
        email = "user@example.com"
        user = get_user_model()(is_active=True)
        user_email(user, email)
        user_username(user, "user")
        user.set_password("test")
        user.save()
        EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
        self.client.login(username=user.username, password="test")
        self.login(self.get_mocked_response(), process="connect")
        if multiple_login:
            self.login(
                self.get_mocked_response(),
                with_refresh_token=False,
                process="connect",
            )
        # get account
        sa = SocialAccount.objects.filter(
            user=user, provider=self.provider.app.provider_id or self.provider.id
        ).get()
        provider_account = sa.get_provider_account()
        self.assertEqual(provider_account.to_str(), self.get_expected_to_str())
        # The following lines don't actually test that much, but at least
        # we make sure that the code is hit.
        provider_account.get_avatar_url()
        provider_account.get_profile_url()
        provider_account.get_brand()
        # get token
        if self.app:
            t = sa.socialtoken_set.get()
            # verify access_token and refresh_token
            self.assertEqual(self.get_access_token(), t.token)
            resp = json.loads(self.get_login_response_json(with_refresh_token=True))
            if "refresh_token" in resp:
                refresh_token = resp.get("refresh_token")
            elif "refreshToken" in resp:
                refresh_token = resp.get("refreshToken")
            else:
                refresh_token = ""
            self.assertEqual(t.token_secret, refresh_token)

    @override_settings(SOCIALACCOUNT_STORE_TOKENS=True)
    def test_account_refresh_token_saved_next_login(self):
        """
        fails if a login missing a refresh token, deletes the previously
        saved refresh token. Systems such as google's oauth only send
        a refresh token on first login.
        """
        self.test_account_tokens(multiple_login=True)

    def login(self, resp_mock=None, process="login", with_refresh_token=True):
        with self.mocked_response():
            resp = self.client.post(
                self.provider.get_login_url(self.request, process=process)
            )
        p = urlparse(resp["location"])
        q = parse_qs(p.query)

        pkce_enabled = app_settings.PROVIDERS.get(self.app.provider, {}).get(
            "OAUTH_PKCE_ENABLED", self.provider.pkce_enabled_default
        )

        self.assertEqual("code_challenge" in q, pkce_enabled)
        self.assertEqual("code_challenge_method" in q, pkce_enabled)
        if pkce_enabled:
            code_challenge = q["code_challenge"][0]
            self.assertEqual(q["code_challenge_method"][0], "S256")

        complete_url = self.provider.get_callback_url()
        self.assertGreater(q["redirect_uri"][0].find(complete_url), 0)
        response_json = self.get_login_response_json(
            with_refresh_token=with_refresh_token
        )

        if isinstance(resp_mock, list):
            resp_mocks = resp_mock
        elif resp_mock is None:
            resp_mocks = []
        else:
            resp_mocks = [resp_mock]

        with self.mocked_response(
            MockedResponse(200, response_json, {"content-type": "application/json"}),
            *resp_mocks,
        ):
            resp = self.client.get(complete_url, self.get_complete_parameters(q))

            # Find the access token POST request, and assert that it contains
            # the correct code_verifier if and only if PKCE is enabled
            request_calls = requests.Session.request.call_args_list
            for args, kwargs in request_calls:
                data = kwargs.get("data", {})
                if (
                    args[0] == "POST"
                    and isinstance(data, dict)
                    and data.get("redirect_uri", "").endswith(complete_url)
                ):
                    self.assertEqual("code_verifier" in data, pkce_enabled)

                    if pkce_enabled:
                        hashed_code_verifier = hashlib.sha256(
                            data["code_verifier"].encode("ascii")
                        )
                        expected_code_challenge = (
                            base64.urlsafe_b64encode(hashed_code_verifier.digest())
                            .rstrip(b"=")
                            .decode()
                        )
                        self.assertEqual(code_challenge, expected_code_challenge)

        return resp

    def get_complete_parameters(self, q):
        return {"code": "test", "state": q["state"][0]}

    def test_authentication_error(self):
        resp = self.client.get(self.provider.get_callback_url())
        self.assertTemplateUsed(
            resp,
            "socialaccount/authentication_error.%s"
            % getattr(settings, "ACCOUNT_TEMPLATE_EXTENSION", "html"),
        )


class OpenIDConnectTests(OAuth2TestsMixin):
    oidc_info_content = {
        "authorization_endpoint": "/login",
        "userinfo_endpoint": "/userinfo",
        "token_endpoint": "/token",
        "jwks_uri": "/jwks",
        "issuer": "https://issuer.example.com",
    }
    userinfo_content = {
        "picture": "https://secure.gravatar.com/avatar/123",
        "email": "ness@some.oidc.server.onett.example",
        "sub": 2187,
        "identities": [],
        "name": "Ness",
    }
    id_token = {
        "email": "ness@some.oidc.server.onett.example",
        "sub": 2187,
        "preferred_username": "wizard",
        "iss": "https://issuer.example.com",
        "aud": "app123id",
    }

    def get_id_token(self) -> dict:
        return self.id_token

    def get_login_response_json(self, with_refresh_token=True) -> str:
        data = json.loads(
            super().get_login_response_json(with_refresh_token=with_refresh_token)
        )
        data["id_token"] = jwt.encode(self.get_id_token(), "secret")
        return json.dumps(data)

    def mocked_response(self, *responses):
        return mocked_response(*responses, callback=self._mocked_responses)

    def get_expected_to_str(self):
        return "ness@some.oidc.server.onett.example"

    def setup_provider(self):
        self.app = setup_app(self.provider_id)
        self.app.provider_id = self.provider_id
        self.app.provider = "openid_connect"
        self.app.settings = {
            "server_url": "https://unittest.example.com",
        }
        self.app.save()
        self.request = RequestFactory().get("/")
        self.provider = self.app.get_provider(self.request)

    def get_mocked_response(self):
        # Enable test_login in OAuth2TestsMixin, but this response mock is unused
        return True

    def _mocked_responses(self, url, *args, **kwargs):
        if url.endswith("/.well-known/openid-configuration"):
            return MockedResponse(200, json.dumps(self.oidc_info_content))
        elif url.endswith("/userinfo"):
            return MockedResponse(200, json.dumps(self.userinfo_content))

    @override_settings(SOCIALACCOUNT_AUTO_SIGNUP=True)
    def test_login_auto_signup(self):
        resp = self.login()
        self.assertRedirects(resp, "/accounts/profile/", fetch_redirect_response=False)
        sa = SocialAccount.objects.get(provider=self.app.provider_id)
        expected_data = {"id_token": self.id_token}
        if self.app.settings.get("fetch_userinfo", True):
            expected_data["userinfo"] = self.userinfo_content
        self.assertDictEqual(sa.extra_data, expected_data)

    def test_404_on_unknown_provider_id(self):
        """
        Make sure that OIDC endpoints hit with an invalid provider_id
        not corresponding to any configured social "apps" returns a 404
        instead of an unhandled SocialApp.DoesNotExist.
        """

        # we can't use self.provider.get_login_url as we intentionally
        # do not want to use the configured provider's ID, so let's inline
        # OpenIDConnectProvider.get_login_url
        login_url = reverse(
            self.app.provider + "_login",
            kwargs={
                # intentionally invalidate the ID
                "provider_id": self.app.provider_id
                + "-invalid"
            },
        )

        resp = self.client.post(login_url)

        self.assertEqual(resp.status_code, 404)

        # same with the callback endpoint - inlining OpenIDConnectProvider.get_callback_url
        callback_url = reverse(
            self.app.provider + "_callback",
            kwargs={
                # intentionally invalidate the ID
                "provider_id": self.app.provider_id
                + "-invalid"
            },
        )

        # note: callback is a GET endpoint
        resp = self.client.get(callback_url)

        self.assertEqual(resp.status_code, 404)
