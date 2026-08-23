"""
Unit Tests — Runtime Configuration (CORS Origin Allow-List).

IEC 62304 §5.7: Verification of the HAZARD-CORS-001 mitigation.
ISO 14971 HAZARD-CORS-001: A wildcard or empty CORS origin allow-list is a
confidentiality hazard — these tests prove the gateway refuses to start
with an unsafe configuration and correctly parses a valid one.
"""

from __future__ import annotations

import pytest
from config import (
    get_cert_store_path,
    get_cors_allowed_origins,
    get_device_common_name,
    get_enrollment_token,
    get_mllp_enabled,
    get_mllp_host,
    get_mllp_port,
    get_mqtt_config,
    get_mqtt_enabled,
    get_provisioning_bootstrap_url,
    get_provisioning_enabled,
    get_provisioning_max_enroll_attempts,
    get_reattestation_interval_seconds,
)


class TestGetCorsAllowedOriginsDefault:
    """No CORS_ALLOWED_ORIGINS set → safe local-dev default, never a wildcard."""

    def test_falls_back_to_localhost_dev_default_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        assert get_cors_allowed_origins() == ["http://localhost:3000"]


class TestGetCorsAllowedOriginsValid:
    """A well-formed, explicit allow-list is parsed correctly."""

    def test_single_origin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://ehr.example.org")
        assert get_cors_allowed_origins() == ["https://ehr.example.org"]

    def test_multiple_comma_separated_origins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "CORS_ALLOWED_ORIGINS",
            "https://ehr.example.org,https://icu-dashboard.example.org",
        )
        assert get_cors_allowed_origins() == [
            "https://ehr.example.org",
            "https://icu-dashboard.example.org",
        ]

    def test_strips_whitespace_around_origins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "CORS_ALLOWED_ORIGINS",
            " https://ehr.example.org , https://icu-dashboard.example.org ",
        )
        assert get_cors_allowed_origins() == [
            "https://ehr.example.org",
            "https://icu-dashboard.example.org",
        ]

    def test_ignores_empty_entries_from_trailing_comma(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://ehr.example.org,")
        assert get_cors_allowed_origins() == ["https://ehr.example.org"]


class TestGetCorsAllowedOriginsRejectsUnsafeValues:
    """HAZARD-CORS-001: wildcard and empty allow-lists must fail closed."""

    def test_rejects_bare_wildcard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
        with pytest.raises(ValueError, match="Wildcard '\\*' is prohibited"):
            get_cors_allowed_origins()

    def test_rejects_wildcard_mixed_with_explicit_origins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://ehr.example.org,*")
        with pytest.raises(ValueError, match="Wildcard '\\*' is prohibited"):
            get_cors_allowed_origins()

    def test_rejects_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
        with pytest.raises(ValueError, match="non-empty"):
            get_cors_allowed_origins()

    def test_rejects_whitespace_only_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "   ")
        with pytest.raises(ValueError, match="non-empty"):
            get_cors_allowed_origins()

    def test_rejects_commas_only_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", ",,,")
        with pytest.raises(ValueError, match="non-empty"):
            get_cors_allowed_origins()


class TestGetMllpEnabled:
    """Phase 5 Section A: MLLP listener is opt-in, disabled by default."""

    def test_disabled_by_default_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MLLP_ENABLED", raising=False)
        assert get_mllp_enabled() is False

    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes"])
    def test_truthy_values_enable(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("MLLP_ENABLED", value)
        assert get_mllp_enabled() is True

    @pytest.mark.parametrize("value", ["false", "False", "0", "no", "", "garbage"])
    def test_falsy_or_unrecognized_values_disable(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("MLLP_ENABLED", value)
        assert get_mllp_enabled() is False


class TestGetMllpHost:
    def test_defaults_to_bind_all_interfaces(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MLLP_HOST", raising=False)
        assert get_mllp_host() == "0.0.0.0"

    def test_reads_explicit_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLLP_HOST", "10.0.0.5")
        assert get_mllp_host() == "10.0.0.5"


class TestGetMllpPort:
    def test_defaults_to_conventional_mllp_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MLLP_PORT", raising=False)
        assert get_mllp_port() == 2575

    def test_reads_explicit_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLLP_PORT", "9999")
        assert get_mllp_port() == 9999

    def test_rejects_non_integer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLLP_PORT", "not-a-port")
        with pytest.raises(ValueError, match="must be an integer"):
            get_mllp_port()

    def test_rejects_out_of_range_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLLP_PORT", "70000")
        with pytest.raises(ValueError, match="between 0 and 65535"):
            get_mllp_port()

    def test_rejects_negative_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MLLP_PORT", "-1")
        with pytest.raises(ValueError, match="between 0 and 65535"):
            get_mllp_port()

    def test_zero_port_is_valid_and_means_ephemeral(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MLLP_PORT", "0")
        assert get_mllp_port() == 0


class TestGetMqttEnabled:
    def test_disabled_by_default_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MQTT_ENABLED", raising=False)
        assert get_mqtt_enabled() is False

    def test_true_enables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MQTT_ENABLED", "true")
        assert get_mqtt_enabled() is True


class TestGetMqttConfig:
    """All MQTT_* env vars unset -> safe, TLS-on-by-default configuration."""

    def _clear_mqtt_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "MQTT_BROKER_HOST",
            "MQTT_BROKER_PORT",
            "MQTT_USE_TLS",
            "MQTT_QOS",
            "MQTT_PUBLISH_INTERVAL_SECONDS",
            "MQTT_DRAIN_BATCH_SIZE",
            "MQTT_TOPIC_PREFIX",
            "MQTT_CLIENT_ID",
            "MQTT_USERNAME",
            "MQTT_PASSWORD",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clear_mqtt_env(monkeypatch)
        cfg = get_mqtt_config()
        assert cfg.broker_host == "localhost"
        assert cfg.broker_port == 8883
        assert cfg.use_tls is True
        assert cfg.qos == 1
        assert cfg.topic_prefix == "icu-edge/vitals"
        assert cfg.client_id == "icu-edge-gateway"
        assert cfg.username is None
        assert cfg.password is None
        assert cfg.publish_interval_seconds == 1.0
        assert cfg.drain_batch_size == 50

    def test_explicit_values_are_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MQTT_BROKER_HOST", "mqtt.example.org")
        monkeypatch.setenv("MQTT_BROKER_PORT", "1883")
        monkeypatch.setenv("MQTT_USE_TLS", "false")
        monkeypatch.setenv("MQTT_QOS", "2")
        monkeypatch.setenv("MQTT_TOPIC_PREFIX", "hospital-a/vitals/")
        monkeypatch.setenv("MQTT_CLIENT_ID", "edge-appliance-07")
        monkeypatch.setenv("MQTT_USERNAME", "edge07")
        monkeypatch.setenv("MQTT_PASSWORD", "s3cret")
        monkeypatch.setenv("MQTT_PUBLISH_INTERVAL_SECONDS", "2.5")
        monkeypatch.setenv("MQTT_DRAIN_BATCH_SIZE", "10")

        cfg = get_mqtt_config()

        assert cfg.broker_host == "mqtt.example.org"
        assert cfg.broker_port == 1883
        assert cfg.use_tls is False
        assert cfg.qos == 2
        assert cfg.topic_prefix == "hospital-a/vitals/"
        assert cfg.client_id == "edge-appliance-07"
        assert cfg.username == "edge07"
        assert cfg.password == "s3cret"
        assert cfg.publish_interval_seconds == 2.5
        assert cfg.drain_batch_size == 10

    def test_rejects_invalid_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clear_mqtt_env(monkeypatch)
        monkeypatch.setenv("MQTT_BROKER_PORT", "not-a-port")
        with pytest.raises(ValueError, match="must be an integer"):
            get_mqtt_config()

    def test_rejects_out_of_range_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clear_mqtt_env(monkeypatch)
        monkeypatch.setenv("MQTT_BROKER_PORT", "0")
        with pytest.raises(ValueError, match="between 1 and 65535"):
            get_mqtt_config()

    def test_rejects_invalid_qos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clear_mqtt_env(monkeypatch)
        monkeypatch.setenv("MQTT_QOS", "3")
        with pytest.raises(ValueError, match="must be 0, 1, or 2"):
            get_mqtt_config()

    def test_rejects_non_positive_publish_interval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_mqtt_env(monkeypatch)
        monkeypatch.setenv("MQTT_PUBLISH_INTERVAL_SECONDS", "0")
        with pytest.raises(ValueError, match="must be positive"):
            get_mqtt_config()

    def test_rejects_non_positive_drain_batch_size(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_mqtt_env(monkeypatch)
        monkeypatch.setenv("MQTT_DRAIN_BATCH_SIZE", "-5")
        with pytest.raises(ValueError, match="must be positive"):
            get_mqtt_config()

    def test_empty_username_string_is_treated_as_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_mqtt_env(monkeypatch)
        monkeypatch.setenv("MQTT_USERNAME", "")
        assert get_mqtt_config().username is None


class TestGetProvisioningEnabled:
    """Phase 5 Section B: device enrollment is opt-in, disabled by default."""

    def test_disabled_by_default_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("PROVISIONING_ENABLED", raising=False)
        assert get_provisioning_enabled() is False

    @pytest.mark.parametrize("value", ["true", "True", "1", "yes"])
    def test_truthy_values_enable(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("PROVISIONING_ENABLED", value)
        assert get_provisioning_enabled() is True


class TestGetProvisioningBootstrapUrl:
    def test_rejects_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PROVISIONING_BOOTSTRAP_URL", raising=False)
        with pytest.raises(ValueError, match="must be set"):
            get_provisioning_bootstrap_url()

    def test_rejects_non_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVISIONING_BOOTSTRAP_URL", "http://control-plane.example.org")
        with pytest.raises(ValueError, match="https://"):
            get_provisioning_bootstrap_url()

    def test_accepts_and_strips_trailing_slash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "PROVISIONING_BOOTSTRAP_URL", "https://control-plane.example.org/"
        )
        assert get_provisioning_bootstrap_url() == "https://control-plane.example.org"


class TestGetEnrollmentToken:
    def test_rejects_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ENROLLMENT_TOKEN_FILE", raising=False)
        monkeypatch.delenv("ENROLLMENT_TOKEN", raising=False)
        with pytest.raises(ValueError, match="ENROLLMENT_TOKEN"):
            get_enrollment_token()

    def test_reads_from_env_var_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ENROLLMENT_TOKEN_FILE", raising=False)
        monkeypatch.setenv("ENROLLMENT_TOKEN", "dev-only-token")
        assert get_enrollment_token() == "dev-only-token"

    def test_prefers_token_file_over_env_var(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        token_file = tmp_path / "token"
        token_file.write_text("file-token\n")
        monkeypatch.setenv("ENROLLMENT_TOKEN_FILE", str(token_file))
        monkeypatch.setenv("ENROLLMENT_TOKEN", "env-token-should-be-ignored")
        assert get_enrollment_token() == "file-token"

    def test_rejects_missing_token_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENROLLMENT_TOKEN_FILE", "/does/not/exist")
        with pytest.raises(ValueError, match="could not be read"):
            get_enrollment_token()

    def test_rejects_empty_token_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        token_file = tmp_path / "token"
        token_file.write_text("   \n")
        monkeypatch.setenv("ENROLLMENT_TOKEN_FILE", str(token_file))
        with pytest.raises(ValueError, match="is empty"):
            get_enrollment_token()


class TestGetDeviceCommonName:
    def test_uses_explicit_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEVICE_COMMON_NAME", "edge-device-042")
        assert get_device_common_name() == "edge-device-042"

    def test_falls_back_to_hostname_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DEVICE_COMMON_NAME", raising=False)
        assert get_device_common_name()  # non-empty; exact hostname is host-dependent


class TestGetCertStorePath:
    def test_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CERT_STORE_PATH", raising=False)
        assert get_cert_store_path() == "/var/lib/icu-edge-gateway/pki"

    def test_explicit_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CERT_STORE_PATH", "/mnt/pki")
        assert get_cert_store_path() == "/mnt/pki"


class TestGetProvisioningMaxEnrollAttempts:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PROVISIONING_MAX_ENROLL_ATTEMPTS", raising=False)
        assert get_provisioning_max_enroll_attempts() == 5

    def test_rejects_non_integer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVISIONING_MAX_ENROLL_ATTEMPTS", "many")
        with pytest.raises(ValueError, match="must be an integer"):
            get_provisioning_max_enroll_attempts()

    def test_rejects_less_than_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PROVISIONING_MAX_ENROLL_ATTEMPTS", "0")
        with pytest.raises(ValueError, match=">= 1"):
            get_provisioning_max_enroll_attempts()


class TestGetReattestationIntervalSeconds:
    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REATTESTATION_INTERVAL_SECONDS", raising=False)
        assert get_reattestation_interval_seconds() == 3600

    def test_rejects_non_positive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REATTESTATION_INTERVAL_SECONDS", "0")
        with pytest.raises(ValueError, match="must be positive"):
            get_reattestation_interval_seconds()
