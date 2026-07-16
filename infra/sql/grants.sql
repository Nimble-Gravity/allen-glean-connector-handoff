/* ============================================================================
 * Read-only DEV SQL login for the Allen & Co Glean connector.
 *
 * glean_dev is the DEVELOPMENT login (used during build/test via Azure Bastion),
 * granted SELECT on ONLY the four in-scope views — no writes, no base-table
 * access. It is temporary and removed at go-live.
 *
 * PRODUCTION does NOT use a SQL login: the connector authenticates with a
 * passwordless MANAGED IDENTITY — see infra/sql/mi_user.sql. No production SQL
 * credentials exist or are shared with anyone.
 *
 * Run AFTER mirror_schema.sql. Pass the password as a sqlcmd variable:
 *   sqlcmd ... -v GLEAN_DEV_PASSWORD="..." -i grants.sql
 *
 * Idempotent.
 * ============================================================================ */

USE master;
GO

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = 'glean_dev')
    CREATE LOGIN glean_dev WITH PASSWORD = '$(GLEAN_DEV_PASSWORD)';
GO

USE ems;
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = 'glean_dev')
    CREATE USER glean_dev FOR LOGIN glean_dev;
GO

/* Least privilege: SELECT on the four in-scope views only. */
GRANT SELECT ON dbo.v_Attendee       TO glean_dev;
GRANT SELECT ON dbo.v_Attendee_Event TO glean_dev;
GRANT SELECT ON dbo.v_Company        TO glean_dev;
GRANT SELECT ON dbo.v_Participation  TO glean_dev;
GO

PRINT 'grants.sql applied: glean_dev has SELECT on the 4 EMS views (dev only).';
GO
