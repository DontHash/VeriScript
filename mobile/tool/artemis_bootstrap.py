"""Reuse Project Auto's Artemis source in an isolated, ignored local runtime."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('D:/Code/Project_auto/tools/artemis'))
    parser.add_argument('--copy-only', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve()
    mobile = Path(__file__).resolve().parents[1]
    runtime = mobile / '.artemis-runtime'
    if not (source / 'artemis/interfaces/cli/main.py').is_file():
        parser.error(f'Cannot find Artemis CLI in {source}')
    runtime.mkdir(exist_ok=True)
    # Copy only engine/MCP/client source. Never copy private configuration,
    # dotenv files, old traces, databases, or Project Auto's application data.
    ignore = shutil.ignore_patterns('.env*', '__pycache__', '*.pyc', '*.log', '*.db', 'traces', '.venv', 'node_modules')
    for relative in ('artemis', 'mcp_server', 'packages/artemis-client'):
        shutil.copytree(source / relative, runtime / relative, dirs_exist_ok=True, ignore=ignore)
    for name in ('pyproject.toml', 'LICENSE'):
        if (source / name).is_file():
            shutil.copy2(source / name, runtime / name)
    (runtime / 'SOURCE.txt').write_text(str(source), encoding='utf-8')
    if args.copy_only:
        print(f'Isolated source copied to {runtime}')
        return
    uv = shutil.which('uv')
    if not uv:
        parser.error('uv must be installed and available on PATH')
    venv = mobile / '.artemis-venv'
    python = venv / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.exists():
        subprocess.run([uv, 'venv', str(venv), '--python', sys.executable, '--system-site-packages'], check=True)
    project = tomllib.loads((source / 'pyproject.toml').read_text(encoding='utf-8'))
    requirements = [d for d in project['project']['dependencies'] if not d.startswith('artemis-client')]
    subprocess.run([uv, 'pip', 'install', '--python', str(python), str(runtime / 'packages/artemis-client'), *requirements], check=True)
    print('Artemis runtime ready. Run ./tool/artemis.ps1 doctor. Configure a model provider in the isolated runtime before autonomous runs.')


if __name__ == '__main__':
    main()
