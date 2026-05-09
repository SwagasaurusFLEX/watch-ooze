# watch-ooze

Live monitor for the Ooze validator on the staccana network.

Lives at <https://watch.ooze.run>.

## What it does

A FastAPI app that:

- Reads the staccana `validator-subsidy` program's on-chain state via the
  staccana RPC at `$STACCANA_RPC_URL` (default: `http://77.42.80.65:8899`)
- Decodes the `ValidatorRegistry` PDA and each registered validator's
  `ValidatorRecord` PDA — Anchor account discriminators + Borsh layout
- Returns aggregated JSON to the frontend at `/api/validators`
- Frontend renders one card per validator, with the Ooze validator
  (`AKzHD1xB...`) highlighted

Read-only. No keys, no signing, no writes. The whole pipeline is RPC
queries against your own VPS.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Visit <http://localhost:8000>.

## Environment variables

| var                       | default                                              |
| ------------------------- | ---------------------------------------------------- |
| `STACCANA_RPC_URL`        | `http://77.42.80.65:8899`                            |
| `SUBSIDY_PROGRAM_ID`      | `Subsidy111111111111111111111111111111111111`        |
| `OOZE_VALIDATOR_IDENTITY` | `AKzHD1xBJVAiDnvQi4P7Z1RhHmbMv8fX7dcTWrisimiL`       |
| `PORT`                    | `8000`                                               |

## Deploy on Railway

Auto-deploys from the `main` branch. Set the custom domain
`watch.ooze.run` after first deploy.
