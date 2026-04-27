"""
xiaowo-release HTTP客户端
封装对小窝记忆系统的API调用
"""

import httpx
import asyncio
import json
import os
import sys
import ast
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

from config import (
    XIAOWO_API_URL,
    XIAOWO_ENABLE_MUSIC,
    XIAOWO_ENABLE_TRAVEL,
    XIAOWO_ENABLE_CODE_ANALYSIS,
    CODE_ANALYSIS_CACHE_TTL,
)


class XiaowoClient:
    """小窝记忆系统HTTP客户端"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or XIAOWO_API_URL
        self.client = None
        self.code_analysis_cache = {}
        self.code_analysis_cache_time = {}
    
    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Content-Type": "application/json"}
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    async def _make_request(self, action: str, params: Dict) -> Dict:
        """调用小窝API"""
        try:
            if not self.client:
                self.client = httpx.AsyncClient(timeout=30.0)
            
            payload = {"action": action, **params}
            response = await self.client.post(
                f"{self.base_url}/api/app",
                json=payload,
                timeout=30.0
            )
            
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}",
                    "text": f"API调用失败: HTTP {response.status_code}"
                }
            
            result = response.json()
            if isinstance(result, dict) and "text" in result:
                return {"success": True, "text": result["text"]}
            elif isinstance(result, str):
                return {"success": True, "text": result}
            else:
                return {"success": True, "text": json.dumps(result, ensure_ascii=False)}
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "text": f"小窝API调用失败: {str(e)}"
            }
    
    # ==================== 旅行系统 ====================
    
    async def travel_suggest_destination(self) -> str:
        """获取旅行目的地建议"""
        result = await self._make_request("travel", {"op": "suggest"})
        return result["text"]
    
    async def travel_prepare(self, destination: str) -> str:
        """旅行前准备"""
        result = await self._make_request("travel", {
            "op": "prepare",
            "destination": destination
        })
        return result["text"]
    
    async def travel_start(self, destination: str, plan: str = "自由探索", clothing: str = "T恤和长裤") -> Dict:
        """开始新旅行"""
        result = await self._make_request("travel", {
            "op": "start",
            "destination": destination,
            "plan": plan,
            "clothing": clothing
        })
        
        # 从返回文本中提取session_id
        text = result["text"]
        session_id = None
        for line in text.split("\n"):
            if "旅行ID：" in line:
                session_id = line.split("：")[1].strip()
                break
        
        return {
            "success": result["success"],
            "text": text,
            "session_id": session_id
        }
    
    async def travel_go(self, session_id: str, action: str) -> str:
        """在旅行中行动"""
        result = await self._make_request("travel", {
            "op": "go",
            "sessionId": session_id,
            "input": action
        })
        return result["text"]
    
    async def travel_end(self, session_id: str, journal: str = "", luggage: str = "") -> str:
        """结束旅行"""
        result = await self._make_request("travel", {
            "op": "end",
            "sessionId": session_id,
            "journal": journal,
            "luggage": luggage
        })
        return result["text"]
    
    async def travel_list(self) -> str:
        """列出所有旅行"""
        result = await self._make_request("travel", {"op": "list"})
        return result["text"]
    
    async def travel_luggage(self) -> str:
        """查看行李"""
        result = await self._make_request("travel", {"op": "luggage"})
        return result["text"]
    
    # ==================== 音乐盒 ====================
    
    async def music_status(self) -> str:
        """查看音乐盒状态"""
        result = await self._make_request("music", {"op": "status"})
        return result["text"]
    
    async def music_on(self, mode: str = "random") -> str:
        """打开音乐盒"""
        if mode == "playlist":
            result = await self._make_request("music", {"op": "on", "request": "playlist"})
        else:
            result = await self._make_request("music", {"op": "on"})
        return result["text"]
    
    async def music_off(self) -> str:
        """关闭音乐盒"""
        result = await self._make_request("music", {"op": "off"})
        return result["text"]
    
    async def music_play(self, request: str = "") -> str:
        """播放音乐"""
        params = {"op": "play"}
        if request:
            params["request"] = request
        result = await self._make_request("music", params)
        return result["text"]
    
    async def music_like(self) -> str:
        """喜欢当前音乐"""
        result = await self._make_request("music", {"op": "like"})
        return result["text"]
    
    async def music_switch(self) -> str:
        """切歌"""
        result = await self._make_request("music", {"op": "switch"})
        return result["text"]
    
    async def music_playlist(self) -> str:
        """查看歌单"""
        result = await self._make_request("music", {"op": "playlist"})
        return result["text"]
    
    # ==================== 代码分析 ====================
    
    def _is_cache_valid(self, key: str) -> bool:
        """检查缓存是否有效"""
        if key not in self.code_analysis_cache_time:
            return False
        
        cache_time = self.code_analysis_cache_time[key]
        age = (datetime.now() - cache_time).total_seconds()
        return age < CODE_ANALYSIS_CACHE_TTL
    
    async def analyze_project_structure(self) -> Dict:
        """分析项目结构"""
        cache_key = "project_structure"
        
        # 检查缓存
        if self._is_cache_valid(cache_key):
            return self.code_analysis_cache[cache_key]
        
        try:
            project_root = Path.cwd()
            py_files = []
            
            # 收集所有Python文件
            for path in project_root.rglob("*.py"):
                # 过滤忽略的目录
                rel_path = path.relative_to(project_root)
                ignore = False
                ignore_patterns = [
                    "__pycache__", ".git", ".env", ".clineignore",
                    "node_modules", ".cache", "data/", "model/"
                ]
                
                for pattern in ignore_patterns:
                    if pattern.endswith("/"):
                        if str(rel_path).startswith(pattern[:-1]):
                            ignore = True
                            break
                    elif pattern in str(rel_path):
                        ignore = True
                        break
                
                if not ignore:
                    py_files.append(path)
            
            # 分析文件结构
            file_info = {}
            import_graph = defaultdict(set)
            all_functions = defaultdict(list)
            all_classes = defaultdict(list)
            
            for filepath in py_files:
                rel_path = str(filepath.relative_to(project_root))
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    tree = ast.parse(content)
                    
                    # 收集import
                    imports = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.append(f"import {alias.name}")
                        elif isinstance(node, ast.ImportFrom):
                            module = node.module or ""
                            for alias in node.names:
                                imports.append(f"from {module} import {alias.name}")
                    
                    # 收集函数和类定义
                    functions = []
                    classes = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            functions.append(node.name)
                        elif isinstance(node, ast.AsyncFunctionDef):
                            functions.append(node.name)
                        elif isinstance(node, ast.ClassDef):
                            classes.append(node.name)
                    
                    # 收集函数调用
                    calls = []
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            if isinstance(node.func, ast.Name):
                                calls.append(node.func.id)
                            elif isinstance(node.func, ast.Attribute):
                                calls.append(node.func.attr)
                    
                    file_info[rel_path] = {
                        "imports": imports,
                        "functions": functions,
                        "classes": classes,
                        "calls": calls,
                        "line_count": len(content.split("\n"))
                    }
                    
                    # 构建import图
                    for imp in imports:
                        if imp.startswith("import "):
                            module = imp[7:].split()[0]
                            import_graph[rel_path].add(module)
                        elif imp.startswith("from "):
                            parts = imp[5:].split(" import ")
                            if len(parts) == 2:
                                module = parts[0].strip()
                                import_graph[rel_path].add(module)
                    
                    # 收集所有函数和类
                    for func in functions:
                        all_functions[func].append(rel_path)
                    for cls in classes:
                        all_classes[cls].append(rel_path)
                        
                except Exception as e:
                    print(f"分析文件 {rel_path} 失败: {e}")
                    continue
            
            # 识别潜在未使用代码
            unused_functions = []
            for func, files in all_functions.items():
                # 检查函数是否被调用
                used = False
                for filepath, info in file_info.items():
                    if func in info["calls"]:
                        used = True
                        break
                
                if not used:
                    unused_functions.append((func, files))
            
            unused_classes = []
            for cls, files in all_classes.items():
                # 简单检查类是否被使用
                used = False
                for filepath, info in file_info.items():
                    for call in info["calls"]:
                        if call.lower().startswith(cls.lower()):
                            used = True
                            break
                    if used:
                        break
                
                if not used:
                    unused_classes.append((cls, files))
            
            # 生成项目总结
            total_files = len(file_info)
            total_functions = sum(len(info["functions"]) for info in file_info.values())
            total_classes = sum(len(info["classes"]) for info in file_info.values())
            
            # 识别主要模块
            core_modules = [
                "core/ai_core.py", "main.py", "ports/feishu.py", 
                "memory/graph_store.py", "tools/schedule_manager.py"
            ]
            
            core_summary = {}
            for module in core_modules:
                if module in file_info:
                    info = file_info[module]
                    core_summary[module] = {
                        "functions": len(info["functions"]),
                        "classes": len(info["classes"]),
                        "imports": len(info["imports"])
                    }
            
            result = {
                "total_files": total_files,
                "total_functions": total_functions,
                "total_classes": total_classes,
                "file_info": file_info,
                "import_graph": {k: list(v) for k, v in import_graph.items()},
                "unused_functions": unused_functions[:10],  # 只显示前10个
                "unused_classes": unused_classes[:10],
                "core_modules": core_summary,
                "analysis_time": datetime.now().isoformat()
            }
            
            # 缓存结果
            self.code_analysis_cache[cache_key] = result
            self.code_analysis_cache_time[cache_key] = datetime.now()
            
            return result
            
        except Exception as e:
            return {
                "error": f"项目分析失败: {str(e)}",
                "analysis_time": datetime.now().isoformat()
            }
    
    async def get_code_summary(self) -> str:
        """获取代码总结（文本格式）"""
        try:
            analysis = await self.analyze_project_structure()
            
            if "error" in analysis:
                return f"❌ 代码分析失败: {analysis['error']}"
            
            text = "📁 项目结构分析\n"
            text += "=" * 50 + "\n\n"
            
            text += f"📊 统计信息:\n"
            text += f"  文件总数: {analysis['total_files']}\n"
            text += f"  函数总数: {analysis['total_functions']}\n"
            text += f"  类总数: {analysis['total_classes']}\n\n"
            
            text += "🏗️ 核心模块:\n"
            for module, stats in analysis.get("core_modules", {}).items():
                text += f"  {module}:\n"
                text += f"    函数: {stats['functions']}, 类: {stats['classes']}, 导入: {stats['imports']}\n"
            
            text += "\n🔗 主要导入关系:\n"
            import_count = 0
            for file, imports in analysis.get("import_graph", {}).items():
                if imports:
                    import_count += 1
                    if import_count <= 5:  # 只显示前5个
                        text += f"  {file} → {', '.join(imports[:3])}"
                        if len(imports) > 3:
                            text += f" 等{len(imports)}个\n"
                        else:
                            text += "\n"
            
            if analysis.get("unused_functions"):
                text += f"\n⚠️ 潜在未使用函数 ({len(analysis['unused_functions'])}个):\n"
                for func, files in analysis["unused_functions"][:5]:
                    text += f"  {func} (定义在: {', '.join(files)})\n"
            
            if analysis.get("unused_classes"):
                text += f"\n⚠️ 潜在未使用类 ({len(analysis['unused_classes'])}个):\n"
                for cls, files in analysis["unused_classes"][:5]:
                    text += f"  {cls} (定义在: {', '.join(files)})\n"
            
            text += f"\n⏰ 分析时间: {analysis['analysis_time']}\n"
            text += "💡 提示: 你可以问更具体的问题，如'解释ai_core.py的功能'或'显示main.py的导入关系'"
            
            return text
            
        except Exception as e:
            return f"❌ 代码分析异常: {str(e)}"
    
    async def explain_file(self, filepath: str) -> str:
        """解释特定文件的功能"""
        try:
            analysis = await self.analyze_project_structure()
            
            if "error" in analysis:
                return f"❌ 分析失败: {analysis['error']}"
            
            if filepath not in analysis.get("file_info", {}):
                # 尝试找到相似的文件
                similar = [f for f in analysis.get("file_info", {}).keys() 
                          if filepath in f or f.endswith(filepath)]
                if similar:
                    filepath = similar[0]
                else:
                    return f"❌ 找不到文件: {filepath}"
            
            info = analysis["file_info"][filepath]
            
            text = f"📄 文件分析: {filepath}\n"
            text += "=" * 50 + "\n\n"
            
            text += f"📊 基本信息:\n"
            text += f"  行数: {info['line_count']}\n"
            text += f"  函数: {len(info['functions'])}个\n"
            text += f"  类: {len(info['classes'])}个\n"
            text += f"  导入: {len(info['imports'])}个\n\n"
            
            if info["functions"]:
                text += f"📋 函数列表:\n"
                for func in info["functions"]:
                    text += f"  - {func}\n"
                text += "\n"
            
            if info["classes"]:
                text += f"🏛️ 类列表:\n"
                for cls in info["classes"]:
                    text += f"  - {cls}\n"
                text += "\n"
            
            if info["imports"]:
                text += f"🔗 导入的模块:\n"
                for imp in info["imports"][:10]:  # 只显示前10个
                    text += f"  - {imp}\n"
                if len(info["imports"]) > 10:
                    text += f"  等{len(info['imports'])}个导入\n"
                text += "\n"
            
            # 根据文件名猜测功能
            if "ai_core" in filepath:
                text += "💡 功能推测: AI核心模块，处理AI调用、工具执行、记忆管理\n"
            elif "feishu" in filepath:
                text += "💡 功能推测: 飞书接口，处理消息收发、事件处理\n"
            elif "graph_store" in filepath:
                text += "💡 功能推测: 图数据库存储，管理记忆的向量检索\n"
            elif "main.py" in filepath:
                text += "💡 功能推测: 主程序入口，启动飞书机器人服务\n"
            elif "schedule" in filepath:
                text += "💡 功能推测: 日程管理，处理提醒和定时任务\n"
            
            text += f"\n⏰ 分析时间: {analysis['analysis_time']}"
            
            return text
            
        except Exception as e:
            return f"❌ 文件分析失败: {str(e)}"


# 全局客户端实例
_client_instance = None

async def get_xiaowo_client() -> XiaowoClient:
    """获取全局xiaowo客户端实例"""
    global _client_instance
    if _client_instance is None:
        _client_instance = XiaowoClient()
        await _client_instance.__aenter__()
    return _client_instance


# 简化API函数
async def travel_control(args: Dict) -> str:
    """旅行系统控制"""
    client = await get_xiaowo_client()
    op = args.get("action", "list")
    
    if op == "suggest":
        return await client.travel_suggest_destination()
    elif op == "prepare":
        destination = args.get("destination", "")
        if not destination:
            return "需要指定目的地 (destination)"
        return await client.travel_prepare(destination)
    elif op == "start":
        destination = args.get("destination", "")
        if not destination:
            return "需要指定目的地 (destination)"
        plan = args.get("plan", "自由探索")
        clothing = args.get("clothing", "T恤和长裤")
        result = await client.travel_start(destination, plan, clothing)
        return result["text"]
    elif op == "go":
        session_id = args.get("session_id", "")
        action = args.get("input", "")
        if not session_id or not action:
            return "需要session_id和input"
        return await client.travel_go(session_id, action)
    elif op == "end":
        session_id = args.get("session_id", "")
        if not session_id:
            return "需要session_id"
        journal = args.get("journal", "")
        luggage = args.get("luggage", "")
        return await client.travel_end(session_id, journal, luggage)
    elif op == "list":
        return await client.travel_list()
    elif op == "luggage":
        return await client.travel_luggage()
    else:
        return f"未知旅行操作: {op}"


async def music_control(args: Dict) -> str:
    """音乐盒控制"""
    client = await get_xiaowo_client()
    op = args.get("action", "status")
    
    if op == "status":
        return await client.music_status()
    elif op == "on":
        mode = args.get("mode", "random")
        return await client.music_on(mode)
    elif op == "off":
        return await client.music_off()
    elif op == "play":
        request = args.get("request", "")
        return await client.music_play(request)
    elif op == "like":
        return await client.music_like()
    elif op == "switch":
        return await client.music_switch()
    elif op == "playlist":
        return await client.music_playlist()
    else:
        return f"未知音乐操作: {op}"


async def code_analysis(args: Dict) -> str:
    """代码分析"""
    client = await get_xiaowo_client()
    op = args.get("action", "summary")
    filepath = args.get("filepath", "")
    
    if op == "summary":
        return await client.get_code_summary()
    elif op == "explain":
        if not filepath:
            return "需要指定文件路径 (filepath)"
        return await client.explain_file(filepath)
    elif op == "structure":
        analysis = await client.analyze_project_structure()
        return json.dumps(analysis, ensure_ascii=False, indent=2)
    else:
        return f"未知代码分析操作: {op}"


if __name__ == "__main__":
    # 测试代码
    async def test():
        async with XiaowoClient() as client:
            print("=== 测试旅行系统 ===")
            result = await client.travel_suggest_destination()
            print(result)
            
            print("\n=== 测试代码分析 ===")
            summary = await client.get_code_summary()
            print(summary)
    
    asyncio.run(test())