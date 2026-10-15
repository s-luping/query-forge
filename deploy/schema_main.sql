-- -*- coding: UTF-8 -*-
-- 主库建表 DDL（queryforge.db，MainBase）
-- 本文件由 scripts/gen_schema_sql.py 自动生成，请勿手改；
-- 修改表结构请改 models/ 下的 ORM 定义后重新生成。

-- ── conversation_messages ──
CREATE TABLE conversation_messages (
	id INTEGER NOT NULL, 
	conversation_id INTEGER NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	sql TEXT, 
	is_valid BOOLEAN, 
	error_message TEXT, 
	columns TEXT, 
	result_data TEXT, 
	llm_call_id INTEGER, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id)
);
CREATE INDEX ix_conversation_messages_conversation_id ON conversation_messages (conversation_id);
CREATE INDEX ix_conversation_messages_llm_call_id ON conversation_messages (llm_call_id);

-- ── conversations ──
CREATE TABLE conversations (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(200), 
	schema_id INTEGER, 
	db_type VARCHAR(20), 
	llm_config_id INTEGER, 
	knowledge_id INTEGER, 
	knowledge_ids TEXT, 
	schema_tables TEXT, 
	context_prompt_id INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(schema_id) REFERENCES db_schemas (id), 
	FOREIGN KEY(knowledge_id) REFERENCES knowledge_items (id)
);
CREATE INDEX ix_conversations_schema_id ON conversations (schema_id);
CREATE INDEX ix_conversations_user_id ON conversations (user_id);

-- ── data_sources ──
CREATE TABLE data_sources (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	db_type VARCHAR(30) NOT NULL, 
	host VARCHAR(200), 
	port INTEGER, 
	"database" VARCHAR(200), 
	username VARCHAR(100), 
	password_enc TEXT, 
	extra_params TEXT, 
	status VARCHAR(20), 
	last_error TEXT, 
	last_tested_at DATETIME, 
	created_by INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);

-- ── db_columns ──
CREATE TABLE db_columns (
	id INTEGER NOT NULL, 
	table_id INTEGER NOT NULL, 
	ordinal INTEGER, 
	name VARCHAR(150) NOT NULL, 
	data_type VARCHAR(100), 
	description TEXT, 
	is_nullable BOOLEAN, 
	default_value VARCHAR(200), 
	column_key VARCHAR(10), 
	foreign_key VARCHAR(200), 
	sample_values TEXT, 
	sensitive_level VARCHAR(20), 
	is_dimension BOOLEAN, 
	is_measure BOOLEAN, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_column_table_name UNIQUE (table_id, name), 
	FOREIGN KEY(table_id) REFERENCES db_tables (id)
);
CREATE INDEX ix_db_columns_sensitive_level ON db_columns (sensitive_level);
CREATE INDEX ix_db_columns_table_id ON db_columns (table_id);

-- ── db_schemas ──
CREATE TABLE db_schemas (
	id INTEGER NOT NULL, 
	owner_user_id INTEGER, 
	datasource_id INTEGER, 
	name VARCHAR(100) NOT NULL, 
	db_type VARCHAR(30), 
	description TEXT, 
	source VARCHAR(30), 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(datasource_id) REFERENCES data_sources (id), 
	UNIQUE (name)
);
CREATE INDEX ix_db_schemas_datasource_id ON db_schemas (datasource_id);
CREATE INDEX ix_db_schemas_owner_user_id ON db_schemas (owner_user_id);

-- ── db_table_relations ──
CREATE TABLE db_table_relations (
	id INTEGER NOT NULL, 
	schema_id INTEGER, 
	left_schema_id INTEGER NOT NULL, 
	right_schema_id INTEGER NOT NULL, 
	left_table VARCHAR(150) NOT NULL, 
	left_column VARCHAR(150) NOT NULL, 
	right_table VARCHAR(150) NOT NULL, 
	right_column VARCHAR(150) NOT NULL, 
	join_type VARCHAR(20), 
	relation_type VARCHAR(20), 
	description TEXT, 
	created_by INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_relation_both_sides UNIQUE (left_schema_id, left_table, left_column, right_schema_id, right_table, right_column), 
	FOREIGN KEY(schema_id) REFERENCES db_schemas (id), 
	FOREIGN KEY(left_schema_id) REFERENCES db_schemas (id), 
	FOREIGN KEY(right_schema_id) REFERENCES db_schemas (id)
);
CREATE INDEX ix_db_table_relations_left_schema_id ON db_table_relations (left_schema_id);
CREATE INDEX ix_db_table_relations_right_schema_id ON db_table_relations (right_schema_id);
CREATE INDEX ix_db_table_relations_schema_id ON db_table_relations (schema_id);

-- ── db_tables ──
CREATE TABLE db_tables (
	id INTEGER NOT NULL, 
	schema_id INTEGER NOT NULL, 
	name VARCHAR(150) NOT NULL, 
	description TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_table_schema_name UNIQUE (schema_id, name), 
	FOREIGN KEY(schema_id) REFERENCES db_schemas (id)
);
CREATE INDEX ix_db_tables_schema_id ON db_tables (schema_id);

-- ── knowledge_items ──
CREATE TABLE knowledge_items (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(200), 
	content TEXT, 
	knowledge_type VARCHAR(50), 
	aliases TEXT, 
	payload TEXT, 
	scope_schema_id INTEGER, 
	is_active INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_knowledge_items_scope_schema_id ON knowledge_items (scope_schema_id);
CREATE INDEX ix_knowledge_items_user_id ON knowledge_items (user_id);

-- ── llm_configs ──
CREATE TABLE llm_configs (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	provider VARCHAR(50) NOT NULL, 
	model VARCHAR(100) NOT NULL, 
	api_key TEXT NOT NULL, 
	base_url VARCHAR(500), 
	max_tokens INTEGER, 
	temperature FLOAT, 
	timeout INTEGER, 
	is_default BOOLEAN, 
	is_active BOOLEAN, 
	is_public BOOLEAN, 
	description TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_llm_configs_user_id ON llm_configs (user_id);

-- ── llm_usage_stats ──
CREATE TABLE llm_usage_stats (
	id INTEGER NOT NULL, 
	stat_date DATE NOT NULL, 
	user_id INTEGER NOT NULL, 
	provider VARCHAR(50), 
	model VARCHAR(100) NOT NULL, 
	call_count INTEGER, 
	success_count INTEGER, 
	prompt_tokens INTEGER, 
	completion_tokens INTEGER, 
	total_tokens INTEGER, 
	cost FLOAT, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_usage_day_user_model UNIQUE (stat_date, user_id, model)
);
CREATE INDEX ix_llm_usage_stats_stat_date ON llm_usage_stats (stat_date);
CREATE INDEX ix_llm_usage_stats_user_id ON llm_usage_stats (user_id);

-- ── role_permissions ──
CREATE TABLE role_permissions (
	id INTEGER NOT NULL, 
	role_id INTEGER NOT NULL, 
	permission_code VARCHAR(120) NOT NULL, 
	resource_type VARCHAR(30) NOT NULL, 
	resource_id INTEGER, 
	resource_key VARCHAR(255), 
	access_type VARCHAR(10) NOT NULL, 
	filter_expression TEXT, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_role_permission_resource UNIQUE (role_id, permission_code, resource_type, resource_id), 
	FOREIGN KEY(role_id) REFERENCES roles (id)
);
CREATE INDEX ix_role_permissions_permission_code ON role_permissions (permission_code);
CREATE INDEX ix_role_permissions_resource_id ON role_permissions (resource_id);
CREATE INDEX ix_role_permissions_resource_key ON role_permissions (resource_key);
CREATE INDEX ix_role_permissions_role_id ON role_permissions (role_id);

-- ── roles ──
CREATE TABLE roles (
	id INTEGER NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	code VARCHAR(80) NOT NULL, 
	description VARCHAR(255), 
	is_system INTEGER NOT NULL, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);
CREATE UNIQUE INDEX ix_roles_code ON roles (code);

-- ── scheduler_jobs ──
CREATE TABLE scheduler_jobs (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	handler VARCHAR(100) NOT NULL, 
	schedule_type VARCHAR(20), 
	cron_expr VARCHAR(100), 
	interval_seconds INTEGER, 
	params TEXT, 
	status VARCHAR(20), 
	is_system BOOLEAN, 
	misfire_grace_time INTEGER, 
	max_instances INTEGER, 
	description VARCHAR(300), 
	last_run_at DATETIME, 
	last_run_status VARCHAR(20), 
	last_run_duration_ms INTEGER, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_scheduler_job_name UNIQUE (name)
);
CREATE INDEX ix_scheduler_jobs_handler ON scheduler_jobs (handler);
CREATE INDEX ix_scheduler_jobs_status ON scheduler_jobs (status);

-- ── sync_job_configs ──
CREATE TABLE sync_job_configs (
	id INTEGER NOT NULL, 
	datasource_id INTEGER NOT NULL, 
	target_schema_name VARCHAR(100) NOT NULL, 
	sync_mode VARCHAR(20), 
	schedule_type VARCHAR(20), 
	schedule_value VARCHAR(100), 
	is_enabled BOOLEAN, 
	auto_classify BOOLEAN, 
	include_tables TEXT, 
	exclude_tables TEXT, 
	last_synced_at DATETIME, 
	last_sync_status VARCHAR(20), 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_sync_job_ds_schema UNIQUE (datasource_id, target_schema_name), 
	FOREIGN KEY(datasource_id) REFERENCES data_sources (id)
);
CREATE INDEX ix_sync_job_configs_datasource_id ON sync_job_configs (datasource_id);

-- ── system_settings ──
CREATE TABLE system_settings (
	id INTEGER NOT NULL, 
	"key" VARCHAR(100) NOT NULL, 
	value TEXT, 
	category VARCHAR(30), 
	is_editable INTEGER, 
	updated_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_system_settings_key ON system_settings ("key");

-- ── user_roles ──
CREATE TABLE user_roles (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	role_id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uix_user_role UNIQUE (user_id, role_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(role_id) REFERENCES roles (id)
);
CREATE INDEX ix_user_roles_role_id ON user_roles (role_id);
CREATE INDEX ix_user_roles_user_id ON user_roles (user_id);

-- ── users ──
CREATE TABLE users (
	id INTEGER NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	password VARCHAR(255) NOT NULL, 
	email VARCHAR(100), 
	role VARCHAR(20), 
	description VARCHAR(255), 
	is_active INTEGER, 
	pwd_ts FLOAT, 
	register_date DATETIME, 
	last_login DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (username)
);

-- ── vector_index_meta ──
CREATE TABLE vector_index_meta (
	id INTEGER NOT NULL, 
	schema_name VARCHAR(100) NOT NULL, 
	status VARCHAR(20), 
	field_count INTEGER, 
	table_count INTEGER, 
	dimension INTEGER, 
	file_path VARCHAR(500), 
	error_message TEXT, 
	built_at DATETIME, 
	created_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_vector_index_meta_schema_name ON vector_index_meta (schema_name);
