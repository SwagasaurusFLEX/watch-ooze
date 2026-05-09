# watch-ooze

Live monitor for the Ooze validator on the staccana network.

Lives at <https://watch.ooze.run>.

## What it does

A FastAPI app that:

- Reads the staccana `validator-subsidy` program's on-chain state via the
  RPC at `$STACCANA_RPC_URL` (default: `http://77.42.80.65:8899`)
- Calls `getProgramAccounts` with a `dataSize: 91` filter to get every
  `ValidatorRecord` PDA in one round-trip
- Decodes each record's metrics (uptime, stake, votes, lifetime subsidy)
- Returns aggregated JSON to the frontend at `/api/validators`
- Frontend renders one card per validator, with the Ooze validator
  highlighted

Read-only. No keys, no signing, no writes.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

## Environment variables

| var                       | default                                              |
| ------------------------- | ---------------------------------------------------- |
| `STACCANA_RPC_URL`        | `http://77.42.80.65:8899`                            |
| `SUBSIDY_PROGRAM_ID`      | `Subsidy111111111111111111111111111111111111`        |
| `OOZE_VALIDATOR_IDENTITY` | `AKzHD1xBJVAiDnvQi4P7Z1RhHmbMv8fX7dcTWrisimiL`       |
| `PORT`                    | `8000`                                               |