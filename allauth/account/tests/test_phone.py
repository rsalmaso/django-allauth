from http import HTTPStatus

from django.conf import settings
from django.urls import reverse

import pytest

from allauth.account.adapter import get_adapter


@pytest.fixture
def phone_only_settings(settings_impacting_urls):
    with settings_impacting_urls(
        ACCOUNT_LOGIN_METHODS=("phone",), ACCOUNT_SIGNUP_FIELDS=["phone*"]
    ):
        yield


def test_signup(db, client, phone, sms_outbox, phone_only_settings):
    assert len(sms_outbox) == 0
    resp = client.post(reverse("account_signup"), data={"phone": phone})
    assert resp.status_code == HTTPStatus.FOUND
    assert len(sms_outbox) == 1
    assert resp["location"] == reverse("account_verify_phone")
    resp = client.get(resp["location"])
    assert resp.status_code == HTTPStatus.OK
    resp = client.post(
        reverse("account_verify_phone"), data={"code": sms_outbox[-1]["code"]}
    )
    assert resp.status_code == HTTPStatus.FOUND
    adapter = get_adapter()
    user = adapter.get_user_by_phone(phone)
    phone2, phone_verified = adapter.get_phone(user)
    assert phone_verified
    assert phone == phone2


def test_signup_invalid_attempts(db, client, phone, sms_outbox, phone_only_settings):
    assert len(sms_outbox) == 0
    resp = client.post(reverse("account_signup"), data={"phone": phone})
    assert resp.status_code == HTTPStatus.FOUND
    adapter = get_adapter()
    user = adapter.get_user_by_phone(phone)
    _, phone_verified = adapter.get_phone(user)
    assert not phone_verified
    assert len(sms_outbox) == 1
    assert resp["location"] == reverse("account_verify_phone")
    resp = client.get(resp["location"])
    assert resp.status_code == HTTPStatus.OK
    for i in range(3):
        resp = client.post(reverse("account_verify_phone"), data={"code": "wrong"})
        assert resp.status_code == (HTTPStatus.OK if i < 2 else HTTPStatus.FOUND)


def test_login_sends_code(
    user_with_phone, client, phone_only_settings, phone, sms_outbox
):
    resp = client.post(reverse("account_login"), data={"login": phone})
    assert resp.status_code == HTTPStatus.FOUND
    assert resp["location"] == reverse("account_confirm_login_code")
    assert len(sms_outbox) == 1


def test_login_with_verified_phone_and_password(
    client, settings_impacting_urls, phone, user_with_phone, user_password
):
    with settings_impacting_urls(
        ACCOUNT_SIGNUP_FIELD=["phone*", "password1*"],
        ACCOUNT_LOGIN_METHODS=["phone"],
    ):
        resp = client.post(
            reverse("account_login"), data={"login": phone, "password": user_password}
        )
        assert resp.status_code == HTTPStatus.FOUND
        assert resp["location"] == settings.LOGIN_REDIRECT_URL


def test_login_with_unverified_phone_and_password(
    client, settings_impacting_urls, phone, password_factory, user_factory, sms_outbox
):
    with settings_impacting_urls(
        ACCOUNT_SIGNUP_FIELDS=["phone*", "password1*"],
        ACCOUNT_LOGIN_METHODS=["phone"],
    ):
        password = password_factory()
        user = user_factory(phone=phone, password=password, phone_verified=False)
        resp = client.post(
            reverse("account_login"), data={"login": phone, "password": password}
        )
        assert resp.status_code == HTTPStatus.FOUND
        assert resp["location"] == reverse("account_verify_phone")
        code = sms_outbox[-1]["code"]
        resp = client.post(reverse("account_verify_phone"), data={"code": code})
        assert resp["location"] == settings.LOGIN_REDIRECT_URL
        phone_verified = get_adapter().get_phone(user)
        assert phone_verified == (phone, True)
