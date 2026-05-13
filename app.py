"""
Ooze Watch — backend for watch.ooze.run

Fetches the staccana validator-subsidy program's on-chain state via the
public RPC at $STACCANA_RPC_URL and serves it to the frontend.

Pipeline:
  1. Call getProgramAccounts on the validator-subsidy program
  2. Filter accounts by Anchor discriminator to find ValidatorRecord accounts
  3. Decode each into structured JSON
  4. Return the records to the frontend

No PDA derivation needed. No external SDK. Just RPC + Borsh decode.
The whole pipeline is read-only — no signing, no writes.
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

STACCANA_RPC_URL = os.getenv("STACCANA_RPC_URL", "http://77.42.74.189:8899")
SUBSIDY_PROGRAM_ID = os.getenv(
    "SUBSIDY_PROGRAM_ID",
    "Subsidy111111111111111111111111111111111111",
)
OOZE_VALIDATOR_IDENTITY = os.getenv(
    "OOZE_VALIDATOR_IDENTITY",
    "AKzHD1xBJVAiDnvQi4P7Z1RhHmbMv8fX7dcTWrisimiL",
)
NETWORK_NAME = os.getenv("NETWORK_NAME", "staccana")

LAMPORTS_PER_SOL = 1_000_000_000
CACHE_TTL_SEC = 10.0

STATIC_DIR = Path(__file__).parent / "static"

# ---------- base58 ----------

_B58_ALPHA = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = bytearray()
    while n > 0:
        n, r = divmod(n, 58)
        out.append(_B58_ALPHA[r])
    for byte in data:
        if byte == 0:
            out.append(_B58_ALPHA[0])
        else:
            break
    return out[::-1].decode()


# ---------- Anchor discriminators ----------

def anchor_account_discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode()).digest()[:8]


VALIDATOR_RECORD_DISCRIMINATOR = anchor_account_discriminator("ValidatorRecord")

VALIDATOR_RECORD_SIZE = 91


def decode_validator_record(data: bytes) -> dict[str, Any] | None:
    if len(data) < VALIDATOR_RECORD_SIZE:
        return None
    if data[:8] != VALIDATOR_RECORD_DISCRIMINATOR:
        return None
    o = 8
    validator = data[o : o + 32]; o += 32
    uptime_bps = struct.unpack_from("<H", data, o)[0]; o += 2
    delegated_stake = struct.unpack_from("<Q", data, o)[0]; o += 8
    votes_cast = struct.unpack_from("<Q", data, o)[0]; o += 8
    last_metrics_slot = struct.unpack_from("<Q", data, o)[0]; o += 8
    last_metrics_nonce = struct.unpack_from("<Q", data, o)[0]; o += 8
    last_distribution_epoch = struct.unpack_from("<Q", data, o)[0]; o += 8
    total_subsidy_received = struct.unpack_from("<Q", data, o)[0]; o += 8
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


# ---------- RPC ----------

async def rpc_call(method: str, params: list[Any] | None = None, timeout: float = 12.0) -> Any:
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

    all_accounts = await rpc_call(
        "getProgramAccounts",
        [
            SUBSIDY_PROGRAM_ID,
            {
                "encoding": "base64",
                "commitment": "confirmed",
                "filters": [{"dataSize": VALIDATOR_RECORD_SIZE}],
            },
        ],
    )

    if not isinstance(all_accounts, list):
        all_accounts = []

    records: list[dict[str, Any]] = []
    for entry in all_accounts:
        try:
            account = entry.get("account", {})
            data_field = account.get("data")
            if not isinstance(data_field, list) or len(data_field) < 1:
                continue
            raw = base64.b64decode(data_field[0])
            decoded = decode_validator_record(raw)
            if decoded is None:
                continue
            records.append(decoded)
        except Exception:
            continue

    records.sort(key=lambda r: r["lifetimeSubsidyLamports"], reverse=True)

    try:
        slot = await rpc_call("getSlot")
    except HTTPException:
        slot = None
    try:
        epoch_info = await rpc_call("getEpochInfo")
    except HTTPException:
        epoch_info = None

    payload = {
        "ourValidator": OOZE_VALIDATOR_IDENTITY,
        "validators": records,
        "registeredCount": len(records),
        "programId": SUBSIDY_PROGRAM_ID,
        "rpcUrl": STACCANA_RPC_URL,
        "network": NETWORK_NAME,
        "slot": slot,
        "epoch": (epoch_info or {}).get("epoch") if isinstance(epoch_info, dict) else None,
        "fetchedAt": int(time.time()),
    }
    cache_set("all", payload)
    return payload


# ---------- FastAPI ----------

app = FastAPI(title="Ooze Watch", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "rpc": STACCANA_RPC_URL,
        "program": SUBSIDY_PROGRAM_ID,
        "network": NETWORK_NAME,
    }


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