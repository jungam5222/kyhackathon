"""모듈·장면 테스트 (지침서 22.2·22.3).

    python3 tests/test_modules.py

엔진 규칙 테스트(22.1)는 campus-sim의 tests/test_rules.py(161개)가 맡는다.
"""
import os
import subprocess
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.join(HERE, '..', 'bot')
sys.path.insert(0, HERE)
sys.path.insert(0, BOT)

from opening_maps import MAP3, KIND, init_lines   # noqa: E402
from bot import Bot                                 # noqa: E402
from mapinfo import cell                            # noqa: E402
from assign import Assigner, Grp                    # noqa: E402
from slots import Slot, P0b, P2, P6                 # noqa: E402
from output import Output                           # noqa: E402
import production                                   # noqa: E402

DIR = {'U': (0, -1), 'D': (0, 1), 'L': (-1, 0), 'R': (1, 0)}
Bot.log = lambda self, s: None        # 테스트에서는 봇 stderr 로그를 끈다


def buildings(rows=MAP3):
    out = {}
    i = 0
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            if ch in KIND:
                out[(x, y)] = (i, KIND[ch])
                i += 1
    return out


def turn_lines(turn, R, units, owners=None, rows=MAP3, Re=0):
    """units: [(team, kind, x, y, n)], owners: {(x, y): 'Y'|'K'}."""
    owners = owners or {}
    out = [f"TURN {turn}", f"RESOURCE {R} {Re}", f"UNITS {len(units)}"]
    out += [f"{t} {k} {x} {y} {n}" for t, k, x, y, n in units]
    bl = buildings(rows)
    out.append(f"BUILDINGS {len(bl)}")
    for (x, y), (i, kind) in sorted(bl.items(), key=lambda kv: kv[1][0]):
        o = owners.get((x, y), 'N')
        out.append(f"{i} {x} {y} {kind} {o} {2 if o != 'N' else 0} "
                   f"{3 if kind == 'PLAZA' else (2 if o == 'Y' else -1)}")
    return out


def mirror_units(units):
    sw = {'Y': 'K', 'K': 'Y'}
    return [(sw[t], k, 14 - x, 14 - y, n) for t, k, x, y, n in units]


def mirror_owners(owners):
    sw = {'Y': 'K', 'K': 'Y'}
    return {(14 - x, 14 - y): sw[o] for (x, y), o in owners.items()}


def parse_moves(cmds):
    """MOVE 줄 → [(x, y, kind, n, 도착 x, 도착 y)]."""
    out = []
    for c in cmds:
        t = c.split()
        if t[0] == 'MOVE':
            x, y, n = int(t[1]), int(t[2]), int(t[4])
            dx, dy = DIR[t[5]]
            out.append((x, y, t[3], n, x + dx, y + dy))
    return out


def spawned(cmds, kind):
    return sum(int(c.split()[2]) for c in cmds if c.startswith(f"SPAWN {kind} "))


# 깃발 5명을 본진 근처에 두어 정원 보충이 일어나지 않게 한다
FLAGS_HOME = [('Y', 'F', 1, 2, 1), ('Y', 'F', 4, 3, 1), ('Y', 'F', 2, 4, 1), ('Y', 'F', 3, 4, 1)]
OWN = {(3, 13): 'Y', (2, 13): 'Y', (2, 6): 'Y', (6, 11): 'Y', (4, 5): 'Y'}


class ThreatTest(unittest.TestCase):
    def test_E1_and_Ed(self):
        b = Bot(init_lines(MAP3, 'Y'))
        units = FLAGS_HOME + [('Y', 'F', 0, 0, 1), ('K', 'W', 6, 6, 3), ('Y', 'W', 2, 6, 1)]
        b.on_turn(turn_lines(30, 10, units, OWN), 0.0)
        th = b.last_ctx.threat
        self.assertEqual(th.E1[cell(6, 6)], 3)
        self.assertEqual(th.E1[cell(6, 7)], 3)       # 이웃 칸
        self.assertEqual(th.E1[cell(6, 8)], 0)       # 2칸 밖
        self.assertEqual(th.Ed(cell(7, 7), 2), 3)    # 광장 2칸 안
        self.assertEqual(th.Ed(cell(7, 7), 1), 0)
        # 상대 생산지 옆은 즉석 생산분을 더한다 (자원 9, 단가 3 → 3명)
        b2 = Bot(init_lines(MAP3, 'Y'))
        b2.on_turn(turn_lines(30, 10, FLAGS_HOME + [('Y', 'F', 0, 0, 1)], OWN, Re=9), 0.0)
        th2 = b2.last_ctx.threat
        self.assertEqual(th2.E1[cell(12, 11)], 3)
        self.assertEqual(th2.E1[cell(11, 11)], 3)
        self.assertEqual(th2.E1[cell(10, 11)], 0)


class ProductionTest(unittest.TestCase):
    def ctx(self, R, eng=0, halls=0, last=False):
        eco = types.SimpleNamespace(R=[R, 0], income=[10 + 2 * halls, 10],
                                    cost=[2 if eng else 3, 3], eng=[eng, 0])
        return types.SimpleNamespace(eco=eco, last=last)

    def test_eng_hold(self):
        for R, want in ((30, 0), (35, 2), (40, 4)):
            pp = production.plan(self.ctx(R), 0, 2, 0, 0, True, 5)
            self.assertTrue(pp.hold)
            self.assertEqual(pp.w_base, want, R)       # 넘침을 막는 최소량만 산다
            self.assertEqual(pp.w_max, R // 3)         # P0 슬롯은 최대까지 쓸 수 있다

    def test_depot_cap(self):
        # 보급소 1개를 처음 먹는 턴: 점령 후 잔고 ≤ 40 − 15 = 25
        pp = production.plan(self.ctx(30), 0, 2, 1, 2, True, 5)
        R1, I = 30, 10
        bal = min(40, R1 - 3 * pp.w_base + I) - 2
        self.assertLessEqual(bal, 25)
        # 보급소 2개: ≤ 10
        pp2 = production.plan(self.ctx(40), 0, 4, 2, 4, True, 5)
        bal2 = min(40, 40 - 3 * pp2.w_base + I) - 4
        self.assertLessEqual(bal2, 10)

    def test_capture_funds_and_last_turn(self):
        pp = production.plan(self.ctx(3), 0, 14, 0, 0, False, 5)   # 점령비 14, 수입 10
        self.assertEqual(pp.w_base, 0)                              # 3 − 0 + 10 ≥ 14 이 안 됨
        pp = production.plan(self.ctx(40, last=True), 0, 0, 0, 0, True, 5)
        self.assertEqual(pp.w_base, 13)                             # 마지막 턴은 전부 쓴다
        pp = production.plan(self.ctx(4), 0, 0, 0, 0, False, 0)
        self.assertTrue(pp.save)                                    # 깃발 0명: 5를 모은다


class AssignTest(unittest.TestCase):
    def setUp(self):
        self.b = Bot(init_lines(MAP3, 'Y'))
        self.b.on_turn(turn_lines(30, 0, FLAGS_HOME + [('Y', 'F', 0, 0, 1)], OWN), 0.0)
        self.ctx = self.b.last_ctx
        self.ctx.t0 = 1e18          # 시간 감시 끔

    def run_asg(self, groups, slots):
        return Assigner(self.ctx, groups, slots, 0, 0, []).run()

    def test_deadline_counts_only_in_time(self):
        """먼 칸에서 오는 인원은 마감 1턴 슬롯을 채운 것으로 치지 않는다 (11.1 + 마감)."""
        c = cell(3, 13)
        sup = Slot(('support', c), c, 2, P6)
        guard = Slot(('guard', 0, 0), c, 2, P0b, deadline=1, atomic=True)
        far = Grp(cell(3, 9), 2)
        far.key, far.tgt = sup.key, c                    # 지원 칸으로 걸어오는 중
        near = Grp(cell(3, 12), 2)
        asg = self.run_asg([far, near], [sup, guard])
        self.assertFalse(guard.failed)
        self.assertGreaterEqual(asg.pt_in_time(c, 1), 2)
        self.assertEqual(near.slot, guard)

    def test_atomic_not_partial(self):
        c = cell(3, 13)
        s = Slot(('hunt', 1, c), c, 3, P0b, deadline=1, atomic=True)
        g = Grp(cell(3, 12), 2)
        asg = self.run_asg([g], [s])
        self.assertTrue(s.failed)
        self.assertIsNot(g.slot, s)
        self.assertEqual(asg.pt[c], 0)

    def test_no_reverse_without_reason(self):
        """INV-03: 지난 턴 p → c로 온 유닛은 이유 없이 c → p로 가지 않는다."""
        p, c, tgt = cell(3, 10), cell(3, 11), cell(3, 8)
        s = Slot(('screen', tgt), tgt, 1, P2)
        g = Grp(c, 1)
        g.came = p
        asg = self.run_asg([g], [s])
        self.assertEqual(g.step, c)
        self.assertEqual(asg.stats['rev_bad'], 1)

    def test_swap_cancel(self):
        """INV-04: a→b와 b→a가 함께 있으면 둘 다 취소하고 목표만 바꾼다."""
        a, b = cell(3, 10), cell(3, 11)
        sa = Slot(('screen', a), a, 1, P2)
        sb = Slot(('screen', b), b, 1, P2)
        ga, gb = Grp(a, 1), Grp(b, 1)
        ga.key, ga.tgt = sb.key, b
        gb.key, gb.tgt = sa.key, a
        asg = self.run_asg([ga, gb], [sa, sb])
        self.assertEqual(asg.moves(), {})
        self.assertTrue(asg.endc_ok)

    def test_no_idle(self):
        """INV-07: 남는 병력은 지원 칸으로 간다."""
        gs = [Grp(cell(2, 6), 4), Grp(cell(4, 5), 3)]
        asg = self.run_asg(gs, [])
        self.assertEqual(asg.stats['idle'], 0)
        self.assertTrue(all(g.slot is not None for g in asg.groups if g.n > 0))


class SceneTest(unittest.TestCase):
    def test_guard_race_radius(self):
        """22.3: 상대 깃발 + 전투병 3이 우리 학생회관 2칸 밖 → 이동 뒤 반경 1 안에 4명 이상."""
        b = Bot(init_lines(MAP3, 'Y'))
        units = FLAGS_HOME + [('Y', 'F', 0, 0, 1), ('Y', 'W', 3, 11, 5),
                              ('K', 'F', 5, 13, 1), ('K', 'W', 5, 13, 3)]
        cmds = b.on_turn(turn_lines(30, 0, units, OWN), 0.0)
        hall = cell(3, 13)
        mp = b.mp
        end = {cell(3, 11): 5}
        for x, y, k, n, ex, ey in parse_moves(cmds):
            if k == 'W':
                end[cell(x, y)] -= n
                end[cell(ex, ey)] = end.get(cell(ex, ey), 0) + n
        inside = sum(n for c, n in end.items() if mp.dist[c][hall] <= 1)
        self.assertGreaterEqual(inside, 4, cmds)

    def test_kill_stationary_flag(self):
        """22.3: 우리 공학관 1칸 옆에 상대 깃발이 혼자 정지 → 처치하러 들어간다."""
        b = Bot(init_lines(MAP3, 'Y'))
        units = FLAGS_HOME + [('Y', 'F', 0, 0, 1), ('Y', 'W', 1, 12, 2), ('K', 'F', 2, 12, 1)]
        b.on_turn(turn_lines(30, 0, units, OWN), 0.0)
        cmds = b.on_turn(turn_lines(31, 0, units, OWN), 0.0)
        dests = [(ex, ey) for x, y, k, n, ex, ey in parse_moves(cmds) if k == 'W']
        self.assertIn((2, 12), dests, cmds)

    def test_eng_capture_turn_holds_purchase(self):
        """22.3: 공학관 점령 턴에는 전투병을 사지 않는다 (넘침 방지 최소량 제외)."""
        b = Bot(init_lines(MAP3, 'Y'))
        own = {k: v for k, v in OWN.items() if k != (2, 13)}
        units = FLAGS_HOME + [('Y', 'F', 2, 12, 1)]
        cmds = b.on_turn(turn_lines(30, 30, units, own), 0.0)
        self.assertIn('MOVE 2 12 F 1 D', cmds)
        # 학생회관 1개 → 수입 12. 30 + 12 − 40 = 2 넘침 → 넘침을 막는 최소 1명만 산다
        self.assertEqual(spawned(cmds, 'W'), 1)
        b2 = Bot(init_lines(MAP3, 'Y'))
        cmds2 = b2.on_turn(turn_lines(30, 40, units, own), 0.0)
        self.assertEqual(spawned(cmds2, 'W'), 4)       # 40 + 12 − 40 = 12 → 3원 × 4


class OutputTest(unittest.TestCase):
    def test_validator_filters_bad_lines(self):
        b = Bot(init_lines(MAP3, 'Y'))
        b.on_turn(turn_lines(30, 9, FLAGS_HOME + [('Y', 'W', 3, 11, 2)], OWN), 0.0)
        out = Output(b.last_ctx)
        lines = out.build(
            spawns=[('W', 5, b.mp.base_us), ('W', 1, cell(7, 7)), ('X', 1, b.mp.base_us)],
            tele=('W', cell(3, 11), cell(6, 11), 1),
            moves={(cell(3, 11), 'W', 'U'): 5, (cell(9, 9), 'W', 'U'): 1,
                   (cell(1, 4), 'W', 'U'): 1},
            caps=[])
        self.assertIn('SPAWN W 4', lines)              # 자원 9, 공학관 보유 단가 2 → 4명까지만
        self.assertFalse(any(l.startswith('TELE') for l in lines))   # 역이 아님
        self.assertIn('MOVE 3 11 W 2 U', lines)        # 인원 5 → 2명까지만
        self.assertFalse(any(l.startswith('MOVE 9 9') for l in lines))
        self.assertGreaterEqual(out.rejected, 4)


class RobustnessTest(unittest.TestCase):
    def test_main_survives_garbage(self):
        init = '\n'.join(init_lines(MAP3, 'Y')) + '\nEND\n'
        blocks = ['TURN 1\nRESOURCE 10 10\nUNITS 0\nBUILDINGS 0\nEND\n',
                  'TURN 2\nRESOURCE x\nUNITS 3\nY W 1\nEND\n',
                  'garbage\nEND\n',
                  '\n'.join(turn_lines(4, 10, [])) + '\nEND\n']
        p = subprocess.run([sys.executable, os.path.join(BOT, 'main.py')],
                           input=init + ''.join(blocks), capture_output=True, text=True,
                           timeout=30)
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.count('END'), len(blocks))

    def test_determinism_and_mirror(self):
        units = FLAGS_HOME + [('Y', 'F', 0, 0, 1), ('Y', 'W', 3, 11, 5), ('Y', 'W', 6, 9, 3),
                              ('K', 'F', 5, 13, 1), ('K', 'W', 5, 13, 3), ('K', 'W', 9, 5, 4)]
        runs = []
        for _ in range(2):
            b = Bot(init_lines(MAP3, 'Y'))
            runs.append([b.on_turn(turn_lines(t, 12, units, OWN), 0.0) for t in (30, 31)])
        self.assertEqual(runs[0], runs[1])             # INV-12
        bk = Bot(init_lines(MAP3, 'K'))
        mirrored = [bk.on_turn(turn_lines(t, 12, mirror_units(units), mirror_owners(OWN)), 0.0)
                    for t in (30, 31)]
        import canon
        self.assertEqual([canon.flip_cmds(c) for c in mirrored], runs[0])


if __name__ == '__main__':
    unittest.main()
