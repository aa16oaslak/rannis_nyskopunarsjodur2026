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


zero_l = 180.5
#232.605 #degrees #zero for large rot stage wrt home (line on stage lines up with 0)

zero_s = -40 #degrees #zero for small rot stage wrt home

# functions for rotation stages #

# ----------------------------------------------
"""
returns microsteps for given angle
"""

def degrees_to_microsteps(resolution, angle):
    return int(angle/resolution)

#-----------------------------------------------


# ---------------------------------------
"""
set speed and acceleration for rotation stages - checks that set speed and acceleration are within bounds
"""
def set_speed_accel(axis, speed, accel):
    if not 0 < speed <= 300:
        raise ValueError("Speed must be between 0 and max speed.")
    if not 0 < accel <= 250:
        raise ValueError("Acceleration must be between 0 and max acceleration.")
    mvst = axis.get_move_settings()
    mvst.Speed = int(speed)
    mvst.Accel = int(accel)
    axis.set_move_settings(mvst)
# ----------------------------------------------

#-----------------------------------------------
""" 
-rotates stage to absolute position
-checks if axis is the large stage
-for large stage: target angle becomes negative to get positive rotation,
                  checks that target angle is within allowed bounds
-command_move_calb() takes angle input - calibrated in main code
"""
def rotate_to_angle(axis, target_angle, large, stop_event, angle_min=29, angle_max=180):  # ← added stop_event
    if large == True:
        zero = zero_l
        if not angle_min <= target_angle <= angle_max:
            raise ValueError("Target angle is out of bounds.")
        target_angle = -target_angle
    else:
        zero = zero_s
    
    axis.command_move_calb(zero + target_angle)
    
    # ← replaced command_wait_for_stop(100) with polling loop
    wait_for_stop(axis, stop_event)
    
    if stop_event.is_set():
        axis.command_stop()  # ensure stage stops if ESC mid-move
        raise RuntimeError("Emergency stop during rotate_to_angle")
#-----------------------------------------------


#-----------------------------------------------
""" 
-rotates stage to relative position
-checks if axis is the large stage
-for large stage: delta angle becomes negative
                  checks that final angle is within allowed bounds
-command_movr_calb() moves to relative angle input - calibrated in main code
"""
def rotate_relative(axis, delta_angle, large, stop_event, angle_min=30, angle_max=180):  # ← added stop_event
    if large == True:
        if not angle_min <= -int(axis.get_position_calb().Position) + zero_l + delta_angle <= angle_max:
            raise ValueError("Target angle is out of bounds.")
        delta_angle = -delta_angle
    
    axis.command_movr_calb(delta_angle)
    
    # ← replaced command_wait_for_stop(100) with polling loop
    wait_for_stop(axis, stop_event)
    
    if stop_event.is_set():
        axis.command_stop()  # ensure stage stops if ESC mid-move
        raise RuntimeError("Emergency stop during rotate_relative")
#-----------------------------------------------

from libximc.highlevel import MvcmdStatus

def wait_for_stop(axis, stop_event, poll_ms=100):
    """Replace command_wait_for_stop() — checks stop_event while waiting."""
    while not stop_event.is_set():
        status = axis.get_status()
        if not (MvcmdStatus.MVCMD_RUNNING in status.MvCmdSts):
            break
        time.sleep(poll_ms / 1000)
    
    if stop_event.is_set():
        axis.command_stop()
        raise RuntimeError("Emergency stop")





# functions for TOptica system #

#-----------------------------------------------
""" functions to collect data """
def read_until_prompt(sock):
    response = b''
    while True:
        chunk = sock.recv(4096)
        response += chunk
        if response.endswith(b'> '):
            break
    return response.decode('utf-8', errors='ignore').strip()

def send_command(sock, cmd):
    sock.sendall((cmd + '\n').encode())
    return read_until_prompt(sock)

def get_float(sock, param):
    """Read a parameter and return it as a float."""
    response = send_command(sock, f"(param-ref '{param})")
    return float(response.split('\n')[0])
#-----------------------------------------------

#-----------------------------------------------
"""collecting data"""

def scan(start_freq, stop_freq, int_time, filename, stop_event):  # ← added stop_event
    s = socket.socket()
    s.connect(('130.208.168.223', 1998))

    # ── Connect and authenticate ───────────────────────────────────────────────
    read_until_prompt(s)
    send_command(s, "(exec 'change-ul 3 \"\")")

    # ── Scan parameters ────────────────────────────────────────────────────────
    FREQ_START      = start_freq
    FREQ_STOP       = stop_freq
    FREQ_STEP       = 0.05
    INTEGRATION     = int_time
    SETTLE_FREQ_TOL = 0.1
    SETTLE_TIMEOUT  = 10.0
    AMP             = get_float(s, 'lockin:mod-out-amplitude')
    AMP_DEF         = get_float(s, 'lockin:mod-out-amplitude-default')
    AMP_TOL         = 0.0005
    OFFSET          = get_float(s, 'lockin:mod-out-offset')
    OFFSET_DEF      = get_float(s, 'lockin:mod-out-offset-default')
    OFFSET_TOL      = 0.0002
    GAIN            = get_float(s, 'lockin:amplifier-gain')
    GAIN_DEF        = 330000

    # ── Apply settings ─────────────────────────────────────────────────────────
    if not np.abs(float(AMP) - float(AMP_DEF)) < AMP_TOL:
        raise ValueError("lockin:mod_out_amplitude incorrect.")
    if not np.abs(OFFSET - OFFSET_DEF) < OFFSET_TOL:
        raise ValueError("lockin:mod_out_offset incorrect.")
    if not GAIN == GAIN_DEF:
        raise ValueError("lockin:amplifier_gain incorrect.")
    print(f"lockin:mod_out_amplitude: {AMP}")
    print(f"lockin:mod_out_offset: {OFFSET}")
    print(f"lockin:amplifier_gain: {GAIN}")
    print("Configuring precise scan mode...")
    send_command(s, f"(param-set! 'frequency:scan-mode-fast #f)")
    send_command(s, f"(param-set! 'lockin:integration-time {INTEGRATION})")

    if stop_event.is_set():  # ← check after setup, before scan starts
        print("🛑 Emergency stop — aborting scan before it started")
        s.close()
        return

    # ── Build frequency list ───────────────────────────────────────────────────
    frequencies = np.arange(FREQ_START, FREQ_STOP + FREQ_STEP, FREQ_STEP)
    print(f"Scan: {FREQ_START} to {FREQ_STOP} GHz in {FREQ_STEP} GHz steps = {len(frequencies)} points")

    # ── Storage ────────────────────────────────────────────────────────────────
    results_freq_set     = []
    results_freq_act     = []
    results_photocurrent = []

    # ── Move to start frequency and wait for full stabilization ───────────────
    print(f"Moving to start frequency {FREQ_START} GHz...")
    send_command(s, f"(param-set! 'frequency:frequency-set {FREQ_START})")

    STABILIZE_TOL     = 0.01
    STABILIZE_HOLD    = 2.0
    STABILIZE_TIMEOUT = 30.0

    t_start      = time.time()
    stable_since = None

    while True:
        if stop_event.is_set():  # ← check during initial stabilisation wait
            print("🛑 Emergency stop during frequency stabilisation")
            s.close()
            return

        freq_act   = get_float(s, 'frequency:frequency-act')
        within_tol = abs(freq_act - FREQ_START) < STABILIZE_TOL

        if within_tol:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= STABILIZE_HOLD:
                print(f"  Frequency stable at {freq_act:.3f} GHz")
                break
        else:
            stable_since = None

        if time.time() - t_start > STABILIZE_TIMEOUT:
            print(f"  Warning: frequency did not fully stabilize "
                  f"(actual: {freq_act:.3f} GHz, target: {FREQ_START} GHz)")
            break

        print(f"  Waiting... current frequency: {freq_act:.3f} GHz")
        time.sleep(0.2)

    print("Proceeding with scan.\n")
    scan_start_time = time.time()

    # ── Scan loop ──────────────────────────────────────────────────────────────
    for i, freq in enumerate(frequencies):
        if stop_event.is_set():  # ← check at start of every frequency step
            print(f"🛑 Emergency stop at frequency step {i+1}/{len(frequencies)}")
            break

        # 1. Set frequency
        send_command(s, f"(param-set! 'frequency:frequency-set {freq})")

        # 2. Wait for frequency to settle
        t_start = time.time()
        while True:
            if stop_event.is_set():  # ← check while waiting to settle
                print("🛑 Emergency stop during frequency settle")
                break
            freq_act = get_float(s, 'frequency:frequency-act')
            if abs(freq_act - freq) < SETTLE_FREQ_TOL:
                break
            if time.time() - t_start > SETTLE_TIMEOUT:
                print(f"  Warning: frequency did not settle at {freq} GHz "
                      f"(actual: {freq_act:.2f} GHz)")
                break
            time.sleep(0.1)

        if stop_event.is_set():  # ← check after settle loop
            break

        # 3. Reset lock-in and wait integration time
        send_command(s, "(exec 'lockin:lock-in-reset)")
        
        # ← split sleep into small chunks so ESC is caught during integration
        integration_s = INTEGRATION / 1000.0
        elapsed = 0.0
        while elapsed < integration_s:
            if stop_event.is_set():
                print("🛑 Emergency stop during integration")
                break
            time.sleep(0.05)
            elapsed += 0.05

        if stop_event.is_set():  # ← check after integration sleep
            break

        # 4. Read lock-in value
        response    = send_command(s, "(param-ref 'lockin:lock-in-value-nanoamp)")
        response    = response.split('\n')[0].strip('()')
        parts       = response.split()
        photocurrent = float(parts[0])
        is_valid    = parts[1] == '#t'

        if not is_valid:
            print(f"  Warning: lock-in value not valid at {freq} GHz, "
                  f"waiting extra integration time...")
            elapsed = 0.0
            while elapsed < integration_s:
                if stop_event.is_set():  # ← check during retry integration
                    break
                time.sleep(0.05)
                elapsed += 0.05

            if stop_event.is_set():
                break

            response     = send_command(s, "(param-ref 'lockin:lock-in-value-nanoamp)")
            response     = response.split('\n')[0].strip('()')
            parts        = response.split()
            photocurrent = float(parts[0])

        # 5. Read actual frequency
        freq_act = get_float(s, 'frequency:frequency-act')

        # 6. Store results
        results_freq_set.append(freq)
        results_freq_act.append(freq_act)
        results_photocurrent.append(photocurrent)

        # Progress update every 30 points
        if i % 30 == 0:
            elapsed_total = time.time() - scan_start_time
            remaining     = (elapsed_total / (i + 1)) * (len(frequencies) - i - 1)
            print(f"  [{i+1}/{len(frequencies)}] {freq:.1f} GHz → "
                  f"actual: {freq_act:.2f} GHz, "
                  f"photocurrent: {photocurrent:.2f} nA, "
                  f"est. remaining: {remaining:.0f}s")

    # ── Save whatever was collected, even if interrupted ───────────────────────
    if results_freq_set:
        if stop_event.is_set():
            print(f"\n🛑 Scan interrupted — saving {len(results_freq_set)} points collected so far")
        else:
            print(f"\nScan complete! {len(results_freq_set)} points in "
                  f"{time.time()-scan_start_time:.1f}s")

        data = np.column_stack([
            np.arange(len(results_freq_set)),
            results_freq_set,
            results_freq_act,
            results_photocurrent
        ])
        file = f"{filename}_{int_time}ms_{start_freq}GHz_to_{stop_freq}.txt"
        np.savetxt(file, data,
                   header="point_number\tfreq_set_GHz\tfreq_act_GHz\tphotocurrent_nA",
                   delimiter='\t')
        print(f"Saved to {file}")
    else:
        print("No data collected — nothing saved")

    s.close()

def position(axis, large):
    if large == True:
        return - int(axis.get_position_calb().Position) + zero_l
    else:
        return int(axis.get_position_calb().Position) - zero_s



def confirm_path_clear(min_deg, max_deg):
    """
    Blocks until the user explicitly confirms the path is clear.
    Returns True only on exact match to the confirmation phrase —
    this avoids accidental Enter-presses confirming a dangerous move.
    """
    print("\n" + "="*60)
    print("⚠️WARNING")
    print("="*60)
    print(f"To reset zero position the stages must return to home ({zero_l}° and {-zero_s}°),")
    print(f"OUTSIDE operating boundaries ({min_deg}° to {max_deg}°).")
    print("This range is not guaranteed to be clear of obstacles.")
    print()
    print("Before continuing:")
    print("  1. Check the full rotation path is clear of cables,")
    print("     mounts, or anything that could collide with the stage.")
    print("  2. Make sure no measurement equipment is in the way.")
    print("="*60)

    response = input("\nType 'clear' to confirm the path is clear and proceed, "
                      "or anything else to cancel: ").strip().lower()

    if response == 'clear':
        print("✅ Confirmed — proceeding with homing.\n")
        return True
    else:
        print("❌ Homing cancelled.\n")
        return False


def home_and_zero(axis1, axis2, name1, name2, min_deg, max_deg, res):
    """
    Moves to home position and sets zero there.
    Requires explicit user confirmation since home_deg may be
    outside the normal safe bounds.
    """
    print(f"  [{name2}] Moving to home position ({zero_s}°)...")

    axis2.command_homezero()

    print(f"  [{name2}] Homed and zeroed ✓")

    if not confirm_path_clear(min_deg, max_deg):
        raise RuntimeError(f"[{name1}] Homing aborted by user — coast not confirmed clear")

    print(f"  [{name1}] Moving to home position ({-zero_l}°)...")

    
    # Temporarily widen soft limits to allow reaching home, if home is outside them
    edges = axis1.get_edges_settings()
    original_left, original_right = edges.LeftBorder, edges.RightBorder
    
    home_steps = degrees_to_microsteps(res, -zero_l)
    if home_steps < original_left or home_steps > original_right:
        # widen just enough to fit home position, with a little margin
        margin = degrees_to_microsteps(res, 5.0)
        edges.LeftBorder  = min(original_left,  home_steps - margin)
        edges.RightBorder = max(original_right, home_steps + margin)
        axis1.set_edges_settings(edges)
        print(f"  [{name1}] Temporarily widened limits to reach home")

    try:
        axis1.command_homezero()
        print(f"  [{name1}] Homed and zeroed ✓")
    finally:
        # Always restore original limits, even if move failed
        edges.LeftBorder  = original_left
        edges.RightBorder = original_right
        axis1.set_edges_settings(edges)
        print(f"  [{name1}] Restored normal safe limits")



def set_boundaries(axis, res, angle_min, angle_max):
    edges = axis.get_edges_settings()
    existing_ender_flags = edges.EnderFlags
    edges.LeftBorder  = degrees_to_microsteps(res, zero_l-angle_max) ## Left border - maximum angle
    edges.RightBorder = degrees_to_microsteps(res, zero_l-angle_min)  ## Right border - minimum angle
    edges.BorderFlags = ximc.BorderFlags(0x07)  # BORDER_IS_ALIVE | BORDER_STOP_LEFT | BORDER_STOP_RIGHT
    edges.EnderFlags  = existing_ender_flags   # keep existing SW1+SW2 config
    axis.set_edges_settings(edges)

