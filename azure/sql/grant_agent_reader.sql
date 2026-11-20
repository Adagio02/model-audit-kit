-- Read-only access to the reporting views for a person or service that is NOT the Function App:
-- the Copilot Studio agent's knowledge connection or a Power BI user.
-- deploy.ps1 runs this when you pass -ReaderLogin you@yourtenant.onmicrosoft.com.
-- The user sees only the four views: no raw metrics JSON tables, no input hashes, no write access.

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$(READER_LOGIN)')
    CREATE USER [$(READER_LOGIN)] FROM EXTERNAL PROVIDER;
GO
GRANT SELECT ON OBJECT::audit.v_runs TO [$(READER_LOGIN)];
GRANT SELECT ON OBJECT::audit.v_findings TO [$(READER_LOGIN)];
GRANT SELECT ON OBJECT::audit.v_check_daily TO [$(READER_LOGIN)];
GRANT SELECT ON OBJECT::audit.v_run_metrics TO [$(READER_LOGIN)];
GO
