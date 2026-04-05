-- QuantGambit PostgreSQL infrastructure bootstrap
-- App schemas are owned by explicit golden schemas and startup preflight/apply scripts.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'platform') THEN
        CREATE ROLE platform WITH LOGIN PASSWORD 'platform_pw';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quantgambit') THEN
        CREATE ROLE quantgambit WITH LOGIN PASSWORD 'quantgambit_pw';
    END IF;
END $$;

SELECT 'CREATE DATABASE platform_db OWNER platform'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'platform_db')
\gexec

SELECT 'CREATE DATABASE quantgambit_bot OWNER quantgambit'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'quantgambit_bot')
\gexec

GRANT ALL PRIVILEGES ON DATABASE deeptrader TO deeptrader_user;
GRANT ALL PRIVILEGES ON DATABASE platform_db TO platform;
GRANT ALL PRIVILEGES ON DATABASE quantgambit_bot TO quantgambit;
