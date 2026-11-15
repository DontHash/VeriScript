"""Run the paired OCR pack in a separate Android application sandbox.

python mobile/tool/compare_ocr.py                       # the 6-page smoke pack
python mobile/tool/compare_ocr.py --pack camera --import-first --tag _base
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='emulator-5554')
    parser.add_argument('--pack', default='pack',
                        help='pack folder under build/ocr-comparison (e.g. camera)')
    parser.add_argument('--tag', default='', help='suffix for output folders, e.g. _base')
    parser.add_argument('--engines', default='mlkit,rapidocr')
    parser.add_argument('--import-first', action='store_true',
                        help='import each image with the default alignment/enhancement first')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    pack = root / 'build/ocr-comparison' / args.pack
    # The original smoke pack keeps its historical app folder name.
    pack_name = 'ocr-comparison' if args.pack == 'pack' else f'ocr-{args.pack}'
    app_dir = f'files/{pack_name}'
    adb = str(Path(os.environ.get('ANDROID_HOME', 'D:/Android/Sdk')) / 'platform-tools/adb.exe')
    prefix = [adb, '-s', args.device]
    network = subprocess.check_output(prefix + ['shell', 'dumpsys', 'connectivity'], text=True)
    if 'Active default network: none' not in network:
        raise SystemExit('Disconnect Android Wi-Fi/data before this offline comparison.')
    (pack.parent / 'connectivity.txt').write_text(network, encoding='utf-8')
    app = 'com.veriscript.veriscript_mobile.benchmark'
    # Only this disposable test package is cleared. Otherwise a previous run's
    # manifest could start OCR before the new input pack has been injected.
    installed = subprocess.run(prefix + ['shell', 'pm', 'path', app], text=True,
                               capture_output=True)
    if installed.stdout.strip():
        cleared = subprocess.check_output(prefix + ['shell', 'pm', 'clear', app], text=True)
        if cleared.strip() != 'Success':
            raise RuntimeError('Could not reset isolated benchmark app: ' + cleared)
    remote = f'/data/local/tmp/veriscript-{pack_name}'
    subprocess.run(prefix + ['shell', 'rm', '-rf', remote], check=True)
    subprocess.run(prefix + ['shell', 'mkdir', '-p', remote], check=True)
    for item in ['pages', 'gt', 'manifest.json']:
        subprocess.run(prefix + ['push', str(pack / item), remote + '/'], check=True)
    env = dict(os.environ, ORG_GRADLE_PROJECT_benchmarkApp='true')
    flutter = shutil.which('flutter') or 'C:/flutter/bin/flutter.bat'
    logpath = pack.parent / f'mobile-{args.pack}{args.tag}.log'
    defines = [f'--dart-define=PACK={pack_name}', f'--dart-define=TAG={args.tag}',
               f'--dart-define=ENGINES={args.engines}',
               f'--dart-define=IMPORT={"1" if args.import_first else "0"}']
    with logpath.open('w', encoding='utf-8') as log:
        process = subprocess.Popen([flutter, 'test', 'integration_test/ocr_comparison_test.dart',
                                    '-d', args.device, '--no-uninstall', *defines],
                                   cwd=root / 'mobile', env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   encoding='utf-8', errors='replace')
        injected = False
        try:
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
                if not injected and '+0:' in line and 'Paired OCR comparison' in line:
                    # Flutter reinstalls integration apps. Publish the manifest last
                    # so the reader cannot observe a partially copied input pack.
                    run = prefix + ['shell', 'run-as', app]
                    subprocess.run(run + ['mkdir', '-p', app_dir], check=True)
                    for folder in ['pages', 'gt']:
                        subprocess.run(run + ['cp', '-r', f'{remote}/{folder}', app_dir + '/'],
                                       check=True)
                    for row in json.loads((pack / 'manifest.json').read_text(encoding='utf-8'))['entries']:
                        for path_key, hash_key in [('image', 'sha256'), ('gt', 'gt_sha256')]:
                            actual = subprocess.check_output(run + ['sha256sum',
                                f'{app_dir}/' + row[path_key]], text=True).split()[0]
                            if actual != row[hash_key]:
                                raise ValueError('Android input hash differs: ' + row[path_key])
                    subprocess.run(run + ['cp', f'{remote}/manifest.json',
                                          f'{app_dir}/manifest.json'], check=True)
                    injected = True
            code = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            raise
    if not injected:
        raise SystemExit('Test never launched; see ' + str(logpath))
    # exec-out preserves binary tar bytes; PowerShell stdout redirection does not.
    archive = subprocess.check_output(prefix + ['exec-out', 'run-as', app, 'tar', '-C',
                                              app_dir, '-cf', '-', 'outputs'])
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(pack, filter='data')
    if code:
        raise SystemExit(code)


if __name__ == '__main__':
    main()
