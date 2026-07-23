from app.domain import caller_card, imported_record, normalise_phone, osm_record


def test_phone_normalisation_handles_indian_mobile_and_landline() -> None:
    assert normalise_phone("98765 43210") == "+919876543210"
    assert normalise_phone("080 4123 4567") == "+918041234567"
    assert normalise_phone("bad number") == ""


def test_import_keeps_only_public_phone_contact_and_caller_safe_fields() -> None:
    record = imported_record(
        {
            "name": "North Star Cafe",
            "area": "Indiranagar",
            "contact_channels": [
                {"type": "email", "value": "private@example.com"},
                {"type": "phone", "value": "+91 98765 43210", "source": "https://example.test"},
            ],
            "notes": "Private owner note",
            "score": 83,
        }
    )
    assert record is not None
    card = caller_card(record)
    assert card["contact_channels"][0]["value"] == "+919876543210"
    assert "notes" not in card
    assert "email" not in str(card)


def test_osm_record_requires_a_name_and_public_phone() -> None:
    assert osm_record({"tags": {"name": "No Number"}}, "Bangalore") is None
    record = osm_record(
        {"type": "node", "id": 123, "tags": {"name": "Riverstone", "phone": "98765 11122", "addr:suburb": "Koramangala"}},
        "Bangalore",
    )
    assert record is not None
    assert record["score"] == 82
    assert record["contact_channels"][0]["value"] == "+919876511122"
