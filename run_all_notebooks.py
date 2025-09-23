import sys
from pathlib import Path
import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

ROOT = Path(__file__).parent.resolve()   # run from the repository root (script dir)

TIMEOUT = 600

def run_notebook(nb_path: Path, timeout=TIMEOUT):
    nb = nbformat.read(nb_path, as_version=4)
    client = NotebookClient(nb, timeout=timeout, kernel_name="python3")
    try:
        client.execute()
        out_path = nb_path.with_suffix(".executed.ipynb")
        nbformat.write(nb, out_path)
        return True, None
    except CellExecutionError as e:
        return False, str(e)
    except Exception as e:
        return False, repr(e)

def main():
    # ignore common virtualenv / package dirs
    exclude_dirs = {".ipynb_checkpoints", ".venv", "venv", "env", ".env", "site-packages"}
    notebooks = [
        p for p in ROOT.rglob("*.ipynb")
        # skip virtualenvs, checkpoint dirs, and any already-executed notebooks
        if not any(part in exclude_dirs for part in p.parts)
        and ".executed" not in p.name
    ]
    failures = []
    for nb in sorted(notebooks):
        print(f"Running {nb} ...", flush=True)
        ok, err = run_notebook(nb)
        if ok:
            print("  OK")
        else:
            print("  FAIL")
            failures.append((nb, err))
    print("\nSummary:")
    print(f"  total: {len(notebooks)}, failed: {len(failures)}")
    if failures:
        for nb, err in failures:
            print(f"\n--- {nb} ---\n{err}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()