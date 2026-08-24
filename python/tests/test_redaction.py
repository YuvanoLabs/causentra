from __future__ import annotations

from causentra import CausentraRuntime, MemoryExporter, PolicyRedactor, default_redactor


def test_policy_redacts_nested_values_and_composes_key_redaction() -> None:
    source = {
        "password": "still-secret",
        "nested": [
            "email alice@example.com",
            {"card": "4111 1111 1111 1111", "pan": "ABCDE1234F"},
        ],
    }

    result = PolicyRedactor()(source)

    assert result == {
        "password": "[REDACTED]",
        "nested": [
            "email [REDACTED]",
            {"card": "[REDACTED]", "pan": "[REDACTED]"},
        ],
    }
    assert source["password"] == "still-secret"


def test_policy_preserves_detector_false_positive_boundaries() -> None:
    value = {
        "invalid_card": "4111 1111 1111 1112",
        "embedded_pan": "XABCDE1234FY",
        "email_like": "alice@example",
        "ordinary": "a 1234567890123456 b",
    }

    assert PolicyRedactor()(value) == value


def test_policy_redacts_email_before_common_punctuation() -> None:
    assert PolicyRedactor()({"message": "Contact alice@example.com."}) == {
        "message": "Contact [REDACTED]."
    }


def test_policy_can_disable_individual_detectors() -> None:
    value = {"email": "alice@example.com", "pan": "ABCDE1234F"}

    assert PolicyRedactor(redact_emails=False)(value) == {
        "email": "alice@example.com",
        "pan": "[REDACTED]",
    }


def test_policy_runs_before_memory_exporter_receives_data() -> None:
    exporter = MemoryExporter()
    runtime = CausentraRuntime("redaction-test", exporter, redactor=PolicyRedactor())

    with runtime.trace("workflow", attributes={"contact": "alice@example.com"}):
        pass

    assert exporter.events[0].attributes["contact"] == "[REDACTED]"
    assert default_redactor({"contact": "alice@example.com"})["contact"] == "alice@example.com"
