import pytest

from vivia.oracle.identifiers import ensure_identifier, parse


def test_parse_splits_schema_and_table():
    assert parse("dmdtrg.d_tiers") == ("DMDTRG", "D_TIERS")


def test_parse_uppercases_a_bare_name():
    assert parse("d_tiers") == (None, "D_TIERS")


def test_ensure_identifier_accepts_a_plain_column():
    assert ensure_identifier("id_tiers") == "ID_TIERS"


def test_ensure_identifier_rejects_a_sql_fragment():
    with pytest.raises(ValueError, match="invalide"):
        ensure_identifier("id; DROP TABLE x")
