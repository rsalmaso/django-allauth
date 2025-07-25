from django.test import TestCase

from allauth.socialaccount.providers.odnoklassniki.provider import OdnoklassnikiProvider
from tests.apps.socialaccount.base import OAuth2TestsMixin
from tests.mocking import MockedResponse


class OdnoklassnikiTests(OAuth2TestsMixin, TestCase):
    provider_id = OdnoklassnikiProvider.id

    def get_mocked_response(self, verified_email=True):
        return MockedResponse(
            200,
            """
{"uid":"561999209121","birthday":"1999-09-09","age":33,"first_name":"Ivan",
"last_name":"Petrov","name":"Ivan Petrov","locale":"en","gender":"male",
"has_email":true,"location":{"city":"Moscow","country":"RUSSIAN_FEDERATION",
"countryCode":"RU","countryName":"Russia"},"online":"web","pic_1":
"http://i500.mycdn.me/res/stub_50x50.gif",
"pic_2":"http://usd1.mycdn.me/res/stub_128x96.gif"}
""",
        )

    def get_expected_to_str(self):
        return "Ivan Petrov"

    def get_login_response_json(self, with_refresh_token=True):
        return '{"access_token": "testac"}'  # noqa
