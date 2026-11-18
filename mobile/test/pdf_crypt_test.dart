import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:image/image.dart' as img;

import 'package:flutter_test/flutter_test.dart';
import 'package:veriscript_mobile/pdf_crypt.dart';
import 'package:veriscript_mobile/pdf_stream.dart';

/// docs/TECH_UPGRADE_PLAN.md E5: AES against FIPS-197, the revision 6 hash
/// against pypdf's implementation.
void main() {
  Uint8List h(String hex) => Uint8List.fromList([
    for (var i = 0; i < hex.length; i += 2) int.parse(hex.substring(i, i + 2), radix: 16),
  ]);
  String x(List<int> v) => v.map((b) => b.toRadixString(16).padLeft(2, '0')).join();

  test('AES-128 and AES-256 match FIPS-197 appendix C', () {
    final plain = h('00112233445566778899aabbccddeeff');
    final out = Uint8List(16);
    Aes(h('000102030405060708090a0b0c0d0e0f')).encryptBlock(plain, 0, out, 0);
    expect(x(out), '69c4e0d86a7b0430d8cdb78070b4c55a');
    Aes(h('000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f'))
        .encryptBlock(plain, 0, out, 0);
    expect(x(out), '8ea2b7ca516745bfeafc49904b496089');
  });

  test('CBC chains blocks (NIST SP 800-38A F.2.5, first two blocks)', () {
    final key = h('603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4');
    final out = Aes(key).cbc(
      h('000102030405060708090a0b0c0d0e0f'),
      h('6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51'),
    );
    expect(x(out), 'f58c4c04d6e5f1ba779eabfb5f7bfbd69cfc4e967edb808d679f777bc6702c7d');
  });

  test('revision 6 password hash matches pypdf', () {
    final pw = utf8.encode('ward-7 रकम');
    final salt = List.generate(8, (i) => i);
    expect(x(pdfHashR6(pw, salt, const [])),
        'b7aca44d99db246a2c8657de08c2b17f79eab1d01cd4fe8b9af0e341028f2ab8');
    expect(x(pdfHashR6(pw, salt, List.generate(48, (i) => i))),
        '2d47f7f49d12080dec78c0b26c9c01920a6584b4343a1dfc56a63d3ea8a5b498');
    expect(x(pdfHashR6(const [], salt, const [])),
        '1403c04eb647d2e60452dfc4eb0a5e0cf322e8a83a759eabbd17d498a93ba041');
  });

  test('strings and streams: random IV, PKCS#7 padding', () {
    final enc = PdfEncryption('ward-7 रकम');
    expect(enc.encrypt(List.filled(16, 1)).length, 48);
    expect(enc.encrypt(const []).length, 32);
    expect(enc.dictionary, allOf(contains('/V 5 /R 6'), contains('/AESV3')));
    expect(x(enc.encrypt([1, 2])) == x(enc.encrypt([1, 2])), isFalse);
  });

  // The writer's protected output, written reproducibly (fixed seed and
  // date) to test/fixtures/protected.pdf; tests/test_pdf_password.py opens
  // that very file with PDFium and pypdf. UPDATE_FIXTURES=1 rewrites it.
  test('protected export matches the fixture the desktop checks', () async {
    final font = TrueTypeFont.parse(File('assets/Mukta-Regular.ttf').readAsBytesSync());
    final page = img.Image(width: 400, height: 300);
    img.fill(page, color: img.ColorRgb8(250, 248, 240));
    final out = File('build/test-output/protected.pdf')..parent.createSync(recursive: true);
    final writer = await StreamingPdfWriter.open(
      out.path,
      title: 'नेपाल receipts',
      font: font,
      password: 'ward-7 रकम',
      random: Random(7),
      now: DateTime.utc(2026, 11, 16, 10),
    );
    expect(writer.encrypted, isTrue);
    for (var i = 0; i < 2; i++) {
      await writer.addPage(
        Uint8List.fromList(img.encodeJpg(page, quality: 80)),
        lines: const [
          PdfTextLine('Total 12,500.75', 20, 20, 200, 24),
          PdfTextLine('नेपाल १२३', 20, 60, 140, 24),
        ],
      );
    }
    await writer.close();
    final bytes = out.readAsBytesSync();
    final raw = latin1.decode(bytes);
    expect(raw, contains('/Encrypt '));
    expect(raw, isNot(contains('12,500.75')));
    expect(raw, isNot(contains('VeriScript Offline')));
    final fixture = File('test/fixtures/protected.pdf');
    if (Platform.environment['UPDATE_FIXTURES'] == '1' || !fixture.existsSync()) {
      fixture.writeAsBytesSync(bytes);
    }
    expect(bytes, fixture.readAsBytesSync());
  });
}
