/// PDF encryption for password-protected exports (docs/TECH_UPGRADE_PLAN.md
/// E5): AES-256 with the PDF 2.0 key derivation (security handler revision
/// 6, ISO 32000-2 §7.6.4.3.4, algorithms 2.B, 8, 9 and 10).
///
/// Only encryption is needed (the writer never reads PDFs back), so AES is
/// implemented encrypt-only here; SHA-2 comes from package:crypto. Checked
/// against the FIPS-197 vectors (test/pdf_crypt_test.dart) and by opening
/// the writer's output with PDFium and pypdf (tests/test_pdf_password.py).
library;

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

// ---------------------------------------------------------------------------
// AES (FIPS-197), encryption only.
// ---------------------------------------------------------------------------

final Uint8List _sbox = () {
  final s = Uint8List(256);
  var p = 1, q = 1;
  int rotl(int x, int n) => ((x << n) | (x >> (8 - n))) & 0xff;
  do {
    p = (p ^ ((p << 1) & 0xff) ^ ((p & 0x80) != 0 ? 0x1b : 0)) & 0xff;
    q ^= (q << 1) & 0xff;
    q ^= (q << 2) & 0xff;
    q ^= (q << 4) & 0xff;
    if ((q & 0x80) != 0) q ^= 0x09;
    q &= 0xff;
    s[p] = q ^ rotl(q, 1) ^ rotl(q, 2) ^ rotl(q, 3) ^ rotl(q, 4) ^ 0x63;
  } while (p != 1);
  s[0] = 0x63;
  return s;
}();

int _xtime(int b) => ((b << 1) ^ ((b & 0x80) != 0 ? 0x1b : 0)) & 0xff;

/// T-tables: one round of SubBytes, ShiftRows and MixColumns per column.
final List<Uint32List> _t = () {
  final t0 = Uint32List(256);
  for (var i = 0; i < 256; i++) {
    final s = _sbox[i], s2 = _xtime(s), s3 = s2 ^ s;
    t0[i] = (s2 << 24) | (s << 16) | (s << 8) | s3;
  }
  int ror(int x, int n) => ((x >> n) | (x << (32 - n))) & 0xffffffff;
  return [
    t0,
    Uint32List.fromList([for (final v in t0) ror(v, 8)]),
    Uint32List.fromList([for (final v in t0) ror(v, 16)]),
    Uint32List.fromList([for (final v in t0) ror(v, 24)]),
  ];
}();

class Aes {
  /// [key] is 16 (AES-128) or 32 (AES-256) bytes.
  Aes(List<int> key) : _w = _expand(key), _rounds = key.length ~/ 4 + 6;

  final Uint32List _w;
  final int _rounds;

  static Uint32List _expand(List<int> key) {
    if (key.length != 16 && key.length != 32) {
      throw ArgumentError('AES key must be 16 or 32 bytes');
    }
    final nk = key.length ~/ 4, rounds = nk + 6;
    final w = Uint32List(4 * (rounds + 1));
    for (var i = 0; i < nk; i++) {
      w[i] = (key[4 * i] << 24) | (key[4 * i + 1] << 16) | (key[4 * i + 2] << 8) | key[4 * i + 3];
    }
    int sub(int x) =>
        (_sbox[x >> 24] << 24) | (_sbox[(x >> 16) & 0xff] << 16) |
        (_sbox[(x >> 8) & 0xff] << 8) | _sbox[x & 0xff];
    var rcon = 1;
    for (var i = nk; i < w.length; i++) {
      var t = w[i - 1];
      if (i % nk == 0) {
        t = sub(((t << 8) | (t >> 24)) & 0xffffffff) ^ (rcon << 24);
        rcon = _xtime(rcon);
      } else if (nk > 6 && i % nk == 4) {
        t = sub(t);
      }
      w[i] = w[i - nk] ^ t;
    }
    return w;
  }

  /// Encrypts the 16 bytes at [inOff] of [input] into [out] at [outOff].
  void encryptBlock(Uint8List input, int inOff, Uint8List out, int outOff) {
    final w = _w, t0 = _t[0], t1 = _t[1], t2 = _t[2], t3 = _t[3];
    int word(int o) =>
        (input[o] << 24) | (input[o + 1] << 16) | (input[o + 2] << 8) | input[o + 3];
    var s0 = word(inOff) ^ w[0], s1 = word(inOff + 4) ^ w[1];
    var s2 = word(inOff + 8) ^ w[2], s3 = word(inOff + 12) ^ w[3];
    var k = 4;
    for (var r = 1; r < _rounds; r++) {
      final a0 = t0[s0 >> 24] ^ t1[(s1 >> 16) & 0xff] ^ t2[(s2 >> 8) & 0xff] ^ t3[s3 & 0xff] ^ w[k];
      final a1 = t0[s1 >> 24] ^ t1[(s2 >> 16) & 0xff] ^ t2[(s3 >> 8) & 0xff] ^ t3[s0 & 0xff] ^ w[k + 1];
      final a2 = t0[s2 >> 24] ^ t1[(s3 >> 16) & 0xff] ^ t2[(s0 >> 8) & 0xff] ^ t3[s1 & 0xff] ^ w[k + 2];
      final a3 = t0[s3 >> 24] ^ t1[(s0 >> 16) & 0xff] ^ t2[(s1 >> 8) & 0xff] ^ t3[s2 & 0xff] ^ w[k + 3];
      s0 = a0;
      s1 = a1;
      s2 = a2;
      s3 = a3;
      k += 4;
    }
    final s = _sbox;
    void put(int o, int a, int b, int c, int d, int key) {
      out[o] = s[a >> 24] ^ (key >> 24);
      out[o + 1] = s[(b >> 16) & 0xff] ^ ((key >> 16) & 0xff);
      out[o + 2] = s[(c >> 8) & 0xff] ^ ((key >> 8) & 0xff);
      out[o + 3] = s[d & 0xff] ^ (key & 0xff);
    }

    put(outOff, s0, s1, s2, s3, w[k]);
    put(outOff + 4, s1, s2, s3, s0, w[k + 1]);
    put(outOff + 8, s2, s3, s0, s1, w[k + 2]);
    put(outOff + 12, s3, s0, s1, s2, w[k + 3]);
  }

  /// CBC over whole blocks ([data] length a multiple of 16), no padding.
  Uint8List cbc(Uint8List iv, Uint8List data) {
    if (data.length % 16 != 0) throw ArgumentError('CBC data must be whole blocks');
    final out = Uint8List(data.length);
    final block = Uint8List.fromList(iv);
    for (var o = 0; o < data.length; o += 16) {
      for (var i = 0; i < 16; i++) {
        block[i] ^= data[o + i];
      }
      encryptBlock(block, 0, out, o);
      block.setRange(0, 16, out, o);
    }
    return out;
  }
}

// ---------------------------------------------------------------------------
// The PDF standard security handler, revision 6.
// ---------------------------------------------------------------------------

/// Algorithm 2.B: the revision 6 password hash.
Uint8List pdfHashR6(List<int> password, List<int> salt, List<int> userKey) {
  var k = Uint8List.fromList(sha256.convert([...password, ...salt, ...userKey]).bytes);
  for (var round = 1;; round++) {
    final unit = [...password, ...k, ...userKey];
    final k1 = Uint8List(unit.length * 64);
    for (var i = 0; i < 64; i++) {
      k1.setRange(i * unit.length, (i + 1) * unit.length, unit);
    }
    final e = Aes(k.sublist(0, 16)).cbc(k.sublist(16, 32), k1);
    var mod3 = 0;
    for (var i = 0; i < 16; i++) {
      mod3 += e[i];
    }
    final hash = [sha256, sha384, sha512][mod3 % 3];
    k = Uint8List.fromList(hash.convert(e).bytes);
    if (round >= 64 && e[e.length - 1] <= round - 32) break;
  }
  return k.sublist(0, 32);
}

/// The password as the handler wants it: UTF-8, at most 127 bytes.
/// (SASLprep is not applied: passwords typed on the phone are used as typed.)
List<int> pdfPasswordBytes(String password) {
  final bytes = utf8.encode(password);
  return bytes.length > 127 ? bytes.sublist(0, 127) : bytes;
}

/// Encrypts strings and streams of one PDF (V5 / R6, AESV3: every object
/// uses the file key directly) and writes the /Encrypt dictionary.
class PdfEncryption {
  PdfEncryption._(this.key, this._random, this.dictionary, this.fileId);

  /// Builds the handler for [userPassword]; the owner password is random,
  /// so permissions cannot be changed without re-creating the file.
  /// [random] is injectable for reproducible test files only.
  factory PdfEncryption(String userPassword, {Random? random}) {
    final rnd = random ?? Random.secure();
    Uint8List bytes(int n) => Uint8List.fromList(List.generate(n, (_) => rnd.nextInt(256)));
    final key = bytes(32);
    final user = pdfPasswordBytes(userPassword);
    final owner = bytes(32);
    final aesZeroIv = Uint8List(16);

    final uvs = bytes(8), uks = bytes(8);
    final u = Uint8List.fromList([...pdfHashR6(user, uvs, const []), ...uvs, ...uks]);
    final ue = Aes(pdfHashR6(user, uks, const [])).cbc(aesZeroIv, key);
    final ovs = bytes(8), oks = bytes(8);
    final o = Uint8List.fromList([...pdfHashR6(owner, ovs, u), ...ovs, ...oks]);
    final oe = Aes(pdfHashR6(owner, oks, u)).cbc(aesZeroIv, key);

    const p = -4; // every permission once opened (print, copy, ...)
    final perms = Uint8List(16);
    ByteData.sublistView(perms).setUint32(0, p & 0xffffffff, Endian.little);
    perms.fillRange(4, 8, 0xff);
    perms.setAll(8, 'Tadb'.codeUnits);
    perms.setAll(12, bytes(4));
    final permsOut = Uint8List(16);
    Aes(key).encryptBlock(perms, 0, permsOut, 0);

    String hex(List<int> v) => v.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    final dictionary =
        '<< /Filter /Standard /V 5 /R 6 /Length 256 '
        '/CF << /StdCF << /Type /CryptFilter /CFM /AESV3 /AuthEvent /DocOpen /Length 32 >> >> '
        '/StmF /StdCF /StrF /StdCF /P $p /EncryptMetadata true '
        '/O <${hex(o)}> /U <${hex(u)}> /OE <${hex(oe)}> /UE <${hex(ue)}> '
        '/Perms <${hex(permsOut)}> >>';
    return PdfEncryption._(key, rnd, dictionary, hex(bytes(16)));
  }

  final Uint8List key;
  final Random _random;

  /// The /Encrypt dictionary (written unencrypted, as the format requires).
  final String dictionary;

  /// A random file identifier (hex) for the trailer's /ID.
  final String fileId;

  late final Aes _aes = Aes(key);

  /// AES-256-CBC with a random IV in front and PKCS#7 padding (§7.6.3).
  Uint8List encrypt(List<int> data) {
    final pad = 16 - data.length % 16;
    final padded = Uint8List(data.length + pad)
      ..setAll(0, data)
      ..fillRange(data.length, data.length + pad, pad);
    final iv = Uint8List.fromList(List.generate(16, (_) => _random.nextInt(256)));
    return Uint8List(16 + padded.length)
      ..setAll(0, iv)
      ..setAll(16, _aes.cbc(iv, padded));
  }

  /// An encrypted string object, as a hex string.
  String string(List<int> bytes) =>
      '<${encrypt(bytes).map((b) => b.toRadixString(16).padLeft(2, '0')).join()}>';
}
