# -*- coding: UTF-8 -*-
"""同步引擎 — 编排连接 → 读取 → diff → 应用 → 记录

变更应用策略：
    add（新增表/字段）    → 自动应用 + 自动分类敏感等级
    modify（修改字段）    → 自动应用（类型/注释/约束等同步更新）
    remove（删除表/字段） → 不自动删除，记录为 pending，待管理员审批
"""
import json
import time
from typing import List, Optional, Tuple

from app.crypto import decrypt_secret
from app.logger import logger
from app.timezone import now_beijing
from crud.base import tx_scope
from models.datasource import DataSource
from models.schema import DbColumn, DbSchema, DbTable
from models.sync import SchemaChangeLog, SyncJobConfig, SyncRunLog
from services.schema_service import invalidate_schema_cache
from services.sync_classify import classify_column
from services.sync_connectors import BaseConnector, get_connector
from services.sync_diff import ChangeRecord, diff_metadata


class SyncEngine:
    """同步引擎 — 执行一次完整的元数据同步"""

    def __init__(self, job: SyncJobConfig, datasource: DataSource,
                 triggered_by: str = 'scheduler'):
        self.job = job
        self.datasource = datasource
        self.triggered_by = triggered_by
        self._connector: Optional[BaseConnector] = None
        self._run_log: Optional[SyncRunLog] = None

    # ── 公共入口 ──────────────────────────────────────────────────

    def run(self) -> SyncRunLog:
        """执行同步，返回 SyncRunLog

        跨库事务说明：执行记录/变更记录在日志库（logs.db），元数据与任务
        状态在主库（queryforge.db），两者无分布式事务，按「日志先行落库、
        主库独立提交」顺序执行；主库失败时回滚主库，日志库 run_log 标记
        failed（与原失败路径一致）。
        """
        start = time.time()
        try:
            # 1. 创建执行记录（日志库，独立事务先拿主键）
            with tx_scope(logs=True) as ldb:
                run_log = SyncRunLog(
                    job_id=self.job.id,
                    triggered_by=self.triggered_by,
                    started_at=now_beijing(),
                    status='running',
                )
                ldb.add(run_log)
                ldb.commit()
                ldb.refresh(run_log)
                self._run_log = run_log

            # 2. 解密密码 + 创建连接器
            password = decrypt_secret(self.datasource.password_enc)
            self._connector = get_connector(
                self.datasource.db_type,
                host=self.datasource.host,
                port=self.datasource.port,
                database=self.datasource.database,
                username=self.datasource.username,
                password=password,
                extra_params=self.datasource.extra_params,
            )

            # 3. 读取源库元数据
            include_tables = _parse_csv(self.job.include_tables)
            exclude_tables = _parse_csv(self.job.exclude_tables)
            source_tables = self._connector.read_metadata(
                include_tables=include_tables or None,
                exclude_tables=exclude_tables or None,
            )
            logger.info(f"同步[{self.job.target_schema_name}]: 源库读取 {len(source_tables)} 张表")

            # 4-6. 主库事务：读取/创建元数据 → Diff → 应用变更
            with tx_scope() as db:
                stored_schema, stored_tables, stored_cols_map = self._get_stored_metadata(db)
                if stored_schema is None:
                    stored_schema = self._create_target_schema(db)

                # 5. Diff
                changes = diff_metadata(source_tables, stored_tables, stored_cols_map)
                logger.info(f"同步[{self.job.target_schema_name}]: 检测到 {len(changes)} 条变更")

                # 6. 应用变更
                stats = self._apply_changes(db, stored_schema, changes)

            # 7. 记录变更日志（日志库）
            self._log_changes(run_log.id, changes)

            # 8. 完成执行记录（日志库）
            run_log.finished_at = now_beijing()
            run_log.status = 'success'
            run_log.tables_total = len(source_tables)
            run_log.tables_synced = stats['tables_touched']
            run_log.columns_added = stats['columns_added']
            run_log.columns_modified = stats['columns_modified']
            run_log.columns_removed = stats['columns_removed']
            run_log.changes_auto = stats['changes_auto']
            run_log.changes_pending = stats['changes_pending']
            run_log.duration_ms = int((time.time() - start) * 1000)
            run_log.summary = json.dumps({
                'source_tables': len(source_tables),
                'changes': len(changes),
                **stats,
            }, ensure_ascii=False)
            with tx_scope(logs=True) as ldb:
                ldb.merge(self._run_log)
                ldb.commit()

            # 9. 更新任务状态（主库）
            with tx_scope() as db:
                self.job.last_synced_at = now_beijing()
                self.job.last_sync_status = 'success'
                db.merge(self.job)
                db.commit()

            # 10. 触发索引重建
            self._trigger_index_rebuild(stored_schema.name)

            logger.info(f"同步完成: {run_log.summary}")
            return run_log

        except Exception as e:
            logger.error(f"同步失败: {e}", exc_info=True)
            now = now_beijing()
            if self._run_log:
                self._run_log.status = 'failed'
                self._run_log.error_message = str(e)[:2000]
                self._run_log.finished_at = now
                self._run_log.duration_ms = int((time.time() - start) * 1000)
            # 失败同样推进尝试时间：否则任务保持"到期"状态，会被 10 分钟巡检
            # 反复重试（失败重试风暴）。下次重试时间为 now + interval。
            self.job.last_synced_at = now
            self.job.last_sync_status = 'failed'
            try:
                # 主库：任务失败状态
                with tx_scope() as db:
                    db.merge(self.job)
                    db.commit()
                # 日志库：执行记录失败状态（merge 而非 add：run_log 可能已
                # 在步骤1提交（有主键），add 会按新行 INSERT 导致主键冲突）
                if self._run_log is not None:
                    with tx_scope(logs=True) as ldb:
                        ldb.merge(self._run_log)
                        ldb.commit()
            except Exception as e2:
                logger.error(f"同步失败状态落库异常: {e2}", exc_info=True)
            return self._run_log
        finally:
            if self._connector:
                self._connector.close()
            # 无论成功/失败都可能已写入部分元数据变更，统一失效读缓存
            invalidate_schema_cache()

    # ── 内部方法 ──────────────────────────────────────────────────

    def _get_stored_metadata(self, db) -> Tuple[Optional[DbSchema], List[DbTable], dict]:
        """获取目标 schema 的存储元数据"""
        schema = db.query(DbSchema).filter(
            DbSchema.name == self.job.target_schema_name
        ).first()

        if not schema:
            return None, [], {}

        # 兼容历史手动导入的同名库：首次通过同步任务维护时补齐数据源关联，
        # 这样数据浏览页和仪表盘可以正确按数据源分组展示。
        changed = False
        if schema.datasource_id != self.datasource.id:
            schema.datasource_id = self.datasource.id
            changed = True
        if not schema.db_type and self.datasource.db_type:
            schema.db_type = self.datasource.db_type
            changed = True
        if changed:
            db.commit()

        tables = db.query(DbTable).filter(
            DbTable.schema_id == schema.id
        ).all()

        # 一次性加载所有列（避免 N+1 查询）
        all_cols = db.query(DbColumn).filter(
            DbColumn.table_id.in_([t.id for t in tables])
        ).order_by(DbColumn.ordinal).all()
        cols_map: dict[int, list[DbColumn]] = {}
        for col in all_cols:
            cols_map.setdefault(col.table_id, []).append(col)

        return schema, tables, cols_map

    def _create_target_schema(self, db) -> DbSchema:
        """创建目标 schema（如不存在）；关联数据源，db_type 取自数据源"""
        schema = DbSchema(
            name=self.job.target_schema_name,
            db_type=self.datasource.db_type,
            datasource_id=self.datasource.id,
            source='sync',
            description=f'自动同步自数据源: {self.datasource.name}',
        )
        db.add(schema)
        db.commit()
        db.refresh(schema)
        logger.info(f"创建目标 schema: {schema.name}")
        return schema

    def _apply_changes(self, db, schema: DbSchema,
                       changes: List[ChangeRecord]) -> dict:
        """应用变更到三层表"""
        stats = {
            'tables_touched': 0,
            'columns_added': 0,
            'columns_modified': 0,
            'columns_removed': 0,
            'changes_auto': 0,
            'changes_pending': 0,
        }

        # 构建 table_name → DbTable 映射（用于列操作）
        table_map: dict[str, DbTable] = {
            t.name: t for t in db.query(DbTable).filter(
                DbTable.schema_id == schema.id
            ).all()
        }

        touched_tables = set()

        for ch in changes:
            if ch.change_type == 'add':
                if ch.object_type == 'table':
                    # 新增表
                    new_val = json.loads(ch.new_value)
                    if ch.object_name not in table_map:
                        table = DbTable(
                            schema_id=schema.id,
                            name=ch.object_name,
                            description=new_val.get('description', ''),
                        )
                        db.add(table)
                        db.flush()
                        table_map[ch.object_name] = table
                        touched_tables.add(ch.object_name)
                        stats['changes_auto'] += 1

                elif ch.object_type == 'column':
                    table_name, col_name = ch.object_name.rsplit('.', 1)
                    table = table_map.get(table_name)
                    if table is None:
                        logger.warning(f"字段新增跳过（表不存在）: {ch.object_name}")
                        continue

                    # 检查是否已存在（防重复）
                    existing = db.query(DbColumn).filter(
                        DbColumn.table_id == table.id,
                        DbColumn.name == col_name,
                    ).first()
                    if existing:
                        continue

                    new_val = json.loads(ch.new_value)
                    # 自动分类敏感等级
                    auto_level = 'public'
                    if self.job.auto_classify:
                        auto_level = classify_column(col_name)

                    db.add(DbColumn(
                        table_id=table.id,
                        ordinal=new_val.get('ordinal', 0) or len(
                            db.query(DbColumn).filter(DbColumn.table_id == table.id).all()
                        ),
                        name=col_name,
                        data_type=new_val.get('data_type', ''),
                        description=new_val.get('description', ''),
                        is_nullable=new_val.get('is_nullable', True),
                        default_value=new_val.get('default_value', ''),
                        column_key=new_val.get('column_key', ''),
                        foreign_key=new_val.get('foreign_key', ''),
                        sensitive_level=auto_level,
                    ))
                    touched_tables.add(table_name)
                    stats['columns_added'] += 1
                    stats['changes_auto'] += 1
                    ch.auto_classified_level = auto_level

            elif ch.change_type == 'modify':
                if ch.object_type == 'table':
                    table = table_map.get(ch.object_name)
                    if table:
                        new_val = json.loads(ch.new_value)
                        if new_val.get('description'):
                            table.description = new_val['description']
                        touched_tables.add(ch.object_name)
                        stats['changes_auto'] += 1

                elif ch.object_type == 'column':
                    table_name, col_name = ch.object_name.rsplit('.', 1)
                    table = table_map.get(table_name)
                    if table is None:
                        continue
                    col = db.query(DbColumn).filter(
                        DbColumn.table_id == table.id,
                        DbColumn.name == col_name,
                    ).first()
                    if col is None:
                        continue

                    new_val = json.loads(ch.new_value)

                    # 更新字段属性
                    col.data_type = new_val.get('data_type', col.data_type)
                    # 注释：源库有值才覆盖
                    if new_val.get('description'):
                        col.description = new_val['description']
                    col.is_nullable = new_val.get('is_nullable', col.is_nullable)
                    col.default_value = new_val.get('default_value', col.default_value)
                    col.column_key = new_val.get('column_key', col.column_key)
                    col.foreign_key = new_val.get('foreign_key', col.foreign_key)

                    touched_tables.add(table_name)
                    stats['columns_modified'] += 1
                    # 类型变更 = 高风险，但仍然自动应用（记录变更供回溯）
                    stats['changes_auto'] += 1

            elif ch.change_type == 'remove':
                # 删除类变更不自动执行，记录为 pending
                if ch.object_type == 'table':
                    stats['columns_removed'] += len(
                        db.query(DbColumn).filter(
                            DbColumn.table_id == table_map[ch.object_name].id
                        ).all()
                    ) if ch.object_name in table_map else 0
                elif ch.object_type == 'column':
                    stats['columns_removed'] += 1
                stats['changes_pending'] += 1

        db.commit()
        stats['tables_touched'] = len(touched_tables)
        return stats

    def _log_changes(self, run_log_id: int, changes: List[ChangeRecord]):
        """记录变更日志（日志库独立会话）"""
        with tx_scope(logs=True) as ldb:
            for ch in changes:
                log_entry = SchemaChangeLog(
                    run_log_id=run_log_id,
                    job_id=self.job.id,
                    datasource_id=self.datasource.id,
                    target_schema_name=self.job.target_schema_name,
                    change_type=ch.change_type,
                    object_type=ch.object_type,
                    object_name=ch.object_name,
                    old_value=ch.old_value,
                    new_value=ch.new_value,
                    auto_classified_level=getattr(ch, 'auto_classified_level', ''),
                    approval_status='pending' if ch.is_high_risk else 'auto_applied',
                )
                ldb.add(log_entry)
            ldb.commit()

    def _trigger_index_rebuild(self, schema_name: str):
        """同步后标记向量索引过期（懒重建，不立即全量构建）

        对话为全库模式（统一 fields 索引），同步任一库都影响全库索引。
        策略：只标记 stale，下次对话召回时检测到 stale 再后台重建（原子写，
        重建期间旧索引继续服务），避免每次同步都触发耗时全量重建。
        """
        try:
            from services.vector_service import mark_index_stale
            mark_index_stale('default')
            logger.info(f"同步后已标记全库向量索引过期: {schema_name}")
        except Exception as e:
            logger.warning(f"索引过期标记失败: {e}")


def _parse_csv(s: str) -> List[str]:
    """逗号分隔字符串 → 列表"""
    if not s:
        return []
    return [x.strip() for x in s.split(',') if x.strip()]
