"""Create a deployment ZIP from a local GitHub or Azure Repos checkout.

Usage: py package_app.py --source C:/src/accounting --output app-deploy.zip
Only application files are included. Credentials, databases and Git history are excluded.
"""
import argparse
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile


def package(source, output):
    source = source.resolve()
    output = output.resolve()
    required = ["app.py", "config.py", "requirements.txt"]
    for name in required:
        if not (source / name).is_file():
            raise ValueError(f"Missing {name}; --source must be the application repository root.")

    selected = [source / "app.py", source / "config.py"]
    for folder in ("database", "routes", "services", "templates", "static"):
        root = source / folder
        if not root.is_dir():
            raise ValueError(f"Missing application directory: {root}")
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(source)
            if not path.is_file() or path.is_symlink() or path.resolve() == output:
                continue
            if any(part.startswith(".") or part in ("__pycache__", "node_modules") for part in relative.parts):
                continue
            if path.suffix.lower() in (".db", ".sqlite", ".sqlite3", ".pyc", ".pem", ".key"):
                continue
            if path.name in ("tokens.json", "bas_review_status.json", "bas_approval.json"):
                continue
            if folder in ("database", "routes", "services") and path.suffix != ".py":
                continue
            selected.append(path)

    requirements = (source / "requirements.txt").read_text(encoding="utf-8")
    if not re.search(r"(?im)^\s*gunicorn(?:\s|[<>=!~\[]|$)", requirements):
        requirements += "\ngunicorn>=23.0,<24.0\n"

    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in selected:
            archive.write(path, path.relative_to(source).as_posix())
        archive.writestr("requirements.txt", requirements)
        archive.write(Path(__file__).with_name("azure_wsgi.py"), "azure_wsgi.py")
    print(f"Created {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("app-deploy.zip"))
    args = parser.parse_args()
    package(args.source, args.output)
