"""Log jumlah baris per tahap: setiap baris yang dibuang tercatat alasannya."""
import pandas as pd


class Attrition:
    def __init__(self):
        self.rows = []

    def log(self, platform, kasus, step, before, after, note=""):
        self.rows.append({"platform": platform, "kasus": kasus, "step": step, "before": int(before),
                          "after": int(after), "removed": int(before) - int(after), "note": note})

    def log_df(self, platform, step, before_df, after_df, note=""):
        """Catat per kasus dari dua DataFrame yang punya kolom `kasus`."""
        b = before_df.groupby("kasus").size()
        a = after_df.groupby("kasus").size()
        for k in sorted(set(b.index) | set(a.index)):
            self.log(platform, k, step, b.get(k, 0), a.get(k, 0), note)

    def frame(self):
        return pd.DataFrame(self.rows, columns=["platform", "kasus", "step", "before", "after", "removed", "note"])
