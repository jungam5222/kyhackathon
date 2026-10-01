"""극단 상태 턴 시간 점검: 모든 칸에 양 팀 유닛이 있고 깃발이 많은 입력을 만들어 넣는다.

    python3 tools/stress.py --sim ~/campus_sim --seeds 5
"""
import argparse
import io
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'bot'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', default=os.path.expanduser('~/campus_sim'))
    ap.add_argument('--seeds', type=int, default=5)
    a = ap.parse_args()
    sys.path.insert(0, a.sim)
    from campus.engine import Game
    from campus.mapgen import generate_map
    import bot as botmod
    worst = 0.0
    for seed in range(1, a.seeds + 1):
        for team in ('Y', 'K'):
            rng = random.Random(seed * 7 + (team == 'K'))
            g = Game(generate_map(seed, 'mixed'))
            init = [l for l in g.init_text(team).splitlines() if l and l != 'END']
            err = sys.stderr
            sys.stderr = io.StringIO()
            b = botmod.Bot(init)
            m = g.map
            cells = [(x, y) for y in range(15) for x in range(15) if m.passable(x, y)]
            for turn in (40, 80, 120, 159, 160):
                units = []
                for (x, y) in cells:
                    for t in ('Y', 'K'):
                        units.append(f"{t} W {x} {y} {rng.randint(1, 6)}")
                        if rng.random() < 0.08:
                            units.append(f"{t} F {x} {y} {rng.randint(1, 2)}")
                blds = []
                for bd in m.buildings:
                    o = rng.choice('NYK')
                    blds.append(f"{bd.id} {bd.x} {bd.y} {bd.type} {o} {2 if o != 'N' else 0} "
                                f"{bd.score if rng.random() < 0.6 else -1}")
                lines = [f"TURN {turn}", "RESOURCE 40 40", f"UNITS {len(units)}"] + units + \
                    [f"BUILDINGS {len(blds)}"] + blds
                t0 = time.perf_counter()
                b.on_turn(lines, t0)
                ms = (time.perf_counter() - t0) * 1000
                worst = max(worst, ms)
            sys.stderr = err
            print(f"seed {seed} {team}: 최악 누적 {worst:.1f}ms")
    print(f"최악 턴 시간 {worst:.1f}ms (한도 300ms, 목표 150ms)")


if __name__ == '__main__':
    main()
