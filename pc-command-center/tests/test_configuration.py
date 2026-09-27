from pcctl.core import config_audit, configuration
from pcctl.core.run import Step


def test_read_only_root_step_is_not_automatically_a_configuration_change():
    step = Step("Read status", ["cat", "/etc/os-release"], root=True)
    assert config_audit.is_configuration_step(step) is False


def test_explicit_mutation_metadata_overrides_fallback():
    assert config_audit.is_configuration_step(Step("Probe", ["systemctl", "status", "x"], mutates=False)) is False
    assert config_audit.is_configuration_step(Step("Custom write", ["my-helper"], mutates=True)) is True


def test_snapshot_keeps_partial_results(monkeypatch):
    item = configuration.ConfigItem("x", "Test", "One", "On", "test")
    monkeypatch.setattr(configuration, "PROVIDERS", (("good", lambda: [item]), ("bad", lambda: (_ for _ in ()).throw(RuntimeError("boom")))))
    snap = configuration.snapshot()
    assert snap.items == (item,)
    assert snap.provider_errors and "bad" in snap.provider_errors[0].lower()
