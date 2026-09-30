from __future__ import annotations
from importlib import metadata
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOTS = ["numpy", "pandas", "scipy", "gradio", "openpyxl", "pytest", "PyYAML"]

def main() -> None:
    todo=[canonicalize_name(x) for x in ROOTS]; seen={}
    while todo:
        name=todo.pop()
        if name in seen: continue
        dist=metadata.distribution(name)
        seen[name]=f"{dist.metadata.get('Name', name)}=={dist.version}"
        for raw in dist.requires or []:
            req=Requirement(raw)
            if req.marker is not None and not req.marker.evaluate({"extra": ""}): continue
            dep=canonicalize_name(req.name)
            if dep not in seen: todo.append(dep)
    lines=["# Exact reference environment generated from the validated Python 3.13 environment."]+[seen[k] for k in sorted(seen)]
    Path("requirements-reference-lock.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
if __name__ == "__main__": main()
