from django.test import TestCase

from allauth.socialaccount.providers.stocktwits.provider import StocktwitsProvider
from allauth.socialaccount.tests import OAuth2TestsMixin
from allauth.tests import MockedResponse


class StocktwitsTests(OAuth2TestsMixin, TestCase):
    provider_id = StocktwitsProvider.id

    def get_mocked_response(self):
        return MockedResponse(
            200,
            """
{
  "response": {
    "status": 200
  },
  "user": {
    "id": 3,
    "username": "zerobeta",
    "name": "Justin Paterno",
    "avatar_url": "http://avatars.stocktwits.com/images/default_avatar_thumb.jpg",
    "avatar_url_ssl": "https://s3.amazonaws.com/st-avatars/images/default_avatar_thumb.jpg",
    "identity": "Official",
    "classification": [
      "ir"
    ]
  }
}
""",
        )  # noqa

    def get_expected_to_str(self):
        return "zerobeta"
