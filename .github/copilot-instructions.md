# Instructions for GitHub Copilot in this repository

Model Audit Kit audits trading-strategy backtests: two CSVs in, seven checks, a PASS / CONDITIONAL /
FAIL verdict and an HTML report out. It runs locally (CLI) and in Azure (Function + Blob + SQL + Foundry).

## Layout
- `src/modelaudit/checks.py`: the audit checks. Each returns `CheckResult(key, title, status, summary, metrics)`.
- `src/modelaudit/cloud/`: the pipeline shared by the CLI, the Azure Function and the Fabric notebook.
  Storage, result sinks and explainers are swappable (`LocalStore`/`BlobStore`, `SqliteSink`/`AzureSqlSink`/
  `MemorySink`, `RuleExplainer`/`AzureOpenAIExplainer`).
- `azure/function_app/`: thin Azure Functions wrapper (Python v2 model). Keep logic out of it.
- `azure/infra/main.bicep`, `azure/sql/*.sql`: infrastructure and schema.

## Rules
- Contract: weights are set at the close of `date` and earn the NEXT period's return. Never compute a
  feature or weight with future data (`shift(-1)`, joins on the wrong date).
- Azure SDKs are imported lazily inside functions so the local path needs only pandas/numpy/scipy/matplotlib.
- No secrets in code or settings files. Storage and SQL use managed identity / `DefaultAzureCredential`;
  the Foundry key is a Key Vault reference.
- Writes to results tables are idempotent per `run_id` (delete then insert in one transaction).
- Bad client input becomes verdict `ERROR` (recorded, not raised); unexpected errors raise so they alert.
- Only summary numbers go to the language model, never the client's raw prices or positions.
- Every change gets a test in `tests/` that runs offline (use `LocalStore`, `SqliteSink`, fake OpenAI client).
- Python 3.11+, line length 110, `ruff` clean. Run `python -m pytest` before committing.
