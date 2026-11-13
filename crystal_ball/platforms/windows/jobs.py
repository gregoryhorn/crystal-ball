"""Pointer-width-correct Win32 Job Object ownership (Windows 10/11)."""
import ctypes
from ctypes import wintypes as w

k32 = ctypes.WinDLL('kernel32', use_last_error=True)

class BASIC(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]

class IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

class EXTENDED(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', BASIC), ('IoInfo', IO),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

for name, args, result in [
    ('CreateJobObjectW', [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
    ('OpenJobObjectW', [w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE),
    ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
    ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
    ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
    ('CloseHandle', [w.HANDLE], w.BOOL), ('GetCurrentProcess', [], w.HANDLE)]:
    fn = getattr(k32, name)
    fn.argtypes = args
    fn.restype = result


def checked(result):
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    return result


class Job:
    def __init__(self, name):
        self.handle = checked(k32.CreateJobObjectW(None, name))
        try:
            info = EXTENDED()
            info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
            checked(k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)))
        except BaseException:
            self.close()
            raise

    def terminate(self):
        checked(k32.TerminateJobObject(self.handle, 1))

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            checked(k32.CloseHandle(handle))


def assign_current(name):
    handle = checked(k32.OpenJobObjectW(0x0001 | 0x0004, False, name))  # ASSIGN_PROCESS | QUERY
    try:
        checked(k32.AssignProcessToJobObject(handle, k32.GetCurrentProcess()))
    finally:
        checked(k32.CloseHandle(handle))
