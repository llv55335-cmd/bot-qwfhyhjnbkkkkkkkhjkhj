"""
自动化记忆检索模块
负责：每次对话前自动检索相关记忆，注入AI上下文
"""

from __future__ import annotations
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

from memory.graph_store import GraphStore
from memory.retrieve import retrieve_related_memories


class AutoRetriever:
    """自动化记忆检索器"""
    
    def __init__(self):
        self.store = GraphStore()
        self.cache = {}  # 简单的缓存，避免重复检索相同query
        self.cache_ttl = 300  # 缓存5分钟
        
    async def retrieve_for_conversation(
        self,
        user_text: str,
        conversation_history: List[Dict[str, Any]],
        chat_id: str = "",
        max_memories: int = 5,
        min_score_threshold: float = 0.3
    ) -> str:
        """
        为对话检索相关记忆
        
        Args:
            user_text: 当前用户输入
            conversation_history: 对话历史
            chat_id: 聊天ID（用于个性化检索）
            max_memories: 最大返回记忆数
            min_score_threshold: 最低相似度阈值
            
        Returns:
            格式化后的记忆上下文字符串
        """
        try:
            # 构建检索query：结合当前输入和最近对话
            query = self._build_query(user_text, conversation_history)
            
            # 检查缓存
            cache_key = f"{chat_id}:{query[:50]}"
            cached = self.cache.get(cache_key)
            if cached and (datetime.now() - cached['timestamp']).total_seconds() < self.cache_ttl:
                print(f"🧠 使用缓存记忆检索: {query[:50]}...")
                return cached['result']
            
            # 使用现有retrieve模块检索
            memory_context = await retrieve_related_memories(
                query_text=query,
                recent_messages=conversation_history,
                top_k=max_memories
            )
            
            # 如果没有检索到记忆，尝试更宽松的检索
            if not memory_context or memory_context == "":
                # 只使用用户输入作为query
                memory_context = await retrieve_related_memories(
                    query_text=user_text,
                    recent_messages=None,
                    top_k=max_memories
                )
            
            # 缓存结果
            if memory_context:
                self.cache[cache_key] = {
                    'result': memory_context,
                    'timestamp': datetime.now()
                }
                
                # 清理过期缓存
                self._clean_cache()
            
            return memory_context or ""
            
        except Exception as e:
            print(f"❌ 自动化记忆检索失败: {e}")
            return ""
    
    def _build_query(
        self,
        user_text: str,
        conversation_history: List[Dict[str, Any]]
    ) -> str:
        """构建检索query，结合当前输入和对话历史"""
        # 提取最近几条对话作为上下文
        recent_context = []
        for msg in conversation_history[-4:]:  # 最近4条
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role and content:
                recent_context.append(f"{role}: {content[:100]}")
        
        # 如果最近对话不为空，结合当前输入
        if recent_context:
            context_str = " | ".join(recent_context)
            query = f"{context_str} | 当前: {user_text}"
        else:
            query = user_text
            
        return query
    
    def _clean_cache(self):
        """清理过期缓存"""
        now = datetime.now()
        expired_keys = []
        
        for key, value in self.cache.items():
            if (now - value['timestamp']).total_seconds() > self.cache_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            print(f"🧹 清理了 {len(expired_keys)} 个过期缓存")
    
    async def search_memories(
        self,
        query: str,
        top_k: int = 10,
        include_content: bool = True
    ) -> List[Dict[str, Any]]:
        """直接搜索记忆，返回结构化结果"""
        try:
            candidates = self.store.fetch_alias_candidates(
                query_text=query,
                max_candidates=top_k * 2  # 获取更多候选用于过滤
            )
            
            if not candidates:
                return []
            
            # 过滤低分结果并格式化
            results = []
            for cand in candidates[:top_k]:
                score = cand.get('base_score', 0)
                if score < 0.2:  # 过滤太低分的
                    continue
                    
                result = {
                    'uri': cand.get('uri', ''),
                    'summary': cand.get('summary', ''),
                    'score': round(score, 3),
                    'importance': cand.get('importance', 3),
                    'is_permanent': cand.get('is_permanent', False),
                    'created_at': cand.get('created_at', ''),
                }
                
                if include_content:
                    result['content'] = cand.get('content', '')[:200] + '...'
                
                results.append(result)
            
            return results
            
        except Exception as e:
            print(f"❌ 记忆搜索失败: {e}")
            return []
    
    async def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆系统统计信息"""
        try:
            # 这里可以添加更多统计信息
            return {
                'cache_size': len(self.cache),
                'store_initialized': True,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {'error': str(e)}


# 全局实例
_retriever_instance = None

def get_retriever() -> AutoRetriever:
    """获取全局检索器实例（单例模式）"""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = AutoRetriever()
    return _retriever_instance


async def auto_retrieve_for_conversation(
    user_text: str,
    conversation_history: List[Dict[str, Any]],
    chat_id: str = "",
    max_memories: int = 5
) -> str:
    """
    自动化检索入口函数
    
    Args:
        user_text: 用户输入
        conversation_history: 对话历史
        chat_id: 聊天ID
        max_memories: 最大记忆数
        
    Returns:
        格式化后的记忆上下文
    """
    retriever = get_retriever()
    return await retriever.retrieve_for_conversation(
        user_text=user_text,
        conversation_history=conversation_history,
        chat_id=chat_id,
        max_memories=max_memories
    )


if __name__ == "__main__":
    # 测试代码
    async def test():
        retriever = AutoRetriever()
        
        # 测试检索
        test_history = [
            {'role': 'user', 'content': '你好'},
            {'role': 'assistant', 'content': '你好！有什么可以帮助你的吗？'}
        ]
        
        result = await retriever.retrieve_for_conversation(
            user_text="今天天气怎么样？",
            conversation_history=test_history,
            chat_id="test_chat"
        )
        
        print("检索结果:")
        print(result)
        
        # 测试搜索
        search_results = await retriever.search_memories("测试", top_k=3)
        print(f"\n搜索到 {len(search_results)} 条记忆")
        
        # 测试统计
        stats = await retriever.get_memory_stats()
        print(f"\n统计信息: {stats}")
    
    asyncio.run(test())