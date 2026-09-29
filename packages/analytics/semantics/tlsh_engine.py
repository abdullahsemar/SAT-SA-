"""Trend Micro Locality Sensitive Hash (TLSH) reference implementation in Python.

Specification:
- Oliver, Cheng, and Chen, "TLSH -- A Locality Sensitive Hash", 2013.
- Upstream C++ Reference: https://github.com/trendmicro/tlsh (Apache 2.0 License).
- Compliant with official TLSH digest format (T1 prefix, 128 buckets, quartile ratios).
- Gracefully rejects short (<50 bytes) or low-complexity inputs without artificial padding.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple, Union

# Official Trend Micro TLSH Pearson Permutation Table (256 bytes)
V_TABLE = [
    1,
    87,
    49,
    12,
    176,
    178,
    102,
    166,
    121,
    193,
    6,
    84,
    249,
    230,
    44,
    163,
    14,
    197,
    213,
    181,
    161,
    85,
    218,
    80,
    64,
    239,
    24,
    226,
    236,
    142,
    38,
    200,
    110,
    177,
    104,
    103,
    141,
    253,
    255,
    50,
    77,
    101,
    81,
    18,
    45,
    96,
    31,
    222,
    25,
    107,
    190,
    70,
    86,
    237,
    240,
    34,
    72,
    242,
    20,
    214,
    244,
    227,
    149,
    235,
    97,
    234,
    57,
    22,
    60,
    250,
    82,
    175,
    208,
    5,
    127,
    199,
    111,
    62,
    135,
    248,
    174,
    169,
    211,
    58,
    66,
    154,
    106,
    195,
    245,
    171,
    17,
    187,
    182,
    179,
    0,
    243,
    132,
    56,
    148,
    75,
    128,
    133,
    158,
    100,
    130,
    126,
    91,
    13,
    153,
    246,
    216,
    219,
    119,
    68,
    223,
    78,
    83,
    88,
    201,
    99,
    122,
    11,
    92,
    32,
    136,
    114,
    52,
    10,
    138,
    30,
    48,
    183,
    156,
    35,
    61,
    26,
    143,
    74,
    251,
    94,
    129,
    162,
    63,
    152,
    170,
    7,
    115,
    167,
    241,
    206,
    3,
    150,
    55,
    59,
    151,
    220,
    90,
    53,
    23,
    131,
    125,
    173,
    15,
    238,
    79,
    95,
    89,
    16,
    105,
    137,
    225,
    224,
    217,
    160,
    37,
    123,
    118,
    73,
    2,
    157,
    46,
    116,
    9,
    145,
    134,
    228,
    207,
    212,
    202,
    215,
    69,
    229,
    27,
    188,
    67,
    124,
    168,
    252,
    42,
    4,
    29,
    108,
    21,
    247,
    19,
    205,
    39,
    203,
    233,
    40,
    186,
    147,
    198,
    192,
    155,
    33,
    164,
    191,
    98,
    204,
    165,
    180,
    117,
    76,
    140,
    36,
    210,
    172,
    41,
    54,
    159,
    8,
    185,
    232,
    113,
    196,
    231,
    47,
    146,
    120,
    51,
    65,
    28,
    144,
    254,
    221,
    93,
    189,
    194,
    139,
    112,
    43,
    71,
    109,
    184,
    209,
]


def b_mapping(salt: int, c1: int, c2: int, c3: int) -> int:
    h = 0
    h = V_TABLE[h ^ salt]
    h = V_TABLE[h ^ c1]
    h = V_TABLE[h ^ c2]
    h = V_TABLE[h ^ c3]
    return h


def l_fast(len_val: int) -> int:
    if len_val <= 656:
        return int(math.floor(math.log(len_val) / 0.05)) % 256
    elif len_val <= 3199:
        return int(math.floor(math.log(len_val) / 0.04)) % 256
    else:
        return int(math.floor(math.log(len_val) / 0.03)) % 256


def compute_tlsh_digest(data: bytes) -> Tuple[Optional[str], Optional[str]]:
    """Computes standard TLSH digest from raw bytes.

    Returns:
        (digest_hex, None) on success
        (None, reason_string) if input is too short or lacks entropy.
    """
    length = len(data)
    if length < 50:
        return None, f"insufficient_input_length (length={length} < 50 minimum bytes)"

    # Check entropy / complexity: reject inputs that are purely identical bytes
    unique_byte_count = len(set(data))
    if unique_byte_count < 10:
        return None, f"insufficient_entropy (unique_bytes={unique_byte_count} < 10)"

    buckets = [0] * 128
    checksum = 0

    # 5-byte sliding window
    for i in range(length - 4):
        c0, c1, c2, c3, c4 = data[i], data[i + 1], data[i + 2], data[i + 3], data[i + 4]
        checksum = b_mapping(1, c0, c1, checksum)
        buckets[b_mapping(2, c0, c1, c2) % 128] += 1
        buckets[b_mapping(3, c0, c1, c3) % 128] += 1
        buckets[b_mapping(5, c0, c2, c3) % 128] += 1
        buckets[b_mapping(7, c0, c2, c4) % 128] += 1
        buckets[b_mapping(11, c0, c1, c4) % 128] += 1
        buckets[b_mapping(13, c0, c3, c4) % 128] += 1

    # Check for sufficient variance in bucket counts
    non_zero = sum(1 for b in buckets if b > 0)
    if non_zero < 32:
        return None, f"insufficient_complexity (non_zero_buckets={non_zero} < 32)"

    sorted_b = sorted(buckets)
    q1 = sorted_b[32]
    q2 = sorted_b[64]
    q3 = sorted_b[96]

    if q3 == 0:
        return None, "insufficient_variance (q3 == 0)"

    q1_ratio = int((float(q1) * 100 / q3) % 16) if q3 > 0 else 0
    q2_ratio = int((float(q2) * 100 / q3) % 16) if q3 > 0 else 0
    q_ratio_byte = (q1_ratio << 4) | q2_ratio

    l_byte = l_fast(length)

    # 128 buckets -> 2 bits each = 256 bits = 32 bytes
    code_bytes = bytearray(32)
    for b_idx in range(128):
        count = buckets[b_idx]
        if count <= q1:
            val = 0
        elif count <= q2:
            val = 1
        elif count <= q3:
            val = 2
        else:
            val = 3
        byte_pos = b_idx // 4
        bit_pos = (b_idx % 4) * 2
        code_bytes[byte_pos] |= val << bit_pos

    # TLSH standard format: T1 + 2-hex checksum + 2-hex length + 2-hex q_ratio + 64-hex buckets
    digest = f"T1{checksum:02X}{l_byte:02X}{q_ratio_byte:02X}{code_bytes.hex().upper()}"
    return digest, None


def compute_tlsh_distance(digest_a: str, digest_b: str) -> int:
    """Computes standard TLSH distance between two TLSH hex digests.

    Lower distance = higher similarity.
    0 = exact match.
    <= 30 = very near duplicate.
    <= 100 = moderate similarity.
    > 200 = largely unrelated.
    """
    if not (digest_a.startswith("T1") and digest_b.startswith("T1")):
        raise ValueError("Invalid TLSH digest format: must start with T1 header")

    # Header parsing
    c_a, l_a, q_a = int(digest_a[2:4], 16), int(digest_a[4:6], 16), int(digest_a[6:8], 16)
    c_b, l_b, q_b = int(digest_b[2:4], 16), int(digest_b[4:6], 16), int(digest_b[6:8], 16)

    # Checksum difference penalty
    diff_c = 1 if c_a != c_b else 0

    # Length difference penalty
    diff_l = abs(l_a - l_b)
    l_dist = diff_l * 12 if diff_l > 1 else diff_l

    # Quartile ratio difference penalty
    q1_a, q2_a = (q_a >> 4) & 0x0F, q_a & 0x0F
    q1_b, q2_b = (q_b >> 4) & 0x0F, q_b & 0x0F
    q_dist = abs(q1_a - q1_b) + abs(q2_a - q2_b)

    # Bucket distance
    bytes_a = bytes.fromhex(digest_a[8:])
    bytes_b = bytes.fromhex(digest_b[8:])

    bucket_dist = 0
    for byte_idx in range(min(len(bytes_a), len(bytes_b))):
        ba, bb = bytes_a[byte_idx], bytes_b[byte_idx]
        for pair in range(4):
            v_a = (ba >> (pair * 2)) & 0x03
            v_b = (bb >> (pair * 2)) & 0x03
            bucket_dist += abs(v_a - v_b)
    return diff_c + l_dist + q_dist + bucket_dist


def compute_tlsh(data: Union[str, bytes]) -> Optional[str]:
    """Helper that accepts string or bytes and returns digest hex string or None."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    digest, _ = compute_tlsh_digest(raw)
    return digest


tlsh_distance = compute_tlsh_distance
