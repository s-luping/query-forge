# -*- coding: UTF-8 -*-
"""
向量存储模块 - 使用 sentence-transformers (纯Python实现，无需FAISS)
模型路径: D:\projects\QueryForge\models\embeddings\bge-m3
"""
import os
import threading

os.environ.setdefault('HF_ENDPOINT', 'https://modelscope.cn')

import pickle
import numpy as np
from typing import List, Dict, Tuple, Optional
from app.logger import logger


PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, 'models', 'embeddings')
VECTOR_INDEX_DIR = os.path.join(PROJECT_ROOT, 'db', 'vectors')


class EmbeddingModel:
    """Sentence-Transformers 模型封装 (BGE-M3)"""

    _instance = None
    _dimension = 1024
    _model_name = 'bge-m3'
    _lock = threading.Lock()

    @classmethod
    def get_local_model_path(cls, model_name: str = None) -> Optional[str]:
        model_name = model_name or cls._model_name
        possible_paths = [
            os.path.join(MODEL_CACHE_DIR, model_name, 'BAAI', model_name),
            os.path.join(MODEL_CACHE_DIR, model_name),
            os.path.join(MODEL_CACHE_DIR, f'BAAI/{model_name}'.replace('/', os.sep)),
        ]
        for local_path in possible_paths:
            if os.path.exists(local_path):
                config_file = os.path.join(local_path, 'config.json')
                if os.path.exists(config_file):
                    logger.info(f"找到本地模型: {local_path}")
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
                            raise RuntimeError(f"未找到本地模型，请先运行 download_model.py 下载模型")

                        cls._dimension = cls._instance.get_sentence_embedding_dimension()
                        logger.info(f"模型加载完成，维度: {cls._dimension}")

                    except ImportError:
                        raise ImportError("sentence-transformers 未安装，请运行: pip install sentence-transformers")
                    except Exception as e:
                        raise RuntimeError(f"加载模型失败: {e}")

        return cls._instance

    @classmethod
    def get_dimension(cls) -> int:
        return cls._dimension

    @classmethod
    def encode(cls, texts: List[str]) -> np.ndarray:
        model = cls.get_instance()
        if model is None:
            raise RuntimeError("Embedding 模型未加载，请先运行 download_model.py 下载模型")
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

        data = {
            'dimension': self.dimension,
            'vectors': self.vectors,
            'documents': self.documents,
            'metadata': self.metadata
        }
        with open(filepath + '.pkl', 'wb') as f:
            pickle.dump(data, f)
        logger.info(f"向量索引已保存: {filepath}")

    def load(self, filepath: str) -> bool:
        pkl_path = filepath + '.pkl'

        if not os.path.exists(pkl_path):
            return False

        with open(pkl_path, 'rb') as f:
            data = pickle.load(f)

        self.dimension = data['dimension']
        self.vectors = data.get('vectors')
        self.documents = data['documents']
        self.metadata = data['metadata']
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

    VECTOR_INDEX_THRESHOLD = 50

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.dimension = EmbeddingModel.get_dimension()
        self.vector_dir = os.path.join(VECTOR_INDEX_DIR, f'user_{user_id}')
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
            'user_id': self.user_id,
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
