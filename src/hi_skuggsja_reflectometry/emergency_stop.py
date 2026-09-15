from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

import keyboard

from .stages import wait_for_stop

if TYPE_CHECKING:
    import libximc.highlevel as ximc


def esc_listener(stop_event: threading.Event, axes: Sequence[ximc.Axis], names: Sequence[str]) -> None:
    keyboard.wait("esc")
    if not stop_event.is_set():
        print("\n🛑 ESC pressed — emergency stop!")
        stop_event.set()
        for axis, name in zip(axes, names):
            try:
                axis.command_stop()
                print(f"  [{name}] stopped ✓")
            except Exception as e:
                print(f"  [{name}] stop failed: {e}")


def run_with_emergency_stop(
    sweep_fn: Callable[..., None],
    axes: Sequence[ximc.Axis],
    names: Sequence[str],
    *sweep_args,
) -> None:
    """Runs sweep_fn(*sweep_args, stop_event) with a background ESC listener
    that can interrupt it, then closes the given axes."""
    stop_event = threading.Event()

    listener = threading.Thread(
        target=esc_listener,
        args=(stop_event, axes, names),
        daemon=True,
    )
    listener.start()

    try:
        sweep_fn(*sweep_args, stop_event)

    except RuntimeError as e:
        print(f"\n🛑 Aborted: {e}")

    finally:
        print("\nClosing connections...")
        for axis, name in zip(axes, names):
            try:
                if stop_event.is_set():
                    wait_for_stop(axis, stop_event)
                    axis.close_device()
                    print(f"  [{name}] disconnected ✓")
            except Exception as e:
                print(f"  [{name}] disconnect failed: {e}")
            finally:
                axis.close_device()
                print(f"  [{name}] disconnected ✓")
