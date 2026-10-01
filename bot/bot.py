"""턴 파이프라인 S1~S14 (지침서 5.2)."""
import sys
import time

import params as P
from mapinfo import MapInfo
from gamestate import TurnData, Memory
from threat import Economy, Threat
from territory import Territory
from modes import Modes
from opening import OpeningPlan
from flags import FlagManager
from squads import SquadManager
from slots import SlotMemory, Slot, build_base_slots, P0d, P1a, P1c, P2
from assign import Ledger, Assigner, Rec
import production
import tele as tele_mod
from output import Output
import canon

LOG_LIMIT = 900 * 1024      # stderr 경기당 1MiB 한도 안쪽
LOG_INIT = True             # 실제 맵 수집용으로 INIT 블록을 한 번 남긴다


class Ctx:
    pass


def clone_slot(s):
    t = Slot(s.key, s.cell, s.base_need, s.tier, None, s.atomic, s.value, s.r, s.meta)
    t.deadline = s.deadline
    return t


class Bot:
    def __init__(self, init_lines, t0=None):
        t0 = t0 if t0 is not None else time.perf_counter()
        self.log_bytes = 0
        raw_init = init_lines
        # K 진영이면 정규 좌표계(우리 본진이 Y 쪽)로 돌려서 처리한다
        self.flip = canon.team_of(init_lines) == 'K'
        if self.flip:
            init_lines = canon.flip_init(init_lines)
        self.mp = MapInfo(init_lines)
        mp = self.mp
        self.mem = Memory(mp)
        try:
            self.opening = OpeningPlan(mp, t0)
        except Exception as e:      # 계획이 실패해도 봇은 돈다
            self.log(f"ERR opening: {e!r}")
            self.opening = None
        self.terr = Territory(mp)
        if self.opening is not None:
            self.terr.set_initial(self.opening.L0)
        self.modes = Modes()
        self.flagm = FlagManager(mp, self.opening)
        self.squadm = SquadManager(mp)
        self.ledger = Ledger()
        self.smem = SlotMemory()
        self.turn = 0
        self.core_need = 0
        self.m = {'rev': 0, 'rev_bad': 0, 'mv': 0, 'swap': 0, 'idle': 0, 'tele': 0,
                  'rej': 0, 'max_ms': 0.0, 'kills': 0}
        if LOG_INIT:
            self.log("INITMAP " + " ".join(raw_init))
        lanes = []
        if self.opening is not None:
            for i, lane in enumerate(self.opening.lanes):
                names = ",".join(f"{mp.blds[b].kind[:3]}{mp.blds[b].x}.{mp.blds[b].y}"
                                 for b in lane[:4])
                lanes.append(f"t{self.opening.start_turns[i]}:{names}")
        self.log(f"INIT {mp.team} D{mp.D} L0{self.opening.L0 if self.opening else '-'} "
                 f"lanes {' | '.join(lanes)}")

    # ------------------------------------------------------------------ 로그
    def log(self, s):
        s = s[:4000] + "\n"
        if self.log_bytes + len(s) > LOG_LIMIT:
            return
        self.log_bytes += len(s.encode('utf-8', 'replace'))
        sys.stderr.write(s)

    # ------------------------------------------------------------------ 가치
    def _bld_value(self, b):
        return self.mem.score_of(b.i) + P.FLAG_FUNC_BONUS.get(b.kind, 0)

    def _flag_value(self, b, td):
        v = self._bld_value(b)
        if b.kind == 'DEPOT' and self.mem.depot_claimed[0][b.i]:
            v -= P.FLAG_FUNC_BONUS['DEPOT']
        if td.owner[b.i] == 1:
            v *= P.ENEMY_OWNED_MULT
        return v

    def _essential(self, td, eco):
        mp = self.mp
        ess = []
        engs = [b for b in mp.by_kind.get('ENG', []) if td.owner[b.i] == 0]
        if len(engs) == 1:
            ess += engs
        for kind in ('HALL', 'HOSPITAL'):
            ess += [b for b in mp.by_kind.get(kind, []) if td.owner[b.i] == 0]
        if len(eco.stations[0]) >= P.TELE_MIN_STATIONS:
            ess += [b for b in mp.by_kind.get('STATION', []) if td.owner[b.i] == 0]
        return ess

    def _spawn_site(self, ctx, f):
        sites = ctx.eco.sites[0]
        if f.site is not None and f.site in sites and f.lane is not None and f.li == 0:
            return f.site
        g = f.goal
        if g is None:
            return self.mp.base_us
        return min(sites, key=lambda s: (self.mp.dist[s][g], 0 if s == self.mp.base_us else 1, s))

    # ------------------------------------------------------------------ 한 턴
    def on_turn(self, lines, t0):
        if self.flip:
            return canon.flip_cmds(self._on_turn(canon.flip_turn(lines), t0))
        return self._on_turn(lines, t0)

    def _on_turn(self, lines, t0):
        mp = self.mp
        # S1·S2 입력·상태 갱신
        td = TurnData(lines, mp)
        self.turn = td.turn
        mem = self.mem
        mem.update(td)
        self.flagm.reconcile(td, td.turn)
        eco = Economy(mp, td)
        th = Threat(mp, td, eco, mem.eflags)
        ctx = Ctx()
        ctx.t0 = t0
        ctx.turn = td.turn
        ctx.last = td.turn >= P.LAST_TURN
        ctx.mp, ctx.td, ctx.mem, ctx.eco, ctx.threat = mp, td, mem, eco, th
        ctx.terr = self.terr
        ctx.smem = self.smem
        ctx.opening = self.opening
        ctx.modes = self.modes
        ctx.bld_value = self._bld_value
        ctx.flag_value = lambda b: self._flag_value(b, td)
        ctx.w_total = sum(td.W[0])
        ctx.core_need = self.core_need
        # S4 모드
        ctx.mode = self.modes.update(td.turn, eco, td, mem)
        ctx.finale = self.modes.finale
        # S5 영역
        ctx.essential = self._essential(td, eco)
        self.terr.update(ctx)
        # S6 깃발 계획
        nF = self.flagm.spawn_count(ctx)
        new_flags = [self.flagm.new_flag(ctx, mp.base_us) for _ in range(nF)]
        goals, sq_slots, locks = self.squadm.update(ctx, self.flagm)
        self.flagm.reserved = {sq.bi for sq in self.squadm.squads}
        self.flagm.assign_tasks(ctx)
        for f in new_flags:
            site = self._spawn_site(ctx, f)
            f.c = f.end = site
            f.site = site
        self.flagm.plan_moves(ctx, goals)
        # S7 슬롯
        base_slots = build_base_slots(ctx) + sq_slots
        # S8 생산 (깃발 첫 선택지 기준)
        for f in self.flagm.flags:
            o = f.opts[0] if f.opts else ('stay', f.c, 0, 0)
            f.end = o[1] if o[0] == 'move' else f.c
        C, caps, dn, dc, eng_sure = self.flagm.capture_info(ctx)
        pp = production.plan(ctx, nF, C, dn, dc, eng_sure, len(self.flagm.flags) - nF)
        # S9·S10 배정과 깃발 호위 검증 (최대 3회)
        base_groups = self.ledger.groups(td)
        asg = None
        bad = 0
        hard = t0 + P.TIME_HARD_MS / 1000.0
        for attempt in range(3):
            groups = [self._copy_grp(g) for g in base_groups]
            slots = [clone_slot(s) for s in base_slots] + self.flagm.option_slots(ctx)
            asg = Assigner(ctx, groups, slots, pp.w_base, pp.w_max, locks).run()
            bad = self.flagm.verify(ctx, asg)
            if bad == 0 or time.perf_counter() > hard:
                break
        self.last_asg = asg
        # 다음 턴 분대 여유 계산용: P0~P2 point 슬롯의 칸별 누적 수요 합
        # (area 경주 수비는 서로 겹쳐 합이 부풀므로 빼고, 분대 슬롯도 뺀다)
        cell_need = {}
        for s in asg.slots:
            if s.tier <= P2 and not s.failed and s.r == 0 and s.key[0] != 'squad':
                cell_need[s.cell] = max(cell_need.get(s.cell, 0), s.need)
        self.core_need = sum(cell_need.values())
        flag_moves = self.flagm.finalize(ctx, asg)
        # S11 TELE
        tl = None
        if time.perf_counter() < hard:
            tl = tele_mod.select(ctx, asg, flag_moves)
        # S13 자원 재확인
        C, caps, dn, dc, eng_sure = self.flagm.capture_info(ctx)
        spentW = sum(asg.prod_used.values())
        extraW = production.leftover_w(ctx, nF, spentW, C, dn, dc)
        # S14 출력
        spawns = [('F', 1, f.site) for f in new_flags]
        for site in sorted(asg.prod_used):
            spawns.append(('W', asg.prod_used[site], site))
        if extraW > 0:
            spawns.append(('W', extraW, mp.base_us))
        moves = {}
        for (c, d), n in asg.moves().items():
            moves[(c, 'W', d)] = moves.get((c, 'W', d), 0) + n
        for f, a, e in flag_moves:
            if e != a and f.tag != 'TELE':
                d = mp.dir_of(a, e)
                if d is not None:
                    moves[(a, 'F', d)] = moves.get((a, 'F', d), 0) + 1
                else:
                    f.end = a
        out = Output(ctx)
        cmds = out.build(spawns, tl, moves, caps)
        # 장부 기록
        recs = asg.ledger_out(td.turn)
        if extraW > 0:
            recs.setdefault(mp.base_us, []).append(Rec(extraW))
        self.ledger.recs = recs
        self.flagm.commit(ctx, [(f, a, f.end) for f, a, e in flag_moves])
        mem.w_spawned_last = sum(out.spawned['W'].values())
        # 로그 (21.1)
        ms = (time.perf_counter() - t0) * 1000.0
        self._turn_log(ctx, asg, out, tl, ms, pp, bad)
        return cmds

    def _copy_grp(self, g):
        h = g.clone(g.n)
        return h

    def _turn_log(self, ctx, asg, out, tl, ms, pp, bad):
        td, mm, terr = ctx.td, self.modes, self.terr
        st = asg.stats
        u0 = sum(1 for s in asg.slots if s.failed and s.tier <= P0d)
        u1 = sum(1 for s in asg.slots if s.failed and P1a <= s.tier <= P1c)
        mv = sum(n for n in asg.moves().values())
        manned = sum(1 for c in terr.F if asg.endc[c] > 0)
        self.m['rev'] += st['rev']
        self.m['rev_bad'] += st['rev_bad']
        self.m['mv'] += mv
        self.m['swap'] += st['swap']
        self.m['idle'] += st['idle']
        self.m['rej'] += out.rejected
        self.m['max_ms'] = max(self.m['max_ms'], ms)
        if tl is not None:
            self.m['tele'] += 1
        line = (f"T{ctx.turn} M{ctx.mode} dP{mm.dP:+.1f} A{mm.A:+d} R{td.R[0]} "
                f"W{sum(td.W[0])}/{sum(td.W[1])} F{sum(td.F[0])}/{sum(td.F[1])} "
                f"S{mm.our_score:.0f}/{mm.enemy_score:.0f} Fr{len(terr.F)}/{manned} "
                f"L{''.join(str(v) for v in terr.L)}{terr.adv_log} "
                f"U{u0},{u1} mv{mv} rv{st['rev']}/{st['rev_bad']} sw{st['swap']} "
                f"id{st['idle']} or{st['orph']} sp{sum(out.spawned['W'].values())}"
                f"{'h' if pp.hold else ''} tl{1 if tl else 0} fb{bad} rj{out.rejected} "
                f"sq{len(self.squadm.squads)} ms{ms:.1f}")
        self.log(line[:P.LOG_LINE_MAX])
        if ctx.last:
            m = self.m
            self.log(f"END rv{m['rev']}/{m['rev_bad']} mv{m['mv']} sw{m['swap']} "
                     f"id{m['idle']} tl{m['tele']} rj{m['rej']} flost{self.flagm.lost_total} "
                     f"ekill{self.mem.eflags_killed_total} sqd{self.squadm.done}/"
                     f"{self.squadm.aborted} maxms{m['max_ms']:.1f}")
