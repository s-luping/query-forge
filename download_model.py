# -*- coding: UTF-8 -*-
"""
从 ModelScope 下载 BGE-M3 多语言嵌入模型
保存路径: {项目根目录}/models/embeddings/bge-m3
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
MODEL_SAVE_DIR = os.path.join(PROJECT_ROOT, 'models', 'embeddings', 'bge-m3')


def _update_db_status(ready: bool, model_path: str = None):
    """更新数据库中的 EMBEDDING_MODEL_READY 状态和模型路径"""
    try:
        from db import SessionLocal

        db = SessionLocal()
        try:
            from models.system import SystemConfig

            def _upsert(key, value):
                row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
                if row:
                    row.value = value
                else:
                    db.add(SystemConfig(key=key, value=value))

            _upsert('EMBEDDING_MODEL_READY', 'true' if ready else 'false')
            if ready and model_path:
                _upsert('EMBEDDING_MODEL_PATH', model_path)
                print(f"  模型路径已缓存: {model_path}")
            db.commit()
            print(f"  数据库状态已更新: EMBEDDING_MODEL_READY = {'true' if ready else 'false'}")
        finally:
            db.close()
    except Exception as e:
        print(f"  ⚠ 更新数据库状态失败: {e}")


def download_model():
    model_name = 'BAAI/bge-m3'

    print("=" * 50)
    print("  BGE-M3 多语言嵌入模型下载")
    print("=" * 50)
    print(f"\n模型名称: {model_name}")
    print(f"保存路径: {MODEL_SAVE_DIR}")
    print()

    os.makedirs(MODEL_SAVE_DIR, exist_ok=True)
    _update_db_status(False)

    try:
        from modelscope import snapshot_download
        print("正在从 ModelScope 下载模型，请稍候...")
        model_dir = snapshot_download(model_name, cache_dir=MODEL_SAVE_DIR)
        print("\n✓ 模型下载成功！")
        print(f"  模型路径: {model_dir}")

        print("\n检查模型文件...")
        required_files = ['config.json', 'pytorch_model.bin', 'tokenizer.json']
        for f in required_files:
            path = os.path.join(model_dir, f)
            if os.path.exists(path):
                size = os.path.getsize(path) / (1024 * 1024)
                print(f"  ✓ {f} ({size:.1f} MB)")
            else:
                print(f"  ✗ {f} 不存在")

        _update_db_status(True, model_dir)
        return True

    except ImportError:
        print("\n未安装 modelscope，正在安装...")
        os.system(f'"{sys.executable}" -m pip install modelscope')
        try:
            from modelscope import snapshot_download
            print("正在从 ModelScope 下载模型，请稍候...")
            model_dir = snapshot_download(model_name, cache_dir=MODEL_SAVE_DIR)
            print("\n✓ 模型下载成功！")
            print(f"  模型路径: {model_dir}")
            _update_db_status(True, model_dir)
            return True
        except Exception as e:
            print(f"\n✗ ModelScope 下载失败: {e}")
            return False
    except Exception as e:
        print(f"\n✗ 下载失败: {e}")
        return False


if __name__ == "__main__":
    success = download_model()
    if success:
        print("\n" + "=" * 50)
        print("  下载完成！可以启动服务了。")
        print("=" * 50)
    input("\n按回车键退出...")
