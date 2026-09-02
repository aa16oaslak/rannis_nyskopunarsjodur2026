import helpers_emerg_stop
from helpers_emerg_stop import *
from timeit import main
import libximc
#pip install libximc ##install the library
from libximc import *
import pathlib
import os
import time
import libximc.highlevel as ximc
import socket
import numpy as np
import threading 
import keyboard 


"""scan settings"""
start_angle = 30 #degrees
end_angle = 30 #degrees 
step = 7.5 #degrees
speed = 20 #steps/s
accel = 15 #steps/s^2
freq_start = 70 #GHz
freq_stop = 400 #GHz
int_time = 3 #ms
filename = f"270826_specular_ref" 
set_zero = False #set to True if you want to set the current position to zero before starting the sweep

""" variables """
angle_min =30 #degrees
angle_max = 180.0 #degrees

""" rotation stage device setup """
device_uri = r'xi-com:\\.\COM3' # replace com no. if needed
device_uri2 = r'xi-com:\\.\COM4'
large_stage = ximc.Axis(device_uri) #name device
large_stage.open_device() #open device
small_stage = ximc.Axis(device_uri2)
small_stage.open_device()

"""calibrate"""
res_large = 0.0072 #degrees per microstep
engine_settings_large = large_stage.get_engine_settings()
large_stage.set_calb(res_large, engine_settings_large.MicrostepMode)
res_small = 0.015 #degrees per microstep 
engine_settings_small = small_stage.get_engine_settings()
small_stage.set_calb(res_small, engine_settings_small.MicrostepMode)


"""set boundaries for large rotation stage"""

set_boundaries(large_stage, res_large, angle_min, angle_max)
print(f"Limits {angle_min}° to {angle_max}° set successfully")



"""
Perfoms a sweep from set_start to set_end with step size step_angle, speed and accel.
If set_zero is True, it will set the current position to zero before starting the sweep.

Note: for large rotation stage positions have a negative sign in front to make them positive
"""
def sweep(start, end, step, speed, accel, setzero, freq_start, freq_stop, int_time, filename, stop_event):  # ← added stop_event

    if setzero == True:
        home_and_zero(large_stage, small_stage, "8MRB450", "8MR174", angle_min, angle_max, res_large) 
    else:
        print(f'Rotating receiver to 30°')
        print(f'Rotating sample to 0°')
        rotate_to_angle(large_stage, 30, large=True, stop_event=stop_event)   # ← added stop_event
        if stop_event.is_set(): return
        rotate_to_angle(small_stage, 0, large=False, stop_event=stop_event)   # ← added stop_event
        if stop_event.is_set(): return
        position_l = -int(large_stage.get_position_calb().Position) + 232.605   
        print(f'Rotated receiver to {position_l}°')
        position_s = int(small_stage.get_position_calb().Position) + 40
        print(f'Rotated sample to {position_s}°')

    if stop_event.is_set(): return

    print(f'Rotating receiver to {2*start}°')
    print(f'Rotating sample to {start}°')
    rotate_to_angle(large_stage, 2*start, large=True, stop_event=stop_event)  # ← added stop_event
    if stop_event.is_set(): return
    rotate_to_angle(small_stage, start, large=False, stop_event=stop_event)   # ← added stop_event
    if stop_event.is_set(): return
    position_l = -int(large_stage.get_position_calb().Position) + 232.605 
    print(f'Rotated receiver to start position: {position_l}°')
    position_s = int(small_stage.get_position_calb().Position) + 40
    print(f'Rotated sample to start position: {position_s}°')

    if stop_event.is_set(): return

    step_l = 2 * step
    amount = int((end - start) / step)

    for i in range(amount + 1):
        if stop_event.is_set():
            print("🛑 Sweep interrupted by emergency stop")
            return

        if not i == 0:
            print(f'Rotating receiver to {2*start + i*step_l}°')
            print(f'Rotating sample to {start + i*step}°')
            position_l = -int(large_stage.get_position_calb().Position) + 232.605
            
            rotate_relative(large_stage, step_l, large=True, stop_event=stop_event)   # ← added stop_event
            if stop_event.is_set(): return
            
            rotate_relative(small_stage, step, large=False, stop_event=stop_event)    # ← added stop_event
            if stop_event.is_set(): return

            position_l = -int(large_stage.get_position_calb().Position) + 232.605
            print(f'Rotated receiver to {position_l}°.')
            position_s = int(small_stage.get_position_calb().Position) + 40
            print(f'Rotated sample to {position_s}°.')

        if stop_event.is_set(): return

        print(f'Connecting to Toptica and starting scan')
        n = start + i * step
        scan(freq_start, freq_stop, int_time, f'{filename}_{n}degrees', stop_event)   # ← added stop_event
        if stop_event.is_set(): return



def run_with_emergency_stop(start, end, step, speed, accel, setzero,
                             freq_start, freq_stop, int_time, filename):
    stop_event = threading.Event()

    # Start ESC listener in background
    listener = threading.Thread(
        target=esc_listener,
        args=(stop_event, [large_stage, small_stage], ["8MRB450", "8MR174"]),
        daemon=True
    )
    listener.start()

    try:
        sweep(start, end, step, speed, accel, setzero,
              freq_start, freq_stop, int_time, filename,
              stop_event)                                  # ← pass stop_event in

    except RuntimeError as e:
        print(f"\n🛑 Aborted: {e}")

    finally:
        print("\nClosing connections...")
        for axis, name in zip([large_stage, small_stage], ["8MRB450", "8MR174"]):
            try:
                if stop_event.is_set():
                    #axis.command_move_calb(0)              # return to zero
                    # don't use rotate_to_angle here — keep it simple in finally
                    wait_for_stop(axis, stop_event)
                    axis.close_device()
                    print(f"  [{name}] disconnected ✓")
            except Exception as e:
                print(f"  [{name}] disconnect failed: {e}")
            finally:
                axis.close_device()
                print(f"  [{name}] disconnected ✓")


def esc_listener(stop_event, axes, names):
    keyboard.wait('esc')
    if not stop_event.is_set():
        print("\n🛑 ESC pressed — emergency stop!")
        stop_event.set()
        for axis, name in zip(axes, names):
            try:
                axis.command_stop()
                print(f"  [{name}] stopped ✓")
            except Exception as e:
                print(f"  [{name}] stop failed: {e}")


# ── entry point ──────────────────────────────
if __name__ == '__main__':
    run_with_emergency_stop(
        start_angle, end_angle, step, speed, accel, set_zero,
        freq_start, freq_stop, int_time, filename
    )