import os
import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALPENGLOW_RPC_URL = os.getenv("ALPENGLOW_RPC_URL", "http://rpc.ooze.run:8899")
PERF_RPC_URL = os.getenv("PERF_RPC_URL", "http://64.130.37.11:8899")
NETWORK_NAME = os.getenv("NETWORK_NAME", "alpenglow")
MY_IDENTITY = os.getenv("MY_IDENTITY", "84zEgKV9w9B2C5h3Ahx61iZTRzU3wVrxJeBYmM9i1ggz")

async def rpc(method: str, params: list = [], url: str = None):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url or ALPENGLOW_RPC_URL, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params
        })
        return r.json().get("result")

@app.get("/api/network")
async def get_network():
    try:
        slot = await rpc("getSlot")
        epoch_info = await rpc("getEpochInfo")
        perf = await rpc("getRecentPerformanceSamples", [1], url=PERF_RPC_URL)
        slot_speed = 0
        tps = 0
        if perf and len(perf) > 0:
            s = perf[0]
            period = s.get("samplePeriodSecs") or 1
            slot_speed = round(s.get("numSlots", 0) / period, 2)
            tps = round(s.get("numTransactions", 0) / period, 1)
        elif epoch_info and epoch_info.get("slotsPerSecond"):
            slot_speed = round(epoch_info["slotsPerSecond"], 2)
        return {
            "network": NETWORK_NAME,
            "slot": slot,
            "epoch": epoch_info.get("epoch"),
            "slot_index": epoch_info.get("slotIndex"),
            "slots_in_epoch": epoch_info.get("slotsInEpoch"),
            "slot_speed": slot_speed,
            "tps": tps,
            "rpc": ALPENGLOW_RPC_URL
        }

    except Exception as e:
        return {"error": str(e)}

@app.get("/api/validators")
async def get_validators():
    try:
        vote_accounts = await rpc("getVoteAccounts")
        current = vote_accounts.get("current", [])
        delinquent = vote_accounts.get("delinquent", [])

        def format_validator(v, status):
            return {
                "identity": v.get("nodePubkey"),
                "vote_account": v.get("votePubkey"),
                "stake": round(v.get("activatedStake", 0) / 1e9, 2),
                "commission": v.get("commission"),
                "last_vote": v.get("lastVote"),
                "root_slot": v.get("rootSlot"),
                "credits": v.get("epochCredits", [[0,0,0]])[-1][1] if v.get("epochCredits") else 0,
                "version": v.get("version", "unknown"),
                "status": status,
                "is_mine": v.get("nodePubkey") == MY_IDENTITY
            }

        validators = (
            [format_validator(v, "active") for v in current] +
            [format_validator(v, "delinquent") for v in delinquent]
        )

        validators.sort(key=lambda x: (not x["is_mine"], -x["stake"]))

        return {
            "validators": validators,
            "active_count": len(current),
            "delinquent_count": len(delinquent),
            "total_stake": round(sum(v["stake"] for v in validators), 2)
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/validator/{vote_account}")
async def get_validator_detail(vote_account: str):
    try:
        vote_accounts = await rpc("getVoteAccounts")
        epoch_info = await rpc("getEpochInfo")
        current = vote_accounts.get("current", [])
        delinquent = vote_accounts.get("delinquent", [])

        # rank by activated stake across the active set
        ranked = sorted(current, key=lambda v: v.get("activatedStake", 0), reverse=True)
        rank = next((i + 1 for i, v in enumerate(ranked)
                     if v.get("votePubkey") == vote_account), None)

        # find the validator in either bucket
        status = "active"
        match = next((v for v in current if v.get("votePubkey") == vote_account), None)
        if match is None:
            match = next((v for v in delinquent if v.get("votePubkey") == vote_account), None)
            status = "delinquent"
        if match is None:
            return {"error": "validator not found"}

        identity = match.get("nodePubkey")
        abs_slot = epoch_info.get("absoluteSlot", 0)
        last_vote = match.get("lastVote", 0)
        lag = max(0, abs_slot - last_vote) if last_vote else None

        # epochCredits -> per-epoch deltas
        ec = match.get("epochCredits", []) or []
        credit_history = [{"epoch": e[0], "credits": e[1] - e[2]} for e in ec][-10:]
        this_epoch_credits = (ec[-1][1] - ec[-1][2]) if ec else 0

        # ---- block production (skip rate) for THIS identity ----
        leader_slots = 0
        blocks_produced = 0
        skip_rate = None
        try:
            bp = await rpc("getBlockProduction", [{"identity": identity}])
            by = (bp.get("value", {}).get("byIdentity", {}) or {}).get(identity)
            if by:
                leader_slots, blocks_produced = by[0], by[1]
                if leader_slots > 0:
                    skip_rate = round((1 - blocks_produced / leader_slots) * 100, 1)
        except Exception:
            pass

        # ---- leader schedule: next leader slot + recent produced block ----
        last_block = None
        next_leader_in = None
        try:
            sched = await rpc("getLeaderSchedule", [None, {"identity": identity}])
            if sched and identity in sched:
                # schedule slots are RELATIVE to the current epoch's first slot
                epoch_first = abs_slot - epoch_info.get("slotIndex", 0)
                abs_slots = [epoch_first + s for s in sched[identity]]
                produced_past = sorted([s for s in abs_slots if s < abs_slot], reverse=True)
                upcoming = sorted([s for s in abs_slots if s > abs_slot])
                if upcoming:
                    next_leader_in = upcoming[0] - abs_slot
                # pull the most recent produced leader slot that has a block
                for s in produced_past[:5]:
                    blk = await rpc("getBlock", [s, {
                        "encoding": "json", "maxSupportedTransactionVersion": 0,
                        "transactionDetails": "full", "rewards": False
                    }])
                    if blk and blk.get("transactions"):
                        txs = blk["transactions"]
                        total_fee = sum(t.get("meta", {}).get("fee", 0) for t in txs)
                        total_cu = sum(t.get("meta", {}).get("computeUnitsConsumed", 0) for t in txs)
                        last_block = {
                            "slot": s,
                            "tx_count": len(txs),
                            "total_fee_sol": round(total_fee / 1e9, 6),
                            "total_compute_units": total_cu,
                        }
                        break
        except Exception:
            pass

        return {
            "identity": identity,
            "vote_account": match.get("votePubkey"),
            "stake": round(match.get("activatedStake", 0) / 1e9, 2),
            "commission": match.get("commission"),
            "last_vote": last_vote,
            "root_slot": match.get("rootSlot"),
            "lag": lag,
            "this_epoch_credits": this_epoch_credits,
            "credit_history": credit_history,
            "version": match.get("version", "unknown"),
            "status": status,
            "rank": rank,
            "active_count": len(current),
            "absolute_slot": abs_slot,
            "epoch": epoch_info.get("epoch"),
            "leader_slots": leader_slots,
            "blocks_produced": blocks_produced,
            "skip_rate": skip_rate,
            "last_block": last_block,
            "next_leader_in": next_leader_in,
            "is_mine": identity == MY_IDENTITY
        }
    except Exception as e:
        return {"error": str(e)}


app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")