# -*- coding: UTF-8 -*-
"""crud.conversation — 对话与消息数据访问

用法：
    from crud.conversation import conversation_crud, message_crud
    conv = conversation_crud.get_owned(1, user_id=3)
"""
from typing import List, Optional, Tuple

from crud.base import BaseCrud, session_scope
from models.conversation import Conversation, ConversationMessage


class ConversationCrud(BaseCrud):
    model = Conversation

    def get_owned(self, conversation_id: int, user_id: int) -> Optional[Conversation]:
        """按归属校验获取对话（防止越权访问他人对话）"""
        return self.get_one(id=conversation_id, user_id=user_id)

    def list_by_user(self, user_id: int) -> List[Conversation]:
        return self.list(user_id=user_id, order_by='updated_at', desc=True)

    def list_all(self) -> List[Conversation]:
        return self.list(order_by='updated_at', desc=True)

    def count_by_user(self, user_id: int) -> int:
        return self.count(user_id=user_id)

    def list_paged(self, user_id: Optional[int], is_admin: bool = False,
                   limit: int = 20, offset: int = 0,
                   search: Optional[str] = None
                   ) -> Tuple[List[Conversation], int]:
        """分页对话列表 + 总数（一次会话，避免全量加载）

        Args:
            user_id: 用户 id；is_admin=True 时忽略（管理员看全部）
            limit: 每页条数
            offset: 偏移量
            search: 关键字（标题或任意消息内容模糊匹配，None/空串不过滤）

        Returns:
            (conversations, total)
        """
        with session_scope() as db:
            q = db.query(Conversation)
            if not is_admin:
                q = q.filter(Conversation.user_id == user_id)
            if search:
                kw = f"%{search.strip()}%"
                has_hit_msg = db.query(ConversationMessage.id).filter(
                    ConversationMessage.conversation_id == Conversation.id,
                    ConversationMessage.content.like(kw)
                ).exists()
                q = q.filter(Conversation.title.like(kw) | has_hit_msg)
            total = q.count()
            conversations = (q.order_by(Conversation.updated_at.desc())
                             .offset(offset).limit(limit).all())
            for c in conversations:
                db.expunge(c)
            return conversations, total

    def list_with_message_counts(self, user_id: Optional[int],
                                 is_admin: bool = False) -> List[Tuple[Conversation, int]]:
        """对话列表 + 各对话消息数（一次 GROUP BY 聚合，避免 N+1 count）"""
        from sqlalchemy import func
        with session_scope() as db:
            q = db.query(Conversation)
            if not is_admin:
                q = q.filter(Conversation.user_id == user_id)
            conversations = q.order_by(Conversation.updated_at.desc()).all()
            for c in conversations:
                db.expunge(c)
            conv_ids = [c.id for c in conversations]
            msg_counts = dict(db.query(ConversationMessage.conversation_id,
                                       func.count(ConversationMessage.id))
                              .filter(ConversationMessage.conversation_id.in_(conv_ids))
                              .group_by(ConversationMessage.conversation_id).all()) if conv_ids else {}
            return [(c, msg_counts.get(c.id, 0)) for c in conversations]

    def bind_telemetry(self, conversation_id: int, message_id: int,
                       call_id: Optional[int], prompt_id: Optional[int]) -> None:
        """回填 LLM 遥测关联键（消息 llm_call_id / 对话 context_prompt_id）"""
        with session_scope() as db:
            if call_id:
                db.query(ConversationMessage).filter(
                    ConversationMessage.id == message_id
                ).update({'llm_call_id': call_id})
            if prompt_id:
                db.query(Conversation).filter(
                    Conversation.id == conversation_id
                ).update({'context_prompt_id': prompt_id})


class MessageCrud(BaseCrud):
    model = ConversationMessage

    def list_by_conversation(self, conversation_id: int) -> List[ConversationMessage]:
        return self.list(conversation_id=conversation_id,
                         order_by='created_at')

    def count_by_conversation(self, conversation_id: int) -> int:
        return self.count(conversation_id=conversation_id)

    def delete_by_conversation(self, conversation_id: int) -> int:
        return self.delete_by(conversation_id=conversation_id)


conversation_crud = ConversationCrud()
message_crud = MessageCrud()
