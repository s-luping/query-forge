-- -*- coding: UTF-8 -*-
-- 遥测库建表 DDL（llm_telemetry.db，TelemetryBase）
-- 本文件由 scripts/gen_schema_sql.py 自动生成，请勿手改；
-- 修改表结构请改 models/ 下的 ORM 定义后重新生成。

-- ── llm_calls ──
CREATE TABLE llm_calls (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	conversation_id INTEGER, 
	message_id INTEGER, 
	config_id INTEGER, 
	provider VARCHAR(50), 
	model VARCHAR(100) NOT NULL, 
	purpose VARCHAR(20), 
	question TEXT, 
	conditions TEXT, 
	prompt_id INTEGER, 
	result TEXT, 
	duration_ms FLOAT, 
	prompt_tokens INTEGER, 
	completion_tokens INTEGER, 
	reasoning_tokens INTEGER, 
	total_tokens INTEGER, 
	cost FLOAT, 
	status VARCHAR(20), 
	error_message TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_llm_calls_conversation_id ON llm_calls (conversation_id);
CREATE INDEX ix_llm_calls_created_at ON llm_calls (created_at);
CREATE INDEX ix_llm_calls_message_id ON llm_calls (message_id);
CREATE INDEX ix_llm_calls_prompt_id ON llm_calls (prompt_id);
CREATE INDEX ix_llm_calls_purpose ON llm_calls (purpose);
CREATE INDEX ix_llm_calls_status ON llm_calls (status);
CREATE INDEX ix_llm_calls_user_id ON llm_calls (user_id);

-- ── llm_prompts ──
CREATE TABLE llm_prompts (
	id INTEGER NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	content TEXT NOT NULL, 
	length INTEGER, 
	created_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_llm_prompts_content_hash ON llm_prompts (content_hash);
