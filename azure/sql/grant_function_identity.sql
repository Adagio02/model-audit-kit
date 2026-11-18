-- Lets the Function App's managed identity read and write audit tables, and nothing else.
-- deploy.ps1 runs this with --var APP_NAME=<function app name>. Run as the Entra admin of the server.

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$(APP_NAME)')
    CREATE USER [$(APP_NAME)] FROM EXTERNAL PROVIDER;
GO
GRANT SELECT, INSERT, DELETE ON SCHEMA::audit TO [$(APP_NAME)];
GO

-- Read-only user for Power BI / Copilot Studio if you add one later:
-- CREATE USER [you@yourdomain.com] FROM EXTERNAL PROVIDER;
-- GRANT SELECT ON SCHEMA::audit TO [you@yourdomain.com];
