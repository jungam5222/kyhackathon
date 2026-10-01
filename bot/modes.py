"""모드 판정 (지침서 9장)과 마감 진입·이탈 (18.1)."""
import params as P

FIX, POS, ATT, FIN = 'FIX', 'POS', 'ATT', 'FIN'


class Modes:
    def __init__(self):
        self.mode = POS
        self.cand = POS
        self.streak = 0
        self.finale = False
        self.fin_since = 0
        self.neg_streak = 0
        self.maj_streak = 0
        self.dP = 0.0
        self.A = 0
        self.maj_est = False
        self.maj_sure = False
        self.our_score = 0
        self.enemy_score = 0

    def update(self, turn, eco, td, mem):
        self.dP = eco.prod_rate[0] - eco.prod_rate[1]
        wu = sum(td.W[0])
        we = sum(td.W[1])
        self.A = wu - we
        est_total, ub_total = mem.totals()
        self.our_score = mem.team_score(0, td)
        self.enemy_score = mem.team_score(1, td)
        self.maj_est = self.our_score > est_total / 2
        self.maj_sure = self.our_score > ub_total / 2
        if not self.finale:
            enter = (self.maj_est and self.dP >= 0 and self.A >= P.FIN_MIN_LEAD and
                     (we <= P.FIN_ENEMY_W or wu >= P.FIN_RATIO * we or
                      (turn >= P.FIN_TURN and self.A >= P.FIN_LEAD)))
            if enter:
                self.finale = True
                self.fin_since = turn
                self.neg_streak = 0
                self.maj_streak = 0
        else:
            self.neg_streak = self.neg_streak + 1 if self.A < 0 else 0
            self.maj_streak = self.maj_streak + 1 if not self.maj_est else 0
            if turn - self.fin_since < P.FIN_MIN_DWELL:
                leave = self.A < P.FIN_BREAK_LEAD
            else:
                leave = (self.neg_streak >= P.FIN_EXIT_TURNS or
                         self.maj_streak >= P.FIN_MAJ_TURNS)
            if leave:
                self.finale = False
        target = FIX if self.dP < -P.DP_EPS else (ATT if self.dP > P.DP_EPS else POS)
        if self.finale:
            self.mode = FIN
            self.cand = target
            self.streak = 0
            return self.mode
        if self.mode == FIN:
            self.mode = target
            self.cand = target
            self.streak = 0
            return self.mode
        if target == self.mode:
            self.streak = 0
            self.cand = target
        else:
            if target == self.cand:
                self.streak += 1
            else:
                self.cand = target
                self.streak = 1
            if self.streak >= P.MODE_HYST:
                self.mode = target
                self.streak = 0
        return self.mode
