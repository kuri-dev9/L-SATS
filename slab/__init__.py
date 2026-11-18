"""레이저 스캔 기반 실별 슬래브 두께 자동 산출."""
from . import history
from .core import (
    AnalysisResult,
    CadPlan,
    Settings,
    analyze,
    load_cad,
    load_grid,
    read_table,
    standardize_grid,
)

__version__ = "0.6.1"
