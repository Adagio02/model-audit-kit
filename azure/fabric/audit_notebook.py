# Fabric notebook: Model Audit Kit in Microsoft Fabric
#
# Import this file into a Fabric workspace (Workspace > Import > Notebook) and attach a Lakehouse.
# It audits every batch under Files/audit-inputs/<client>/<batch>/ that has a submit.json, writes
# the HTML reports to Files/audit-reports/, and stores results as Delta tables (audit_runs,
# audit_check_results, audit_explanations) that a Power BI semantic model reads with Direct Lake.
#
# Setup (see azure/fabric/README.md):
#   1. Build the wheel on your PC:  .venv\Scripts\python.exe -m pip wheel . --no-deps -w dist
#   2. Upload dist\modelaudit-0.2.0-py3-none-any.whl to the Lakehouse: Files/wheels/
#   3. Point Files/audit-inputs at your data: a OneLake shortcut to the audit-inputs container of
#      the storage account from deploy.ps1, or upload the demo batch folders by hand.

# %% [cell 1] Install the audit engine from the Lakehouse
# %pip install /lakehouse/default/Files/wheels/modelaudit-0.2.0-py3-none-any.whl --quiet

# %% [cell 2] Parameters (mark this cell as a parameter cell so a pipeline can override them)
lakehouse_files = "/lakehouse/default/Files"   # LocalStore root: containers are folders here
only_new = True                                # skip batches already in audit_runs
use_foundry = False                            # True: explain findings with a Foundry model
foundry_endpoint = ""                          # https://<resource>.openai.azure.com
foundry_deployment = "gpt-4.1-mini"
foundry_key_vault = ""                         # https://<vault>.vault.azure.net (secret foundry-api-key)

# %% [cell 3] Find batches waiting for an audit
from pathlib import Path

import pandas as pd
from pyspark.sql import functions as F

from modelaudit.cloud.explain import AzureOpenAIExplainer, RuleExplainer
from modelaudit.cloud.pipeline import process_batch
from modelaudit.cloud.sinks import MemorySink
from modelaudit.cloud.store import INPUTS, LocalStore

inputs = Path(lakehouse_files) / INPUTS
pending = sorted((p.parent.parent.name, p.parent.name) for p in inputs.glob("*/*/submit.json"))

done = set()
if only_new and spark.catalog.tableExists("audit_runs"):  # noqa: F821 (spark is provided by Fabric)
    done = {(r.client, r.batch) for r in spark.table("audit_runs").select("client", "batch").collect()}  # noqa: F821
todo = [b for b in pending if b not in done]
print(f"{len(pending)} batches found, {len(todo)} to audit")

# %% [cell 4] Run the audits (same code path as the Azure Function)
if use_foundry:
    from notebookutils import credentials  # Fabric built-in; reads Key Vault as you

    key = credentials.getSecret(foundry_key_vault, "foundry-api-key")
    explainer = AzureOpenAIExplainer(foundry_endpoint, foundry_deployment, api_key=key)
else:
    explainer = RuleExplainer()

store, sink = LocalStore(lakehouse_files), MemorySink()
outcomes = [process_batch(store, sink, explainer, client, batch) for client, batch in todo]
display(pd.DataFrame([{"client": o.client, "batch": o.batch, "verdict": o.verdict, "error": o.error}  # noqa: F821
                      for o in outcomes]))

# %% [cell 5] Upsert into Delta tables (delete this batch's old rows, then append)
for name, rows in sink.tables().items():
    if not rows:
        continue
    table = f"audit_{name}"
    frame = spark.createDataFrame(pd.DataFrame(rows).astype(object).where(pd.notna, None))  # noqa: F821
    if name == "runs":
        frame = frame.withColumn("audited_utc", F.to_timestamp("audited_utc"))
    if spark.catalog.tableExists(table):  # noqa: F821
        ids = ", ".join(f"'{r['run_id']}'" for r in sink.tables()["runs"])
        spark.sql(f"DELETE FROM {table} WHERE run_id IN ({ids})")  # noqa: F821
        frame.write.mode("append").option("mergeSchema", "true").saveAsTable(table)
    else:
        frame.write.mode("overwrite").saveAsTable(table)
    print(f"{table}: {frame.count()} rows written")

# %% [cell 6] Quick look: what failed, and why
display(spark.sql("""
    SELECT r.client, r.batch, r.verdict, c.check_key, c.status, e.explanation
    FROM audit_runs r
    JOIN audit_check_results c ON c.run_id = r.run_id
    LEFT JOIN audit_explanations e ON e.run_id = c.run_id AND e.check_key = c.check_key
    WHERE c.status <> 'PASS'
    ORDER BY r.audited_utc DESC
"""))  # noqa: F821
