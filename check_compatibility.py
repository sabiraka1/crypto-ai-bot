# check_compatibility.py
def check_scoring_compatibility():
    from analysis.scoring_engine import ScoringEngine
    from config.settings import TradingConfig
    
    cfg = TradingConfig()
    scorer = ScoringEngine()
    
    print("🔍 Checking scoring compatibility:")
    print(f"  - Config MIN_SCORE_TO_BUY: {cfg.MIN_SCORE_TO_BUY}")
    print(f"  - Scorer min_score_to_buy: {scorer.min_score_to_buy}")
    print(f"  - Scoring range: [0.0 .. 1.0]")
    print(f"  - Max possible score: 1.0 (3/3 conditions)")
    print(f"  - Typical score: 0.33-0.66")
    
    if cfg.MIN_SCORE_TO_BUY > 0.6:
        print("  ❌ PROBLEM: Threshold too high for normalized scale!")
        print("  🔧 FIX: Set MIN_SCORE_TO_BUY=0.40 in .env")
    else:
        print("  ✅ Threshold compatible with normalized scale")

if __name__ == "__main__":
    check_scoring_compatibility()