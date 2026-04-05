-- Bootstrap databases and users for dashboard vs bot workloads.
-- Run as a superuser (e.g., postgres).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'quantgambit_dashboard_user') THEN
        CREATE ROLE quantgambit_dashboard_user LOGIN PASSWORD 'change_me_dashboard';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'quantgambit_bot_user') THEN
        CREATE ROLE quantgambit_bot_user LOGIN PASSWORD 'change_me_bot';
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'quantgambit_dashboard') THEN
        CREATE DATABASE quantgambit_dashboard OWNER quantgambit_dashboard_user;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'quantgambit_bot') THEN
        CREATE DATABASE quantgambit_bot OWNER quantgambit_bot_user;
    END IF;
END$$;

-- Example grants (run inside each database if needed):
-- GRANT CONNECT ON DATABASE quantgambit_dashboard TO quantgambit_dashboard_user;
-- GRANT CONNECT ON DATABASE quantgambit_bot TO quantgambit_bot_user;
