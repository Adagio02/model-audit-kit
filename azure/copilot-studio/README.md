# Copilot Studio agent: "What failed validation yesterday?"

An agent that answers questions about audit results in plain English, grounded in the Azure SQL
views (or a Fabric data agent). Copilot Studio has a 30-day trial, at aka.ms/TryCopilotStudio, and it
needs a work or school account.

## 1. Give the agent read-only data access

Run this in the Azure portal's SQL *Query editor* as the Entra admin. Use the account the agent
will connect with:

```sql
CREATE USER [you@yourtenant.onmicrosoft.com] FROM EXTERNAL PROVIDER;
GRANT SELECT ON OBJECT::audit.v_runs TO [you@yourtenant.onmicrosoft.com];
GRANT SELECT ON OBJECT::audit.v_findings TO [you@yourtenant.onmicrosoft.com];
GRANT SELECT ON OBJECT::audit.v_check_daily TO [you@yourtenant.onmicrosoft.com];
```

The views hide raw metrics JSON and input hashes, and the agent can't write anything.

## 2. Create the agent

At copilotstudio.microsoft.com go to *Create > New agent*, name it **Audit Desk** and paste these instructions:

```
You answer questions about independent backtest audits stored in the views v_runs, v_findings
and v_check_daily.
- A run has a verdict: PASS, CONDITIONAL (warnings only), FAIL, or ERROR (input could not be audited).
- A finding is a check with status WARN or FAIL. Use the explanation and suggested_action columns
  to say why it failed and what to do.
- "Yesterday", "this week" etc. refer to audit_date.
- Always name the client, batch and check. Link report_uri when you mention a run.
- If the data does not answer the question, say so. Never invent runs, numbers or explanations.
- Do not give investment advice or predict returns; audits test backtest integrity only.
```

## 3. Add knowledge

*Knowledge > Add > Azure SQL*: server `<server>.database.windows.net`, database `auditdb`, sign in
with Microsoft Entra, and select the three `audit.v_*` views. Add a description to each column,
for example *verdict: PASS, CONDITIONAL, FAIL or ERROR*. Descriptions noticeably improve answers.

**Fabric alternative (needs F2):** create a *Fabric data agent* on the Lakehouse tables. Give it the
same instructions and publish it, then in Copilot Studio add it under *Tools/Agents > Microsoft Fabric*.

## 4. Test questions

- What failed validation yesterday?
- Which client has the most look-ahead failures this month?
- Why did demo / leaky_momentum fail, and what should they fix?
- How many runs errored, and what were the error messages?
- Show the pass rate by week.

Check every answer against `SELECT * FROM audit.v_findings`. Note which questions it gets wrong and
how changing a column description or an instruction fixed it.

## 5. Optional: an action

Add a *Tool > Agent flow* that calls `POST https://<app>/api/audits?code=<key>` (the `RunAudit`
function) so the agent can rerun a batch when asked. Require a confirmation message first.
