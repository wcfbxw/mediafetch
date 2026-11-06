"""Douyin Web request signing.

``a_bogus`` and ``x-secsdk-web-signature`` are reproduced here so the API can
be called without a browser. The primitives are vendored from
Evil0ctal/Douyin_TikTok_Download_API (dtk 5.1.10), Apache-2.0. See
DOUYIN_SIGNING_LICENSE.txt in this directory.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, unquote, urlencode

from app.services.douyin_sm3 import sm3_to_array

ALPHABETS: Final[Mapping[str, str]] = {
    "s3": "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe",
    "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",
}

SALT: Final = "dhzx"
HEADER_MAGIC: Final[tuple[int, int]] = (3, 82)
SDK_VERSION: Final[tuple[int, int, int, int]] = (1, 0, 1, 0)
PAYLOAD_KEY: Final = 0xD3
FORTNIGHT_EPOCH_MS: Final = 1_721_836_800_000
PAGE_ID: Final = 6241
AID: Final = 6383
NOISE_MASKS: Final[tuple[int, int, int]] = (0x91, 0x42, 0x2C)
DATA_MASKS: Final[tuple[int, int, int]] = (0x6E, 0xBD, 0xD3)
FIELD_ORDER: Final[tuple[str, ...]] = (
    "L34",
    "L44",
    "L56",
    "L61",
    "L73",
    "L29",
    "L70",
    "L45",
    "L35",
    "L49",
    "L38",
    "L66",
    "L51",
    "L68",
    "L28",
    "L48",
    "L64",
    "L47",
    "L30",
    "L71",
    "L26",
    "L55",
    "L31",
    "L69",
    "L59",
    "L40",
    "L62",
    "L63",
    "L27",
    "L72",
    "L41",
    "L74",
    "L57",
    "L52",
    "L42",
    "L39",
    "L33",
    "L67",
    "L53",
    "L43",
    "L65",
    "L46",
    "L36",
    "L24",
    "L60",
    "L32",
    "L79",
    "L80",
    "L84",
    "L85",
)
CANARIES: Final[tuple[tuple[int, int, int], ...]] = ((3, 11, 12), (4, 8, 9), (5, 12, 13))


@dataclass(frozen=True, slots=True)
class DigestChain:
    slots: tuple[str, str, str]
    indices: tuple[int, int]
    canary: tuple[int, int, int]


DIGEST_CHAINS: Final[Mapping[str, DigestChain]] = {
    "query": DigestChain(("L48", "L49", "L51"), (9, 18), CANARIES[0]),
    "body": DigestChain(("L52", "L53", "L55"), (10, 19), CANARIES[1]),
    "user_agent": DigestChain(("L56", "L57", "L59"), (11, 21), CANARIES[2]),
}

ENV_FLAGS: Final = 1
DETECT_FLAGS: Final = 14
NR_FLAGS: Final = 0x21
NR_TAG: Final[tuple[int, int, int, int]] = (0, 0, 0, 0)
TRIPWIRE_LOCKED: Final = 3
CALL_BUCKET: Final = 6
DEFAULT_BROWSER_INFO: Final = "1920|947|1920|1032|1920|1032|1920|1080|Win32"
_TASKBAR_PX: Final = 48
_CHROME_PX: Final = 85

_HEADER_NOISE_BANDS: Final[Mapping[str, int]] = {
    "chrome": 0,
    "firefox": 40,
    "safari": 81,
    "edge": 125,
    "huawei": 170,
    "other": 210,
}
_TRIPWIRE_SET: Final = 0xB2
_TRIPWIRE_FREE: Final = 0x4D


def build_browser_info(
    *,
    inner_width: int,
    inner_height: int,
    outer_width: int,
    outer_height: int,
    avail_width: int,
    avail_height: int,
    screen_width: int,
    screen_height: int,
    platform: str,
) -> str:
    return "|".join(
        str(value)
        for value in (
            inner_width,
            inner_height,
            outer_width,
            outer_height,
            avail_width,
            avail_height,
            screen_width,
            screen_height,
            platform,
        )
    )


def browser_info_from_screen(width: int, height: int, platform: str) -> str:
    avail_height = max(height - _TASKBAR_PX, 1)
    return build_browser_info(
        inner_width=width,
        inner_height=max(avail_height - _CHROME_PX, 1),
        outer_width=width,
        outer_height=avail_height,
        avail_width=width,
        avail_height=avail_height,
        screen_width=width,
        screen_height=height,
        platform=platform,
    )


def rc4(key: bytes, data: bytes) -> bytes:
    box = [0] * 256
    for index in range(256):
        box[255 - index] = index
    j = 0
    for index in range(256):
        j = (j * box[index] + j + key[index % len(key)]) % 256
        box[index], box[j] = box[j], box[index]

    out = bytearray(len(data))
    i = j = 0
    for index, byte in enumerate(data):
        i = (i + 1) % 256
        j = (j + box[i]) % 256
        box[i], box[j] = box[j], box[i]
        out[index] = byte ^ box[(box[i] + box[j]) % 256]
    return bytes(out)


def encode_base64(data: bytes, alphabet: str = "s4") -> str:
    table = ALPHABETS[alphabet]
    out: list[str] = []
    for offset in range(0, len(data), 3):
        chunk = data[offset : offset + 3]
        block = int.from_bytes(chunk + b"\x00" * (3 - len(chunk)), "big")
        digits = [(block >> shift) & 0x3F for shift in (18, 12, 6, 0)]
        out.extend(table[digit] for digit in digits[: len(chunk) + 1])
    out.append("=" * ((4 - len(out) % 4) % 4))
    return "".join(out)


def _family_of(user_agent: str) -> str:
    ua = user_agent.lower()
    for name in ("edg", "huawei", "firefox", "chrome", "safari"):
        if name in ua:
            return {"edg": "edge"}.get(name, name)
    return "other"


def _header_noise(user_agent: str, rng: random.Random) -> int:
    base = _HEADER_NOISE_BANDS.get(_family_of(user_agent), _HEADER_NOISE_BANDS["other"])
    return (base + int(rng.random() * 40)) & 0xFF


def _probe_noise(rng: random.Random) -> int:
    value = int(rng.random() * 240)
    return value + value % 2 + 1 if value > 109 else value


def _tripwire_noise(rng: random.Random) -> int:
    return (int(rng.random() * 255) & _TRIPWIRE_FREE) | _TRIPWIRE_SET


def _mask_pair(
    pair: tuple[int, int],
    rng: random.Random,
    *,
    low: int | None = None,
    high: int | None = None,
) -> list[int]:
    noise = int(rng.random() * 65535)
    low = noise & 0xFF if low is None else low & 0xFF
    high = (noise >> 8) & 0xFF if high is None else high & 0xFF
    return [
        (low & 0xAA) | (pair[0] & 0x55),
        (low & 0x55) | (pair[0] & 0xAA),
        (high & 0xAA) | (pair[1] & 0x55),
        (high & 0x55) | (pair[1] & 0xAA),
    ]


def _expand_noise(body: bytes, rng: random.Random) -> bytes:
    out = bytearray()
    for offset in range(0, len(body), 3):
        group = body[offset : offset + 3]
        if len(group) < 3:
            out.append(group[0])
            if len(group) > 1 and group[1]:
                out.append(group[1])
            continue
        noise = int(rng.random() * 1000) & 0xFF
        out.extend(
            (noise & mask) | (byte & data)
            for mask, data, byte in zip(NOISE_MASKS, DATA_MASKS, group, strict=True)
        )
        out.append(
            (group[0] & NOISE_MASKS[0])
            | (group[1] & NOISE_MASKS[1])
            | (group[2] & NOISE_MASKS[2])
        )
    return bytes(out)


def js_bytes(text: str) -> bytes:
    out = bytearray()
    units = text.encode("utf-16-le")
    for index in range(0, len(units), 2):
        code = units[index] | (units[index + 1] << 8)
        if code & 0xFF00:
            out.append(code >> 8)
        out.append(code & 0xFF)
    return bytes(out)


def _le_bytes(value: int, count: int) -> list[int]:
    return [(value >> (8 * index)) & 0xFF for index in range(count)]


def canary(digest: Sequence[int], offset: int, sentinel: int, fallback: int) -> int:
    for byte in digest[offset:]:
        if byte != sentinel:
            return byte
    return fallback


def digest_of(text: str) -> list[int]:
    return sm3_to_array(sm3_to_array(text + SALT))


def user_agent_digest(user_agent: str) -> list[int]:
    key = bytes((ENV_FLAGS // 256, ENV_FLAGS % 256, DETECT_FLAGS % 256))
    sealed = rc4(key, bytes(byte & 0xFF for byte in js_bytes(user_agent.strip())))
    return sm3_to_array(encode_base64(sealed, "s3"))


def chain_bytes(chain: DigestChain, digest: Sequence[int]) -> tuple[int, int, int]:
    first, second = chain.indices
    return digest[first], digest[second], canary(digest, *chain.canary)


class ABogus:
    def __init__(
        self,
        user_agent: str,
        *,
        browser_info: str = DEFAULT_BROWSER_INFO,
        page_id: int = PAGE_ID,
        aid: int = AID,
        rng: random.Random | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.browser_info = browser_info
        self.page_id = page_id
        self.aid = aid
        self._rng = rng or random.Random()

    def _fields(self, query: str, body: str, now_ms: int) -> dict[str, int]:
        digests = {
            "query": digest_of(query),
            "body": digest_of(body),
            "user_agent": user_agent_digest(self.user_agent),
        }
        ink = now_ms - 1
        fortnights = (now_ms - FORTNIGHT_EPOCH_MS) // (1000 * 60 * 60 * 24 * 14)
        info_bytes = js_bytes(self.browser_info)
        tail_bytes = js_bytes(f"{(now_ms + 3) & 0xFF},")

        fields: dict[str, int] = {
            "L24": 41,
            "L26": fortnights,
            "L27": CALL_BUCKET,
            "L28": 3,
            "L35": ENV_FLAGS & 0xFF,
            "L36": (ENV_FLAGS // 256) & 0xFF,
            "L38": NR_FLAGS & 0xFF,
            "L39": (NR_FLAGS >> 8) & 0xFF,
            "L66": TRIPWIRE_LOCKED,
            "L79": len(info_bytes) & 0xFF,
            "L80": (len(info_bytes) >> 8) & 0xFF,
            "L84": len(tail_bytes) & 0xFF,
            "L85": (len(tail_bytes) >> 8) & 0xFF,
        }
        for index, byte in enumerate(_le_bytes(now_ms, 6)):
            fields[f"L{29 + index}"] = byte
        for index, byte in enumerate(_le_bytes(DETECT_FLAGS, 4)):
            fields[f"L{44 + index}"] = byte
        for index, byte in enumerate(NR_TAG):
            fields[f"L{40 + index}"] = byte
        for index, byte in enumerate(_le_bytes(ink, 6)):
            fields[f"L{60 + index}"] = byte
        for index, byte in enumerate(_le_bytes(self.page_id, 4)):
            fields[f"L{67 + index}"] = byte
        for index, byte in enumerate(_le_bytes(self.aid, 4)):
            fields[f"L{71 + index}"] = byte
        for name, chain in DIGEST_CHAINS.items():
            for slot, value in zip(chain.slots, chain_bytes(chain, digests[name]), strict=True):
                fields[slot] = value
        return fields

    def get_value(
        self,
        query: str,
        *,
        body: str = "",
        content_type: str = "",
        now_ms: int | None = None,
    ) -> str:
        if "multipart/form-data" in content_type.lower():
            body = ""
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        if now < FORTNIGHT_EPOCH_MS:
            raise ValueError(f"clock is before the a_bogus epoch: {now}")
        fields = self._fields(query, body, now)

        version = _mask_pair(SDK_VERSION[:2], self._rng) + _mask_pair(
            SDK_VERSION[2:],
            self._rng,
            low=_probe_noise(self._rng),
            high=_tripwire_noise(self._rng),
        )

        checksum = 0
        for byte in version:
            checksum ^= byte
        for name in FIELD_ORDER:
            checksum ^= fields[name]

        body_bytes = bytes(fields[name] for name in FIELD_ORDER)
        body_bytes += js_bytes(self.browser_info)
        body_bytes += js_bytes(f"{(now + 3) & 0xFF},")
        body_bytes += bytes((checksum,))

        header = bytes(
            _mask_pair(HEADER_MAGIC, self._rng, high=_header_noise(self.user_agent, self._rng))
        )
        frame = _expand_noise(body_bytes, self._rng)
        sealed = rc4(bytes((PAYLOAD_KEY,)), bytes(version) + frame)
        return encode_base64(header + sealed, "s4")


# Douyin's x-secsdk-web-signature.
WEBSIGN_SALT: Final = "A96D855A08C0A9707F8BEF0D9A527E4E"
UIFID_COOKIE_NAMES: Final[tuple[str, ...]] = (
    "uifid",
    "uifid_temp",
    "uifidtemp",
    "UIFID",
    "UIFID_TEMP",
    "UIFIDTEMP",
)
VERIFY_FP_COOKIE: Final = "s_v_web_id"
SIGNATURE_PARAM: Final = "x-secsdk-web-signature"
UIFID_PARAM: Final = "uifid"
TIMESTAMP_PARAM: Final = "timestamp"
VERIFY_FP_PARAMS: Final[tuple[str, ...]] = ("verifyFp", "fp")
EXPIRE_HEADER: Final = "x-secsdk-web-expire"


def pick_uifid(cookies: Mapping[str, str] | None) -> str | None:
    for name in UIFID_COOKIE_NAMES:
        value = (cookies or {}).get(name)
        if value:
            return value
    return None


def encode_pairs(pairs: Sequence[tuple[str, str]]) -> str:
    return "&".join(f"{quote(key, safe='*-._')}={quote(value, safe='*-._')}" for key, value in pairs)


def sign_web(
    pairs: Sequence[tuple[str, str]],
    uifid: str,
    *,
    timestamp: int | None = None,
) -> tuple[str, str, dict[str, str]]:
    stamp = str(int(time.time() if timestamp is None else timestamp))
    covered = list(pairs)
    if not any(name == UIFID_PARAM for name, _ in covered):
        covered.append((UIFID_PARAM, uifid))
    covered.append((TIMESTAMP_PARAM, stamp))
    query = encode_pairs(covered)
    signature = hashlib.md5(
        f"{uifid}_{stamp}_{WEBSIGN_SALT}_{query}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    headers = {
        UIFID_PARAM: uifid,
        SIGNATURE_PARAM: signature,
        EXPIRE_HEADER: stamp,
    }
    return f"{query}&{SIGNATURE_PARAM}={signature}", signature, headers


def _split_pair(part: str) -> tuple[str, str]:
    name, _, value = part.partition("=")
    return unquote(name), unquote(value)


def sign_detail_query(
    *,
    video_id: str,
    user_agent: str,
    cookies: Mapping[str, str],
    screen_width: int = 1920,
    screen_height: int = 1080,
) -> tuple[str, dict[str, str]]:
    """Return the signed query and the secsdk headers for a Douyin detail request."""

    uifid = pick_uifid(cookies)
    if not uifid:
        raise ValueError("missing UIFID_TEMP")

    params = {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "pc_client_type": "1",
        "version_code": "170400",
        "version_name": "17.4.0",
        "cookie_enabled": "true",
        "screen_width": str(screen_width),
        "screen_height": str(screen_height),
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "143.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "143.0.0.0",
        "os_name": "Windows",
        "os_version": "10",
        "cpu_core_num": "8",
        "device_memory": "8",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "50",
        "aweme_id": video_id,
    }
    query = urlencode(params)
    bogus = ABogus(
        user_agent,
        browser_info=browser_info_from_screen(screen_width, screen_height, "Win32"),
    ).get_value(query)
    pairs = [
        _split_pair(part)
        for part in f"{query}&a_bogus={quote(bogus, safe='')}".split("&")
        if part
    ]

    verify_fp = cookies.get(VERIFY_FP_COOKIE)
    if verify_fp:
        for name in VERIFY_FP_PARAMS:
            pairs.append((name, verify_fp))

    signed_query, _signature, headers = sign_web(pairs, uifid)
    return signed_query, headers


__all__ = [
    "ABogus",
    "DEFAULT_BROWSER_INFO",
    "UIFID_COOKIE_NAMES",
    "browser_info_from_screen",
    "pick_uifid",
    "sign_detail_query",
    "sign_web",
]
