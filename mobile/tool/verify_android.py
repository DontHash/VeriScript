"""Run Android integration and inject its video fixture over ADB after reinstall."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--device', default='emulator-5554')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
os.chdir(root)
sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Android/Sdk'))
adb = sdk / 'platform-tools/adb.exe'
flutter = shutil.which('flutter') or 'C:/flutter/bin/flutter.bat'
prefix = [str(adb), '-s', args.device, 'shell']
network = subprocess.check_output(prefix + ['dumpsys', 'connectivity'], text=True)
if 'Active default network: none' not in network:
    raise SystemExit('Disconnect Android networking first; no active default network is required.')
fixture = root / 'build/verification/book-fixture.mp4'
if not fixture.exists():
    subprocess.run([sys.executable, 'tool/make_book_fixture.py'], check=True)
fixture.with_name('connectivity.txt').write_text(network, encoding='utf-8')
subprocess.run([str(adb), '-s', args.device, 'push', str(fixture), '/data/local/tmp/veriscript-book.mp4'], check=True)
injected = False
with fixture.with_name('android-integration.log').open('w', encoding='utf-8') as log:
    process = subprocess.Popen([flutter, 'test', 'integration_test/offline_test.dart', '-d', args.device, '--no-uninstall'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    try:
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
            log.flush()
            if not injected and '+0:' in line and 'Bundled first-launch OCR' in line:
                # flutter test reinstalls and clears private files. Inject only
                # once the new test process has launched. adb push preserves
                # binary bytes; shell stdin can truncate a binary stream.
                subprocess.run(prefix + ['run-as', 'com.veriscript.veriscript_mobile', 'mkdir', '-p', 'files'], check=True)
                subprocess.run(prefix + ['run-as', 'com.veriscript.veriscript_mobile', 'cp', '/data/local/tmp/veriscript-book.mp4', 'files/book-fixture.mp4'], check=True)
                received = subprocess.check_output(prefix + ['run-as', 'com.veriscript.veriscript_mobile', 'sha256sum', 'files/book-fixture.mp4'], text=True).split()[0]
                if received != hashlib.sha256(fixture.read_bytes()).hexdigest():
                    raise RuntimeError('Fixture transfer checksum differs')
                injected = True
        code = process.wait()
    except BaseException:
        process.terminate()
        process.wait()
        raise
if not injected:
    raise SystemExit('The test never started; video fixture was not injected.')
raise SystemExit(code)
