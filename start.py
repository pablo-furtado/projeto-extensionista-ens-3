# ruff: noqa: E402

import subprocess
import sys




def run():
    processes = []

    # DJANGO
    processes.append(subprocess.Popen([
        sys.executable, "manage.py",
        "runserver"
    ]))
    
    for p in processes:
        p.wait()

if __name__ == "__main__":
    run()
