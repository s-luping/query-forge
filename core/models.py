from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime


class TextToSqlRequest(BaseModel):
    """文本转SQL请求模型"""
    query: str
    table_names: Optional[List[str]] = None
    knowledge_id: Optional[int] = None
    db_type: Optional[str] = "sqlite"
    schema_name: Optional[str] = None
    llm_config_id: Optional[int] = None


class SqlValidationResponse(BaseModel):
    """SQL验证响应模型"""
    is_valid: bool
    sql_query: str
    error_message: Optional[str] = None
    columns: Optional[List[str]] = None


class ChartDataResponse(BaseModel):
    """图表数据响应模型"""
    sql_query: str
    data: List[Dict[str, Any]]
    chart_type: str
    chart_config: Dict[str, Any]
    total_rows: int
    # 前端可选的可视化类型列表，始终包含'table'
    possible_chart_types: List[str] = []


class HistoricalSQLItem(BaseModel):
    """SQL历史记录项模型"""
    id: Optional[int] = None
    query: str
    sql_query: str
    is_valid: bool
    error_message: Optional[str] = None
    user_id: str
    created_at: Optional[datetime] = None
    rating: Optional[int] = None
    schema_name: Optional[str] = None
    knowledge_id: Optional[int] = None


class HistoricalSQLResponse(BaseModel):
    """SQL历史记录响应模型"""
    items: List[HistoricalSQLItem]
    total: int


class RatingRequest(BaseModel):
    """评分请求模型"""
    history_id: int
    rating: int  # 1-5分
