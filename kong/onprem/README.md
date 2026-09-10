# Self-hosted AI Gateway 2.0

This branch runs a local Kong Gateway Enterprise hybrid deployment:

- `kong-database` is the Postgres store for the control plane.
- `kong-cp` is the self-hosted control plane and Admin API (`localhost:8001`).
- `kong-dp` is the self-hosted data plane and demo entry point (`localhost:8000`).
- `kong/onprem/certs/cluster.crt` and `cluster.key` are the local shared-mTLS pair generated at startup. They are deliberately ignored by Git.

The Konnect AI Gateway 2.0 export was converted locally with `deck file ai2kong`. That conversion produces ordinary Kong Gateway primitives (Services, Routes, Consumers, Consumer Groups, and AI plugins). The reviewed, secret-free equivalent is committed as [`../deck/kong.yaml`](../deck/kong.yaml); its provider credentials use decK environment substitutions such as `DECK_OPENAI_API_KEY` instead of values exported from Konnect.

Run the deployment with:

```sh
./scripts/start_self_hosted_demo.sh
```

Set `KONG_LICENSE_DATA` to the one-line JSON Enterprise license in `.env` before starting. The demo uses Enterprise-only Consumer Groups and AI Gateway plugins, so Kong will reject the configuration without it.

The script generates a new local cluster certificate only when one does not already exist, starts the Postgres-backed hybrid topology, then syncs the converted Gateway configuration to `kong-cp`. No Konnect API, control plane, or managed data plane is used.

Stop the deployment while preserving its local database:

```sh
./scripts/stop_self_hosted_demo.sh
```

To recreate the topology from scratch, remove all local volumes:

```sh
./scripts/stop_self_hosted_demo.sh --volumes
```

The next start creates a fresh control-plane database and syncs the configuration again.
