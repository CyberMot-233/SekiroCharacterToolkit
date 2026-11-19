"""Read commit headroom, not just free physical RAM (no system settings changed)."""
import ctypes
import os


def peak_working_set():
    if os.name != 'nt': return None
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)] + [(n,ctypes.c_size_t) for n in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    get=ctypes.windll.kernel32.GetCurrentProcess;get.restype=wintypes.HANDLE
    query=ctypes.windll.psapi.GetProcessMemoryInfo;query.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    if not query(get(),ctypes.byref(counters),counters.cb):raise ctypes.WinError()
    return counters.PeakWorkingSetSize


def available_commit():
    if os.name != 'nt':
        return None
    class Status(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
            ('total_phys', 'avail_phys', 'total_page', 'avail_page', 'total_virtual', 'avail_virtual', 'extended')]
    status = Status(); status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return status.avail_page


def require_memory(minimum=768*1024**2):
    available = available_commit()
    if available is not None and available < minimum:
        raise MemoryError(f'SCT_MEMORY: 系统可提交内存不足（剩余 {available/1024**3:.2f} GB）；'
                          '请先关闭占用大量内存的 CS2/模拟器后继续。已完成批次保留，不需要重新解包。')
    return available
