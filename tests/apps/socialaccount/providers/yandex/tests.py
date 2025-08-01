from django.test import TestCase

from allauth.socialaccount.providers.yandex.provider import YandexProvider
from tests.apps.socialaccount.base import OAuth2TestsMixin
from tests.mocking import MockedResponse


class YandexTests(OAuth2TestsMixin, TestCase):
    provider_id = YandexProvider.id

    yandex_data = """
        {
            "login": "vasya",
                "old_social_login": "uid-mmzxrnry",
                    "default_email": "test@yandex.ru",
                        "id": "1000034426",
                            "client_id": "4760187d81bc4b7799476b42b5103713",
                                "emails": [
                                    "test@yandex.ru",
                                    "other-test@yandex.ru"
                                ],
                                "openid_identities": [
                                    "http://openid.yandex.ru/vasya/",
                                    "http://vasya.ya.ru/"
                                ]
        }"""

    def get_mocked_response(self, data=None):
        if data is None:
            data = self.yandex_data
        return MockedResponse(200, data)

    def get_expected_to_str(self):
        return "test@yandex.ru"

    def get_login_response_json(self, with_refresh_token=True):
        return """
            {
                "access_token":"testac",
                "refresh_token":"1:GN686QVt0mmakDd9:A4pYuW9LGk0_UnlrMIWklk",
                "token_type":"bearer",
                "expires_in":124234123534
            }"""
