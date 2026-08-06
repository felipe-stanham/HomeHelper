"""Unit tests for UserStore username normalization (P-0011 cap-001).

Mocks the DB and asserts on the params actually handed to SQL, which is where
the case folding has to land.
"""
from unittest.mock import Mock

from latarnia.auth.users import (
    BOOTSTRAP_USERNAME,
    UserStore,
    normalize_username,
)


def _store():
    db = Mock()
    return UserStore(db), db


# ------------------------------------------------------- normalize_username

def test_normalize_username_folds_case():
    assert normalize_username("Felipe") == "felipe"


def test_normalize_username_strips_whitespace():
    assert normalize_username("  ADMIN  ") == "admin"


def test_normalize_username_leaves_lowercase_untouched():
    assert normalize_username("admin") == "admin"


def test_normalize_username_tolerates_empty():
    # post_login passes whatever the form carried; None must not blow up.
    assert normalize_username("") == ""
    assert normalize_username(None) == ""


# ------------------------------------------------------------- write path

def test_create_user_stores_lowercase():
    store, db = _store()
    store.create_user("Felipe")
    params = db.execute_returning.call_args.args[1]
    assert params[0] == "felipe"


def test_create_user_strips_and_folds():
    store, db = _store()
    store.create_user("  MiXeD.Case_99  ")
    assert db.execute_returning.call_args.args[1][0] == "mixed.case_99"


# -------------------------------------------------------------- read path

def test_get_user_by_username_folds_lookup():
    store, db = _store()
    store.get_user_by_username("ADMIN")
    assert db.query_one.call_args.args[1] == ("admin",)


def test_get_user_by_username_still_matches_exact_sql():
    # The SQL itself must stay a plain equality — no lower() in the query, so
    # the users_username_key index is still used.
    store, db = _store()
    store.get_user_by_username("admin")
    sql = db.query_one.call_args.args[0]
    assert "WHERE username = %s" in sql
    assert "lower(" not in sql.lower()


def test_bootstrap_superuser_lookup_unaffected():
    store, db = _store()
    db.query_one.return_value = None
    store.get_or_create_bootstrap_superuser()
    # Lookup normalized, and the INSERT still writes the canonical name.
    assert db.query_one.call_args.args[1] == (BOOTSTRAP_USERNAME,)
    assert db.execute_returning.call_args.args[1] == (BOOTSTRAP_USERNAME,)


def test_bootstrap_superuser_returns_existing_without_insert():
    store, db = _store()
    db.query_one.return_value = {"id": "u1", "username": "admin"}
    assert store.get_or_create_bootstrap_superuser()["username"] == "admin"
    db.execute_returning.assert_not_called()
