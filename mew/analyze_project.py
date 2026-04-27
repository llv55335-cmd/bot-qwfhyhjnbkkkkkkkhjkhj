#!/usr/bin/env python3
"""
项目分析脚本：分析 import 关系、死代码和冗余 import。
"""

import os
import ast
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Set, List, Tuple

class ProjectAnalyzer:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()
        self.all_py_files = []
        self.imports: Dict[str, Set[str]] = defaultdict(set)  # file -> set of imported modules
        self.local_imports: Dict[str, Set[str]] = defaultdict(set)  # file -> set of local imported modules
        self.exports: Dict[str, Set[str]] = defaultdict(set)  # file -> set of defined functions/classes
        self.references: Dict[str, Set[str]] = defaultdict(set)  # file -> set of referenced names
        self.import_details: Dict[str, Dict] = defaultdict(dict)  # file -> {module: [imported_names]}
        
    def collect_files(self):
        """收集所有Python文件"""
        for dirpath, dirnames, filenames in os.walk(self.root_dir):
            # 跳过隐藏目录和虚拟环境
            dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in ('__pycache__', 'node_modules', 'venv', '.venv')]
            for filename in filenames:
                if filename.endswith('.py'):
                    full_path = Path(dirpath) / filename
                    self.all_py_files.append(full_path)
        print(f"找到 {len(self.all_py_files)} 个Python文件")
    
    def relative_to_project(self, path: Path) -> str:
        """将路径转换为相对于项目根的模块路径"""
        rel_path = path.relative_to(self.root_dir)
        # 将路径转换为模块格式（去掉.py，用点分隔）
        module_parts = []
        for part in rel_path.parts:
            if part.endswith('.py'):
                part = part[:-3]
            if part != '__init__':
                module_parts.append(part)
        return '.'.join(module_parts)
    
    def is_local_module(self, module_name: str, current_file: Path) -> bool:
        """判断模块是否为本地模块"""
        # 检查模块是否可能对应本地文件
        if module_name.startswith('.'):
            return True
            
        # 检查是否存在对应的本地文件
        # 将模块名转换为可能的文件路径
        module_parts = module_name.split('.')
        possible_paths = []
        
        # 尝试在当前目录下查找
        current_dir = current_file.parent
        test_path = current_dir
        for part in module_parts:
            test_path = test_path / part
        possible_paths.append(test_path.with_suffix('.py'))
        possible_paths.append(test_path / '__init__.py')
        
        # 尝试在项目根目录下查找
        test_path = self.root_dir
        for part in module_parts:
            test_path = test_path / part
        possible_paths.append(test_path.with_suffix('.py'))
        possible_paths.append(test_path / '__init__.py')
        
        for path in possible_paths:
            if path.exists():
                return True
        return False
    
    def analyze_file(self, filepath: Path):
        """分析单个Python文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"无法解析文件 {filepath}: {e}")
            return
        
        rel_path = str(filepath.relative_to(self.root_dir))
        
        # 收集导入
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
                    self.imports[rel_path].add(module)
                    if self.is_local_module(module, filepath):
                        self.local_imports[rel_path].add(module)
                    # 记录导入详情
                    if rel_path not in self.import_details:
                        self.import_details[rel_path] = {}
                    self.import_details[rel_path][module] = [alias.asname or alias.name]
                    
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                level = node.level  # 相对导入级别
                if level > 0:
                    # 相对导入，构建绝对模块名
                    current_module = self.relative_to_project(filepath)
                    if current_module:
                        parts = current_module.split('.')
                        base_parts = parts[:-(level-1) if level > 1 else None]
                        if module:
                            full_module = '.'.join(base_parts + [module])
                        else:
                            full_module = '.'.join(base_parts)
                    else:
                        full_module = module
                else:
                    full_module = module
                
                if full_module:
                    self.imports[rel_path].add(full_module)
                    if self.is_local_module(full_module, filepath) or level > 0:
                        self.local_imports[rel_path].add(full_module)
                    
                    # 记录导入详情
                    if rel_path not in self.import_details:
                        self.import_details[rel_path] = {}
                    imported_names = []
                    for alias in node.names:
                        imported_names.append(alias.asname or alias.name)
                    self.import_details[rel_path][full_module] = imported_names
        
        # 收集定义和引用
        visitor = DefinitionVisitor()
        visitor.visit(tree)
        
        self.exports[rel_path].update(visitor.definitions)
        self.references[rel_path].update(visitor.references)
    
    def analyze(self):
        """分析整个项目"""
        self.collect_files()
        for filepath in self.all_py_files:
            self.analyze_file(filepath)
        
        # 构建模块依赖图
        dependency_graph = self.build_dependency_graph()
        
        # 分析结果
        self.print_analysis(dependency_graph)
    
    def build_dependency_graph(self) -> Dict[str, Set[str]]:
        """构建模块依赖图"""
        graph = defaultdict(set)
        # 创建从文件路径到模块名的映射
        file_to_module = {}
        for filepath in self.all_py_files:
            rel_path = str(filepath.relative_to(self.root_dir))
            module_name = self.relative_to_project(filepath)
            file_to_module[rel_path] = module_name
        
        # 构建依赖关系
        for filepath, imports in self.local_imports.items():
            source_module = file_to_module.get(filepath, filepath)
            for imp in imports:
                # 尝试找到目标模块
                target_module = imp
                # 简化处理：直接使用导入名
                graph[source_module].add(target_module)
        
        return graph
    
    def print_analysis(self, dependency_graph: Dict[str, Set[str]]):
        """打印分析结果"""
        print("\n" + "="*80)
        print("项目文件结构和主要模块调用关系")
        print("="*80)
        
        # 打印所有文件
        print("\n所有Python文件:")
        for filepath in sorted(self.all_py_files):
            rel_path = str(filepath.relative_to(self.root_dir))
            module_name = self.relative_to_project(filepath)
            print(f"  {rel_path} (模块: {module_name})")
        
        # 打印导入关系
        print("\n\n模块依赖关系:")
        for source, targets in sorted(dependency_graph.items()):
            if targets:
                print(f"  {source} -> {', '.join(sorted(targets))}")
        
        # 分析潜在的死代码
        print("\n\n潜在的死代码（未使用的函数/类）:")
        all_definitions = set()
        all_references = set()
        
        for filepath in self.all_py_files:
            rel_path = str(filepath.relative_to(self.root_dir))
            module_name = self.relative_to_project(filepath)
            
            definitions = self.exports.get(rel_path, set())
            references = self.references.get(rel_path, set())
            
            # 在定义前添加模块前缀以避免命名冲突
            prefixed_defs = {f"{module_name}.{d}" for d in definitions}
            prefixed_refs = {f"{module_name}.{r}" for r in references}
            
            all_definitions.update(prefixed_defs)
            all_references.update(prefixed_refs)
            
            # 检查当前文件内未使用的定义
            unused_in_file = definitions - references
            if unused_in_file:
                print(f"\n  {rel_path}:")
                for item in sorted(unused_in_file):
                    # 检查是否在其他文件中被引用（简化处理）
                    print(f"    - {item}")
        
        # 跨文件检查（简化版）
        print("\n\n跨文件使用情况分析:")
        potentially_unused = all_definitions - all_references
        if potentially_unused:
            print("以下定义可能未被使用:")
            for item in sorted(potentially_unused):
                print(f"  - {item}")
        else:
            print("未发现明显的未使用定义")
        
        # 分析冗余import
        print("\n\n潜在冗余的import语句:")
        for filepath in self.all_py_files:
            rel_path = str(filepath.relative_to(self.root_dir))
            imports_info = self.import_details.get(rel_path, {})
            definitions = self.exports.get(rel_path, set())
            references = self.references.get(rel_path, set())
            
            unused_imports = []
            for module, imported_names in imports_info.items():
                # 检查每个导入的名称是否被使用
                for name in imported_names:
                    if name not in references:
                        unused_imports.append((module, name))
            
            if unused_imports:
                print(f"\n  {rel_path}:")
                for module, name in unused_imports:
                    print(f"    - from {module} import {name}")

class DefinitionVisitor(ast.NodeVisitor):
    """AST访问者，收集定义和引用"""
    def __init__(self):
        self.definitions = set()
        self.references = set()
    
    def visit_FunctionDef(self, node):
        self.definitions.add(node.name)
        self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node):
        self.definitions.add(node.name)
        self.generic_visit(node)
    
    def visit_ClassDef(self, node):
        self.definitions.add(node.name)
        self.generic_visit(node)
    
    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self.references.add(node.id)
        self.generic_visit(node)
    
    def visit_Attribute(self, node):
        # 简化处理：只记录属性访问的最后一层
        if isinstance(node.ctx, ast.Load):
            # 尝试获取属性名
            try:
                attr_name = node.attr
                self.references.add(attr_name)
            except:
                pass
        self.generic_visit(node)

def main():
    if len(sys.argv) > 1:
        root_dir = sys.argv[1]
    else:
        root_dir = os.getcwd()
    
    analyzer = ProjectAnalyzer(root_dir)
    analyzer.analyze()

if __name__ == "__main__":
    main()