# -*- coding: UTF-8 -*-
"""
向量索引构建器
"""
import os
import hashlib
import numpy as np
from typing import List, Dict, Any, Optional

from app.logger import logger
from core.VectorStore import FieldVectorStore, MetricVectorStore, ValueVectorStore
from core.VectorIndexBuilder import VECTOR_INDEX_THRESHOLD
from models import SchemaSessionLocal
from models.schema import Schema

_embedding_model = None
_embedding_dimension = 768


def _get_embedding_model():
    """获取本地 Embedding 模型（懒加载）"""
    global _embedding_model, _embedding_dimension
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = 'paraphrase-multilingual-MiniLM-L12-v2'
            logger.info(f"加载本地 Embedding 模型: {model_name}")
            _embedding_model = SentenceTransformer(model_name)
            _embedding_dimension = _embedding_model.get_sentence_embedding_dimension()
            logger.info(f"模型加载完成，维度: {_embedding_dimension}")
        except ImportError:
            logger.warning("sentence-transformers 未安装，使用 hash 算法")
            _embedding_model = "hash"
            _embedding_dimension = 1024
    return _embedding_model


class VectorIndexBuilder:
    """向量索引构建器"""

    def __init__(self, user_id: int):
        """
        初始化向量索引构建器
        :param user_id: 用户ID
        """
        self.user_id = user_id
        model = _get_embedding_model()
        if model == "hash":
            self.dimension = 1024
        else:
            self.dimension = _embedding_dimension
        self.vector_dir = os.path.join('db', 'vectors', f'user_{self.user_id}')
        os.makedirs(self.vector_dir, exist_ok=True)

    def _get_embedding(self, text: str) -> np.ndarray:
        """获取文本的向量表示"""
        if not text or not text.strip():
            return np.zeros(self.dimension, dtype='float32')

        model = _get_embedding_model()
        if model == "hash":
            return self._get_hash_embedding(text)

        try:
            embedding = model.encode(text, convert_to_numpy=True)
            return embedding.astype('float32')
        except Exception as e:
            logger.warning(f"Embedding 失败: {e}，使用 hash 算法")
            return self._get_hash_embedding(text)

    def _get_hash_embedding(self, text: str) -> np.ndarray:
        """使用 hash 算法生成向量（备用方案）"""
        text = text.strip().lower()
        vector = np.zeros(self.dimension, dtype='float32')

        words = text.split()
        for word in words:
            hash_val = int(hashlib.md5(word.encode()).hexdigest()[:8], 16)
            idx = hash_val % self.dimension
            weight = len(word) / 10.0
            vector[idx] += weight

        for i in range(self.dimension):
            hash_input = f"{text}_{i}".encode('utf-8')
            hash_val = int(hashlib.sha256(hash_input).hexdigest()[:8], 16)
            vector[i] += (hash_val % 1000) / 1000.0

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        return vector.astype('float32')

    def _get_embeddings(self, texts: List[str]) -> List[np.ndarray]:
        """批量获取文本向量"""
        if not texts:
            return []

        model = _get_embedding_model()
        if model == "hash":
            return [self._get_hash_embedding(text) for text in texts]

        try:
            embeddings = model.encode(texts, convert_to_numpy=True)
            return [e.astype('float32') for e in embeddings]
        except Exception as e:
            logger.warning(f"批量 Embedding 失败: {e}，使用 hash 算法")
            return [self._get_hash_embedding(text) for text in texts]

    def should_build_index(self, schema_name: Optional[str] = None) -> bool:
        """判断是否需要构建向量索引（字段数超过阈值）"""
        count = self.get_field_count(schema_name)
        return count >= VECTOR_INDEX_THRESHOLD

    def get_field_count(self, schema_name: Optional[str] = None) -> int:
        """获取字段数量"""
        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)
            return query.count()
        finally:
            db.close()

    def build_indexes(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """构建所有向量索引"""
        logger.info(f"开始为用户 {self.user_id} 构建向量索引（FAISS本地）...")

        field_count = self.get_field_count(schema_name)
        if field_count == 0:
            logger.warning("没有找到Schema数据，跳过索引构建")
            return {'success': False, 'message': '没有Schema数据', 'field_count': 0}

        result = {
            'success': True,
            'field_count': field_count,
            'indexes': {}
        }

        result['indexes']['fields'] = self._build_field_index(schema_name)
        result['indexes']['metrics'] = self._build_metric_index(schema_name)
        result['indexes']['values'] = self._build_value_index(schema_name)

        logger.info(f"向量索引构建完成: 字段数={field_count}")
        return result

    def _build_field_index(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """构建字段向量索引"""
        logger.info("开始构建字段向量索引...")

        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)

            items = query.all()
            if not items:
                return {'success': False, 'count': 0}

            field_store = FieldVectorStore()
            texts = []
            field_data = []

            for item in items:
                text = f"{item.table_name}.{item.column_name}: {item.column_description or ''}"
                texts.append(text)
                field_data.append({
                    'field_name': item.column_name,
                    'field_description': item.column_description or '',
                    'table_name': item.table_name,
                    'column_type': item.column_type or ''
                })

            vectors = self._get_embeddings(texts)

            for i, data in enumerate(field_data):
                field_store.add_field(
                    field_name=data['field_name'],
                    field_description=data['field_description'],
                    table_name=data['table_name'],
                    column_type=data['column_type'],
                    vector=vectors[i]
                )

            filepath = self._get_filepath(schema_name, 'fields')
            field_store.save(filepath)
            logger.info(f"字段向量索引已保存: {filepath}, 共 {len(items)} 个字段")

            return {'success': True, 'count': len(items), 'filepath': filepath}
        finally:
            db.close()

    def _build_metric_index(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """构建指标向量索引"""
        logger.info("开始构建指标向量索引...")

        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)

            items = query.all()
            if not items:
                return {'success': False, 'count': 0}

            metric_store = MetricVectorStore()
            metric_keywords = ['金额', '价格', '数量', '计数', '总和', '平均', '最大', '最小',
                               '总计', '利润', '成本', '销售额', 'amount', 'price', 'count',
                               'sum', 'avg', 'total']

            texts = []
            metric_data = []

            for item in items:
                field_name = item.column_name.lower()
                field_desc = (item.column_description or '').lower()
                if any(kw in field_name or kw in field_desc for kw in metric_keywords):
                    texts.append(f"{item.column_name}: {item.column_description or ''} (表 {item.table_name})")
                    metric_data.append({
                        'metric_name': item.column_name,
                        'metric_description': item.column_description or '',
                        'table_name': item.table_name
                    })

            if not texts:
                return {'success': True, 'count': 0, 'message': '未检测到指标字段'}

            vectors = self._get_embeddings(texts)

            for i, data in enumerate(metric_data):
                metric_store.add_metric(
                    metric_name=data['metric_name'],
                    metric_description=data['metric_description'],
                    table_name=data['table_name'],
                    vector=vectors[i]
                )

            filepath = self._get_filepath(schema_name, 'metrics')
            metric_store.save(filepath)
            logger.info(f"指标向量索引已保存: {filepath}, 共 {len(texts)} 个指标")

            return {'success': True, 'count': len(texts), 'filepath': filepath}
        finally:
            db.close()

    def _build_value_index(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """构建字段值向量索引"""
        logger.info("开始构建字段值向量索引...")

        db = SchemaSessionLocal()
        try:
            query = db.query(Schema).filter(Schema.user_id == self.user_id)
            if schema_name:
                query = query.filter(Schema.schema_name == schema_name)

            items = query.all()
            if not items:
                return {'success': False, 'count': 0}

            value_store = ValueVectorStore()
            texts = []
            value_data = []

            for item in items:
                if item.sample_values:
                    for value in [v.strip() for v in item.sample_values.split(',') if v.strip()][:10]:
                        texts.append(f"{item.table_name}.{item.column_name} = {value}")
                        value_data.append({
                            'field_name': item.column_name,
                            'value': value,
                            'table_name': item.table_name
                        })

            if not texts:
                return {'success': True, 'count': 0, 'message': '没有示例值数据'}

            vectors = self._get_embeddings(texts)

            for i, data in enumerate(value_data):
                value_store.add_value(
                    field_name=data['field_name'],
                    value=data['value'],
                    table_name=data['table_name'],
                    vector=vectors[i]
                )

            filepath = self._get_filepath(schema_name, 'values')
            value_store.save(filepath)
            logger.info(f"字段值向量索引已保存: {filepath}, 共 {len(texts)} 个值")

            return {'success': True, 'count': len(texts), 'filepath': filepath}
        finally:
            db.close()

    def _get_filepath(self, schema_name: Optional[str], index_type: str) -> str:
        """获取索引文件路径"""
        filename = f'{schema_name}_{index_type}.pkl' if schema_name else f'{index_type}.pkl'
        return os.path.join(self.vector_dir, filename)

    def rebuild_indexes(self, schema_name: Optional[str] = None) -> Dict[str, Any]:
        """重建所有向量索引"""
        logger.info(f"开始为用户 {self.user_id} 重建向量索引...")
        self._clear_indexes(schema_name)
        result = self.build_indexes(schema_name)
        logger.info(f"向量索引重建完成")
        return result

    def _clear_indexes(self, schema_name: Optional[str] = None):
        """清除向量索引文件"""
        import glob
        if schema_name:
            patterns = [os.path.join(self.vector_dir, f'{schema_name}_{t}{ext}')
                       for t in ['fields', 'metrics', 'values'] for ext in ['.pkl', '.pkl.index']]
        else:
            patterns = glob.glob(os.path.join(self.vector_dir, '*.pkl'))
            patterns.extend(glob.glob(os.path.join(self.vector_dir, '*.pkl.index')))

        for filepath in patterns:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"已删除索引文件: {filepath}")

    def get_index_info(self, schema_name: Optional[str] = None) -> dict:
        """获取向量索引信息"""
        info = {
            'user_id': self.user_id,
            'vector_dir': self.vector_dir,
            'field_count': self.get_field_count(schema_name),
            'should_build_index': self.should_build_index(schema_name),
            'threshold': VECTOR_INDEX_THRESHOLD,
            'indexes': {}
        }

        for index_type in ['fields', 'metrics', 'values']:
            filepath = self._get_filepath(schema_name, index_type)
            info['indexes'][index_type] = {
                'exists': os.path.exists(filepath),
                'filepath': filepath,
                **({'size': os.path.getsize(filepath)} if os.path.exists(filepath) else {})
            }

        return info

    def ensure_index_exists(self, schema_name: Optional[str] = None) -> bool:
        """确保索引存在，不存在且字段数超过阈值则自动创建"""
        info = self.get_index_info(schema_name)
        if all(idx['exists'] for idx in info['indexes'].values()):
            return False

        if info['should_build_index']:
            logger.info(f"字段数量 {info['field_count']} 超过阈值，自动创建向量索引")
            self.build_indexes(schema_name)
            return True

        return False


def build_user_indexes(user_id: int, schema_name: Optional[str] = None) -> Dict[str, Any]:
    """为用户构建向量索引"""
    return VectorIndexBuilder(user_id).build_indexes(schema_name)


def rebuild_user_indexes(user_id: int, schema_name: Optional[str] = None) -> Dict[str, Any]:
    """为用户重建向量索引"""
    return VectorIndexBuilder(user_id).rebuild_indexes(schema_name)


def check_and_build_index(user_id: int, schema_name: Optional[str] = None) -> Dict[str, Any]:
    """检查并在需要时自动构建向量索引"""
    builder = VectorIndexBuilder(user_id)
    info = builder.get_index_info(schema_name)

    if all(idx['exists'] for idx in info['indexes'].values()):
        return {'action': 'none', 'message': '索引已存在', 'info': info}

    if info['should_build_index']:
        result = builder.build_indexes(schema_name)
        return {'action': 'built', 'message': f'已自动创建索引（字段数: {info["field_count"]}）',
                'info': info, 'build_result': result}

    return {'action': 'skipped', 'message': f'字段数未达阈值 {VECTOR_INDEX_THRESHOLD}', 'info': info}
