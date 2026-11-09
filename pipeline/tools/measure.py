"""Run a command and report its wall time and peak memory (T4, T5a laptop checks).

    python -m pipeline.tools.measure -- python -m pipeline run source/article-XX.md --from tts

Peak memory is the largest single process in the run: on Windows the peak committed
memory of any process in a Job Object that holds this tool and everything it starts
(the venv launcher, the real python.exe, any helper); on Linux/macOS the peak resident
size of the largest child. Standard library only.
"""

from __future__ import annotations

import subprocess
import sys
import time


class _WindowsJob:
    """Put this process (and so every process it starts) in a Job Object and read the
    job's peak committed memory. Counting only the child is not enough on Windows:
    `.venv\\Scripts\\python.exe` is a small launcher that starts the real python.exe."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                  wintypes.DWORD, ctypes.c_void_p]
        self.k32, self.ctypes = k32, ctypes
        self.job = k32.CreateJobObjectW(None, None)
        self.ok = bool(self.job) and bool(k32.AssignProcessToJobObject(self.job, k32.GetCurrentProcess()))

    def peak(self) -> int:
        ctypes = self.ctypes
        if not self.ok:
            return 0

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                        ("SchedulingClass", ctypes.c_uint32)]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        info = EXTENDED_LIMIT()
        if not self.k32.QueryInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info), None):
            return 0  # 9 = JobObjectExtendedLimitInformation
        return int(info.PeakProcessMemoryUsed)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("usage: python -m pipeline.tools.measure -- <command> [args...]")
        return 2
    job = _WindowsJob() if sys.platform == "win32" else None
    start = time.monotonic()
    proc = subprocess.Popen(args)
    proc.wait()
    wall = time.monotonic() - start
    if job is not None:
        peak = job.peak()
    else:
        import resource

        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        peak *= 1 if sys.platform == "darwin" else 1024  # Linux reports KiB
    print(f"[measure] exit code {proc.returncode}, wall time {wall:.1f} s, peak memory {peak / 2**20:.0f} MB (largest process)")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
