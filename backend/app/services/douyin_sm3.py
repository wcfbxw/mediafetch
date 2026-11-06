"""Pure-Python SM3 used by Douyin's a_bogus signature.

Vendored from Evil0ctal/Douyin_TikTok_Download_API (dtk 5.1.10),
Apache-2.0. See DOUYIN_SIGNING_LICENSE.txt in this directory.
"""

from __future__ import annotations

_MASK = 0xFFFFFFFF

IV: tuple[int, ...] = (
    0x7380166F,
    0x4914B2B9,
    0x172442D7,
    0xDA8A0600,
    0xA96F30BC,
    0x163138AA,
    0xE38DEE4D,
    0xB0FB0E4E,
)

_T0 = 0x79CC4519
_T1 = 0x7A879D8A


def _rotl(value: int, bits: int) -> int:
    bits %= 32
    return ((value << bits) & _MASK) | (value >> (32 - bits))


def _ff(index: int, x: int, y: int, z: int) -> int:
    if index < 16:
        return x ^ y ^ z
    return (x & y) | (x & z) | (y & z)


def _gg(index: int, x: int, y: int, z: int) -> int:
    if index < 16:
        return x ^ y ^ z
    return (x & y) | ((~x & _MASK) & z)


def _expand(block: bytes) -> tuple[list[int], list[int]]:
    w = [int.from_bytes(block[index * 4 : index * 4 + 4], "big") for index in range(16)]
    for index in range(16, 68):
        value = w[index - 16] ^ w[index - 9] ^ _rotl(w[index - 3], 15)
        value = value ^ _rotl(value, 15) ^ _rotl(value, 23)
        w.append((value ^ _rotl(w[index - 13], 7) ^ w[index - 6]) & _MASK)
    return w, [(w[index] ^ w[index + 4]) & _MASK for index in range(64)]


def _compress(state: tuple[int, ...], block: bytes) -> tuple[int, ...]:
    w, w1 = _expand(block)
    a, b, c, d, e, f, g, h = state
    for index in range(64):
        t = _T0 if index < 16 else _T1
        ss1 = _rotl((_rotl(a, 12) + e + _rotl(t, index)) & _MASK, 7)
        ss2 = ss1 ^ _rotl(a, 12)
        tt1 = (_ff(index, a, b, c) + d + ss2 + w1[index]) & _MASK
        tt2 = (_gg(index, e, f, g) + h + ss1 + w[index]) & _MASK
        d = c
        c = _rotl(b, 9)
        b = a
        a = tt1
        h = g
        g = _rotl(f, 19)
        f = e
        e = (tt2 ^ _rotl(tt2, 9) ^ _rotl(tt2, 17)) & _MASK
    return tuple(
        (left ^ right) & _MASK
        for left, right in zip(state, (a, b, c, d, e, f, g, h), strict=True)
    )


def _pad(message: bytes) -> bytes:
    bit_length = len(message) * 8
    padded = message + b"\x80"
    padded += b"\x00" * ((56 - len(padded) % 64) % 64)
    return padded + bit_length.to_bytes(8, "big")


def sm3_hash(message: bytes) -> bytes:
    state = IV
    padded = _pad(message)
    for offset in range(0, len(padded), 64):
        state = _compress(state, padded[offset : offset + 64])
    return b"".join(word.to_bytes(4, "big") for word in state)


def sm3_to_array(data: str | bytes | list[int]) -> list[int]:
    if isinstance(data, str):
        raw = data.encode("utf-8")
    elif isinstance(data, bytes):
        raw = data
    else:
        raw = bytes(data)
    return list(sm3_hash(raw))


__all__ = ["IV", "sm3_hash", "sm3_to_array"]
