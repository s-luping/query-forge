# -*- coding: UTF-8 -*-
"""
向量存储模块 - 使用 sentence-transformers (纯Python实现，无需FAISS)
模型路径: D:\projects\QueryForge\models\embeddings\bge-m3
"""
import os
import threading
import json

os.environ.setdefault('HF_ENDPOINT', 'https://modelscope.cn')

import numpy as np
from typing import List, Dict, Tuple, Optional
from app.logger import logger
from crud.base import session_scope


# core/retrieval/vector_store.py → 上溯 3 级到项目根
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, 'models', 'embeddings')
VECTOR_INDEX_DIR = os.path.join(PROJECT_ROOT, 'db', 'vectors')

# 默认向量参数（数据库无配置时使用）
_DEFAULT_VECTOR_CONFIG = {
    'VECTOR_INDEX_THRESHOLD': 50,
    'FIELD_RECALL_TOP_K': 20,
    'MAX_TABLES': 10,
}


def get_vector_config(key: str):
    """从数据库读取向量参数，不存在则返回默认值"""
    try:
        from models.system import SystemSetting
        with session_scope() as db:
            row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
            if row is not None and str(row.value).strip():
                return int(str(row.value))
    except Exception:
        pass
    return _DEFAULT_VECTOR_CONFIG.get(key, 0)


class EmbeddingModel:
    """Sentence-Transformers 模型封装 (BGE-M3)"""

    _instance = None
    _dimension = 1024
    _model_name = 'bge-m3'
    _lock = threading.Lock()

    @classmethod
    def _set_db_ready(cls, ready: bool):
        """更新数据库中的模型就绪状态"""
        try:
            from models.system import SystemSetting
            with session_scope() as db:
                row = db.query(SystemSetting).filter(SystemSetting.key == 'EMBEDDING_MODEL_READY').first()
                value = 'true' if ready else 'false'
                if row:
                    row.value = value
                else:
                    db.add(SystemSetting(key='EMBEDDING_MODEL_READY', value=value))
                if not ready:
                    path_row = db.query(SystemSetting).filter(SystemSetting.key == 'EMBEDDING_MODEL_PATH').first()
                    if path_row:
                        path_row.value = ''
                db.commit()
        except Exception as e:
            logger.warning(f"更新 EMBEDDING_MODEL_READY 状态失败: {e}")

    @classmethod
    def _get_db_path(cls) -> Optional[str]:
        """从数据库读取缓存的模型路径"""
        try:
            from models.system import SystemSetting
            with session_scope() as db:
                row = db.query(SystemSetting).filter(SystemSetting.key == 'EMBEDDING_MODEL_PATH').first()
                if row and str(row.value):
                    return str(row.value)
        except Exception:
            pass
        return None

    @classmethod
    def _set_db_path(cls, path: str):
        """缓存模型路径到数据库"""
        try:
            from models.system import SystemSetting
            with session_scope() as db:
                row = db.query(SystemSetting).filter(SystemSetting.key == 'EMBEDDING_MODEL_PATH').first()
                if row:
                    row.value = path
                else:
                    db.add(SystemSetting(key='EMBEDDING_MODEL_PATH', value=path))
                db.commit()
        except Exception as e:
            logger.warning(f"缓存模型路径失败: {e}")

    @classmethod
    def is_ready(cls) -> bool:
        """检查嵌入模型是否就绪（优先查数据库状态）"""
        try:
            from models.system import SystemSetting
            with session_scope() as db:
                row = db.query(SystemSetting).filter(SystemSetting.key == 'EMBEDDING_MODEL_READY').first()
                if row and str(row.value) == 'true':
                    return True
        except Exception:
            pass
        # 数据库查询失败时，降级检查文件系统
        return cls.get_local_model_path() is not None

    @classmethod
    def get_local_model_path(cls, model_name: str = None) -> Optional[str]:
        model_name = model_name or cls._model_name
        # 优先从数据库读取缓存的路径（快速）
        cached_path = cls._get_db_path()
        if cached_path and cached_path.strip() and os.path.exists(os.path.join(cached_path, 'config.json')):
            logger.info(f"从数据库缓存获取模型路径: {cached_path}")
            return cached_path
        # 缓存失效，扫描目录
        possible_paths = [
            os.path.join(MODEL_CACHE_DIR, model_name, 'BAAI', model_name),
            os.path.join(MODEL_CACHE_DIR, model_name),
            os.path.join(MODEL_CACHE_DIR, f'BAAI/{model_name}'.replace('/', os.sep)),
            # ModelScope snapshot_download(cache_dir=...)
            os.path.join(MODEL_CACHE_DIR, model_name, 'models', 'BAAI--bge-m3', 'snapshots', 'master'),
        ]
        for local_path in possible_paths:
            if os.path.exists(local_path):
                config_file = os.path.join(local_path, 'config.json')
                if os.path.exists(config_file):
                    logger.info(f"扫描目录找到本地模型: {local_path}")
                    cls._set_db_path(local_path)  # 缓存到数据库
                    return local_path
        return None

    @classmethod
    def get_instance(cls, model_name: str = 'bge-m3'):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    local_path = cls.get_local_model_path(model_name)

                    try:
                        from sentence_transformers import SentenceTransformer
                        logger.info(f"加载 Embedding 模型: {model_name}")

                        if local_path:
                            cls._instance = SentenceTransformer(local_path)
                            logger.info(f"从本地加载模型: {local_path}")
                        else:
                            cls._set_db_ready(False)
                            raise RuntimeError(f"未找到本地模型，请先运行 download_model.py 下载模型")

                        cls._dimension = cls._instance.get_sentence_embedding_dimension()
                        cls._set_db_path(local_path)  # 确保路径已缓存
                        cls._set_db_ready(True)
                        logger.info(f"模型加载完成，维度: {cls._dimension}")

                    except ImportError:
                        cls._set_db_ready(False)
                        raise ImportError("sentence-transformers 未安装，请运行: pip install sentence-transformers")
                    except Exception as e:
                        cls._set_db_ready(False)
                        raise RuntimeError(f"加载模型失败: {e}")

        return cls._instance

    @classmethod
    def get_dimension(cls) -> int:
        return cls._dimension

    @classmethod
    def encode(cls, texts: List[str]) -> np.ndarray:
        if not cls.is_ready():
            raise RuntimeError("Embedding 模型未就绪，请先在系统设置中下载模型")
        model = cls.get_instance()
        if model is None:
            raise RuntimeError("Embedding 模型加载失败")
        embeddings = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return embeddings.astype('float32')


class VectorIndex:
    """纯Python向量索引 - 使用numpy实现相似度搜索"""

    def __init__(self, dimension: int = 1024):
        self.dimension = dimension
        self.vectors: np.ndarray = None
        self.documents: List[str] = []
        self.metadata: List[Dict] = []

    def build(self, vectors: np.ndarray, documents: List[str], metadata: List[Dict]):
        if len(vectors) == 0:
            return

        self.vectors = np.array(vectors).astype('float32')
        self.documents = documents
        self.metadata = metadata
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self.vectors = self.vectors / norms
        logger.info(f"向量索引构建完成: {len(vectors)} 个向量")

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> List[Tuple[str, Dict, float]]:
        if self.vectors is None or len(self.vectors) == 0:
            return []

        query = np.array(query_vector).astype('float32')
        if query.ndim == 1:
            query = query.reshape(1, -1)
        query = query / np.linalg.norm(query)

        similarities = np.dot(self.vectors, query.T).flatten()
        top_k = min(top_k, len(similarities))
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            if idx < len(self.documents):
                distance = 1.0 - similarities[idx]
                results.append((
                    self.documents[idx],
                    self.metadata[idx],
                    float(distance)
                ))
        return results

    def save(self, filepath: str):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # 使用 np.savez 保存向量 + JSON 保存元数据，替代 pickle（消除 RCE 风险）
        npz_path = filepath + '.npz'
        meta_path = filepath + '.meta.json'

        # 向量数据用 numpy 二进制格式（高效且安全）
        vectors_arr = np.asarray(self.vectors) if self.vectors is not None else np.array([])
        np.savez(npz_path, vectors=vectors_arr)

        # 元数据用 JSON（文本格式，安全可读）
        meta = {
            'dimension': self.dimension,
            'documents': self.documents,
            'metadata': self.metadata,
        }
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)

        self._last_save_path = npz_path
        logger.info(f"向量索引已保存: {npz_path}")

    def load(self, filepath: str) -> bool:
        npz_path = filepath + '.npz'
        meta_path = filepath + '.meta.json'

        # 兼容旧版 pickle 文件（一次性迁移后可移除）
        pkl_path = filepath + '.pkl'
        if os.path.exists(pkl_path) and not os.path.exists(npz_path):
            logger.info("检测到旧版 pickle 格式索引，正在迁移...")
            import pickle as _pickle
            with open(pkl_path, 'rb') as f:
                data = _pickle.load(f)
            self.dimension = data['dimension']
            self.vectors = data.get('vectors')
            self.documents = data['documents']
            self.metadata = data['metadata']
            # 自动保存为新格式
            self.save(filepath)
            # 删除旧 pickle 文件
            os.remove(pkl_path)
            logger.info(f"迁移完成，旧 pickle 文件已删除: {pkl_path}")
            return True

        if not os.path.exists(npz_path) or not os.path.exists(meta_path):
            return False

        # 加载向量（numpy 二进制）
        data = np.load(npz_path, allow_pickle=False)
        self.vectors = data['vectors'].tolist() if data['vectors'].size > 0 else None

        # 加载元数据（JSON）
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)

        self.dimension = meta['dimension']
        self.documents = meta['documents']
        self.metadata = meta['metadata']
        logger.info(f"向量索引已加载: {len(self.documents)} 个向量")
        return True

    def clear(self):
        self.vectors = None
        self.documents = []
        self.metadata = []

    @property
    def is_built(self) -> bool:
        return self.vectors is not None and len(self.vectors) > 0

    @property
    def count(self) -> int:
        return len(self.documents)


class SchemaVectorStore:
    """Schema 向量存储 - 仅管理字段索引"""

    def __init__(self):
        self.dimension = EmbeddingModel.get_dimension()
        self.vector_dir = VECTOR_INDEX_DIR
        os.makedirs(self.vector_dir, exist_ok=True)

        self.field_index = VectorIndex(self.dimension)

    def build_from_schemas(self, schemas: List[Dict], schema_name: Optional[str] = None) -> Dict:
        if not schemas:
            return {'success': False, 'message': '没有数据'}

        field_texts, field_meta = [], []

        for s in schemas:
            table = s.get('table_name', '')
            column = s.get('column_name', '')
            desc = s.get('column_description', '') or ''
            col_type = s.get('column_type', '') or ''

            field_texts.append(f"{table}.{column}: {desc}")
            field_meta.append({
                'schema_name': s.get('schema_name', ''),
                'table_name': table,
                'field_name': column,
                'description': desc,
                'column_type': col_type,
                'sample_values': s.get('sample_values', '')
            })

        results = {'success': True, 'indexes': {}}

        if field_texts:
            vectors = EmbeddingModel.encode(field_texts)
            self.field_index.build(vectors, field_texts, field_meta)
            results['indexes']['fields'] = {'count': len(field_texts)}

        self.save(schema_name)
        results['field_count'] = len(schemas)
        logger.info(f"向量索引构建完成: 字段={len(field_texts)}")
        return results

    def search_fields(self, query: str, top_k: int = 10) -> List[Dict]:
        if not self.field_index.is_built:
            return []
        vector = EmbeddingModel.encode([query])[0]
        results = self.field_index.search(vector, top_k)
        return [meta for _, meta, _ in results]

    def save(self, schema_name: Optional[str] = None):
        prefix = f"{schema_name}_" if schema_name else ""
        self.field_index.save(os.path.join(self.vector_dir, f"{prefix}fields"))

    def load(self, schema_name: Optional[str] = None) -> bool:
        prefix = f"{schema_name}_" if schema_name else ""
        return self.field_index.load(os.path.join(self.vector_dir, f"{prefix}fields"))

    def is_ready(self) -> bool:
        return self.field_index.is_built

    def get_info(self, schema_name: Optional[str] = None) -> Dict:
        prefix = f"{schema_name}_" if schema_name else ""
        return {
            'dimension': self.dimension,
            'vector_dir': self.vector_dir,
            'fields': {
                'count': self.field_index.count,
                'is_built': self.field_index.is_built,
                'filepath': os.path.join(self.vector_dir, f"{prefix}fields")
            }
        }

    def clear(self):
        self.field_index.clear()
