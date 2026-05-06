"""
一次性导入 memory_system/ 下所有 .md 到 graph_memory.db
=====================================================

用法：
  python scripts/ingest_initial.py                    # 实际写入
  python scripts/ingest_initial.py --dry-run          # 仅预览
  python scripts/ingest_initial.py --root /custom/path # 自定义根目录

文件夹 → URI domain + 默认 context 的映射在 FOLDER_RULES 里。
跳过 snapshot/ 和 README/（年糕原话：自建后端不再依赖 snapshot 仪式）。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from glob import glob

# 让脚本能从项目根 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ROOT  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("ingest_initial")


# ==================== 文件夹映射规则 ====================

FOLDER_RULES = {
    "profile": {
        "domain": "profile",
        "context": ["identity"],
        "importance": 8,
        "is_permanent": False,
    },
    "persistent": {
        "domain": "persistent",
        "context": ["core_belief"],
        "importance": 10,
        "is_permanent": True,
    },
    "events": {
        "domain": "events",
        "context": ["emotional"],
        "importance": 6,
        "is_permanent": False,
    },
    "projects": {
        "domain": "projects",
        "context": ["work"],
        "importance": 5,
        "is_permanent": False,
    },
    "CAEL_box": {
        "domain": "diary",
        "context": ["cael_diary"],
        "importance": 6,
        "is_permanent": False,
    },
    "rice_cake_box": {
        "domain": "diary",
        "context": ["ricecake_diary"],
        "importance": 6,
        "is_permanent": False,
    },
    "CAEL_only": {
        "domain": "private",
        "context": ["cael_only"],
        "importance": 5,
        "is_permanent": False,
    },
    # 跳过：
    # snapshot/  —— 自建后端不再依赖
    # README/    —— 说明文档
}

# 顶层根目录的散落 .md（如 to_do_list.md、sentences.md）
ROOT_LEVEL_RULES = {
    "to_do_list.md": {
        "domain": "todo",
        "context": ["task"],
        "importance": 4,
    },
    "sentences.md": {
        "domain": "sentences",
        "context": ["quote"],
        "importance": 5,
    },
}


# ==================== 主流程 ====================

async def main(root: str, dry_run: bool = False) -> None:
    log.info(f"开始扫描 {root}")
    log.info(f"模式: {'DRY RUN（仅预览）' if dry_run else '实际写入'}")
    log.info("=" * 50)

    if not dry_run:
        # 提前 import，触发 graph_store 初始化
        try:
            from memory.ingest import ingest_md_file  # noqa: F401
        except Exception as e:
            log.error(f"无法 import memory.ingest: {e}")
            log.error("请确认 memory/graph_store.py 是否就绪，并安装了 sqlite-vec、sentence-transformers")
            return

    total = 0
    success = 0
    skipped = 0

    # 1. 扫文件夹
    for folder_name, rules in FOLDER_RULES.items():
        folder = os.path.join(root, folder_name)
        if not os.path.isdir(folder):
            log.info(f"[skip] 目录不存在: {folder_name}/")
            continue

        files = sorted(glob(os.path.join(folder, "**/*.md"), recursive=True))
        if not files:
            log.info(f"[skip] 目录无 .md 文件: {folder_name}/")
            continue

        log.info(f"\n📁 {folder_name}/ ({len(files)} 个文件)")
        log.info(f"   domain={rules['domain']} context={rules['context']}")

        for fpath in files:
            total += 1
            rel = os.path.relpath(fpath, root)

            # 跳过空文件
            try:
                if os.path.getsize(fpath) < 5:
                    log.debug(f"[skip empty] {rel}")
                    skipped += 1
                    continue
            except OSError:
                skipped += 1
                continue

            if dry_run:
                log.info(f"  [DRY] {rel}")
                success += 1
            else:
                try:
                    from memory.ingest import ingest_md_file
                    mid = await ingest_md_file(
                        path=fpath,
                        domain=rules["domain"],
                        context=rules["context"],
                        importance=rules["importance"],
                        is_permanent=rules.get("is_permanent", False),
                        auto_ingested=False,  # 手动初始化，不是 AI 自动
                    )
                    if mid > 0:
                        log.info(f"  ✓ {rel} (id={mid})")
                        success += 1
                    else:
                        log.warning(f"  ✗ {rel} (失败)")
                except Exception as e:
                    log.exception(f"  ✗ {rel}: {e}")

    # 2. 扫顶层散落 .md
    for fname, rules in ROOT_LEVEL_RULES.items():
        fpath = os.path.join(root, fname)
        if not os.path.isfile(fpath):
            continue

        total += 1
        log.info(f"\n📄 {fname}")

        if dry_run:
            log.info(f"  [DRY] {fname} -> {rules}")
            success += 1
        else:
            try:
                from memory.ingest import ingest_md_file
                mid = await ingest_md_file(
                    path=fpath,
                    domain=rules["domain"],
                    context=rules["context"],
                    importance=rules["importance"],
                    is_permanent=rules.get("is_permanent", False),
                    auto_ingested=False,
                )
                if mid > 0:
                    log.info(f"  ✓ id={mid}")
                    success += 1
                else:
                    log.warning(f"  ✗ 失败")
            except Exception as e:
                log.exception(f"  ✗ {e}")

    # 3. 总结
    log.info("=" * 50)
    log.info(f"扫描完成：总计 {total} 个文件，成功 {success}，跳过 {skipped}")


# ==================== CLI ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一次性导入 memory_system/ 到 graph_memory.db")
    parser.add_argument("--root", default=ROOT, help=f"memory_system 根目录（默认: {ROOT}）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际写入")
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        log.error(f"根目录不存在: {args.root}")
        sys.exit(1)

    asyncio.run(main(args.root, dry_run=args.dry_run))
