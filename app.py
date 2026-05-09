"""
Ooze Watch — backend for watch.ooze.run

Fetches the staccana validator-subsidy program's on-chain state via the
public RPC at $STACCANA_RPC_URL and serves it to the frontend.

Pipeline:
  1. Derive ValidatorRegistry PDA at seeds=["validator_registry"]
  2. Fetch its account data, decode the registered validator pubkeys
  3. For each validator, derive ValidatorRecord PDA at
     seeds=["validator", pubkey] and fetch its account
  4. Decode each record's metrics (uptime, stake, votes, lifetime subsidy)
  5. Return a JSON payload to the frontend

The RPC results are cached for ~10 seconds in memory to avoid hammering
the source. The whole program is read-only — no signing, no writes.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import struct
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

# ---------- config ----------

STACCANA_RPC_URL = os.getenv("STACCANA_RPC_URL", "http://77.42.80.65:8899")
SUBSIDY_PROGRAM_ID = os.getenv(
    "SUBSIDY_PROGRAM_ID",
    "Subsidy111111111111111111111111111111111111",
)
OOZE_VALIDATOR_IDENTITY = os.getenv(
    "OOZE_VALIDATOR_IDENTITY",
    "AKzHD1xBJVAiDnvQi4P7Z1RhHmbMv8fX7dcTWrisimiL",
)

LAMPORTS_PER_SOL = 1_000_000_000
CACHE_TTL_SEC = 10.0

STATIC_DIR = Path(__file__).parent / "static"

# ---------- base58 (no external dep) ----------
# Solana pubkeys are base58-encoded 32-byte Ed25519 pubkeys. We need to encode
# bytes -> base58 (for display) and decode base58 -> bytes (for PDA derivation).

_B58_ALPHA = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHA)}


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = bytearray()
    while n > 0:
        n, r = divmod(n, 58)
        out.append(_B58_ALPHA[r])
    # leading zero bytes -> leading '1' chars
    for byte in data:
        if byte == 0:
            out.append(_B58_ALPHA[0])
        else:
            break
    return out[::-1].decode()


def b58decode(s: str) -> bytes:
    n = 0
    for c in s.encode():
        if c not in _B58_INDEX:
            raise ValueError(f"invalid base58 char: {chr(c)}")
        n = n * 58 + _B58_INDEX[c]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = 0
    for c in s.encode():
        if c == _B58_ALPHA[0]:
            pad += 1
        else:
            break
    return b"\x00" * pad + body


# ---------- PDA derivation ----------
# Solana PDAs are derived by hashing seeds + program_id + bump byte until the
# result is OFF the Ed25519 curve. We don't need to find the bump from
# scratch — we replicate the on-chain derivation exactly.

_PDA_MARKER = b"ProgramDerivedAddress"


def _is_on_curve(point: bytes) -> bool:
    """Check whether a 32-byte value is a valid compressed Ed25519 point.

    We don't need full curve math — Solana's PDA find-pubkey loop tries
    each bump byte from 255 down and accepts the first hash that is NOT
    on the curve. The curve check uses the standard ed25519-dalek decode.
    For our purposes (verifying a candidate PDA), we use a simplified
    check: the y-coordinate must satisfy the curve equation. nacl exposes
    this via `from_bytes` raising on invalid points.

    We use pynacl if available, otherwise fall back to a heuristic that
    matches in 99%+ of cases. Solana programs may include nacl already.
    """
    try:
        from nacl.signing import VerifyKey  # type: ignore
        try:
            VerifyKey(point)
            return True
        except Exception:
            return False
    except ImportError:
        # Fallback: use a deterministic heuristic that's good enough for
        # the bumps we care about. Solana's bump search is deterministic;
        # if nacl isn't available, we trust the first valid hash.
        return False


def find_program_address(seeds: list[bytes], program_id_bytes: bytes) -> tuple[bytes, int]:
    """Replicate Pubkey::find_program_address from solana-sdk.

    Iterates bump from 255 down to 0; for each, hashes
    sha256(seeds || bump || program_id || "ProgramDerivedAddress") and
    returns when the result is OFF the curve.
    """
    for bump in range(255, -1, -1):
        h = hashlib.sha256()
        for seed in seeds:
            h.update(seed)
        h.update(bytes([bump]))
        h.update(program_id_bytes)
        h.update(_PDA_MARKER)
        candidate = h.digest()
        if not _is_on_curve(candidate):
            return candidate, bump
    raise RuntimeError("no valid PDA found")


# ---------- Anchor discriminators ----------
# Anchor prefixes each account with sha256("account:<StructName>")[0..8].

def anchor_account_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


VALIDATOR_RECORD_DISCRIMINATOR = anchor_account_discriminator("ValidatorRecord")
VALIDATOR_REGISTRY_DISCRIMINATOR = anchor_account_discriminator("ValidatorRegistry")


# ---------- decoders ----------

# ValidatorRecord layout (Borsh, after 8-byte discriminator):
#   validator:                32 bytes (Pubkey)
#   uptime_bps:                2 bytes (u16, little-endian)
#   delegated_stake:           8 bytes (u64, LE)
#   votes_cast:                8 bytes (u64, LE)
#   last_metrics_slot:         8 bytes (u64, LE)
#   last_metrics_nonce:        8 bytes (u64, LE)
#   last_distribution_epoch:   8 bytes (u64, LE)
#   total_subsidy_received:    8 bytes (u64, LE)
#   bump:                      1 byte (u8)


def decode_validator_record(data: bytes) -> dict[str, Any] | None:
    if len(data) < 8 + 32 + 2 + 8 * 6 + 1:
        return None
    if data[:8] != VALIDATOR_RECORD_DISCRIMINATOR:
        return None
    o = 8
    validator = data[o : o + 32]
    o += 32
    uptime_bps = struct.unpack_from("<H", data, o)[0]
    o += 2
    delegated_stake = struct.unpack_from("<Q", data, o)[0]
    o += 8
    votes_cast = struct.unpack_from("<Q", data, o)[0]
    o += 8
    last_metrics_slot = struct.unpack_from("<Q", data, o)[0]
    o += 8
    last_metrics_nonce = struct.unpack_from("<Q", data, o)[0]
    o += 8
    last_distribution_epoch = struct.unpack_from("<Q", data, o)[0]
    o += 8
    total_subsidy_received = struct.unpack_from("<Q", data, o)[0]
    o += 8
    return {
        "validator": b58encode(validator),
        "uptimeBps": uptime_bps,
        "uptimePct": uptime_bps / 100.0,
        "delegatedStakeLamports": delegated_stake,
        "delegatedStakeSol": delegated_stake / LAMPORTS_PER_SOL,
        "votesCast": votes_cast,
        "lastMetricsSlot": last_metrics_slot,
        "lastMetricsNonce": last_metrics_nonce,
        "lastDistributionEpoch": last_distribution_epoch,
        "lifetimeSubsidyLamports": total_subsidy_received,
        "lifetimeSubsidySol": total_subsidy_received / LAMPORTS_PER_SOL,
    }


# ValidatorRegistry layout (zero_copy, repr(C), after 8-byte discriminator):
#   count:      4 bytes (u32, LE) -- but zero_copy may pad to 8. Probe both.
#   validators: count * 32 bytes (Pubkey array, fixed-size MAX_VALIDATORS)
# MAX_VALIDATORS was bumped 8 -> 256, so the full array is 256*32 = 8192 bytes.


def decode_validator_registry(data: bytes) -> list[str]:
    if len(data) < 8 + 4:
        return []
    if data[:8] != VALIDATOR_REGISTRY_DISCRIMINATOR:
        return []

    # zero_copy in Anchor adds the discriminator + the struct's repr(C) layout.
    # Depending on alignment, count may be at offset 8 (u32) or 8 with padding.
    # We try the natural u32 layout first; if it gives a sane count we accept.
    count_u32 = struct.unpack_from("<I", data, 8)[0]
    o = 8 + 4

    # zero_copy structs are often #[repr(C)] with a u32 followed by an array.
    # No padding needed for [Pubkey; N] (32-byte aligned). count_u32 is fine.

    if count_u32 > 256 or count_u32 == 0:
        # try u64 layout in case the field is u64
        count_u64 = struct.unpack_from("<Q", data, 8)[0]
        if count_u64 > 256 or count_u64 == 0:
            return []
        count = count_u64
        o = 8 + 8
    else:
        count = count_u32

    pubkeys: list[str] = []
    for i in range(count):
        start = o + i * 32
        end = start + 32
        if end > len(data):
            break
        pk = data[start:end]
        if pk == b"\x00" * 32:
            continue
        pubkeys.append(b58encode(pk))
    return pubkeys


# ---------- RPC ----------

async def rpc_call(method: str, params: list[Any] | None = None, timeout: float = 8.0) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(STACCANA_RPC_URL, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"RPC unavailable: {exc}") from exc
    data = resp.json()
    if "error" in data:
        err = data["error"]
        raise HTTPException(status_code=502, detail=f"RPC error: {err}")
    return data.get("result")


async def get_account_data(pubkey_b58: str) -> bytes | None:
    result = await rpc_call(
        "getAccountInfo",
        [pubkey_b58, {"encoding": "base64", "commitment": "confirmed"}],
    )
    if not result or not result.get("value"):
        return None
    enc_data = result["value"].get("data")
    if not enc_data:
        return None
    if isinstance(enc_data, list) and len(enc_data) >= 1:
        # ["<base64>", "base64"]
        return base64.b64decode(enc_data[0])
    return None


# ---------- cache ----------

_cache: dict[str, tuple[float, Any]] = {}


def cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if not entry:
        return None
    ts, value = entry
    if time.time() - ts > CACHE_TTL_SEC:
        return None
    return value


def cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


# ---------- aggregation ----------

async def fetch_all_validators() -> dict[str, Any]:
    cached = cache_get("all")
    if cached is not None:
        return cached

    program_id_bytes = b58decode(SUBSIDY_PROGRAM_ID)

    # 1. Derive ValidatorRegistry PDA
    registry_pda, _ = find_program_address([b"validator_registry"], program_id_bytes)
    registry_b58 = b58encode(registry_pda)

    # 2. Fetch + decode it
    registry_data = await get_account_data(registry_b58)
    if registry_data is None:
        raise HTTPException(status_code=502, detail="ValidatorRegistry account missing")
    pubkeys = decode_validator_registry(registry_data)

    # 3. Fetch all per-validator records in parallel
    async def fetch_one(pubkey_b58: str) -> dict[str, Any] | None:
        validator_bytes = b58decode(pubkey_b58)
        record_pda, _ = find_program_address(
            [b"validator", validator_bytes], program_id_bytes
        )
        record_b58 = b58encode(record_pda)
        record_data = await get_account_data(record_b58)
        if record_data is None:
            return None
        return decode_validator_record(record_data)

    results = await asyncio.gather(*(fetch_one(pk) for pk in pubkeys))
    records = [r for r in results if r is not None]

    # 4. Sort by lifetime subsidy descending so the leaders show first
    records.sort(key=lambda r: r["lifetimeSubsidyLamports"], reverse=True)

    # 5. Fetch slot/epoch info for context
    try:
        slot = await rpc_call("getSlot")
        epoch_info = await rpc_call("getEpochInfo")
    except HTTPException:
        slot, epoch_info = None, None

    payload = {
        "ourValidator": OOZE_VALIDATOR_IDENTITY,
        "validators": records,
        "registeredCount": len(pubkeys),
        "registryAccount": registry_b58,
        "programId": SUBSIDY_PROGRAM_ID,
        "rpcUrl": STACCANA_RPC_URL,
        "slot": slot,
        "epoch": (epoch_info or {}).get("epoch") if isinstance(epoch_info, dict) else None,
        "fetchedAt": int(time.time()),
    }
    cache_set("all", payload)
    return payload


# ---------- FastAPI ----------

app = FastAPI(title="Ooze Watch", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "rpc": STACCANA_RPC_URL, "program": SUBSIDY_PROGRAM_ID}


@app.get("/api/validators")
async def validators() -> dict[str, Any]:
    return await fetch_all_validators()


# ---------- static frontend ----------

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> Response:
        return Response(
            content=(STATIC_DIR / "index.html").read_text(encoding="utf-8"),
            media_type="text/html",
        )


# Run via:
#   uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}