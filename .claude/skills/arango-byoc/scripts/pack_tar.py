#!/usr/bin/env python3
"""Create a BYOC .tar.gz with GNU long names and no macOS xattr pax headers."""
from __future__ import annotations

import sys
import tarfile
from pathlib import Path


def filt(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    parts = Path(info.name).parts
    if "__pycache__" in parts or info.name.endswith((".pyc", ".pyo")):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = "user"
    return info


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("usage: pack_tar.py OUT.tar.gz MEMBER [MEMBER ...]")
    out = Path(sys.argv[1])
    members = [Path(m) for m in sys.argv[2:]]
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz", format=tarfile.GNU_FORMAT, compresslevel=6) as tar:
        for src in members:
            if not src.exists():
                raise SystemExit(f"missing {src}")
            tar.add(src, arcname=src.name, filter=filt)
    print("packed " + ", ".join(p.name for p in members))


if __name__ == "__main__":
    main()
