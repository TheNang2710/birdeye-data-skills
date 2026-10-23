"""Bundled data / logic modules for the birdeye skill CLI.

Everything the CLI needs for the six shipped skills lives right here so the
project stays self-contained and dependency-free:

    wallet_data.py      wallet score + wallet style maths (Skill #13 / #11)
    kline_pattern.py    candlestick pattern classifier (Skill #21)
    trending_score.py   token trending momentum score (Skill #22)
    junk_ml.py          junk-token logistic-regression runtime (Skill #23)
    junk_modes.py       supervised junk scorer (Skill #23)
    lr_params.json      trained LR parameters
    junk_supervised_model.json  supervised GBM model
"""
