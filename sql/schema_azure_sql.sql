-- =============================================================================
-- OPTISTACK DATABASE - AZURE SQL DATABASE SCHEMA (T-SQL)
-- Arquitectura: Azure IoT Hub -> Azure Functions -> Azure ML (Extreme Points 3D)
--               -> Azure SQL Database <-> Azure App Service (HMI 3D Dashboard)
-- =============================================================================

-- 1. Tabla Maestra de Camiones / Furgones (CRUD de Flota con medidas personalizadas)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[TruckMaster]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[TruckMaster] (
        [TruckID]        INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [TruckPlate]     NVARCHAR(30)  NOT NULL UNIQUE,
        [TruckName]      NVARCHAR(120) NOT NULL,
        [LengthCm]       FLOAT         NOT NULL CHECK ([LengthCm] > 0),
        [WidthCm]        FLOAT         NOT NULL CHECK ([WidthCm] > 0),
        [HeightCm]       FLOAT         NOT NULL CHECK ([HeightCm] > 0),
        [MaxWeightKg]    FLOAT         NOT NULL CHECK ([MaxWeightKg] > 0),
        [EmptyWeightKg]  FLOAT         NOT NULL DEFAULT 0,
        [IsActive]       BIT           NOT NULL DEFAULT 1,
        [CreatedAt]      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

-- 2. Tabla Maestra de Rutas / Agencias Destino (CRUD + Carga Masiva Excel)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[AgencyMaster]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[AgencyMaster] (
        [AgencyID]       NVARCHAR(40)  NOT NULL PRIMARY KEY,
        [AgencyName]     NVARCHAR(120) NOT NULL,
        [RouteCode]      NVARCHAR(60)  NOT NULL,
        [ZoneOrder]      INT           NOT NULL DEFAULT 1, -- Prioridad LIFO (1 = Fondo/Última parada, N = Puerta/Primera parada)
        [City]           NVARCHAR(100) NULL,
        [ColorHex]       NVARCHAR(12)  NOT NULL DEFAULT '#38BDF8',
        [IsActive]       BIT           NOT NULL DEFAULT 1,
        [CreatedAt]      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
    );
END
GO

-- 3. Tabla de Mapas de Estiba / Sesiones de Carga (StowageMaps)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[StowageMaps]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[StowageMaps] (
        [StowageMapID]   INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [MapCode]        NVARCHAR(50)  NOT NULL UNIQUE,
        [TruckID]        INT           NOT NULL,
        [TruckPlate]     NVARCHAR(30)  NOT NULL,
        [TruckName]      NVARCHAR(120) NOT NULL,
        [RouteSummary]   NVARCHAR(200) NULL,
        [LengthCm]       FLOAT         NOT NULL,
        [WidthCm]        FLOAT         NOT NULL,
        [HeightCm]       FLOAT         NOT NULL,
        [MaxWeightKg]    FLOAT         NOT NULL,
        [Status]         NVARCHAR(25)  NOT NULL DEFAULT 'IN_PROGRESS', -- IN_PROGRESS, COMPLETED, ARCHIVED
        [CreatedAt]      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [FK_StowageMaps_TruckMaster] FOREIGN KEY ([TruckID]) REFERENCES [dbo].[TruckMaster]([TruckID])
    );
END
GO

-- 4. Tabla de Datos de Paquetes y Coordenadas 3D (PackageData)
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id = OBJECT_ID(N'[dbo].[PackageData]') AND type in (N'U'))
BEGIN
    CREATE TABLE [dbo].[PackageData] (
        [PackageID]      INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        [GuideID]        NVARCHAR(60)  NOT NULL,
        [StowageMapID]   INT           NOT NULL,
        [LengthCm]       FLOAT         NOT NULL CHECK ([LengthCm] > 0),
        [WidthCm]        FLOAT         NOT NULL CHECK ([WidthCm] > 0),
        [HeightCm]       FLOAT         NOT NULL CHECK ([HeightCm] > 0),
        [WeightKg]       FLOAT         NOT NULL CHECK ([WeightKg] > 0),
        [TargetAgencyID] NVARCHAR(40)  NOT NULL,
        [CoordX]         FLOAT         NOT NULL DEFAULT 0, -- Posición longitudinal (0 = Fondo cabina -> LengthCm = Puerta)
        [CoordY]         FLOAT         NOT NULL DEFAULT 0, -- Posición vertical (0 = Piso -> HeightCm = Techo)
        [CoordZ]         FLOAT         NOT NULL DEFAULT 0, -- Posición transversal (0 = Pared Izq -> WidthCm = Pared Der)
        [PlacedLengthCm] FLOAT         NOT NULL,           -- Dimensión en eje X tras rotación óptima
        [PlacedWidthCm]  FLOAT         NOT NULL,           -- Dimensión en eje Z tras rotación óptima
        [PlacedHeightCm] FLOAT         NOT NULL,           -- Dimensión en eje Y
        [RotationState]  NVARCHAR(20)  NOT NULL DEFAULT 'LWH',
        [SequenceOrder]  INT           NOT NULL,
        [SourceDevice]   NVARCHAR(60)  NOT NULL DEFAULT 'IoT-RPi-Scanner-01',
        [ScannedAt]      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT [FK_PackageData_StowageMaps] FOREIGN KEY ([StowageMapID]) REFERENCES [dbo].[StowageMaps]([StowageMapID]) ON DELETE CASCADE,
        CONSTRAINT [FK_PackageData_AgencyMaster] FOREIGN KEY ([TargetAgencyID]) REFERENCES [dbo].[AgencyMaster]([AgencyID])
    );

    CREATE INDEX [IX_PackageData_StowageMap_Seq] ON [dbo].[PackageData] ([StowageMapID], [SequenceOrder]);
    CREATE UNIQUE INDEX [UX_PackageData_Map_Guide] ON [dbo].[PackageData] ([StowageMapID], [GuideID]);
END
GO
