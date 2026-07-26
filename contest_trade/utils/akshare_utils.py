"""
akshare 的工具函数

"""
import json
import hashlib
from pathlib import Path
from datetime import datetime
from loguru import logger
from utils.cache_io import read_cache, write_cache

import akshare as ak

DEFAULT_AKSHARE_CACHE_DIR = Path(__file__).parent / "akshare_cache"

class CachedAksharePro:
    def __init__(self, cache_dir=None):
        if not cache_dir:
            self.cache_dir = DEFAULT_AKSHARE_CACHE_DIR
        else:
            self.cache_dir = Path(cache_dir)
        if not self.cache_dir.exists():
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def run(self, func_name: str, func_kwargs: dict, verbose: bool = False):
        func_kwargs_str = json.dumps(func_kwargs, sort_keys=True, ensure_ascii=False)
        return self.run_with_cache(func_name, func_kwargs_str, verbose)

    def run_with_cache(self, func_name: str, func_kwargs: str, verbose: bool = False):
        func_kwargs = json.loads(func_kwargs)
        args_hash = hashlib.sha256(
            json.dumps(func_kwargs, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        trigger_time = datetime.now().strftime("%Y%m%d%H")
        args_hash = f"{args_hash}_{trigger_time}"
        func_cache_dir = self.cache_dir / func_name
        if not func_cache_dir.exists():
            func_cache_dir.mkdir(parents=True, exist_ok=True)
        func_cache_file = func_cache_dir / f"{args_hash}.json.gz"
        if func_cache_file.exists():
            if verbose:
                print(f"load result from {func_cache_file}")
            try:
                return read_cache(func_cache_file)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                logger.warning(f"Ignoring invalid AKShare cache {func_cache_file}: {exc}")
        if verbose:
            print(f"cache miss for {func_name} with args: {func_kwargs}")
        result = getattr(ak, func_name)(**func_kwargs)
        if verbose:
            print(f"save result to {func_cache_file}")
        write_cache(func_cache_file, result)
        return result

akshare_cached = CachedAksharePro()
