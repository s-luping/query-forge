# -*- coding: UTF-8 -*-
"""
从 ModelScope 下载 BGE-M3 多语言嵌入模型
保存路径: D:\projects\QueryForge\models\embeddings\bge-m3
"""
import os
import sys

MODEL_SAVE_DIR = os.path.join(os.path.dirname(__file__), 'models', 'embeddings', 'bge-m3')


def download_model():
    model_name = 'BAAI/bge-m3'
    
    print("=" * 50)
    print("  BGE-M3 多语言嵌入模型下载")
    print("=" * 50)
    print(f"\n模型名称: {model_name}")
    print(f"保存路径: {MODEL_SAVE_DIR}")
    print()
    
    os.makedirs(MODEL_SAVE_DIR, exist_ok=True)
    
    try:
        from modelscope import snapshot_download
        print("正在从 ModelScope 下载模型，请稍候...")
        model_dir = snapshot_download(model_name, cache_dir=MODEL_SAVE_DIR)
        print(f"\n✓ 模型下载成功！")
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
        
        return True
        
    except ImportError:
        print("\n未安装 modelscope，正在安装...")
        os.system(f'pip install --user modelscope')
        try:
            from modelscope import snapshot_download
            print("正在从 ModelScope 下载模型，请稍候...")
            model_dir = snapshot_download(model_name, cache_dir=MODEL_SAVE_DIR)
            print(f"\n✓ 模型下载成功！")
            print(f"  模型路径: {model_dir}")
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
