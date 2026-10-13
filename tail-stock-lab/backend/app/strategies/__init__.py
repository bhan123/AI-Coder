from .fishing_v1 import FishingV1Strategy
from .limit_up_ambush import LimitUpAmbushAlertStrategy
from .leader_reconvergence_p4 import LeaderReconvergenceStrategy
from .platform_breakout_p3 import PlatformBreakoutStrategy
from .sector_resonance_p1 import SectorResonancePullbackStrategy
from .trend_pullback_p2 import TrendPullbackStrategy

ALL_STRATEGIES = {
    FishingV1Strategy.strategy_id: FishingV1Strategy,
    LimitUpAmbushAlertStrategy.strategy_id: LimitUpAmbushAlertStrategy,
    SectorResonancePullbackStrategy.strategy_id: SectorResonancePullbackStrategy,
    TrendPullbackStrategy.strategy_id: TrendPullbackStrategy,
    PlatformBreakoutStrategy.strategy_id: PlatformBreakoutStrategy,
    LeaderReconvergenceStrategy.strategy_id: LeaderReconvergenceStrategy,
}

__all__ = [
    "FishingV1Strategy",
    "LimitUpAmbushAlertStrategy",
    "SectorResonancePullbackStrategy",
    "TrendPullbackStrategy",
    "PlatformBreakoutStrategy",
    "LeaderReconvergenceStrategy",
    "ALL_STRATEGIES",
]
