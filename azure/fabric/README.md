# Phase 2: orchestrate in Fabric or Azure Data Factory

Phase 1 runs one audit per upload. Phase 2 adds a scheduled, observable pipeline around it and
a reporting layer. Pick **one** of the two routes; Fabric is where Microsoft is putting new work.

## Route A: Microsoft Fabric (recommended)

**Cost:** the Fabric trial is free, but Copilot in Fabric and Fabric data agents **do not run on
trial capacity**. For Phase 3 you need a paid F2 capacity, created in the Azure portal. **Pause it
whenever you're not using it**, because it bills by the hour while running.

1. **Workspace + Lakehouse.** At app.fabric.microsoft.com create a workspace `model-audit` and a
   Lakehouse `audit_lh`.
2. **Connect your storage without copying it.** In the Lakehouse, go to *Files > New shortcut >
   Azure Data Lake Storage Gen2* and use `https://<storage>.dfs.core.windows.net/audit-inputs`. Name
   the shortcut `audit-inputs`, and do the same for `audit-reports`. Sign in with your organizational
   account (you have Storage Blob Data Contributor from `main.bicep`).
3. **Upload the engine.** On your PC run `.venv\Scripts\python.exe -m pip wheel . --no-deps -w dist`
   and upload `dist\modelaudit-0.2.0-py3-none-any.whl` to `Files/wheels/`.
4. **Import the notebook.** Go to *Workspace > Import > Notebook > `azure/fabric/audit_notebook.py`*,
   attach `audit_lh`, uncomment the `%pip install` line and run all cells. It audits each batch that
   isn't in `audit_runs` yet and writes three Delta tables.
5. **Build the pipeline.** Create *New item > Data pipeline* `daily-audit`:
   - **Notebook** activity running `audit_notebook` (set `only_new = true`).
   - **On failure**, an **Office 365 Outlook** activity that emails you.
   - **Schedule** it daily, or add a **storage event trigger** on `audit-inputs` for `submit.json`.
6. **Try Copilot for Data Factory** (needs F2). In the pipeline editor, open Copilot and try:
   - *"Summarize this pipeline."*
   - *"Add a step that copies audit.runs from my Azure SQL database into the Lakehouse table sql_runs every day."*
   - In a Dataflow Gen2 on `audit_check_results`: *"Remove rows where status is PASS and add a column
     with the number of days since audited_utc."*
   Write down what it got right and what you had to fix.
7. **Semantic model.** In the Lakehouse SQL endpoint, choose *New semantic model* with the three
   tables, then follow `azure/powerbi/README.md`. A Direct Lake model reads Delta tables with no
   import refresh.

## Route B: Azure Data Factory

1. Create a Data Factory in the same resource group (portal, about 2 minutes). Give its managed
   identity **Storage Blob Data Reader** on the storage account.
2. Create a **linked service** to the Function App (*Azure Function*, function key from
   `az functionapp keys list -g <rg> -n <app>`).
3. Pipeline `daily-audit`:
   - **Get Metadata** on `audit-inputs` (child items) gives the client folders, and a **ForEach** over
     them with a second Get Metadata gives the batch folders.
   - **Azure Function** activity: method `POST`, function `audits`, body
     `{"client": "@{item().client}", "batch": "@{item().batch}"}`. It calls the `RunAudit` HTTP
     function, which runs the same pipeline as the blob trigger.
   - **Schedule trigger**, daily.
4. Monitor runs under *Monitor > Pipeline runs*, and add an alert on failed runs.

The blob trigger already audits every upload, so in Route B the pipeline is for scheduled re-runs,
backfills and practising ADF. In real work you'd keep one entry point per batch.
