CREATE TABLE IF NOT EXISTS bot_configs (
    tenant_id TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    config JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, bot_id, version)
);

CREATE INDEX IF NOT EXISTS bot_configs_latest_idx
ON bot_configs (tenant_id, bot_id, version DESC);
