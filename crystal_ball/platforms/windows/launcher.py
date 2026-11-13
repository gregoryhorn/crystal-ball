"""Contain this launcher before starting any requested executable."""
import os
import subprocess
import sys


def main():
    # Executed by absolute script path using the core interpreter; no engine imports.
    sys.path.insert(0, os.path.dirname(__file__))
    from jobs import assign_current
    name, ready, *argv = sys.argv[1:]
    try:
        assign_current(name)
        with open(ready, 'w', encoding='utf-8') as handle:
            handle.write('contained')
        child = subprocess.Popen(argv, shell=False, stdin=sys.stdin.buffer,
                                 stdout=sys.stdout.buffer, stderr=sys.stderr.buffer)
        return child.wait()
    except BaseException as exc:
        print(f'Windows owned launcher unavailable: {exc}', file=sys.stderr, flush=True)
        return 125


if __name__ == '__main__':
    raise SystemExit(main())
