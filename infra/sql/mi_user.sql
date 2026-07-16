/* ============================================================================
 * Entra (Azure AD) database user for a MANAGED IDENTITY — Azure only.
 *
 * Enables the passwordless connector path (DB_AUTH_MODE=msi): the Container Apps
 * job/app (and the dev Windows VM) authenticate to Azure SQL with their managed
 * identity instead of a SQL login. This creates a contained DB user mapped to
 * that identity and grants SELECT on the four in-scope views.
 *
 * Run ONCE against the Azure SQL Database, connected AS THE ENTRA ADMIN of the
 * logical server (a SQL login cannot create external-provider users):
 *   sqlcmd -S <server>.database.windows.net -d ems -G \
 *          -v MI_NAME="<managed-identity-display-name>" -i mi_user.sql
 *
 * NOT applicable to the local Docker SQL (no Entra) — skip it there.
 * ============================================================================ */

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$(MI_NAME)')
    CREATE USER [$(MI_NAME)] FROM EXTERNAL PROVIDER;
GO

GRANT SELECT ON dbo.v_Attendee       TO [$(MI_NAME)];
GRANT SELECT ON dbo.v_Attendee_Event TO [$(MI_NAME)];
GRANT SELECT ON dbo.v_Company        TO [$(MI_NAME)];
GRANT SELECT ON dbo.v_Participation  TO [$(MI_NAME)];
GO

PRINT 'mi_user.sql applied: managed identity has SELECT on the 4 EMS views.';
GO
