-- Run only in PostgreSQL with an account allowed to create extensions.
CREATE EXTENSION IF NOT EXISTS postgis;
-- Current MVP stores portable GeoJSON in JSON text; geodesic calculations run in pyproj.
-- Future spatial indexes can use generated geometry columns in a reviewed additive migration.
