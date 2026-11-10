import pytest

from vivia.oracle.sql_guard import RejectedSQL, ensure_safe_fragment, ensure_single_select


def test_plain_select_is_accepted():
    ensure_single_select("SELECT id FROM dual")


def test_with_cte_is_accepted():
    ensure_single_select("WITH c AS (SELECT 1 x FROM dual) SELECT x FROM c")


def test_template_is_not_confused_with_oracle_syntax():
    ensure_single_select("SELECT * FROM #SCH#.orders WHERE dt = TO_DATE('#PNDATE#', 'YYYYMMDD')")


def test_ddl_is_rejected():
    with pytest.raises(RejectedSQL):
        ensure_single_select("DROP TABLE dual")


def test_dml_is_rejected():
    with pytest.raises(RejectedSQL):
        ensure_single_select("DELETE FROM dual")


def test_multiple_statements_are_rejected():
    with pytest.raises(RejectedSQL):
        ensure_single_select("SELECT 1 FROM dual; SELECT 2 FROM dual")


def test_stacked_ddl_after_select_is_rejected():
    with pytest.raises(RejectedSQL):
        ensure_single_select("SELECT 1 FROM dual; DROP TABLE dual")


def test_safe_fragment_is_accepted():
    ensure_safe_fragment("1 = 1")


def test_unsafe_fragment_stacking_ddl_is_rejected():
    with pytest.raises(RejectedSQL):
        ensure_safe_fragment("1 = 1; DROP TABLE dual")
