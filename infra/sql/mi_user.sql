/* ============================================================================
 * Entra (Azure AD) database user for a MANAGED IDENTITY — Azure only.
 *
 * Enables the passwordless connector path (DB_AUTH_MODE=msi): the Container Apps
 * job/app (and the dev Windows VM) authenticate to Azure SQL with their managed
 * identity instead of a SQL login. This creates a contained DB user mapped to
 * that identity and grants SELECT on the in-scope EMS views (schema `rpt`).
 *
 * Run ONCE against the real EMS database, connected AS THE ENTRA ADMIN of the
 * server/instance (a SQL login cannot create external-provider users):
 *   sqlcmd -S <mi-host>.database.windows.net -d <ems-database> -G \
 *          -v MI_NAME="<managed-identity-display-name>" -i mi_user.sql
 *
 * NOT applicable to the local Docker SQL mock (no Entra, and its views are the
 * dbo placeholders v_Attendee/... — skip it there).
 * ============================================================================ */

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = '$(MI_NAME)')
    CREATE USER [$(MI_NAME)] FROM EXTERNAL PROVIDER;
GO

-- The five in-scope views (schema `rpt`); mirrors views/catalog.py (enabled=True).
GRANT SELECT ON rpt.v_EventInstance_Attendee      TO [$(MI_NAME)];
GRANT SELECT ON rpt.v_Catering_TableAssignment    TO [$(MI_NAME)];
GRANT SELECT ON rpt.v_Activity_Attendee_TimeRange TO [$(MI_NAME)];
GRANT SELECT ON rpt.v_TravelAir                   TO [$(MI_NAME)];
GRANT SELECT ON rpt.v_TravelGround                TO [$(MI_NAME)];
GO

-- Disabled in the catalog until the read replica can bind ConferenceImage
-- (SQL 4413). Uncomment each here when its view is enabled in views/catalog.py:
-- GRANT SELECT ON rpt.v_Attendee_Global           TO [$(MI_NAME)];
-- GRANT SELECT ON rpt.v_Invitation_CurrentStatus  TO [$(MI_NAME)];

PRINT 'mi_user.sql applied: managed identity has SELECT on the 5 in-scope rpt views.';
GO
