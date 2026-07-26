import pandas as pd
import time
from contest_trade.config.config import PROJECT_ROOT
from pathlib import Path
from loguru import logger
from contest_trade.utils.cache_io import read_cache, write_cache

class DataSourceBase:
    
    def __init__(self, name: str):
        self.name = name
        self.data_cache_dir = Path(PROJECT_ROOT) / "data_source" / "data_cache" / self.name
        if not self.data_cache_dir.exists():
            self.data_cache_dir.mkdir(parents=True, exist_ok=True)

    def get_data_cached(self, trigger_time: str) -> pd.DataFrame:
        """
        get data from data source, return format should be a pandas dataframe
        including cols: ['title', 'content', 'pub_time', 'url']
        """
        cache_file_name = trigger_time.replace(" ", "_").replace(":", "-")
        cache_file = self.data_cache_dir / f"{cache_file_name}.json.gz"
        if cache_file.exists():
            start_time = time.time()
            try:
                df = read_cache(cache_file)
            except (OSError, ValueError, TypeError) as exc:
                logger.warning(f"忽略损坏的数据源缓存 {cache_file}: {exc}")
                return None
            if not isinstance(df, pd.DataFrame):
                logger.warning(f"忽略非 DataFrame 数据源缓存: {cache_file}")
                return None
            if df['pub_time'].dtype == 'datetime64[ns]':
                df['pub_time'] = df['pub_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
            elapsed = time.time() - start_time
            logger.info(f"[耗时] {self.name} 读取缓存完成: {elapsed:.2f}秒, {len(df)}条数据")
            return df
        else:
            return None

    def save_data_cached(self, trigger_time: str, data: pd.DataFrame): 
        cache_file_name = trigger_time.replace(" ", "_").replace(":", "-")
        cache_file = self.data_cache_dir / f"{cache_file_name}.json.gz"
        write_cache(cache_file, data)

    def get_data(self, trigger_time: str) -> pd.DataFrame:
        """
        get data from data source, return format should be a pandas dataframe
        including cols: ['title', 'content', 'pub_time', 'url']
        """
        pass
