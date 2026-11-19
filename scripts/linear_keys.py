"""Bounded linear key reduction, tested against every input sample."""
import numpy as np


def reduce_keys(times, values, tolerance=1e-7):
    times = np.asarray(times, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if len(times) != len(values) or not np.isfinite(values).all():
        raise ValueError('Invalid key arrays')
    if len(times) < 3:
        return np.arange(len(times))
    if np.any(np.diff(times) <= 0):
        raise ValueError('Sample times must increase')
    keep = {0, len(times)-1}; pending = [(0, len(times)-1)]
    while pending:
        lo, hi = pending.pop()
        if hi-lo < 2: continue
        estimate = values[lo] + (values[hi]-values[lo]) * ((times[lo+1:hi]-times[lo])/(times[hi]-times[lo]))
        error = abs(estimate-values[lo+1:hi]); offset = int(np.argmax(error))
        if error[offset] > tolerance:
            pivot = lo+1+offset; keep.add(pivot); pending.extend(((lo,pivot),(pivot,hi)))
    indices = np.array(sorted(keep), dtype=int)
    if np.max(abs(np.interp(times, times[indices], values[indices])-values)) > tolerance+1e-12:
        raise RuntimeError('Key reduction exceeded tolerance')
    return indices
