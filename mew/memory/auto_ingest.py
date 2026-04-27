"""
自动化记忆抽取模块
负责：每次对话后自动分析重要性，抽取关键记忆存储到图数据库
"""

from __future__ import annotations
import asyncio
import json
import re
import uuid
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from .graph_store import GraphStore, CORE_AGENT_NODE_UUID, DEFAULT_DOMAIN
from .openrouter_client import chat_json


class AutoIngester:
    """自动化记忆抽取器"""
    
    def __init__(self):
        self.store = GraphStore()
        self.min_importance_threshold = 3  # 重要性阈值（1-5）
        self.recent_processed = {}  # 最近处理的对话，避免重复处理
        self.recent_ttl = 60  # 60秒内不重复处理相同对话
        
    async def analyze_conversation_importance(
        self,
        user_text: str,
        bot_text: str,
        conversation_history: List[Dict[str, Any]]
    ) -> Tuple[bool, int]:
        """
        分析对话重要性
        
        Args:
            user_text: 用户输入
            bot_text: AI回复
            conversation_history: 完整对话历史
            
        Returns:
            (是否值得存储, 重要性评分1-5)
        """
        try:
            # 简单的启发式规则 + AI判断
            
            # 1. 长度检查：太短的对话可能不值得存储
            if len(user_text) < 10 or len(bot_text) < 10:
                return False, 1
            
            # 2. 关键词检查：包含某些关键词可能更重要
            important_keywords = [
                '重要', '记住', '记得', '备忘', '提醒',
                '喜欢', '爱', '讨厌', '害怕', '担心',
                '生日', '纪念日', '节日', '约定',
                '第一次', '最后', '永远', '一直',
                '秘密', '心事', '梦想', '目标'
            ]
            
            keyword_importance = 0
            for keyword in important_keywords:
                if keyword in user_text or keyword in bot_text:
                    keyword_importance += 1
            
            # 3. 情感强度检查（简单版）
            emotion_words = [
                '开心', '高兴', '快乐', '兴奋',
                '伤心', '难过', '悲伤', '哭泣',
                '生气', '愤怒', '恼火',
                '害怕', '恐惧', '担心', '焦虑'
            ]
            
            emotion_count = 0
            for word in emotion_words:
                if word in user_text or word in bot_text:
                    emotion_count += 1
            
            # 4. 使用AI进行深度分析
            ai_importance = await self._ai_judge_importance(user_text, bot_text)
            
            # 综合评分
            base_score = 1
            if keyword_importance > 0:
                base_score += 1
            if emotion_count > 0:
                base_score += 1
            if ai_importance > base_score:
                base_score = ai_importance
            
            # 确保在1-5范围内
            importance = min(5, max(1, base_score))
            
            # 判断是否值得存储
            worth_storing = importance >= self.min_importance_threshold
            
            return worth_storing, importance
            
        except Exception as e:
            print(f"❌ 对话重要性分析失败: {e}")
            return False, 1
    
    async def _ai_judge_importance(self, user_text: str, bot_text: str) -> int:
        """使用AI判断对话重要性"""
        try:
            system_prompt = """你是记忆重要性评估器。评估这段对话是否值得作为长期记忆存储。
            
评分标准：
1分：日常寒暄、简单问答
2分：普通信息交流、简单建议
3分：有情感表达、个人偏好、一般事件
4分：重要事件、深刻感受、关键决策
5分：转折点、重大发现、核心价值观、关系里程碑

只输出一个数字（1-5）。"""
            
            user_prompt = f"""用户：{user_text[:200]}
助理：{bot_text[:200]}

请评分（1-5）："""
            
            response = await chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt
            )
            
            # 尝试解析响应
            if isinstance(response, dict):
                # 如果chat_json返回的是JSON，尝试提取
                text = json.dumps(response, ensure_ascii=False)
            else:
                text = str(response)
            
            # 提取数字
            numbers = re.findall(r'\b[1-5]\b', text)
            if numbers:
                return int(numbers[0])
            else:
                return 3  # 默认值
                
        except Exception as e:
            print(f"⚠️ AI重要性评估失败，使用默认值: {e}")
            return 3
    
    async def extract_and_store_memory(
        self,
        user_text: str,
        bot_text: str,
        chat_id: str = "",
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        抽取并存储记忆（如果值得）
        
        Args:
            user_text: 用户输入
            bot_text: AI回复
            chat_id: 聊天ID（用于个性化存储）
            conversation_history: 完整对话历史（可选，用于上下文）
            
        Returns:
            是否成功存储了记忆
        """
        try:
            # 检查是否最近处理过（避免重复处理）
            dialogue_key = f"{chat_id}:{user_text[:50]}:{bot_text[:50]}"
            if dialogue_key in self.recent_processed:
                timestamp = self.recent_processed[dialogue_key]
                if (datetime.now() - timestamp).total_seconds() < self.recent_ttl:
                    print(f"⏭️ 跳过最近处理过的对话")
                    return False
            
            # 分析重要性
            worth_storing, importance = await self.analyze_conversation_importance(
                user_text=user_text,
                bot_text=bot_text,
                conversation_history=conversation_history or []
            )
            
            if not worth_storing:
                print(f"📝 对话重要性 {importance}/5 未达到阈值 {self.min_importance_threshold}，跳过存储")
                # 仍然标记为已处理
                self.recent_processed[dialogue_key] = datetime.now()
                self._clean_recent_processed()
                return False
            
            print(f"💾 对话重要性 {importance}/5 达到阈值，开始抽取记忆...")
            
            # 使用现有的ingest逻辑抽取记忆
            from .ingest import extract_memory_candidates, _clamp, _slugify
            
            candidates = await extract_memory_candidates(user_text, bot_text)
            if not candidates:
                print("⚠️ 未抽取到记忆候选")
                self.recent_processed[dialogue_key] = datetime.now()
                return False
            
            stored_count = 0
            for cand in candidates[:2]:  # 最多存储2个记忆
                try:
                    summary = (cand.get("summary") or "").strip()
                    content = (cand.get("content") or summary).strip()
                    
                    if not summary or not content:
                        continue
                    
                    disclosures = (cand.get("disclosures") or [])[:3]
                    if not disclosures:
                        continue
                    
                    # 使用chat_id作为路径的一部分，实现个性化存储
                    base_path = _slugify(cand.get("path") or f"chat/{chat_id}/{summary[:20]}")
                    domain = DEFAULT_DOMAIN
                    
                    # 检查是否已存在类似记忆
                    eid = self.store.get_edge_id_by_path(domain, base_path)
                    node_uuid = None
                    
                    if eid:
                        # 如果已存在，获取节点UUID
                        node_uuid = self.store.get_child_uuid_by_edge_id(eid)
                    
                    if not node_uuid:
                        # 创建新节点
                        node_uuid = str(uuid.uuid4())
                    
                    # 存储记忆版本
                    memory_id = self.store.create_or_update_memory_version(
                        node_uuid=node_uuid,
                        content=content,
                        summary=summary,
                        importance=_clamp(cand.get("importance", importance)),
                        is_permanent=bool(cand.get("is_permanent", importance >= 4))
                    )
                    
                    # 添加边和路径
                    for i, d in enumerate(disclosures, 1):
                        edge_id = self.store.add_edge(
                            CORE_AGENT_NODE_UUID,
                            node_uuid,
                            d,
                            priority=_clamp(cand.get("importance", importance))
                        )
                        self.store.add_or_replace_path(
                            domain,
                            base_path if len(disclosures) == 1 else f"{base_path}/d{i}",
                            edge_id
                        )
                    
                    # 标记记忆被使用
                    self.store.mark_memory_used(memory_id, f"auto_ingest from chat:{chat_id}")
                    
                    stored_count += 1
                    print(f"✅ 存储记忆: {summary[:50]}... (ID: {memory_id})")
                    
                except Exception as e:
                    print(f"❌ 存储单个记忆失败: {e}")
                    continue
            
            # 标记为已处理
            self.recent_processed[dialogue_key] = datetime.now()
            self._clean_recent_processed()
            
            if stored_count > 0:
                print(f"🎉 成功存储了 {stored_count} 条记忆")
                return True
            else:
                print("⚠️ 未成功存储任何记忆")
                return False
            
        except Exception as e:
            print(f"❌ 自动化记忆抽取存储失败: {e}")
            return False
    
    def _clean_recent_processed(self):
        """清理最近处理记录"""
        now = datetime.now()
        expired_keys = []
        
        for key, timestamp in self.recent_processed.items():
            if (now - timestamp).total_seconds() > self.recent_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.recent_processed[key]
        
        if expired_keys:
            print(f"🧹 清理了 {len(expired_keys)} 个过期处理记录")
    
    async def batch_process_conversation(
        self,
        conversation_history: List[Dict[str, Any]],
        chat_id: str = ""
    ) -> int:
        """
        批量处理对话历史，抽取重要记忆
        
        Args:
            conversation_history: 完整对话历史
            chat_id: 聊天ID
            
        Returns:
            成功存储的记忆数量
        """
        stored_count = 0
        
        # 将对话历史分组为（用户输入，AI回复）对
        pairs = []
        current_user = None
        
        for msg in conversation_history:
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            if role == 'user':
                current_user = content
            elif role == 'assistant' and current_user is not None:
                pairs.append((current_user, content))
                current_user = None
        
        # 处理每对对话
        for user_text, bot_text in pairs[-10:]:  # 只处理最近10对
            try:
                success = await self.extract_and_store_memory(
                    user_text=user_text,
                    bot_text=bot_text,
                    chat_id=chat_id,
                    conversation_history=conversation_history
                )
                
                if success:
                    stored_count += 1
                    
                # 短暂延迟，避免API限制
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"❌ 处理对话对失败: {e}")
                continue
        
        return stored_count
    
    async def get_ingestion_stats(self) -> Dict[str, Any]:
        """获取抽取统计信息"""
        return {
            'min_importance_threshold': self.min_importance_threshold,
            'recent_processed_count': len(self.recent_processed),
            'timestamp': datetime.now().isoformat()
        }


# 全局实例
_ingester_instance = None

def get_ingester() -> AutoIngester:
    """获取全局抽取器实例（单例模式）"""
    global _ingester_instance
    if _ingester_instance is None:
        _ingester_instance = AutoIngester()
    return _ingester_instance


async def auto_ingest_conversation(
    user_text: str,
    bot_text: str,
    chat_id: str = "",
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> bool:
    """
    自动化抽取入口函数
    
    Args:
        user_text: 用户输入
        bot_text: AI回复
        chat_id: 聊天ID
        conversation_history: 对话历史
        
    Returns:
        是否成功存储了记忆
    """
    ingester = get_ingester()
    return await ingester.extract_and_store_memory(
        user_text=user_text,
        bot_text=bot_text,
        chat_id=chat_id,
        conversation_history=conversation_history
    )


if __name__ == "__main__":
    # 测试代码
    async def test():
        ingester = AutoIngester()
        
        # 测试重要性分析
        user_text = "今天是我生日，你记得吗？"
        bot_text = "当然记得！生日快乐！这是我为你准备的虚拟礼物～"
        
        worth, importance = await ingester.analyze_conversation_importance(
            user_text=user_text,
            bot_text=bot_text,
            conversation_history=[]
        )
        
        print(f"重要性分析: worth={worth}, importance={importance}")
        
        # 测试记忆抽取
        success = await ingester.extract_and_store_memory(
            user_text=user_text,
            bot_text=bot_text,
            chat_id="test_chat"
        )
        
        print(f"记忆抽取结果: {success}")
        
        # 测试统计
        stats = await ingester.get_ingestion_stats()
        print(f"统计信息: {stats}")
    
    asyncio.run(test())