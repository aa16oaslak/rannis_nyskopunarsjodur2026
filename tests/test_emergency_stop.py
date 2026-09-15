import threading

from hi_skuggsja_reflectometry import emergency_stop
from tests.fakes import FakeAxis, ImmediateThread


def test_esc_listener_sets_stop_event_and_stops_axes(monkeypatch):
    monkeypatch.setattr(emergency_stop.keyboard, "wait", lambda _key: None)
    axes = [FakeAxis(), FakeAxis()]
    stop_event = threading.Event()

    emergency_stop.esc_listener(stop_event, axes, ["a", "b"])

    assert stop_event.is_set()
    assert all(("stop",) in axis.calls for axis in axes)


def test_esc_listener_is_noop_if_stop_event_already_set(monkeypatch):
    monkeypatch.setattr(emergency_stop.keyboard, "wait", lambda _key: None)
    axes = [FakeAxis(), FakeAxis()]
    stop_event = threading.Event()
    stop_event.set()

    emergency_stop.esc_listener(stop_event, axes, ["a", "b"])

    assert all(axis.calls == [] for axis in axes)


def test_run_with_emergency_stop_normal_completion_closes_once(monkeypatch):
    monkeypatch.setattr(emergency_stop.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(emergency_stop, "esc_listener", lambda *a, **k: None)  # ESC never pressed
    axes = [FakeAxis(), FakeAxis()]

    sweep_calls = []
    def sweep_fn(marker, stop_event):
        sweep_calls.append((marker, stop_event.is_set()))

    emergency_stop.run_with_emergency_stop(sweep_fn, axes, ["a", "b"], "extra")

    assert sweep_calls == [("extra", False)]
    for axis in axes:
        assert axis.calls == [("close",)]  # closed exactly once, no stop() issued


def test_run_with_emergency_stop_catches_runtime_error_from_sweep(monkeypatch, capsys):
    monkeypatch.setattr(emergency_stop.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(emergency_stop, "esc_listener", lambda *a, **k: None)
    axes = [FakeAxis()]

    def sweep_fn(stop_event):
        raise RuntimeError("boom")

    emergency_stop.run_with_emergency_stop(sweep_fn, axes, ["a"])  # must not propagate

    assert "Aborted: boom" in capsys.readouterr().out
    assert axes[0].calls == [("close",)]


def test_run_with_emergency_stop_esc_pressed_before_sweep_runs(monkeypatch):
    monkeypatch.setattr(emergency_stop.threading, "Thread", ImmediateThread)

    def stub_listener(stop_event, axes, names):
        stop_event.set()  # simulate ESC firing before sweep_fn ever gets called

    monkeypatch.setattr(emergency_stop, "esc_listener", stub_listener)
    axes = [FakeAxis()]

    def sweep_fn(stop_event):
        assert stop_event.is_set()

    emergency_stop.run_with_emergency_stop(sweep_fn, axes, ["a"])

    # finally-block's wait_for_stop() call raises immediately (stop_event already
    # set), issuing one command_stop(), then the outer unconditional close runs once
    assert axes[0].calls == [("stop",), ("close",)]
