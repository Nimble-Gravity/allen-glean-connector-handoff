/* ============================================================================
 * Mock EMS schema for the Allen & Co Glean connector dev environment.
 *
 * Creates a small event-management schema (Allen & Co runs conferences) and the
 * FOUR read-only views the connector indexes:
 *   v_Attendee, v_Attendee_Event, v_Company, v_Participation
 *
 * The view columns intentionally match the placeholder columns used by the
 * connector's per-view builders (src/allenco_connector/views/*/document_builder.py):
 *   v_Attendee        → AttendeeID, FirstName, LastName
 *   v_Attendee_Event  → AttendeeEventID, EventName, AttendeeID
 *   v_Company         → CompanyID, CompanyName
 *   v_Participation   → ParticipationID, CompanyID, AttendeeID
 *
 * Each view also exposes ModifiedDate — the change-tracking column the connector
 * uses for INCREMENTAL sync (WATERMARK_COLUMN in views/*/query.py).
 *
 * ⚠️ This is a MOCK for local Docker + the Azure dev mirror. When Allen & Co
 * confirms the real EMS schema, update this file and the document builders (and
 * confirm the real change-tracking column, if any).
 *
 * Idempotent: safe to re-run. Run first, then grants.sql.
 * ============================================================================ */

IF DB_ID('ems') IS NULL
    CREATE DATABASE ems;
GO

USE ems;
GO

/* ---------------------------------------------------------------- base tables */
IF OBJECT_ID('dbo.Company') IS NULL
CREATE TABLE dbo.Company (
    CompanyID    INT           NOT NULL PRIMARY KEY,
    CompanyName  NVARCHAR(200) NOT NULL,
    Industry     NVARCHAR(100) NULL,
    City         NVARCHAR(100) NULL,
    [State]      NVARCHAR(50)  NULL,
    ModifiedDate DATETIME2     NULL
);
GO

IF OBJECT_ID('dbo.Attendee') IS NULL
CREATE TABLE dbo.Attendee (
    AttendeeID   INT           NOT NULL PRIMARY KEY,
    FirstName    NVARCHAR(100) NOT NULL,
    LastName     NVARCHAR(100) NOT NULL,
    Email        NVARCHAR(200) NULL,
    Title        NVARCHAR(150) NULL,
    CompanyID    INT           NULL REFERENCES dbo.Company(CompanyID),
    ModifiedDate DATETIME2     NULL
);
GO

IF OBJECT_ID('dbo.[Event]') IS NULL
CREATE TABLE dbo.[Event] (
    EventID   INT           NOT NULL PRIMARY KEY,
    EventName NVARCHAR(200) NOT NULL,
    EventDate DATE          NULL,
    Location  NVARCHAR(150) NULL
);
GO

IF OBJECT_ID('dbo.AttendeeEvent') IS NULL
CREATE TABLE dbo.AttendeeEvent (
    AttendeeEventID INT          NOT NULL PRIMARY KEY,
    AttendeeID      INT          NOT NULL REFERENCES dbo.Attendee(AttendeeID),
    EventID         INT          NOT NULL REFERENCES dbo.[Event](EventID),
    [Status]        NVARCHAR(50) NULL,
    RegisteredDate  DATE         NULL,
    ModifiedDate    DATETIME2    NULL
);
GO

IF OBJECT_ID('dbo.Participation') IS NULL
CREATE TABLE dbo.Participation (
    ParticipationID INT            NOT NULL PRIMARY KEY,
    CompanyID       INT            NOT NULL REFERENCES dbo.Company(CompanyID),
    AttendeeID      INT            NULL REFERENCES dbo.Attendee(AttendeeID),
    EventID         INT            NULL REFERENCES dbo.[Event](EventID),
    [Role]          NVARCHAR(100)  NULL,
    Amount          DECIMAL(18, 2) NULL,
    ModifiedDate    DATETIME2      NULL
);
GO

/* ---------------------------------------------------------------- sample data */
IF NOT EXISTS (SELECT 1 FROM dbo.Company)
INSERT INTO dbo.Company (CompanyID, CompanyName, Industry, City, [State], ModifiedDate) VALUES
    (1001, N'Meridian Capital Partners', N'Financial Services', N'New York',    N'NY', '2026-05-01T09:00:00'),
    (1002, N'Northwind Media Group',     N'Media',              N'Los Angeles', N'CA', '2026-05-02T09:00:00'),
    (1003, N'Cascade Technologies',      N'Technology',         N'Seattle',     N'WA', '2026-05-03T09:00:00'),
    (1004, N'Sunrise Biosciences',       N'Healthcare',         N'Boston',      N'MA', '2026-05-04T09:00:00');
GO

IF NOT EXISTS (SELECT 1 FROM dbo.Attendee)
INSERT INTO dbo.Attendee (AttendeeID, FirstName, LastName, Email, Title, CompanyID, ModifiedDate) VALUES
    (2001, N'Ada',       N'Lovelace', N'ada.lovelace@meridiancap.com',    N'Managing Director', 1001, '2026-05-05T10:00:00'),
    (2002, N'Alan',      N'Turing',   N'alan.turing@cascadetech.com',     N'CEO',               1003, '2026-05-06T10:00:00'),
    (2003, N'Grace',     N'Hopper',   N'grace.hopper@northwindmedia.com', N'President',         1002, '2026-05-07T10:00:00'),
    (2004, N'Katherine', N'Johnson',  N'k.johnson@sunrisebio.com',        N'CFO',               1004, '2026-05-08T10:00:00'),
    (2005, N'Edsger',    N'Dijkstra', N'e.dijkstra@cascadetech.com',      N'CTO',               1003, '2026-05-09T10:00:00');
GO

IF NOT EXISTS (SELECT 1 FROM dbo.[Event])
INSERT INTO dbo.[Event] (EventID, EventName, EventDate, Location) VALUES
    (3001, N'Sun Valley Conference 2026', '2026-07-08', N'Sun Valley, ID'),
    (3002, N'Winter Media Summit 2026',   '2026-01-20', N'Aspen, CO');
GO

IF NOT EXISTS (SELECT 1 FROM dbo.AttendeeEvent)
INSERT INTO dbo.AttendeeEvent (AttendeeEventID, AttendeeID, EventID, [Status], RegisteredDate, ModifiedDate) VALUES
    (4001, 2001, 3001, N'Confirmed', '2026-05-01', '2026-05-10T11:00:00'),
    (4002, 2002, 3001, N'Confirmed', '2026-05-03', '2026-05-11T11:00:00'),
    (4003, 2003, 3002, N'Confirmed', '2025-12-10', '2026-05-12T11:00:00'),
    (4004, 2004, 3001, N'Invited',   '2026-05-15', '2026-05-13T11:00:00'),
    (4005, 2005, 3001, N'Confirmed', '2026-05-04', '2026-05-14T11:00:00');
GO

IF NOT EXISTS (SELECT 1 FROM dbo.Participation)
INSERT INTO dbo.Participation (ParticipationID, CompanyID, AttendeeID, EventID, [Role], Amount, ModifiedDate) VALUES
    (5001, 1001, 2001, 3001, N'Sponsor',   250000.00, '2026-05-15T12:00:00'),
    (5002, 1003, 2002, 3001, N'Presenter', 0.00,      '2026-05-16T12:00:00'),
    (5003, 1002, 2003, 3002, N'Sponsor',   120000.00, '2026-05-17T12:00:00'),
    (5004, 1004, 2004, 3001, N'Attendee',  0.00,      '2026-05-18T12:00:00');
GO

/* ---------------------------------------------------------------------- views */
CREATE OR ALTER VIEW dbo.v_Company AS
    SELECT CompanyID, CompanyName, Industry, City, [State], ModifiedDate
    FROM dbo.Company;
GO

CREATE OR ALTER VIEW dbo.v_Attendee AS
    SELECT a.AttendeeID, a.FirstName, a.LastName, a.Email, a.Title,
           a.CompanyID, c.CompanyName, a.ModifiedDate
    FROM dbo.Attendee a
    LEFT JOIN dbo.Company c ON c.CompanyID = a.CompanyID;
GO

CREATE OR ALTER VIEW dbo.v_Attendee_Event AS
    SELECT ae.AttendeeEventID, ae.AttendeeID, ae.EventID,
           e.EventName, e.EventDate, ae.[Status], ae.RegisteredDate, ae.ModifiedDate
    FROM dbo.AttendeeEvent ae
    JOIN dbo.[Event] e ON e.EventID = ae.EventID;
GO

CREATE OR ALTER VIEW dbo.v_Participation AS
    SELECT p.ParticipationID, p.CompanyID, p.AttendeeID, p.EventID,
           p.[Role], p.Amount, p.ModifiedDate
    FROM dbo.Participation p;
GO

PRINT 'mirror_schema.sql applied: ems database, 4 EMS views (with ModifiedDate), and sample data ready.';
GO
