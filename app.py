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

ALPENGLOW_RPC_URL = os.getenv("ALPENGLOW_RPC_URL", "http://77.42.74.189:8899")
NETWORK_NAME = os.getenv("NETWORK_NAME", "alpenglow")
MY_IDENTITY = os.getenv("MY_IDENTITY", "84zEgKV9w9B2C5h3Ahx61iZTRzU3wVrxJeBYmM9i1ggz")

async def rpc(method: str, params: list = []):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(ALPENGLOW_RPC_URL, json={
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
        perf = await rpc("getRecentPerformanceSamples", [1])
        slot_speed = 0
        if perf and len(perf) > 0:
            s = perf[0]
            slot_speed = round(s.get("numSlots", 0) / s["samplePeriodSecs"], 2)
        elif epoch_info and epoch_info.get("slotsPerSecond"):
            slot_speed = round(epoch_info["slotsPerSecond"], 2)
        return {
            "network": NETWORK_NAME,
            "slot": slot,
            "epoch": epoch_info.get("epoch"),
            "slot_index": epoch_info.get("slotIndex"),
            "slots_in_epoch": epoch_info.get("slotsInEpoch"),
            "slot_speed": slot_speed,
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

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def index():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")