"""Unit tests for migration notice forwarding (P-0011 cap-003).

Postgres notices arrive as psycopg Diagnostic objects; a stub with the two
attributes the handler reads is enough to pin the severity mapping.
"""
import logging

from latarnia.auth.db import _forward_notice

LOGGER_NAME = "latarnia.auth.db"


class _Diag:
    def __init__(self, severity, message):
        self.severity_nonlocalized = severity
        self.severity = severity
        self.message_primary = message


def _records(caplog, level):
    return [r for r in caplog.records
            if r.name == LOGGER_NAME and r.levelno == level]


def test_forward_notice_warning_severity_logs_warning(caplog):
    logger = logging.getLogger(LOGGER_NAME)
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        _forward_notice(logger, _Diag("WARNING", "renamed x -> x2"))
    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert "renamed x -> x2" in warnings[0].getMessage()


def test_forward_notice_notice_severity_logs_debug(caplog):
    logger = logging.getLogger(LOGGER_NAME)
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        _forward_notice(logger, _Diag("NOTICE", "quiet"))
    assert not _records(caplog, logging.WARNING)
    debugs = _records(caplog, logging.DEBUG)
    assert len(debugs) == 1
    assert "quiet" in debugs[0].getMessage()


def test_forward_notice_error_severity_logs_warning(caplog):
    logger = logging.getLogger(LOGGER_NAME)
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        _forward_notice(logger, _Diag("ERROR", "bad"))
    assert len(_records(caplog, logging.WARNING)) == 1


def test_forward_notice_tolerates_missing_attributes(caplog):
    """A Diagnostic with nothing populated must not raise inside the handler."""
    logger = logging.getLogger(LOGGER_NAME)

    class _Empty:
        pass

    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        _forward_notice(logger, _Empty())
    assert not _records(caplog, logging.WARNING)
