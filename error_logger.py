import pandas as pd
import os
from signal_analyzer import explain_signal

ERROR_FILE = "error_signals.csv"

def log_error_signal(row):
    explanation = explain_signal(row)
    row["explanation"] = explanation

    df = pd.DataFrame([row])

    if os.path.exists(ERROR_FILE):
        df.to_csv(ERROR_FILE, mode='a', index=False, header=False)
    else:
        df.to_csv(ERROR_FILE, index=False, header=True)
