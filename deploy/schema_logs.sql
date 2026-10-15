-- -*- coding: UTF-8 -*-
-- 日志库建表 DDL（logs.db，LogsBase）
-- 本文件由 scripts/gen_schema_sql.py 自动生成，请勿手改；
-- 修改表结构请改 models/ 下的 ORM 定义后重新生成。

-- ── query_audit_logs ──
CREATE TABLE query_audit_logs (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	username VARCHAR(50), 
	"query" TEXT NOT NULL, 
	generated_sql TEXT, 
	modified_sql TEXT, 
	tables_accessed TEXT, 
	columns_accessed TEXT, 
	hit_sensitive BOOLEAN, 
	was_blocked BOOLEAN, 
	block_reason VARCHAR(500), 
	pipeline_log TEXT, 
	duration_ms INTEGER, 
	created_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_query_audit_logs_created_at ON query_audit_logs (created_at);
CREATE INDEX ix_query_audit_logs_hit_sensitive ON query_audit_logs (hit_sensitive);
CREATE INDEX ix_query_audit_logs_user_id ON query_audit_logs (user_id);
CREATE INDEX ix_query_audit_logs_was_blocked ON query_audit_logs (was_blocked);

-- ── schema_change_logs ──
CREATE TABLE schema_change_logs (
	id INTEGER NOT NULL, 
	run_log_id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	datasource_id INTEGER NOT NULL, 
	target_schema_name VARCHAR(100) NOT NULL, 
	change_type VARCHAR(20) NOT NULL, 
	object_type VARCHAR(20) NOT NULL, 
	object_name VARCHAR(300) NOT NULL, 
	old_value TEXT, 
	new_value TEXT, 
	auto_classified_level VARCHAR(20), 
	approval_status VARCHAR(20), 
	approved_by INTEGER, 
	approved_at DATETIME, 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_log_id) REFERENCES sync_run_logs (id)
);
CREATE INDEX ix_schema_change_logs_approval_status ON schema_change_logs (approval_status);
CREATE INDEX ix_schema_change_logs_change_type ON schema_change_logs (change_type);
CREATE INDEX ix_schema_change_logs_created_at ON schema_change_logs (created_at);
CREATE INDEX ix_schema_change_logs_datasource_id ON schema_change_logs (datasource_id);
CREATE INDEX ix_schema_change_logs_job_id ON schema_change_logs (job_id);
CREATE INDEX ix_schema_change_logs_run_log_id ON schema_change_logs (run_log_id);

-- ── sync_run_logs ──
CREATE TABLE sync_run_logs (
	id INTEGER NOT NULL, 
	job_id INTEGER NOT NULL, 
	triggered_by VARCHAR(50), 
	started_at DATETIME, 
	finished_at DATETIME, 
	status VARCHAR(20), 
	tables_total INTEGER, 
	tables_synced INTEGER, 
	columns_added INTEGER, 
	columns_modified INTEGER, 
	columns_removed INTEGER, 
	changes_auto INTEGER, 
	changes_pending INTEGER, 
	error_message TEXT, 
	duration_ms INTEGER, 
	summary TEXT, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_sync_run_logs_job_id ON sync_run_logs (job_id);
