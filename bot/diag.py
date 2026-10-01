"""경기 지표 (지침서 21.2).

즉시 승패로 160턴 전에 끝나는 경기가 많으므로 P-METRIC_EVERY 턴마다와 마지막 턴에
누적 지표 한 줄(M)을 남긴다. 마지막으로 찍힌 M 줄이 그 경기의 지표다.
"""
import params as P


class Metrics:
    def __init__(self):
        self.mv = 0              # 전투병 이동 수
        self.rv_all = 0          # 전체 되돌림 (사유 무관 a→b 다음 턴 b→a)
        self.rev_bad = 0         # 사유 없는 역행 시도 (INV-03, 취소 전)
        self.swap = 0            # 맞교환·순환 취소
        self.idle = 0            # 놀림 (슬롯 없는 유닛-턴, 고아 대기 제외)
        self.unsafe_wait = 0     # 안전 문제로 제자리에 멈춘 이동 (INV-11)
        self.cov_sum = 0.0       # 라인 완성 후 경계 배치율
        self.cov_n = 0
        self.top3_sum = 0.0      # 상위 3더미 비중
        self.top3_n = 0
        self.f_exposed = 0       # 깃발 노출 (E1 > 같은 칸 아군)
        self.f_turns = 0
        self.f45 = None          # 45턴까지 (깃발 손실, 상대 깃발 처치)
        self.overflow = 0        # 상한 40으로 버린 자원 (보급소 포함)
        self.rej = 0             # 출력 검증기가 거른 줄
        self.tele_turns = 0
        self.tele_units = 0
        self.eng_turns = 0
        self.hall_turns = 0
        self.dp_sum = 0.0
        self.turns = 0
        self.max_ms = 0.0
        self.prev_edges = {}

    def update(self, ctx, asg, out, tl, flags, cap, ms):
        """cap = (C, depot_n): 이번 턴 점령 비용과 처음 먹는 보급소 수."""
        eco, th, terr = ctx.eco, ctx.threat, ctx.terr
        self.turns += 1
        edges = {}
        for g in asg.groups:
            if g.n > 0 and g.step is not None and g.step != g.c and g.tag != 'TELE':
                edges[(g.c, g.step)] = edges.get((g.c, g.step), 0) + g.n
        for (a, b), n in edges.items():
            self.mv += n
            back = self.prev_edges.get((b, a), 0)
            if back:
                self.rv_all += min(back, n)
        self.prev_edges = edges
        st = asg.stats
        self.rev_bad += st['rev_bad']
        self.swap += st['swap']
        self.idle += st['idle']
        self.unsafe_wait += st.get('unsafe_wait', 0)
        if terr.line_done and terr.F:
            live = [c for c in terr.F if c not in terr.occupied]
            if live:
                self.cov_sum += sum(1 for c in live if asg.endc[c] > 0) / len(live)
                self.cov_n += 1
        tot = sum(asg.endc)
        if tot >= P.METRIC_TOP3_MIN_W:
            self.top3_sum += sum(sorted(asg.endc, reverse=True)[:3]) / tot
            self.top3_n += 1
        for f in flags:
            self.f_turns += 1
            if th.E1[f.end] > asg.endc[f.end]:
                self.f_exposed += 1
        R, I = eco.R[0], eco.income[0]
        left = R - out.spent + I
        if left > P.RES_CAP:
            self.overflow += left - P.RES_CAP
        C, depot_n = cap
        if depot_n:
            bal = min(P.RES_CAP, left) - C
            self.overflow += max(0, bal + P.DEPOT_BONUS * depot_n - P.RES_CAP)
        self.rej += out.rejected
        if tl is not None:
            self.tele_turns += 1
            self.tele_units += tl[3]
        if eco.eng[0]:
            self.eng_turns += 1
        if eco.halls[0]:
            self.hall_turns += 1
        self.dp_sum += eco.prod_rate[0] - eco.prod_rate[1]
        self.max_ms = max(self.max_ms, ms)

    def snap_f45(self, lost, kills):
        if self.f45 is None:
            self.f45 = (lost, kills)

    def line(self, turn, lost, kills, squads, why=None):
        def pct(a, b):
            return f"{100.0 * a / b:.0f}" if b else '-'
        f45 = self.f45 if self.f45 is not None else (lost, kills)
        return (f"M{turn} rv{self.rv_all}/{self.mv}={pct(self.rv_all, self.mv)}% "
                f"rb{self.rev_bad} sw{self.swap} id{self.idle} uw{self.unsafe_wait} "
                f"cov{pct(self.cov_sum, self.cov_n)}% top3{pct(self.top3_sum, self.top3_n)}% "
                f"fexp{pct(self.f_exposed, self.f_turns)}% f45:{f45[0]}/{f45[1]} "
                f"fall:{lost}/{kills} of{self.overflow} rj{self.rej} "
                f"tl{self.tele_turns}/{self.tele_units} eng{self.eng_turns} hall{self.hall_turns} "
                f"dP{self.dp_sum / max(1, self.turns):+.2f} sq{squads[0]}/{squads[1]}"
                f"{'(' + ','.join(f'{k}{v}' for k, v in sorted((why or {}).items())) + ')' if why else ''} "
                f"ms{self.max_ms:.0f}")
