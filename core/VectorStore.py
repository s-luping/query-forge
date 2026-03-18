# d:\projects\py\query-forge\core\VectorStore.py
import os
import pickle
import numpy as np
import faiss
from typing import List, Dict, Tuple, Optional
from app.logger import logger


class VectorStore:
    """向量存储类 - 使用FAISS进行本地向量检索"""

    def __init__(self, dimension: int = 1024, index_type: str = "flat"):
        """
        初始化向量存储
        :param dimension: 向量维度（默认1024）
        :param index_type: 索引类型 (flat, ivf, hnsw)
        """
        self.dimension = dimension
        self.index_type = index_type
        self.index = None
        self.documents = []
        self.metadata = []
        self.is_built = False

    def build_index(self, vectors: np.ndarray):
        """构建FAISS索引"""
        if self.index_type == "flat":
            self.index = faiss.IndexFlatL2(self.dimension)
        elif self.index_type == "ivf":
            quantizer = faiss.IndexFlatL2(self.dimension)
            nlist = min(100, len(vectors) // 10)
            self.index = faiss.IndexIVFFlat(quantizer, self.dimension, nlist)
            self.index.train(vectors)
        elif self.index_type == "hnsw":
            self.index = faiss.IndexHNSWFlat(self.dimension, 32)
        else:
            self.index = faiss.IndexFlatL2(self.dimension)

        self.index.add(vectors)
        self.is_built = True
        logger.info(f"向量索引构建完成，索引类型: {self.index_type}, 向量数量: {len(vectors)}")

    def add_documents(self, vectors: np.ndarray, documents: List[str], metadata: List[Dict]):
        """添加文档到向量存储"""
        if len(vectors) != len(documents) or len(vectors) != len(metadata):
            raise ValueError("向量、文档和元数据的数量必须一致")

        if self.index is None:
            self.build_index(vectors)
        else:
            self.index.add(vectors)

        self.documents.extend(documents)
        self.metadata.extend(metadata)
        logger.info(f"添加了 {len(vectors)} 个文档到向量存储")

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> List[Tuple[str, Dict, float]]:
        """搜索最相似的文档"""
        if not self.is_built or self.index is None:
            logger.warning("向量索引未构建，无法搜索")
            return []

        query_vector = query_vector.reshape(1, -1).astype('float32')
        distances, indices = self.index.search(query_vector, top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.documents):
                results.append((
                    self.documents[idx],
                    self.metadata[idx],
                    float(distances[0][i])
                ))

        return results

    def save(self, filepath: str):
        """保存向量存储到文件"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        data = {
            'dimension': self.dimension,
            'index_type': self.index_type,
            'documents': self.documents,
            'metadata': self.metadata,
            'is_built': self.is_built
        }

        if self.index is not None:
            faiss.write_index(self.index, filepath + '.index')

        with open(filepath, 'wb') as f:
            pickle.dump(data, f)

        logger.info(f"向量存储已保存到: {filepath}")

    def load(self, filepath: str):
        """从文件加载向量存储"""
        if not os.path.exists(filepath):
            logger.warning(f"向量存储文件不存在: {filepath}")
            return False

        with open(filepath, 'rb') as f:
            data = pickle.load(f)

        self.dimension = data['dimension']
        self.index_type = data['index_type']
        self.documents = data['documents']
        self.metadata = data['metadata']
        self.is_built = data['is_built']

        if os.path.exists(filepath + '.index'):
            self.index = faiss.read_index(filepath + '.index')
            logger.info(f"向量索引已加载，包含 {self.index.ntotal} 个向量")
        else:
            self.index = None
            logger.warning("向量索引文件不存在")

        logger.info(f"向量存储已从 {filepath} 加载")
        return True

    def clear(self):
        """清空向量存储"""
        self.index = None
        self.documents = []
        self.metadata = []
        self.is_built = False
        logger.info("向量存储已清空")


class FieldVectorStore(VectorStore):
    """字段向量存储 - 用于字段信息检索"""

    def __init__(self, dimension: int = 1024):
        super().__init__(dimension, index_type="flat")

    def add_field(self, field_name: str, field_description: str, table_name: str,
                  column_type: str, vector: np.ndarray):
        """添加字段信息"""
        document = f"{table_name}.{field_name}: {field_description}"
        metadata = {
            'type': 'field',
            'field_name': field_name,
            'table_name': table_name,
            'column_type': column_type,
            'description': field_description
        }
        self.add_documents(vector.reshape(1, -1), [document], [metadata])


class MetricVectorStore(VectorStore):
    """指标向量存储 - 用于指标信息检索"""

    def __init__(self, dimension: int = 1024):
        super().__init__(dimension, index_type="flat")

    def add_metric(self, metric_name: str, metric_description: str,
                   table_name: str, vector: np.ndarray):
        """添加指标信息"""
        document = f"{metric_name}: {metric_description} (来自表 {table_name})"
        metadata = {
            'type': 'metric',
            'metric_name': metric_name,
            'table_name': table_name,
            'description': metric_description
        }
        self.add_documents(vector.reshape(1, -1), [document], [metadata])


class ValueVectorStore(VectorStore):
    """字段值向量存储 - 用于字段值检索"""

    def __init__(self, dimension: int = 1024):
        super().__init__(dimension, index_type="flat")

    def add_value(self, field_name: str, value: str, table_name: str,
                  vector: np.ndarray):
        """添加字段值"""
        document = f"{table_name}.{field_name} = {value}"
        metadata = {
            'type': 'value',
            'field_name': field_name,
            'table_name': table_name,
            'value': value
        }
        self.add_documents(vector.reshape(1, -1), [document], [metadata])
