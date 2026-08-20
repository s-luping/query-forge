# -*- coding: UTF-8 -*-
"""crud.vector — 向量索引元数据数据访问

用法：
    from crud.vector import vector_index_crud
    meta = vector_index_crud.get_by_schema('sales')
"""
from typing import Optional

from crud.base import BaseCrud
from models.vector_index import VectorIndexMeta


class VectorIndexCrud(BaseCrud):
    model = VectorIndexMeta

    def get_by_schema(self, schema_name: str) -> Optional[VectorIndexMeta]:
        return self.get_one(schema_name=schema_name)

    def list_ready(self) -> list:
        return self.list(status='ready')


vector_index_crud = VectorIndexCrud()
