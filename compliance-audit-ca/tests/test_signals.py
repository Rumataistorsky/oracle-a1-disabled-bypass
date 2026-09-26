from pathlib import Path

import pytest

from cacomply.crawl import crawl_local
from cacomply.signals import collect_signals, evaluate

FIXTURE = Path(__file__).parent / "fixtures" / "site"


@pytest.fixture(scope="module")
def signals():
    pages = crawl_local(FIXTURE)
    assert [p.kind for p in pages][0] == "home"
    return collect_signals(pages, ["ON"])


def test_forms_and_consent(signals):
    assert signals["email_signup_form"] is True
    assert signals["collects_personal_info"] is True
    assert signals["prechecked_checkboxes"] == 1
    assert signals["sender_identified"] is False  # email but no postal address


def test_privacy_and_trackers(signals):
    assert signals["has_privacy_page"] is False
    assert signals["has_terms_page"] is True
    assert set(signals["trackers"]) == {"google_analytics", "meta_pixel"}
    assert signals["uses_trackers"] is True
    assert signals["has_cookie_banner"] is False
    assert signals["privacy_officer_named"] is False


def test_accessibility_counts(signals):
    assert signals["images_missing_alt"] == 2
    assert signals["images_total"] == 4
    assert signals["html_lang_missing_pages"] == 1
    assert signals["inputs_without_label"] == 2  # email + checkbox on the home page


def test_commerce_signals(signals):
    assert signals["ecommerce"] is True
    assert signals["has_drip_pricing"] is True
    assert signals["sale_price_claims"] >= 1
    assert signals["green_claims"] >= 2
    assert signals["subscription_or_recurring"] is True
    assert signals["reviews_or_testimonials"] is True
    assert signals["free_claims"] >= 1


def test_geography(signals):
    assert signals["mentions_quebec"] is True
    assert signals["targets_quebec"] is True  # inferred from "Montréal" even though only ON was passed
    assert signals["has_french_version"] is False


def test_evaluate_expressions():
    s = {"a": True, "b": False, "n": 3, "kind": "home"}
    assert evaluate("a", s)
    assert not evaluate("b", s)
    assert evaluate("a and not b", s)
    assert evaluate("n > 2 and n <= 3", s)
    assert evaluate("kind == 'home'", s)
    assert not evaluate("missing_signal", s)
    with pytest.raises(ValueError):
        evaluate("a ||| b", s)
