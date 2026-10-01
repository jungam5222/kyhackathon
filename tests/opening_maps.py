"""지침서 부록 A의 맵 2·3 (건물 종류 포함)과 INIT 만들기."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bot'))

KIND = {'h': 'HALL', 's': 'STATION', 'E': 'ENG', '+': 'HOSPITAL', 'L': 'LIBRARY',
        'W': 'WATCH', 'D': 'DEPOT', 'P': 'PLAZA'}

MAP2 = """......#........
.#.+...#...L...
..sY#..........
...#.......h.#.
...#.....W.#.#.
...............
...#....D....E.
......sPs......
.E....D....#...
...............
.#.#.W.....#...
.#.h.......#...
..........#Ks..
...L...#...+.#.
........#......""".split()

MAP3 = """.............#.
..#........hE.#
..##.D.........
.#Y.....s...+..
.............#.
...#s#...W....#
..L............
.......P.......
............L..
#....W...#s#...
.#.............
..+...s.....K#.
.........D.##..
#.Eh........#..
.#.............""".split()


def init_lines(rows, team):
    terrain = []
    blds = []
    bases = {}
    for y, r in enumerate(rows):
        line = ''
        for x, ch in enumerate(r):
            if ch in ('Y', 'K'):
                bases[ch] = (x, y)
                line += 'H'
            elif ch in KIND:
                blds.append((x, y, KIND[ch]))
                line += 'B'
            else:
                line += ch
        terrain.append(line)
    out = ['INIT 15 15', f'TEAM {team}'] + [f'MAP {r}' for r in terrain]
    out.append(f'BUILDINGS {len(blds)}')
    for i, (x, y, k) in enumerate(blds):
        out.append(f'{i} {x} {y} {k}')
    out += [f"BASE Y {bases['Y'][0]} {bases['Y'][1]}", f"BASE K {bases['K'][0]} {bases['K'][1]}"]
    return out


def plan_for(rows, team):
    import canon
    from mapinfo import MapInfo
    from opening import OpeningPlan
    lines = init_lines(rows, team)
    if team == 'K':
        lines = canon.flip_init(lines)
    mp = MapInfo(lines)
    return mp, OpeningPlan(mp)


if __name__ == '__main__':
    from mapinfo import cx, cy
    for name, rows in (('map2', MAP2), ('map3', MAP3)):
        mp, plan = plan_for(rows, 'K')
        print(name, 'nflags', plan.nflags)
        for li, lane in enumerate(plan.lanes):
            # K 진영은 정규 좌표계라 원래 좌표로 되돌려 보여 준다
            items = [f"{mp.blds[b].kind}({14 - mp.blds[b].x},{14 - mp.blds[b].y})t{plan.cap_turn[b]}"
                     for b in lane]
            print(f"  lane{li} start t{plan.start_turns[li]} site "
                  f"({14 - cx(plan.sites[li])},{14 - cy(plan.sites[li])}): " + ", ".join(items))
        print('  escorts', [(mp.blds[b].kind, t) for b, n, t in plan.escorts])
